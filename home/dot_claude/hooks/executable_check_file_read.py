#!/usr/bin/env python3
"""Agent PreToolUse hook: ファイル読み取りツールのセンシティブパス遮断。

`[file] claude_read_deny_globs` は Claude では ``Read()`` の deny permission に
なるが、Copilot には対応する機構が無い:

  - ``permissions-config.json`` はファイル規則を表現できない (bash の allow と
    locations だけ)
  - sandbox の ``deniedPaths`` は **絶対パス限定・ワイルドカード非対応**で、
    しかも cwd は自動で read/write 許可される

そのため「リポジトリの中に置かれた秘密ファイル」(``certs/server.key`` など) は
Copilot からは読めてしまう。ここを埋めるのがこの hook。

判定は Claude の permission と **同じリスト** (``common.toml`` の
``[file] claude_read_deny_globs``) を読むので、ルールは 1 箇所に書けばよい。

fail-closed: ポリシーを読めない場合は素通りさせず deny する。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (
    emit_pretool_deny,
    get_path,
    normalize_tool_kind,
    read_input,
)

_AGENTS_DIR = os.environ.get("AGENTS_CONFIG_DIR")
if not _AGENTS_DIR:
    _CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    _AGENTS_DIR = os.path.join(_CONFIG_HOME, "agents")
sys.path.insert(0, _AGENTS_DIR)
_POLICY_IMPORT_ERROR: str | None = None
try:
    import command_policy as _policy
except Exception as _exc:  # pragma: no cover - 構文エラー等も拾う
    _policy = None  # type: ignore[assignment]
    _POLICY_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"


def main() -> None:
    data = read_input()
    if not isinstance(data, dict):
        sys.exit(0)

    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str):
        sys.exit(0)
    if normalize_tool_kind(tool_name) != "view":
        sys.exit(0)

    tool_input = data.get("tool_input")
    path = get_path(tool_input) if isinstance(tool_input, dict) else ""
    if not path:
        sys.exit(0)

    if _policy is None:
        emit_pretool_deny(
            "ポリシーモジュールを読み込めませんでした "
            f"({_AGENTS_DIR}/command_policy.py): {_POLICY_IMPORT_ERROR}\n"
            "安全のためファイル読み取りを拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行してください。"
        )
        return

    try:
        globs = _policy.load_read_deny_globs()
    except Exception as exc:
        emit_pretool_deny(
            f"ポリシー定義を解釈できませんでした ({exc})。\n"
            "安全のためファイル読み取りを拒否しています。"
        )
        return

    if not globs:
        emit_pretool_deny(
            "ポリシー定義に [file] claude_read_deny_globs がありません。\n"
            "設定が壊れている可能性があるため、安全のため拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行してください。"
        )
        return

    matched = _policy.matches_any_glob(path, globs)
    if matched:
        emit_pretool_deny(
            f"`{path}` はセンシティブなファイルとして読み取りが禁止されています "
            f"(パターン: {matched})。\n"
            "秘密情報はエージェントに渡さず、必要なら値を伏せた形で共有してください。"
        )
        return

    sys.exit(0)


if __name__ == "__main__":
    main()
