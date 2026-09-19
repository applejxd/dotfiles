"""秘密情報 (鍵・トークン・認証ファイル) の検出。

★守る対象のファイル名・ディレクトリ・環境変数名は ``tables.toml`` にある。
ファイルを足したいだけなら TOML 側を編集すればよい。
"""
from __future__ import annotations

import os
import re

from . import tables
from ._shared import (
    _INTERPRETER_CODE_ARG_FLAGS,
    _SENSITIVE_ENV_RE,
    _SENSITIVE_SUFFIXES,
    _SHELL_CODE_ARG_FLAGS,
    _STDIN_CODE_INTERPRETERS,
    _STDIN_CODE_SHELLS,
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
        reason = _is_sensitive_token(token, heuristic=heuristic)
        if reason:
            return reason
    return None


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
        scanned = re.sub(r"'[^']*'", "", text) if honour_quotes else text
        return [
            m.group(1)
            for m in re.finditer(
                r"(?<!\\)\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", scanned
            )
            if _SENSITIVE_ENV_RE.search(m.group(1))
        ]

    def _code_argument(tokens: list[str]) -> str | None:
        """`sh -c CODE` / `python -c CODE` のコード引数を返す。"""
        if _cmd_name(tokens[0]) not in (
            _STDIN_CODE_SHELLS | _STDIN_CODE_INTERPRETERS
        ):
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
        for m in re.finditer(r"[0-9]*>{1,2}\|?\s*[^\s&][^\s;&|)<>]*", cmd):
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
