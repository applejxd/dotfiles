"""ファイルの読み取り・持ち出し・書き込み先に関するルール。"""
from __future__ import annotations

import re

from . import tables
from ._shared import (
    _SENSITIVE_ENV_RE,
    FILE_READ_COMMANDS,
    _basename,
    _normalize,
    _policy,
    _segments,
)
from .sensitive import is_sensitive_path

_GIT_FILE_SUBCOMMANDS = tables.as_set("rules_files", "git_file_subcommands")


_LISTING_COMMANDS = tables.as_set("rules_files", "listing_commands")


ENV_EXPOSURE_BINS = tables.as_set("rules_files", "env_exposure_bins")


_BARE_ONLY_DUMP_BINS = tables.as_set("rules_files", "bare_only_dump_bins")


ARCHIVE_COMMANDS = tables.as_list("rules_files", "archive_commands")


def check_file_read(cmd: str) -> str | None:
    """ファイル読み込み・複製コマンドがセンシティブパスを対象にしていないか。

    `git diff <path>` のように、許可済みコマンドでも引数がセンシティブなら止める。
    """
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head == "git" and len(tokens) > 2 and tokens[1] in _GIT_FILE_SUBCOMMANDS:
            matched = is_sensitive_path(" ".join(tokens[1:]))
            if matched:
                return (
                    f"`git {tokens[1]}` がセンシティブなパスを対象にしています "
                    f"(パターン: {matched})"
                )
            continue
        if head not in FILE_READ_COMMANDS:
            continue
        matched = is_sensitive_path(
            segment, heuristic=head not in _LISTING_COMMANDS
        )
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
        if not args and not (head in _BARE_ONLY_DUMP_BINS and len(tokens) > 1):
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


_PIP_BIN_RE = re.compile(r"^(?:/\S*/)?pip[0-9.]*$")


_PYTHON_BIN_RE = re.compile(r"^(?:/\S*/)?python[0-9.]*$")


# -mpip のように -m と値がくっついた形
_PYTHON_DASH_M_RE = re.compile(r"^-m(.+)$")


_PIP_RUNNERS = tables.as_set("rules_files", "pip_runners")


_PIP_RUNNER_VALUE_OPTS = tables.as_set("rules_files", "pip_runner_value_opts")


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
        _normalize(cmd) if _policy is not None else [cmd]
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
            # `--from pkg` のように値を取るオプションは、その値ごと読み飛ばす
            # (読み飛ばさないと値を実行対象と誤認して検査が止まる)
            i = 1
            # `pipx run pkg` の run のように、実行対象の前に挟まるサブコマンド
            if head == "pipx" and i < len(tokens) and tokens[i] == "run":
                i += 1
            while i < len(tokens):
                token = tokens[i]
                if token.startswith("-"):
                    if "=" not in token and token in _PIP_RUNNER_VALUE_OPTS:
                        i += 2
                    else:
                        i += 1
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
                if (
                    token == "-m"
                    and i + 1 < len(tokens)
                    and _PIP_BIN_RE.match(_basename(tokens[i + 1]))
                ):
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
