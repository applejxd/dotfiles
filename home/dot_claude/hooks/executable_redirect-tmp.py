#!/usr/bin/env python3
"""
Claude Code PreToolUse hook: /tmp 使用をブロックし ./.tmp へリダイレクト

対象ツール:
  - Bash    : コマンド文字列に /tmp/ または $TMPDIR/${TMPDIR} が含まれる場合
  - Read / Write / Edit / MultiEdit : file_path / path が /tmp/ で始まる場合

exit 0: 許可
exit 2: ブロック（stderr のメッセージを Claude へのフィードバックとして渡す）
"""
from __future__ import annotations

import json
import os
import re
import sys

# /tmp/ リテラル、または $TMPDIR / ${TMPDIR} を含むパターン
_TMP_BASH_PATTERN = re.compile(
    r"/tmp/"           # リテラル /tmp/
    r"|\$\{?TMPDIR\}?" # $TMPDIR または ${TMPDIR}
    r"|\$\{?TEMP\}?"   # $TEMP または ${TEMP}
    r"|\$\{?TMP\}?",   # $TMP または ${TMP}
)

_TMP_PATH_PREFIX = "/tmp/"

_REDIRECT_MESSAGE = """\
[hook blocked] /tmp/ の使用が検出されました。
プロジェクトローカルの一時ディレクトリ ./.tmp/ を代わりに使用してください。

  対処手順:
    1. mkdir -p ./.tmp
    2. /tmp/... のパスを ./.tmp/... に置き換えて再実行

  例: /tmp/result.json  →  ./.tmp/result.json
"""


def _blocked(path_hint: str) -> None:
    print(f"{_REDIRECT_MESSAGE}\n  検出パス/コマンド: {path_hint}", file=sys.stderr)
    sys.exit(2)


def check_bash(tool_input: dict) -> None:
    cmd: str = tool_input.get("command", "")
    if _TMP_BASH_PATTERN.search(cmd):
        _blocked(cmd.strip()[:120])


def check_file_path(tool_input: dict) -> None:
    # Read / Write は "file_path"、Edit / MultiEdit は "path"
    path: str = tool_input.get("file_path", "") or tool_input.get("path", "")
    if path.startswith(_TMP_PATH_PREFIX):
        _blocked(path)


_TOOL_HANDLERS: dict[str, callable] = {
    "Bash": check_bash,
    "Read": check_file_path,
    "Write": check_file_path,
    "Edit": check_file_path,
    "MultiEdit": check_file_path,
}


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name: str = data.get("tool_name", "")
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        sys.exit(0)

    handler(data.get("tool_input", {}))
    sys.exit(0)


if __name__ == "__main__":
    main()
