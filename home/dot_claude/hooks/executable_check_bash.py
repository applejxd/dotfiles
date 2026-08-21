#!/usr/bin/env python3
"""
Agent (Claude Code / Copilot CLI) PreToolUse hook: Bash コマンドの安全性チェック

危険なパターンを検出して deny (拒否) または ask (ユーザー承認を要求) を返す。

  - deny: 承認の余地なく拒否する。センシティブ情報の露出や壊滅的な削除など
  - ask : エージェントが提案し、ユーザーが承認すればそのまま実行される。
          ファイル削除のような「危険だが承認すれば妥当」な操作に使う

判定の主軸は common.toml の [bash] deny / ask。同じリストから Claude の
permission も生成されるので、ルールは 1 箇所に書けばよい。
permission リストは Claude にしか効かないが、この hook は Copilot にも効く。

出力規約は ``agent_compat.emit_pretool_deny`` / ``emit_pretool_ask`` に委譲する
(両ツール対応)。

fail-closed: ポリシー設定を読めない場合は素通りさせず deny する。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 同一ディレクトリの lib/ にあるヘルパを import
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (  # noqa: E402
    emit_pretool_ask,
    emit_pretool_deny,
    get_command,
    normalize_tool_kind,
    read_input,
)

# ~/.config/agents/ (chezmoi 管理) にあるポリシーモジュールを import
# AGENTS_CONFIG_DIR で差し替え可能 (テスト・コンテナから repo の実体を指すため)
_AGENTS_DIR = os.environ.get("AGENTS_CONFIG_DIR")
if not _AGENTS_DIR:
    _CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    _AGENTS_DIR = os.path.join(_CONFIG_HOME, "agents")
sys.path.insert(0, _AGENTS_DIR)
try:
    import command_policy as _policy  # noqa: E402
except ImportError:  # pragma: no cover
    _policy = None  # type: ignore[assignment]

# ─── センシティブパスの判定 ──────────────────────────────────────────
# コマンド文字列全体への部分一致は誤検知が多い
# (`grep -rn token .` の token は検索語であってパスではない、
#  `git commit -m "fix token refresh"` の token はメッセージの一部)。
# 引数トークンを 1 つずつ見て「パスらしいか」→「センシティブか」の順で判定する。

# ファイル名そのものが秘密を意味するもの (basename の完全一致 / 前方一致)
_SENSITIVE_BASENAMES = {
    ".env", ".netrc", ".pypirc", ".npmrc", "credentials", "key.txt",
    "shadow", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}
_SENSITIVE_BASENAME_PREFIXES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
_SENSITIVE_SUFFIXES = (
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk", ".asc",
)
# パスに含まれると秘密領域とみなすディレクトリ
_SENSITIVE_DIRS = (".ssh", ".gnupg", ".aws", ".config/gh", "secrets")
# basename に含まれると秘密とみなす語 (パスらしいトークンにのみ適用)
_SENSITIVE_WORD_RE = re.compile(
    r"(?:secret|password|passwd|credential|api[_-]?key|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
# 明示的に除外する (サンプル・テンプレート)
_SENSITIVE_EXEMPT_RE = re.compile(
    r"(?:\.example$|\.sample$|\.template$|\.tmpl$|\.md$|\.rst$|\.txt\.example$)",
    re.IGNORECASE,
)
# /etc 配下の特定ファイル
_SENSITIVE_ABS_PATHS = {"/etc/shadow", "/etc/passwd", "/etc/sudoers"}

# grep 系は最初の非フラグ引数が検索語なのでパス判定から除外する
_PATTERN_FIRST_COMMANDS = {"grep", "rg", "ag", "ack", "egrep", "fgrep", "sed", "awk"}
# 末尾の引数が書き込み先になるコマンド (コピー先が .env でも読み取りではない)
_DEST_LAST_COMMANDS = {"cp", "mv", "install", "ln", "rsync", "scp"}


def _looks_like_path(token: str) -> bool:
    """引数がパスらしいか。検索語や通常の単語を除外するための判定。"""
    if "/" in token or token.startswith("~"):
        return True
    if token.startswith(".") and len(token) > 1:
        return True
    # foo.pem のように既知の拡張子を持つもの
    return token.lower().endswith(_SENSITIVE_SUFFIXES)


def _is_sensitive_token(token: str) -> str | None:
    """パスらしいトークンがセンシティブなら、その理由を返す。"""
    cleaned = token.strip("'\"")
    if not cleaned or not _looks_like_path(cleaned):
        return None

    expanded = cleaned.replace("~", os.path.expanduser("~"), 1)
    normalized = os.path.normpath(expanded)
    base = os.path.basename(normalized)

    if _SENSITIVE_EXEMPT_RE.search(base):
        return None
    # `.env.example` のようにサンプルであることが接尾辞で分かるもの
    if base.startswith(".env.") and base != ".env.local":
        return None

    if normalized in _SENSITIVE_ABS_PATHS:
        return normalized
    parts = normalized.split("/")
    for d in _SENSITIVE_DIRS:
        if d in parts or (d.count("/") and d in normalized):
            return f"{d} 配下"
    if base in _SENSITIVE_BASENAMES or base.startswith(_SENSITIVE_BASENAME_PREFIXES):
        return base
    if base.lower().endswith(_SENSITIVE_SUFFIXES):
        return base
    if _SENSITIVE_WORD_RE.search(base):
        return base
    return None


def is_sensitive_path(text: str) -> str | None:
    """コマンド文字列にセンシティブなパス引数が含まれていれば理由を返す。

    ``cp .env.example .env`` のように「サンプルから作る」形は正当なので、
    cp / mv の最終引数 (コピー先) は判定対象から外す。
    """
    tokens = text.split()
    if not tokens:
        return None
    head = _basename(tokens[0].strip("'\""))
    args = tokens[1:]
    if head in _DEST_LAST_COMMANDS and len(args) >= 2:
        # 末尾は書き込み先。読み取り元だけを見る
        args = args[:-1]
    skip_pattern_arg = head in _PATTERN_FIRST_COMMANDS
    for token in args:
        if token.startswith("-"):
            continue
        if skip_pattern_arg:
            # 最初の非フラグ引数は検索語なので飛ばす
            skip_pattern_arg = False
            continue
        reason = _is_sensitive_token(token)
        if reason:
            return reason
    return None

# ─── ファイル内容を読むコマンド ──────────────────────────────────────
FILE_READ_COMMANDS = [
    "grep", "rg", "ag", "ack", "cat", "tac", "head", "tail", "nl",
    "sed", "awk", "less", "more", "sort", "uniq", "cut", "column",
    "strings", "xxd", "hexdump", "jq", "yq",
    "base64", "od", "xxd", "diff", "vimdiff",
    # 内容を別の場所へ複製・転送するもの (読み取りと同じ露出リスク)
    "cp", "mv", "install", "rsync", "scp", "sftp", "dd", "tee",
    "ln", "shred", "split", "gpg", "openssl",
]

# ─── 環境変数を露出するコマンド ─────────────────────────────────────
# 引数なしの全件露出に加え、`printenv AWS_SECRET_ACCESS_KEY` のような
# 個別参照や `env | grep key` のような絞り込みも対象にする。
ENV_EXPOSURE_BINS = {"env", "printenv", "export", "set", "declare", "typeset"}
# 環境変数名としてセンシティブなもの
_SENSITIVE_ENV_RE = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API[_-]?KEY|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|SESSION)",
    re.IGNORECASE,
)

# ─── アーカイブコマンド ───────────────────────────────────────────────
ARCHIVE_COMMANDS = ["tar", "zip", "gzip", "bzip2", "7z", "xz"]

# ─── インラインコードを受け取るインタプリタ ─────────────────────────
_INLINE_CODE_BINS = {"python", "perl", "ruby", "node", "php", "awk", "gawk", "mawk"}
_INLINE_CODE_FLAGS = {"-c", "-e", "-E", "-r", "-p", "--eval", "--print"}
# コード片から外部コマンドを起動する形
_INLINE_EXEC_RE = re.compile(
    r"(?:os\.system|subprocess\.|popen|execSync|spawnSync|child_process|"
    r"\bsystem\s*\(|\bexec\s*\(|\bqx\s*[({/]|`[^`]+`|\bshell_exec\b|\bpassthru\b)",
    re.IGNORECASE,
)

# ─── curl/wget でのファイル送信パターン ──────────────────────────────
CURL_FILE_SEND_PATTERN = re.compile(
    r"\b(curl|wget)\b.*(?:-d\s*@|-F\s*['\"]?[^=]+=@|--data-binary\s*@)",
    re.IGNORECASE,
)


def _segments(cmd: str) -> list[str]:
    """normalize 済みセグメント + 元の文字列を返す。

    normalize は shlex を通るのでクォートや ``${VAR}`` の形が変わる。
    パターン照合では元の文字列も併せて見て取りこぼさないようにする。
    """
    segs = list(_policy.normalize(cmd)) if _policy is not None else []
    segs.append(cmd)
    return segs


def check_file_read(cmd: str) -> str | None:
    """ファイル読み込み・複製コマンドがセンシティブパスを対象にしていないか"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head not in FILE_READ_COMMANDS:
            continue
        matched = is_sensitive_path(segment)
        if matched:
            return (
                f"`{head}` がセンシティブなパスを対象にしています "
                f"(パターン: {matched})"
            )
    return None


def check_env_exposure(cmd: str) -> str | None:
    """環境変数を露出するコマンドを検出。

    引数なしの全件出力に加え、`printenv AWS_SECRET_ACCESS_KEY` のような
    個別参照や `env | grep -i key` のような絞り込みも拒否する。
    `env FOO=1 cmd` は normalize がラッパーとして剥がすのでここには来ない。
    """
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head not in ENV_EXPOSURE_BINS:
            continue
        args = [t for t in tokens[1:] if not t.startswith("-")]
        if not args:
            return (
                f"環境変数を全件出力するコマンドは許可されていません: `{segment.strip()}`\n"
                "特定の変数を確認する場合は `echo $VAR_NAME` を使用してください。"
            )
        if any(_SENSITIVE_ENV_RE.search(a) for a in args):
            return (
                f"センシティブな環境変数を出力しようとしています: `{segment.strip()}`"
            )
    # `env | grep -i key` のように絞り込む形
    if re.search(r"\b(?:env|printenv)\b\s*(?:\||$)", cmd) and _SENSITIVE_ENV_RE.search(cmd):
        return (
            f"環境変数からセンシティブな値を抽出しようとしています: `{cmd.strip()[:200]}`"
        )
    return None


def check_archive(cmd: str) -> str | None:
    """アーカイブコマンドがセンシティブパスを含んでいないか"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head not in ARCHIVE_COMMANDS:
            continue
        matched = is_sensitive_path(segment)
        if matched:
            return (
                f"`{head}` でセンシティブなパスをアーカイブしようとしています "
                f"(パターン: {matched})"
            )
    return None


def check_curl_file_send(cmd: str) -> str | None:
    """curl/wget でセンシティブファイルの内容を送信しようとしていないか"""
    if CURL_FILE_SEND_PATTERN.search(cmd):
        matched = is_sensitive_path(cmd)
        if matched:
            return (
                f"curl/wget でセンシティブなファイルを送信しようとしています "
                f"(パターン: {matched})"
            )
    return None


def check_xargs_pipe(cmd: str) -> str | None:
    """find | xargs cat/grep のような組み合わせを検出"""
    if "xargs" in cmd:
        for read_cmd in FILE_READ_COMMANDS:
            if re.search(rf"\bxargs\b.*\b{re.escape(read_cmd)}\b", cmd):
                matched = is_sensitive_path(cmd)
                if matched:
                    return (
                        f"xargs + `{read_cmd}` でセンシティブなパスを読み込もうとしています "
                        f"(パターン: {matched})"
                    )
    return None


def _pip_suggestion(cmd: str) -> str:
    """pip コマンドに対応する uv/uvx の代替案を返す"""
    if re.search(r"\binstall\b", cmd):
        return "代替: `uv add <package>` または `uvx <package>`"
    if re.search(r"\buninstall\b", cmd):
        return "代替: `uv remove <package>`"
    if re.search(r"\blist\b", cmd):
        return "代替: `uv pip list`"
    if re.search(r"\bshow\b", cmd):
        return "代替: `uv pip show <package>`"
    if re.search(r"\bfreeze\b", cmd):
        return "代替: `uv pip freeze`"
    return "代替: `uv <subcommand>` または `uvx <tool>`"


def check_git_c_dangerous(cmd: str) -> str | None:
    """`git -C <dir>` 経由で deny 対象のサブコマンドを実行しようとしていないか"""
    # git -C <path> [options] <subcommand> の形を検出
    if not re.search(r"\bgit\b\s+-C\b", cmd):
        return None
    dangerous = ("push", "reset", "rebase", "config")
    for sub in dangerous:
        if re.search(rf"\bgit\b.*\s-C\s.*\b{sub}\b", cmd, re.IGNORECASE):
            return (
                f"`git -C` で禁止されたサブコマンド `{sub}` の実行を検出しました。\n"
                f"このコマンドはセキュリティポリシーによりブロックされています。"
            )
    return None


_FIND_DANGEROUS_EXEC_RE = re.compile(
    r"\bfind\b.+?"
    r"(?:"
    r"-exec\s+(?:rm|unlink|shred|rmdir)\b"  # -exec rm/unlink/shred/rmdir
    r"|-delete\b"                            # -delete フラグ
    r")",
    re.IGNORECASE | re.DOTALL,
)


def check_find_dangerous(cmd: str) -> str | None:
    """`find -exec rm` や `find -delete` でファイルを削除しようとしていないか"""
    if not re.search(r"\bfind\b", cmd):
        return None
    if _FIND_DANGEROUS_EXEC_RE.search(cmd):
        return (
            "`find` コマンドによるファイル削除操作（-exec rm / -delete 等）です。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            "削除対象を確認して問題なければ承認してください。"
        )
    return None


_PIP_BIN_RE = re.compile(r"^(?:/\S*/)?pip[0-9.]*$")
_PYTHON_BIN_RE = re.compile(r"^(?:/\S*/)?python[0-9.]*$")
# -mpip のように -m と値がくっついた形
_PYTHON_DASH_M_RE = re.compile(r"^-m(.+)$")
# uvx / uv tool run / pipx など、pip を間接的に起動しうるランナー
_PIP_RUNNERS = {"uvx", "pipx"}


def check_pip_redirect(cmd: str) -> str | None:
    """pip / python -m pip の直接使用を uv/uvx にリダイレクトする。

    ポリシー照合と同じ normalize を通してから各セグメントの先頭トークンを見るので、
    以下の抜け道をすべて塞ぐ:

      * ``cd foo && pip install x``  (生文字列の先頭アンカーだと素通りしていた)
      * ``pip3 install x``           (``pip\\b`` が ``pip3`` に一致しなかった)
      * ``python3 -m pip install x`` (``\\bpython\\b`` が ``python3`` に一致しなかった)
      * ``python3 -mpip install x``  (``-m`` と値がくっついた形)
      * ``/usr/bin/pip install x``   (絶対パス指定)
      * ``uvx pip install x``        (ランナー経由)
      * ``uv pip install x`` は許可 (uv のサブコマンドであり pip 本体ではない)
    """
    segments = (
        _policy.normalize(cmd) if _policy is not None else [cmd]
    )
    for segment in segments:
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if _PIP_BIN_RE.match(head):
            return (
                "pip の直接使用は禁止されています。uv / uvx を使用してください。\n"
                f"{_pip_suggestion(segment)}"
            )
        if head in _PIP_RUNNERS and len(tokens) > 1:
            # uvx pip install ... / pipx run pip ...
            for token in tokens[1:]:
                if token.startswith("-"):
                    continue
                if _PIP_BIN_RE.match(_basename(token)):
                    return (
                        f"`{head}` 経由の pip 実行は禁止されています。"
                        "uv / uvx を使用してください。\n"
                        f"{_pip_suggestion(segment)}"
                    )
                break
        if _PYTHON_BIN_RE.match(head):
            for i, token in enumerate(tokens[1:], start=1):
                # -m pip (値が別トークン)
                if token == "-m" and i + 1 < len(tokens):
                    if _PIP_BIN_RE.match(_basename(tokens[i + 1])):
                        return (
                            f"`{head} -m pip` は禁止されています。"
                            "uv / uvx を使用してください。\n"
                            f"{_pip_suggestion(segment)}"
                        )
                # -mpip (値がくっついた形)
                m = _PYTHON_DASH_M_RE.match(token)
                if m and _PIP_BIN_RE.match(_basename(m.group(1))):
                    return (
                        f"`{head} -m pip` は禁止されています。"
                        "uv / uvx を使用してください。\n"
                        f"{_pip_suggestion(segment)}"
                    )
    return None


def check_policy_loaded(cmd: str) -> str | None:
    """ポリシー設定を読めないときは fail-closed で拒否する。

    以前は import 失敗時に ``_policy = None`` として全チェックを
    素通りさせていたため、``~/.config/agents/`` の破損 (docs のトラブルシュートに
    ある ``__pycache__`` 由来の import 失敗など) で **全ガードが無言で消えて**いた。
    ここで止めることで、壊れていることが必ず表面化する。
    """
    if _policy is None:
        return (
            f"ポリシーモジュールを読み込めませんでした ({_AGENTS_DIR}/command_policy.py)。\n"
            "安全のため bash コマンドを拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行し、"
            f"`{_AGENTS_DIR}/__pycache__/` が残っていれば削除してください。"
        )
    if not Path(_policy.DEFAULT_COMMON_PATH).is_file():
        return (
            f"ポリシー定義が見つかりません ({_policy.DEFAULT_COMMON_PATH})。\n"
            "安全のため bash コマンドを拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行してください。"
        )
    return None


_PIPE_TO_SHELL_RE = re.compile(
    r"\|\s*(?:sudo\s+)?(?:/\S*/)?(?:sh|bash|zsh|dash|ksh|fish|ash|python[0-9.]*|perl|ruby|node)\b"
    r"(?!\s+[^\s|&;<>-])",
)


def check_pipe_to_shell(cmd: str) -> str | None:
    """`curl ... | sh` のように取得したものをそのまま実行していないか。

    引数付きの `| bash script.sh` は対象外 (スクリプトを渡しているだけで、
    パイプの内容をコードとして実行しているわけではない)。
    """
    if _PIPE_TO_SHELL_RE.search(cmd):
        return (
            "取得した内容をそのままシェル/インタプリタに流し込んでいます。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            "内容を検証できないため許可されていません。\n"
            "一度ファイルに保存して内容を確認してから実行してください。"
        )
    return None


def check_git_add_sensitive(cmd: str) -> str | None:
    """`git add .env` のようにセンシティブファイルをバージョン管理に載せていないか"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if len(tokens) < 3:
            continue
        if _basename(tokens[0]) != "git" or tokens[1] not in ("add", "stage"):
            continue
        for token in tokens[2:]:
            if token.startswith("-"):
                continue
            reason = _is_sensitive_token(token)
            if reason:
                return (
                    f"センシティブなファイルを git に追加しようとしています ({reason})。\n"
                    "秘密情報はコミットせず、.gitignore に追加してください。"
                )
    return None


def check_interpreter_inline_code(cmd: str) -> str | None:
    """`python3 -c "..."` / `perl -e "..."` の中でセンシティブな操作をしていないか。

    normalize は素のコマンド列 (`os.system('git push')` の中身など) を
    取り出せないことがあるため、コード文字列そのものを検査する。
    """
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = re.sub(r"[0-9.]+$", "", _basename(tokens[0]))
        if head not in _INLINE_CODE_BINS:
            continue
        if not any(t in _INLINE_CODE_FLAGS for t in tokens[1:]):
            continue
        # コード片にセンシティブなパスや外部実行が含まれていないか
        reason = is_sensitive_path(segment)
        if reason:
            return (
                f"`{head}` のインラインコードがセンシティブなパスを参照しています ({reason})。"
            )
        if _INLINE_EXEC_RE.search(segment):
            return (
                f"`{head}` のインラインコードから外部コマンドを実行しようとしています。\n"
                f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                "スクリプトファイルに書いて内容を確認できる形にしてください。"
            )
    return None


def check_policy_deny(cmd: str) -> str | None:
    """common.toml の bash.deny に該当すれば block する.

    Claude Code permission リストの既知バグ (cd && bypass, git -C bypass,
    compound 命令の個別評価欠如) に対する最終防波堤。shell command を
    normalize (cd, git -C, compound 分割) してから pattern match する。
    """
    patterns = _policy.load_deny()
    matched = _policy.find_match(cmd, patterns)
    if matched:
        return (
            f"`{matched}` は deny パターンに一致するためブロックされました。\n"
            "このコマンドは common.toml の [bash] deny で禁止されています。"
        )
    return None


def check_policy_ask(cmd: str) -> str | None:
    """common.toml の bash.ask に該当すればユーザー承認を要求する.

    deny と違い、ユーザーが承認すればそのまま実行される。
    deny チェックの後に評価されるので、より具体的な deny パターン
    (例: ``git reset --hard``) が一般形の ask (``git reset``) に優先する。
    """
    patterns = _policy.load_ask()
    matched = _policy.find_match(cmd, patterns)
    if matched:
        return (
            f"`{matched}` は承認が必要な操作です (common.toml の [bash] ask)。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            "内容を確認して問題なければ承認してください。"
        )
    return None


# ─── rm の壊滅的ターゲット (承認の余地なく deny) ──────────────────────
# critical_ask で `rm -rf` を承認可能にする代わりに、取り返しのつかない
# ターゲットだけはここで hard-deny する。
# cwd 配下 (`.` / `./*` / `*`) は critical_ask 側に任せる (プロジェクト内は
# ユーザーが承認して消せるべきなので、ここでは落とさない)。
_CATASTROPHIC_DIRS = {
    "/",
    "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64", "/opt",
    "/proc", "/root", "/sbin", "/srv", "/sys", "/usr", "/var",
    "/Applications", "/Library", "/System", "/Users", "/Volumes",
}
_HOME_TOKENS = {"~", "$HOME", "${HOME}"}
# /home/<user> や /Users/<user> のようなホームディレクトリそのもの
_HOME_DIR_RE = re.compile(r"^/(?:home|Users)/[^/]+$")
_RM_BIN_RE = re.compile(r"^(?:/\S*/)?rm$")


def _basename(token: str) -> str:
    """``/bin/rm`` -> ``rm``"""
    return token.rsplit("/", 1)[-1] if "/" in token else token


def _canonical_rm_target(raw: str) -> str | None:
    """rm の引数を guard 比較用の正準形にする。

    末尾の ``/*`` と ``/`` を畳む (``/etc/*`` は ``/etc`` と同じ危険度)。
    """
    token = raw.strip().strip("'\"")
    if not token:
        return None
    while token.endswith("/*"):
        token = token[:-2] or "/"
    while len(token) > 1 and token.endswith("/"):
        token = token[:-1]
    return token or None


def _is_catastrophic_rm_target(token: str) -> bool:
    canonical = _canonical_rm_target(token)
    if canonical is None:
        return False
    if canonical in _HOME_TOKENS or canonical == "..":
        return True
    if canonical in _CATASTROPHIC_DIRS:
        return True
    if _HOME_DIR_RE.match(canonical):
        return True
    if canonical == os.path.expanduser("~"):
        return True
    return False


def check_rm_root_guard(cmd: str) -> str | None:
    """`rm` がシステム全体・ホーム・親ディレクトリを対象にしていないか。

    `cd /elsewhere && rm -rf /` や `sh -c "rm -rf ~"` のような回避を防ぐため、
    ポリシー照合と同じ normalize を通してから各セグメントを検査する。
    normalize は shlex を通るため ``${HOME}`` の波括弧が落ちることがある。
    元の文字列も併せて検査して取りこぼさないようにする。
    """
    segments = list(_policy.normalize(cmd)) if _policy is not None else []
    segments.append(cmd)
    for segment in segments:
        tokens = segment.split()
        if not tokens or not _RM_BIN_RE.match(_basename(tokens[0])):
            continue
        if any(t == "--no-preserve-root" for t in tokens):
            return (
                "`rm --no-preserve-root` は許可されていません。\n"
                "ルートディレクトリの削除は承認の対象外です。"
            )
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            if _is_catastrophic_rm_target(token):
                return (
                    f"`rm` が壊滅的なパス `{token}` を対象にしています。\n"
                    "システム全体・ホーム・親ディレクトリの削除は承認の対象外です。\n"
                    "削除したい対象を具体的なパスで指定し直してください。"
                )
    return None


# uv 非依存のチェック（常時有効）
#
# DENY_CHECKS が先に評価される。ASK_CHECKS は deny に該当しなかったものだけを
# 対象にするので、例えば `rm -rf /` は root guard (deny) が critical_ask より
# 優先される。
DENY_CHECKS = [
    check_policy_loaded,      # ★最初に実行: 設定が読めないなら fail-closed
    check_rm_root_guard,      # 壊滅的な削除は承認の余地なし
    # 具体的な代替案を返せるチェックは、汎用の policy_deny より先に置く
    # (先に一致したものがメッセージを決めるため)
    check_pip_redirect,       # pip → uv/uvx (プロジェクト種別を問わず全面禁止)
    check_pipe_to_shell,      # curl ... | sh の類
    check_interpreter_inline_code,  # python -c "os.system(...)" の類
    check_git_add_sensitive,  # git add .env の類
    check_policy_deny,        # common.toml の [bash] deny を強制
    check_env_exposure,       # 引数なし環境変数露出は問答無用でブロック
    check_git_c_dangerous,    # -C 経由の deny サブコマンド実行をブロック
    check_file_read,
    check_archive,
    check_curl_file_send,
    check_xargs_pipe,
]

# 承認を求めるチェック（ユーザーが許可すればそのまま実行される）
ASK_CHECKS = [
    check_policy_ask,         # common.toml の [bash] ask
    check_find_dangerous,     # find -exec rm / -delete によるファイル削除
]


def main() -> None:
    data = read_input()

    if normalize_tool_kind(data.get("tool_name", "")) != "bash":
        sys.exit(0)

    cmd = get_command(data.get("tool_input", {}))
    if not cmd:
        sys.exit(0)

    for check in DENY_CHECKS:
        reason = check(cmd)
        if reason:
            emit_pretool_deny(f"[hook blocked] {reason}")

    for check in ASK_CHECKS:
        reason = check(cmd)
        if reason:
            emit_pretool_ask(f"[hook] 承認が必要です\n{reason}")

    sys.exit(0)


if __name__ == "__main__":
    main()
