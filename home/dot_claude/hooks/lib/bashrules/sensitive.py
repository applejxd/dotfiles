"""秘密情報 (鍵・トークン・認証ファイル) の検出。

★守る対象のファイル名・ディレクトリ・環境変数名は ``tables.toml`` にある。
ファイルを足したいだけなら TOML 側を編集すればよい。
"""

from __future__ import annotations

import os
import re

from . import shellparse, tables
from ._shared import (
    _INTERPRETER_CODE_ARG_FLAGS,
    _SENSITIVE_ENV_RE,
    _SENSITIVE_SUFFIXES,
    _SHELL_CODE_ARG_FLAGS,
    _STDIN_CODE_INTERPRETERS,
    _STDIN_CODE_SHELLS,
    REDIRECT_TARGET_RE,
    _basename,
    _cmd_name,
    _looks_like_path,
    _normalize_guard_path,
    _segments,
    _write_targets,
)

_SENSITIVE_BASENAMES = tables.as_set("sensitive", "sensitive_basenames")


_SENSITIVE_BASENAME_PREFIXES = tables.as_tuple("sensitive", "sensitive_basename_prefixes")


_SENSITIVE_DIRS = tables.as_tuple("sensitive", "sensitive_dirs")


_HEURISTIC_SENSITIVE_DIRS = tables.as_tuple("sensitive", "heuristic_sensitive_dirs")


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


_SOURCE_CODE_SUFFIXES = tables.as_tuple("sensitive", "source_code_suffixes")


_SENSITIVE_ABS_PATHS = tables.as_set("sensitive", "sensitive_abs_paths")


# プロセスの環境変数を覗くパス
_PROC_ENVIRON_RE = re.compile(r"/proc/(?:\d+|self)/environ")


_HISTORY_BASENAMES = tables.as_set("sensitive", "history_basenames")


_CREDENTIAL_PATHS = tables.as_tuple("sensitive", "credential_paths")


_PATTERN_FIRST_COMMANDS = tables.as_set("sensitive", "pattern_first_commands")


_DEST_LAST_COMMANDS = tables.as_set("sensitive", "dest_last_commands")


def _is_sensitive_token(token: str, *, heuristic: bool = True) -> str | None:
    """パスらしいトークンがセンシティブなら、その理由を返す。

    ``heuristic=False`` にすると、語彙による曖昧な判定 (`secrets` という名前の
    ディレクトリなど) を行わず、確実な証拠 (`.env` / `id_rsa` / `.ssh` 配下 /
    `*.pem` など) だけで判定する。
    """
    cleaned = token.strip("'\"")
    if not cleaned:
        return None

    normalized = _normalize_guard_path(cleaned)
    base = os.path.basename(normalized)

    if _SENSITIVE_EXEMPT_RE.search(base):
        return None
    # `.env.example` のようにサンプルであることが接尾辞で分かるもの
    if base.startswith(".env.") and base != ".env.local":
        return None
    # credentials のような既知の basename は slash や拡張子がなくても
    # ファイル名そのものが秘密を意味する。
    if base in _SENSITIVE_BASENAMES or base.startswith(_SENSITIVE_BASENAME_PREFIXES):
        return base
    if base in _HISTORY_BASENAMES:
        return f"シェル履歴 ({base})"
    if not _looks_like_path(cleaned):
        return None

    if normalized in _SENSITIVE_ABS_PATHS:
        return normalized
    if _PROC_ENVIRON_RE.search(normalized):
        return "プロセスの環境変数"
    for cred in _CREDENTIAL_PATHS:
        if normalized.endswith(cred):
            return base
    parts = normalized.split("/")
    for d in _SENSITIVE_DIRS:
        if d in parts or (d.count("/") and d in normalized):
            return f"{d} 配下"
    if heuristic:
        for d in _HEURISTIC_SENSITIVE_DIRS:
            if d in parts:
                return f"{d} 配下"
    if base.lower().endswith(_SENSITIVE_SUFFIXES):
        return base
    if (
        heuristic
        and _SENSITIVE_WORD_RE.search(base)
        and not base.lower().endswith(_SOURCE_CODE_SUFFIXES)
    ):
        return base
    return None


def is_sensitive_path(text: str, *, heuristic: bool = True) -> str | None:
    """コマンド文字列にセンシティブなパス引数が含まれていれば理由を返す。

    ``cp .env.example .env`` のように「サンプルから作る」形は正当なので、
    cp / mv の最終引数 (コピー先) は判定対象から外す。
    ``shellparse`` で単純コマンドに分け、コマンドごとに判定する。
    see docs/change/0012-bash-hook-shared-parser.md
    """
    for command in shellparse.parse(text):
        reason = _sensitive_argument(command, heuristic=heuristic)
        if reason:
            return reason
    return None


def _pieces(value: str) -> list[str]:
    """空白を含む引数 (``python3 -c "..."`` のコード) は断片も見る。"""
    return value.split() if any(c.isspace() for c in value) else [value]


def _sensitive_argument(command: shellparse.Command, *, heuristic: bool) -> str | None:
    argv = command.argv
    candidates: list[str] = []
    if argv:
        candidates = _path_arguments(_basename(argv[0]), list(argv[1:]))
    # リダイレクトの対象 (`cat < .env`)。ヒアドキュメントの区切り語は対象ではない
    candidates += [
        r.target.value
        for r in command.redirects
        if r.target is not None and r.op not in ("<<", "<<-")
    ]
    for candidate in candidates:
        for piece in _pieces(candidate):
            reason = _is_sensitive_token(piece, heuristic=heuristic)
            if reason:
                return reason
    return None


def _path_arguments(head: str, args: list[str]) -> list[str]:
    """パスとして扱う引数 (フラグ・検索語・コピー先を除いたもの)。"""
    if head in _DEST_LAST_COMMANDS and len(args) >= 2:
        # 末尾は書き込み先。読み取り元だけを見る
        args = args[:-1]
    out: list[str] = []
    skip_pattern_arg = head in _PATTERN_FIRST_COMMANDS
    skip_next = False
    for token in args:
        if skip_next:
            # -e / -f の値 (検索語・スクリプト・検索語のファイル)
            skip_next = False
            continue
        if token.startswith("-"):
            if skip_pattern_arg:
                given, separate = _pattern_option(head, token)
                if given:
                    # 検索語をオプションで渡すと、非フラグ引数はすべてパスになる
                    skip_pattern_arg = False
                    skip_next = separate
            continue
        if skip_pattern_arg:
            # 最初の非フラグ引数は検索語なので飛ばす
            skip_pattern_arg = False
            continue
        out.append(token)
    return out


# 検索語 (スクリプト) をオプションで渡すときの短い文字・長いオプションと、短いオプションの束で
# 後ろを値として取る文字 (-A3 / -m1 / awk の -F: など。ここで束の解釈をやめる)。
# 意味がコマンドで違う (ack の -f は一覧、ag の -f は symlink、grep の -F は値なし) ので、
# コマンドごとに持つ
_GREP_PATTERN_OPTIONS = ("ef", ("--regexp", "--file"), "ABCDdm")
_AWK_PATTERN_OPTIONS = ("f", ("--file",), "Fv")
_PATTERN_OPTIONS = {
    "grep": _GREP_PATTERN_OPTIONS,
    "egrep": _GREP_PATTERN_OPTIONS,
    "fgrep": _GREP_PATTERN_OPTIONS,
    "rg": ("ef", ("--regexp", "--file"), "ABCMmgtTdj"),
    "sed": ("ef", ("--expression", "--file"), "l"),
    "awk": _AWK_PATTERN_OPTIONS,
    "mawk": _AWK_PATTERN_OPTIONS,
    "gawk": ("ef", ("--file", "--source"), "Fv"),
    "ack": ("g", (), "ABCm"),
    "ag": ("g", (), "ABCGm"),
}
# 検索語を取らなくなるオプション (値なし)
_NO_PATTERN_FLAGS = {"rg": ("--files",), "ack": ("-f",)}


def _pattern_option(head: str, token: str) -> tuple[bool, bool]:
    """検索語 (スクリプト) をオプションで渡しているか、値が次のトークンか。"""
    if token in _NO_PATTERN_FLAGS.get(head, ()):
        return True, False
    shorts, longs, valued = _PATTERN_OPTIONS.get(head, ("", (), ""))
    if token in longs:
        return True, True
    if any(token.startswith(f"{opt}=") for opt in longs):
        return True, False
    if token.startswith("--") or token == "-":
        return False, False
    for i, ch in enumerate(token[1:], start=1):
        if ch in shorts:
            return True, i == len(token) - 1
        if ch.isdigit() or ch in valued:
            break
    return False, False


_SECRET_SINK_COMMANDS = tables.as_set("sensitive", "secret_sink_commands")


_SECRET_EGRESS_COMMANDS = tables.as_set("sensitive", "secret_egress_commands")


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


def _drop_single_quoted(text: str) -> str:
    """二重引用符の外にある単引用符の範囲を取り除く (シェルが展開しない部分)。

    二重引用符の中の ``'`` (``"Don't"``) は引用ではないので対にしない。
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_double = False
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            end = text.find("'", i + 1)
            if end != -1:
                i = end + 1
                continue
        if ch == '"':
            in_double = not in_double
        out.append(ch)
        i += 1
    return "".join(out)


def check_secret_env_echo(cmd: str) -> str | None:
    """センシティブな環境変数の値を出力先へ流していないか。

    止めるのは値が外に出る形だけにする:

      * `echo $GITHUB_TOKEN` のように標準出力・ファイル・クリップボードへ出す
      * `curl -H "Authorization: Bearer $TOKEN"` のように外部へ送る

    `gh api -H "... $GITHUB_TOKEN"` や `docker run -e API_TOKEN=$API_TOKEN`、
    `test -n "$GITHUB_TOKEN"` のように、値を出力せずプロセスへ渡すだけの形は
    通常の開発操作なので対象外にする。
    シングルクォート内はシェルが展開しないので対象から外す。
    """

    def _sensitive_names(text: str, *, honour_quotes: bool = True) -> list[str]:
        # `sh -c 'echo $TOKEN'` は子シェルが展開するので、コード引数を持つ
        # セグメントではシングルクォートを剥がさずに見る。
        # `\$TOKEN` のようにエスケープされた形はリテラルなので除外する
        scanned = _drop_single_quoted(text) if honour_quotes else text
        return [
            m.group(1)
            for m in re.finditer(r"(?<!\\)\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", scanned)
            if _SENSITIVE_ENV_RE.search(m.group(1))
        ]

    def _code_argument(tokens: list[str]) -> str | None:
        """`sh -c CODE` / `python -c CODE` のコード引数を返す。"""
        if _cmd_name(tokens[0]) not in (_STDIN_CODE_SHELLS | _STDIN_CODE_INTERPRETERS):
            return None
        flags = _SHELL_CODE_ARG_FLAGS | _INTERPRETER_CODE_ARG_FLAGS
        for i, token in enumerate(tokens[1:], start=1):
            if token in flags and i + 1 < len(tokens):
                return tokens[i + 1].strip("'\"")
        return None

    def _scan(text: str, *, honour_quotes: bool, depth: int = 0) -> str | None:
        for segment in _segments(text):
            tokens = segment.split()
            if not tokens:
                continue
            names = _sensitive_names(segment, honour_quotes=honour_quotes)
            if not names:
                continue
            head = _basename(tokens[0])
            if head in _SECRET_SINK_COMMANDS:
                return (
                    f"センシティブな環境変数 `${names[0]}` を出力しようとしています。\n"
                    f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
                    "値を画面やファイルに出さない形で扱ってください。"
                )
            if head in _SECRET_EGRESS_COMMANDS:
                return (
                    f"センシティブな環境変数 `${names[0]}` を外部へ送信しようと"
                    f"しています。\n実行しようとしているコマンド: {cmd.strip()[:200]}\n"
                    "値を外部に出さない形で扱ってください。"
                )
            # `sh -c '...'` はコード引数を展開して同じ判定を続ける
            if depth < 2:
                inner = _code_argument(tokens)
                if inner:
                    hit = _scan(inner, honour_quotes=False, depth=depth + 1)
                    if hit:
                        return hit
        return None

    if not _sensitive_names(cmd, honour_quotes=False):
        return None
    hit = _scan(cmd, honour_quotes=True)
    if hit:
        return hit
    # リダイレクトでファイルへ書き出す形 (`printf %s "$TOKEN" > f` など)
    if _write_targets(cmd):
        for m in REDIRECT_TARGET_RE.finditer(cmd):
            prefix = cmd[: m.start()]
            names = _sensitive_names(prefix)
            if names:
                return (
                    f"センシティブな環境変数 `${names[0]}` をファイルへ書き出そうと"
                    f"しています。\n実行しようとしているコマンド: {cmd.strip()[:200]}"
                )
    return None


def check_history_access(cmd: str) -> str | None:
    """`history` でシェル履歴を読み出していないか (過去の秘密が残っている)。"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        if _basename(tokens[0]) in ("history", "fc"):
            return (
                "シェル履歴には過去に入力した秘密が残っている可能性があるため、"
                "参照は許可されていません。"
            )
    return None
