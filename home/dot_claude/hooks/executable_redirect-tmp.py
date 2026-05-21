#!/usr/bin/env python3
"""
Agent (Claude Code / Copilot CLI) PreToolUse hook: /tmp 使用をブロックし ./.tmp へリダイレクト

対象 kind:
  - bash   : コマンド文字列に /tmp/ または $TMPDIR/${TMPDIR} が含まれる場合
  - view / create / edit : path が /tmp/ で始まる場合

出力規約は ``agent_compat.emit_pretool_deny`` に委譲する (両ツール対応)。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 同一ディレクトリの lib/ にあるヘルパを import
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (  # noqa: E402
    emit_pretool_deny,
    get_command,
    get_path,
    normalize_tool_kind,
    read_input,
)

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
    emit_pretool_deny(f"{_REDIRECT_MESSAGE}\n  検出パス/コマンド: {path_hint}")


def _check_bash(tool_input: dict) -> None:
    cmd = get_command(tool_input)
    if _TMP_BASH_PATTERN.search(cmd):
        _blocked(cmd.strip()[:120])


def _check_file_path(tool_input: dict) -> None:
    path = get_path(tool_input)
    if path.startswith(_TMP_PATH_PREFIX):
        _blocked(path)


_HANDLERS = {
    "bash": _check_bash,
    "view": _check_file_path,
    "create": _check_file_path,
    "edit": _check_file_path,
}


def main() -> None:
    data = read_input()
    kind = normalize_tool_kind(data.get("tool_name", ""))
    handler = _HANDLERS.get(kind)
    if handler is None:
        sys.exit(0)

    handler(data.get("tool_input", {}))
    sys.exit(0)


if __name__ == "__main__":
    main()
