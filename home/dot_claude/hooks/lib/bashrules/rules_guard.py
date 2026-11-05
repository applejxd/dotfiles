"""防御機構そのものと、環境への永続的な変更の保護。

hook や settings.json の改変、シェル起動ファイルへの追記、権限昇格、
グローバルな環境変数の書き換えなどを扱う。
"""

from __future__ import annotations

import os
import re
import shlex

from . import shellparse, tables
from ._shared import (
    _basename,
    _cmd_name,
    _commands,
    _normalize_guard_path,
    _policy,
    _redirect_write_targets,
    _segments,
    _workspace_root,
    _write_targets,
)
from .rules_exec import _is_inline_code_segment

# シェルが値をコードとして実行する入口の環境変数 (名前は完全一致。BASH_FUNC_ だけ前方一致)。
# 検出する形・入れないもの・限界は docs/spec/guard/pi-guard.md#コードの入口になる環境変数
# (pi 側 judge/rules_guard.ts の codeEntryEnv と同じ規則。片方だけ直さない)
# 通常の引数は走査しない: 単純コマンドの語の列の、代入になりうる位置だけを見る
_ENTRY_NAMES = frozenset(
    {"PS4", "PROMPT_COMMAND", "BASH_ENV", "LD_PRELOAD", "LD_AUDIT", "DYLD_INSERT_LIBRARIES"}
)
_ENTRY_ASSIGN_WORD_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_%]*)(?:\[[^\]]*\])?\+?=(.*)", re.S)
_PS4_EXPANSION_RE = re.compile(
    r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*(?:\[(?:[0-9]+|@)\])?\})"
)
_ENTRY_KEYWORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}"})
_ENTRY_WRAPPERS = frozenset(
    {
        "env",
        "sudo",
        "doas",
        "time",
        "command",
        "nice",
        "nohup",
        "timeout",
        "stdbuf",
        "xargs",
        "exec",
        "builtin",
    }
)
_ENTRY_WRAPPER_VALUE_OPTS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "sudo": frozenset(
        {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t", "--user", "--group"}
    ),
    "doas": frozenset({"-u", "-C"}),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "xargs": frozenset({"-I", "-n", "-P", "-s", "-L", "-E", "-d", "-a"}),
    "exec": frozenset({"-a"}),
}
_ENTRY_DECLARE = frozenset({"export", "declare", "typeset", "local", "readonly"})
_ENTRY_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})


def _entry_name(name: str) -> bool:
    return name in _ENTRY_NAMES or name.startswith("BASH_FUNC_")


def _ps4_safe(value: str) -> bool:
    """PS4 の値が、リテラルと単純な展開 (`$NAME`・`${NAME}`・`${NAME[数字]}`・`${NAME[@]}`) だけか。"""
    return re.search(r"[$`\\]", _PS4_EXPANSION_RE.sub("", value)) is None


def _entry_assign(word: str) -> str | None:
    """`NAME=値`・`NAME+=値` の語が名簿の変数への代入なら名前を返す (値が安全な PS4 は除く)。"""
    m = _ENTRY_ASSIGN_WORD_RE.fullmatch(word)
    if m is None or not _entry_name(m.group(1)):
        return None
    return None if m.group(1) == "PS4" and _ps4_safe(m.group(2)) else m.group(1)


def _entry_target(word: str | None) -> str | None:
    """`read`・`printf -v` の設定先の変数名 (添字は外す)が名簿なら名前を返す。値は取れないので常に拒否側。"""
    if word is None:
        return None
    name = re.sub(r"\[.*", "", word, flags=re.S)
    return name if _entry_name(name) else None


def _short_opts(
    args: list[str], value_chars: str
) -> tuple[list[tuple[str, str | None]], list[str]]:
    """短いオプションを読む。`value_chars` の文字は値を取る (同じ語の残り、無ければ次の語)。`--` と長いオプションは読み飛ばす。"""
    opts: list[tuple[str, str | None]] = []
    i = 0
    while i < len(args):
        t = args[i]
        if t == "--":
            i += 1
            break
        if t.startswith("--"):
            i += 1
            continue
        if not t.startswith("-") or len(t) < 2:
            break
        for k in range(1, len(t)):
            if t[k] in value_chars:
                rest = t[k + 1 :]
                if rest:
                    opts.append((t[k], rest))
                else:
                    opts.append((t[k], args[i + 1] if i + 1 < len(args) else None))
                    i += 1
                break
            opts.append((t[k], None))
        i += 1
    return opts, args[i:]


def _env_split_string(args: list[str], j: int) -> tuple[str | None, int]:
    """`env -S` の文字列 (語の残り・`=` の後・次の語) と、消費した語数。"""
    t = args[j]
    if t in ("-S", "--split-string"):
        return (args[j + 1] if j + 1 < len(args) else None), 2
    if t.startswith("--split-string="):
        return t[len("--split-string=") :], 1
    if t.startswith("-S") and not t.startswith("--"):
        return t[2:], 1
    return None, 0


def _shlex_or_split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _entry_in_words(words: list[str], depth: int) -> str | None:
    """1 つの単純コマンドの語の列から、名簿の変数の設定・コールバックの入口を見つける。"""
    i = 0
    while i < len(words) and words[i] in _ENTRY_KEYWORDS:
        i += 1
    while i < len(words) and _ENTRY_ASSIGN_WORD_RE.fullmatch(words[i]):
        hit = _entry_assign(words[i])
        if hit is not None:
            return hit
        i += 1
    if i >= len(words):
        return None
    head = _basename(words[i])
    args = words[i + 1 :]
    if head in _ENTRY_WRAPPERS:
        value_opts = _ENTRY_WRAPPER_VALUE_OPTS.get(head, frozenset())
        j = 0
        while j < len(args):
            t = args[j]
            if t == "--":
                j += 1
                break
            if head == "env" and t.startswith(("-S", "--split-string")):
                text, used = _env_split_string(args, j)
                if text is None:
                    return None
                return _entry_in_words(["env", *_shlex_or_split(text), *args[j + used :]], depth)
            if t.startswith("-") and len(t) > 1:
                j += 2 if t in value_opts else 1
                continue
            break
        if head == "timeout" and j < len(args):
            j += 1  # DURATION
        return _entry_in_words(args[j:], depth)
    if head in _ENTRY_DECLARE:
        for t in args:
            hit = _entry_assign(t)
            if hit is not None:
                return hit
        return None
    if head == "printf":
        for ch, value in _short_opts(args, "v")[0]:
            if ch == "v":
                return _entry_target(value)
        return None
    if head == "read":
        opts, operands = _short_opts(args, "adinNptu")
        for ch, value in opts:
            if ch == "a":
                hit = _entry_target(value)
                if hit is not None:
                    return hit
        for t in operands:
            hit = _entry_target(t)
            if hit is not None:
                return hit
        return None
    if head in ("mapfile", "readarray"):
        opts, operands = _short_opts(args, "dnOsuCc")
        if any(ch == "C" for ch, _ in opts):
            return "mapfile -C"
        for t in operands:
            hit = _entry_target(t)
            if hit is not None:
                return hit
        return None
    if head in ("compgen", "complete"):
        return (
            "compgen -C" if any(ch == "C" for ch, _ in _short_opts(args, "AFGWPSXoC")[0]) else None
        )
    if head in _ENTRY_SHELLS and depth < 3:
        for k, t in enumerate(args):
            if not t.startswith("-") or t.startswith("--") or len(t) < 2:
                break
            if "c" in t[1:]:
                if k + 1 >= len(args):
                    return None
                for inner in shellparse.parse(args[k + 1]):
                    hit = _entry_in_words(list(inner.argv), depth + 1)
                    if hit is not None:
                        return hit
                return None
    return None


def code_entry_env(cmd: str) -> str | None:
    """コードの入口になる環境変数の設定・コールバックの入口を見つける。見つからなければ None。"""
    for command in _commands(cmd):
        hit = _entry_in_words(list(command.argv), 0)
        if hit is not None:
            return hit
    return None


def check_guard_tampering(cmd: str) -> str | None:
    """hook や permission 設定そのものを無効化しようとしていないか。

    コマンドによる変更 (`rm` / `chmod` など) に加え、リダイレクトによる
    上書き (`> ~/.claude/settings.json`) も検出する。
    """
    targets = (
        "/.claude/hooks",
        "/.claude/settings.json",
        "/.copilot/hooks",
        "/.copilot/permissions-config.json",
        "/.config/agents",
        "/.git/config",
        "/.git/hooks",
        ".git/config",
        ".git/hooks",
    )

    def _hits(token: str) -> bool:
        expanded = _normalize_guard_path(token)
        return any(t in expanded for t in targets)

    # リダイレクト先がガード設定なら、どのコマンドでも上書きになる
    for target in _redirect_write_targets(cmd):
        if _hits(target):
            return (
                f"エージェントのガード設定 (`{target}`) を上書きしようとしています。\n"
                "hook や permission の無効化に繋がるため許可されていません。"
            )

    # インラインコードの中でパスを直接触る形 (`open('...', 'w')` など)。
    # インラインコードは読み書きの区別が静的に付かないので一律で止める。
    #
    # ★ この走査はコマンド全体ではなく、インタプリタのインラインコード
    #   セグメントに限定する。全体を走査すると、閉じ引用符と次の開き引用符の
    #   間 (実際にはクォートされていないシェルコード) を 1 つの引用文字列と
    #   誤認する。例: `echo "a"; ls ~/.config/agents; echo "b"` の
    #   `; ls ~/.config/agents; echo ` が引用文字列として一致してしまい、
    #   読み取りしかしていないコマンドが拒否されていた。
    for segment in _segments(cmd):
        if not _is_inline_code_segment(segment):
            continue
        for m in re.finditer(
            r"""['"]([^'"]*(?:\.claude|\.copilot|/agents|\.git/)[^'"]*)['"]""", segment
        ):
            if _hits(m.group(1)):
                return (
                    f"エージェントのガード設定 (`{m.group(1)}`) を操作しようとしています。\n"
                    "インラインコードは読み書きの区別が付かないため許可されていません。\n"
                    f"代替: 内容を見るだけなら `cat {m.group(1)}` や "
                    f"`grep <pattern> {m.group(1)}` を使ってください。\n"
                    "設定を変えたい場合は chezmoi のソースを編集してください。"
                )

    # 環境変数の差し替えで hook の読み込み先やモジュール解決を乗っ取る形
    for m in re.finditer(r"\b(AGENTS_CONFIG_DIR|PYTHONPATH|CLAUDE_[A-Z_]*HOOK[A-Z_]*)=(\S*)", cmd):
        name, value = m.group(1), m.group(2)
        if name == "PYTHONPATH":
            expanded = value.strip("'\"").replace("~", os.path.expanduser("~"), 1)
            absolute = os.path.normpath(os.path.join(os.getcwd(), expanded))
            # プロジェクト内への追加は正当なので、外部を指す場合だけ止める
            if not absolute.startswith(os.getcwd() + os.sep):
                return (
                    f"`PYTHONPATH={value}` で hook のモジュール解決先を差し替えようと"
                    "しています。\nリポジトリ外のパスの指定は許可されていません。"
                )
            continue
        return (
            f"`{name}` を差し替えて hook の設定読み込み先を変えようとしています。\n"
            "hook や permission の無効化に繋がるため許可されていません。"
        )

    entry = code_entry_env(cmd)
    if entry is not None:
        return (
            f"シェルが値をコードとして実行する入口の環境変数 (`PS4` など。今回は `{entry}`) の設定は許可されていません。\n"
            "対象は PROMPT_COMMAND・BASH_ENV・LD_PRELOAD・LD_AUDIT・DYLD_INSERT_LIBRARIES・BASH_FUNC_* と、"
            "値にコマンド置換などを含む PS4、`compgen -C` / `complete -C` / `mapfile -C` です。"
        )

    mutating = {
        "rm",
        "rmdir",
        "unlink",
        "mv",
        "cp",
        "chmod",
        "chown",
        "truncate",
        "shred",
        "ln",
        "sed",
        "tee",
        "dd",
        "install",
    }
    # chezmoi は破壊的サブコマンドのときだけ対象にする (diff / status は無害)
    chezmoi_mutating = {"forget", "destroy", "remove", "unmanage"}
    for command in _commands(cmd):
        tokens = list(command.argv)
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head == "chezmoi":
            if len(tokens) < 2 or tokens[1] not in chezmoi_mutating:
                continue
        elif head not in mutating:
            continue
        for token in tokens[1:]:
            if _hits(token):
                return (
                    f"エージェントのガード設定 (`{token}`) を変更しようとしています。\n"
                    "hook や permission の無効化に繋がるため許可されていません。\n"
                    "設定を変えたい場合は chezmoi のソースを編集してください。"
                )
    return None


def check_shell_startup_write(cmd: str) -> str | None:
    """シェル起動ファイルや認証ファイルへの書き込みを検出する。

    追記されると以後のすべてのシェルで任意コードが走るため、永続化の
    典型的な足がかりになる。読み取りは許可する
    (`cp ~/.bashrc ./backup/` のように起動ファイルを複製元にする形は通す)。
    """
    targets = (
        ".bashrc",
        ".bash_profile",
        ".bash_login",
        ".zshrc",
        ".zshenv",
        ".zprofile",
        ".profile",
        ".login",
        ".cshrc",
        ".kshrc",
        "authorized_keys",
        "known_hosts",
        ".ssh/config",
        ".netrc",
        "crontab",
        ".gitconfig",
    )

    def _hits(token: str) -> str | None:
        cleaned = token.strip("'\"")
        base = os.path.basename(cleaned.rstrip("/"))
        for target in targets:
            if "/" in target:
                if cleaned.endswith(target):
                    return target
            elif base == target:
                return target
        return None

    for token in _write_targets(cmd):
        if _hits(token):
            return (
                f"シェル起動ファイル `{token}` へ書き込もうとしています。\n"
                "以後のシェルで任意コードが走るため許可されていません。"
            )
    # インラインコードからの書き込み。読み書きの区別が静的に付かないので、
    # 起動ファイルのパスを参照している時点で止める。
    # 引用符の対応は静的に取れないため、パスになりうる文字列を切り出して見る。
    for segment in _segments(cmd):
        if not _is_inline_code_segment(segment):
            continue
        for token in re.split(r"[^\w./~@:-]+", segment):
            # `users[0].login` のような属性アクセスと区別するため、
            # パス区切りかホーム参照を含むものだけを対象にする
            if not token or not ("/" in token or token.startswith("~")):
                continue
            if _hits(token):
                return (
                    f"インラインコードがシェル起動ファイル `{token}` を"
                    "参照しています。\n読み書きの区別が付かないため"
                    "許可されていません。"
                )
    return None


def check_privilege_escalation(cmd: str) -> str | None:
    """setuid 付与やアカウント/認証設定の変更を検出する。"""
    for command in _commands(cmd):
        tokens = list(command.argv)
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head == "chmod":
            for token in tokens[1:]:
                # `a+s` などの記号表記と、setuid/setgid ビットを含む 4 桁表記
                if re.fullmatch(r"[ugoa]*\+[rwxXst]*s[rwxXst]*", token) or (
                    re.fullmatch(r"[0-7]{4}", token) and int(token[0]) & 0o6
                ):
                    return (
                        f"`chmod {token}` は setuid/setgid を付与する操作です。\n"
                        "権限昇格に繋がるため許可されていません。"
                    )
        if head in {
            "usermod",
            "useradd",
            "adduser",
            "groupadd",
            "passwd",
            "chpasswd",
            "visudo",
            "gpasswd",
        }:
            return (
                f"`{head}` はアカウント・認証設定を変更する操作です。\n"
                "権限昇格に繋がるため許可されていません。"
            )
    # shadow / sudoers は root 専用で、読み取り自体が機密 (ハッシュや昇格経路)。
    # passwd / group は world-readable なので、書き換えるときだけ止める。
    if re.search(r"/etc/(?:sudoers|shadow)", cmd):
        return (
            "認証設定ファイル (/etc/shadow, /etc/sudoers) を操作しようとしています。\n"
            "権限昇格に繋がるため許可されていません。"
        )
    if any(re.search(r"/etc/(?:passwd|group)", target) for target in _write_targets(cmd)):
        return (
            "アカウント設定ファイル (/etc 配下) を書き換えようとしています。\n"
            "権限昇格に繋がるため許可されていません。"
        )
    return None


_MISE_GLOBAL_FLAGS = tables.as_set("rules_guard", "mise_global_flags")


_MISE_GLOBAL_SUBCOMMANDS = {
    ("settings", "set"): "mise の設定を書き換えます",
    ("settings", "unset"): "mise の設定を書き換えます",
    ("settings", "add"): "mise の設定を書き換えます",
    ("global",): "ホームのグローバル設定を書き換えます",
}


# ツール自身を置き換える / 導入物を消す操作。承認の余地なく拒否する。
# common.toml に書けない (mise は runner 扱いで normalize が先頭を落とす)
_MISE_FATAL_SUBCOMMANDS = {
    ("self-update",): "mise 自身を更新します",
    ("implode",): "mise の導入物をすべて削除します",
}


_COMPILER_BINS = tables.as_set("rules_guard", "compiler_bins")


def _writes_outside_workspace(path: str) -> bool:
    """コンパイラの出力先などが workspace の外を指すか。

    判定できないとき (workspace 不明・変数展開あり) は False を返す。ここは
    「プロジェクト外への影響」を拾うための補助で、fail-closed にすると
    通常のビルドまで止まるため。
    """
    workspace = _workspace_root()
    if workspace is None or not path:
        return False
    if any(ch in path for ch in "$`"):
        return False
    expanded = os.path.expanduser(path)
    resolved = os.path.normpath(os.path.join(workspace, expanded))
    return not resolved.startswith(workspace + os.sep)


def check_tool_self_update(cmd: str) -> str | None:
    """ツール自身を置き換える / 導入物を消す操作を検出する。

    `uv self update` などは common.toml の deny で拾えるが、mise は runner
    扱いで normalize が先頭の `mise` を落とすため一致しない。ここで判定する。

    エージェントがツールチェーンを更新する正当な理由は無く、影響は全
    プロジェクトに及ぶ。元のバージョンを知らないと戻せないので deny にする。
    """
    for segment in _segments(cmd):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        if not tokens or _basename(tokens[0].strip("'\"")) != "mise":
            continue
        subcommands = tuple(t.strip("'\"") for t in tokens[1:] if not t.startswith("-"))
        for prefix, why in _MISE_FATAL_SUBCOMMANDS.items():
            if subcommands[: len(prefix)] == prefix:
                return (
                    f"`mise {' '.join(prefix)}` は{why}。\n"
                    "全プロジェクトに影響し元に戻しにくいため許可されていません。\n"
                    "必要ならユーザー自身で実行してください。"
                )
    return None


def check_global_env_mutation(cmd: str) -> str | None:
    """プロジェクトの外に残る環境変更を検出する。

    `mise use -g` はホームの設定を書き換え、`cmake --build --target install` は
    システムへファイルを置く。どちらもフラグの位置が自由なので、
    common.toml の前方一致パターンでは取りこぼす。
    """
    for segment in _segments(cmd):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0].strip("'\""))
        rest = [t.strip("'\"") for t in tokens[1:]]
        if head == "mise":
            subcommands = tuple(t for t in rest if not t.startswith("-"))
            if subcommands[:1] == ("use",) and (_MISE_GLOBAL_FLAGS & set(rest)):
                return (
                    "`mise use -g` はホームのグローバル設定を書き換えます。\n"
                    f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                    "プロジェクト内で済むなら `-g` を外してください。"
                )
            for prefix, why in _MISE_GLOBAL_SUBCOMMANDS.items():
                if subcommands[: len(prefix)] == prefix:
                    return (
                        f"`mise {' '.join(prefix)}` は{why}。\n"
                        f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                        "内容を確認して問題なければ承認してください。"
                    )
        if head == "cmake" and "--target" in rest:
            target = rest[rest.index("--target") + 1 :]
            if target and target[0] == "install":
                return (
                    "`cmake --build --target install` はビルド成果物を"
                    "システムへインストールします。\n"
                    f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                    "インストール先を確認して問題なければ承認してください。"
                )
        if head in _COMPILER_BINS and "-o" in rest:
            output = rest[rest.index("-o") + 1 :]
            if output and _writes_outside_workspace(output[0]):
                return (
                    f"`{head} -o {output[0]}` はプロジェクトの外へ実行ファイルを"
                    "書き出します。\n"
                    f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                    "出力先を確認して問題なければ承認してください。"
                )
    return None


def check_git_config_write(cmd: str) -> str | None:
    """任意コマンド実行や資格情報の奪取に繋がる git config の書き込みを止める。

    `git config alias.p push` のように設定キーへ値を書くと、以後 `git p` で
    deny 対象のコマンドを実行できてしまう。キー名は接頭辞が可変なので、
    トークン完全一致のポリシー照合では拾えない。
    """
    dangerous = (
        "alias.",
        "core.hookspath",
        "core.editor",
        "core.pager",
        "core.sshcommand",
        "core.fsmonitor",
        "credential.",
        "url.",
        "filter.",
        "diff.external",
        "difftool.",
        "mergetool.",
        "pager.",
        "include.path",
        "includeif.",
        "sequence.editor",
        "gpg.program",
        "ssh.variant",
        "protocol.",
    )
    for command in _commands(cmd):
        tokens = list(command.argv)
        if len(tokens) < 3:
            continue
        if _basename(tokens[0]) != "git" or tokens[1] != "config":
            continue
        rest = [t for t in tokens[2:] if not t.startswith("-")]
        if not rest:
            continue
        key = rest[0].lower()
        if any(key.startswith(prefix) for prefix in dangerous) and len(rest) > 1:
            return (
                f"`git config {rest[0]}` は任意コマンドの実行や資格情報の取得に"
                "繋がる設定です。\nエージェント経由での変更は許可されていません。"
            )
    return None


def check_block_device_write(cmd: str) -> str | None:
    """`dd of=/dev/sda` のようにブロックデバイスへ直接書き込んでいないか。"""
    for segment in _segments(cmd):
        m = re.search(r"\bof=(/dev/\S+)", segment)
        if m and not re.match(r"^/dev/(?:null|stdout|stderr|tty|zero)$", m.group(1)):
            return (
                f"ブロックデバイス `{m.group(1)}` へ直接書き込もうとしています。\n"
                "ディスクを破壊する操作は許可されていません。"
            )
    return None


# PR ビューアの統合 CLI (merge-cli.ts) を起動するランタイムと、実行しない先頭のコマンド
_MERGE_CLI_RUNTIMES = {
    "node",
    "nodejs",
    "tsx",
    "ts-node",
    "bun",
    "bunx",
    "deno",
    "npx",
    "pnpx",
    "pnpm",
    "yarn",
    "npm",
}
_MERGE_CLI_NON_EXECUTING = {"echo", "printf", "grep", "rg", "cat", "man", "which", "type"}
_MERGE_CLI_DENIED_SUBCOMMANDS = {"merge", "recover"}


def check_pr_viewer_merge_cli(cmd: str) -> str | None:
    """PR ビューアの統合 CLI の `merge` / `recover` を、エージェントが叩く操作を拒否する。

    統合の権限は人のブラウザ操作だけにある。`plan` や、スクリプトを実行しない
    参照 (`grep` / `cat` / `git log -- <path>`) は拒否しない。
    """
    for segment in _segments(cmd):
        for part in _policy.split_command_segments(segment) if _policy is not None else [segment]:
            try:
                tokens = shlex.split(part)
            except ValueError:
                tokens = part.split()
            while tokens and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
                tokens = tokens[1:]
            if not tokens or _basename(tokens[0]) in _MERGE_CLI_NON_EXECUTING:
                continue
            script = next((i for i, t in enumerate(tokens) if t.endswith("merge-cli.ts")), None)
            if script is None:
                continue
            if script > 0 and not any(_cmd_name(t) in _MERGE_CLI_RUNTIMES for t in tokens[:script]):
                continue
            subcommand = next((t for t in tokens[script + 1 :] if not t.startswith("-")), None)
            if subcommand in _MERGE_CLI_DENIED_SUBCOMMANDS:
                return "PR ビューアの統合 CLI の merge / recover は、人が操作するものです。エージェントは実行できません。"
    return None
