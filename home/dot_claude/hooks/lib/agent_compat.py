"""エージェント (Claude Code / Copilot CLI) hook 共通ユーティリティ

両ツールの仕様差を吸収するヘルパ:
- tool_name の正規化 (大文字小文字・別名)
- tool_input から path/command を共通キーで取り出す
- ブロック出力 (PreToolUse) / 継続強制出力 (Stop) の発出

検証ベース:
- Copilot CLI 公式 docs (hooks-reference, 2025-05 時点)
  https://docs.github.com/en/copilot/reference/hooks-reference
- Claude Code 公式 docs (hooks, 2025-05 時点)
  https://docs.claude.com/en/docs/claude-code/hooks
- 実機検証: Copilot CLI で
    Pattern A: stdout JSON + exit 0      → ブロック成功
    Pattern B: stdout JSON + exit 2      → ブロック成功 (JSON 優先)
    Pattern C: exit 2 + stderr           → ブロック失敗 (スルー)
- Claude Code は exit 0 で stdout を JSON として解釈する仕様
  (公式: "JSON output is only processed on exit 0")
- → 両ツール対応の最小公倍数 = "stdout JSON + exit 0"
"""
from __future__ import annotations

import json
import sys
from typing import Any

# ─── ツール名の正規化テーブル ──────────────────────────────────
# Claude Code: PascalCase / Copilot CLI: lowercase
# 同じ kind に属するツールは同一の正規名へマップする
_TOOL_KIND_MAP: dict[str, str] = {
    # bash 系
    "Bash": "bash",
    "bash": "bash",
    # ファイル読み取り系
    "Read": "view",
    "view": "view",
    # ファイル新規作成系
    "Write": "create",
    "create": "create",
    # ファイル編集系
    "Edit": "edit",
    "MultiEdit": "edit",  # Claude Code v2.0 系で削除済み (後方互換のため残す)
    "edit": "edit",
}


def normalize_tool_kind(tool_name: str) -> str | None:
    """ツール名を kind ("bash" / "view" / "create" / "edit") に正規化。

    未知のツールは None を返す。
    """
    return _TOOL_KIND_MAP.get(tool_name)


def get_command(tool_input: dict[str, Any]) -> str:
    """bash 系ツールのコマンド文字列を取得。"""
    return tool_input.get("command", "")


def get_path(tool_input: dict[str, Any]) -> str:
    """ファイル系ツールのパスを取得。

    - Claude Code (Read/Write): "file_path"
    - Claude Code (Edit): "path"
    - Copilot CLI (view/create/edit): "path"
    """
    return tool_input.get("file_path") or tool_input.get("path") or ""


def emit_pretool_deny(reason: str, *, exit_code: int = 0) -> None:
    """PreToolUse でツール実行を拒否する。プロセスは終了する。

    出力は両ツール対応のフォーマット:
      - Copilot CLI: top-level の permissionDecision を読む
      - Claude Code: hookSpecificOutput.permissionDecision を読む
      - どちらも exit 0 + stdout JSON で deny として解釈する

    Args:
        reason: ユーザ/エージェントに返す理由文。
        exit_code: 0 を推奨 (両ツール対応)。
                   Copilot は 2 でも JSON を読むが、Claude は exit 2 だと
                   stdout を無視するため、両対応するには 0 が安全。
    """
    payload = {
        # Copilot CLI 形式 (フラット)
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
        # Claude Code 形式 (ネスト)
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    sys.exit(exit_code)


def emit_stop_block(reason: str, *, exit_code: int = 0) -> None:
    """Stop/agentStop でターン継続を強制する。プロセスは終了する。

    両ツールとも { "decision": "block", "reason": ... } 形式で同じ。

    Args:
        reason: 次ターンに与える追加プロンプト。
        exit_code: 0 を推奨。
    """
    payload = {"decision": "block", "reason": reason}
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    sys.exit(exit_code)


def read_input() -> dict[str, Any]:
    """stdin の JSON ペイロードを読み取る。失敗時は空 dict。"""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return {}
