#!/usr/bin/env python3
"""
Agent (Claude Code / Copilot CLI) PreToolUse hook: /tmp 使用をブロックし ./.tmp へリダイレクト

対象 kind:
  - bash   : コマンド文字列に /tmp/ または $TMPDIR/${TMPDIR} が含まれる場合
  - view / create / edit : path が /tmp/ で始まる場合

例外 (allowlist):
  - ``/tmp/claude-*/...`` 配下のパスは Claude Code のバックグラウンドタスクや
    shell snapshot などが利用するため通過させる。

出力規約は ``agent_compat.emit_pretool_deny`` に委譲する (両ツール対応)。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# 同一ディレクトリの lib/ にあるヘルパを import
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (  # noqa: E402
    emit_pretool_deny,
    get_command,
    get_path,
    normalize_tool_kind,
    read_input,
)

# /tmp/ リテラル使用を検出するためのパターン群

_TMP_PATH_PREFIX = "/tmp/"

# allowlist: Claude Code が使う /tmp/claude-* 配下 (claude-<uid>/ や
# claude-shell-snapshot-* など) は通過させる
_ALLOWED_TMP_PATTERN = re.compile(r"^/tmp/claude-[^/]+(?:/|$)")

# bash コマンド中の /tmp/ トークン抽出用 (空白や区切り文字までを 1 トークンとみなす)
_TMP_BASH_TOKEN = re.compile(r"/tmp/[^\s;|&'\"`)>{}<]*")

_REDIRECT_MESSAGE = """\
[hook blocked] /tmp/ の使用が検出されました。
プロジェクトローカルの一時ディレクトリ ./.tmp/ を代わりに使用してください。

  対処手順:
    1. mkdir -p ./.tmp
    2. /tmp/... のパスを ./.tmp/... に置き換えて再実行

  例: /tmp/result.json  →  ./.tmp/result.json

  例外: /tmp/claude-*/ 配下 (Claude Code バックグラウンドタスク等) は許可されます。
"""


def _blocked(path_hint: str) -> None:
    emit_pretool_deny(f"{_REDIRECT_MESSAGE}\n  検出パス/コマンド: {path_hint}")


def _is_allowed_tmp_path(path: str) -> bool:
    return bool(_ALLOWED_TMP_PATTERN.match(path))


def _check_bash(tool_input: dict[str, Any]) -> None:
    cmd = get_command(tool_input)
    # $TMPDIR / $TEMP / $TMP の使用は解決先が不明なため一律 block
    if re.search(r"\$\{?(?:TMPDIR|TEMP|TMP)\}?", cmd):
        _blocked(cmd.strip()[:120])
        return
    # /tmp/ トークンを個別に検査し、allowlist 外があれば block
    for match in _TMP_BASH_TOKEN.finditer(cmd):
        if not _is_allowed_tmp_path(match.group(0)):
            _blocked(cmd.strip()[:120])
            return


def _check_file_path(tool_input: dict[str, Any]) -> None:
    path = get_path(tool_input)
    if path.startswith(_TMP_PATH_PREFIX) and not _is_allowed_tmp_path(path):
        _blocked(path)


_HANDLERS = {
    "bash": _check_bash,
    "view": _check_file_path,
    "create": _check_file_path,
    "edit": _check_file_path,
}


def main() -> None:
    data = read_input()
    if not isinstance(data, dict):
        sys.exit(0)

    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        sys.exit(0)

    kind = normalize_tool_kind(tool_name)
    handler = _HANDLERS.get(kind)
    if handler is None:
        sys.exit(0)

    handler(tool_input)
    sys.exit(0)


if __name__ == "__main__":
    main()
