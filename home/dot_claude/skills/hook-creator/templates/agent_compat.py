"""Agent (Claude Code / Copilot CLI) hook 共通ユーティリティ

両ツールの仕様差を吸収する最小ヘルパ。新規 hook プロジェクトの開始時に
これをコピーして使う。既に ``~/.claude/hooks/lib/agent_compat.py`` が
存在するならそちらを優先する (重複を避ける)。

検証ベース (2026-05):
- Copilot CLI 公式 docs (hooks-reference)
  https://docs.github.com/en/copilot/reference/hooks-reference
- Claude Code 公式 docs
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
    # 検索系
    "Grep": "grep",
    "grep": "grep",
    # Glob
    "Glob": "glob",
    "glob": "glob",
}


def normalize_tool_kind(tool_name: str) -> str | None:
    """ツール名を kind ("bash" / "view" / "create" / "edit" / "grep" / "glob") に
    正規化。未知のツールは None を返す。"""
    return _TOOL_KIND_MAP.get(tool_name)


def get_command(tool_input: dict[str, Any]) -> str:
    """bash 系ツールのコマンド文字列を取得。"""
    return tool_input.get("command", "")


def get_path(tool_input: dict[str, Any]) -> str:
    """ファイル系ツールのパスを取得。

    - Claude Code (Read/Write): ``file_path``
    - Claude Code (Edit): ``path``
    - Copilot CLI (view/create/edit): ``path``
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


def emit_pretool_ask(reason: str, *, exit_code: int = 0) -> None:
    """PreToolUse でユーザへの承認プロンプトを強制する。プロセスは終了する。

    deny と違い、ユーザが承認すればツールはそのまま実行される。

    各モードでの挙動 (2026-08 時点の公式 docs):
      - Claude 対話 / auto / bypassPermissions : プロンプトが出る
      - Claude dontAsk                          : 自動拒否
      - Claude ``-p`` (非対話)                  : プロンプト不能。操作はスキップ
      - Copilot CLI (対話)                      : **自動承認される**。1.0.53 以降の
        既知バグ (github/copilot-cli#3590)。確実に止めたいなら deny を使う
      - Copilot cloud agent                     : deny として扱われる

    注意: Claude では ask 時の reason はユーザにのみ表示され LLM には渡らない。
    """
    payload = {
        "permissionDecision": "ask",
        "permissionDecisionReason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        },
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    sys.exit(exit_code)


def emit_stop_block(reason: str, *, exit_code: int = 0) -> None:
    """Stop/agentStop でターン継続を強制する。プロセスは終了する。

    両ツールとも ``{"decision": "block", "reason": ...}`` 形式で同じ。
    """
    payload = {"decision": "block", "reason": reason}
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    sys.exit(exit_code)


def emit_session_context(additional_context: str, *, exit_code: int = 0) -> None:
    """SessionStart や PostToolUseFailure で context を agent に注入する。

    両ツール共通: ``{"additionalContext": "..."}`` を stdout に出す。
    """
    payload = {"additionalContext": additional_context}
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    sys.exit(exit_code)


def read_input() -> dict[str, Any]:
    """stdin の JSON ペイロードを読み取る。失敗時は空 dict。"""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return {}


def is_copilot_cli() -> bool:
    """現在の実行環境が Copilot CLI かどうかを判定。"""
    import os
    return os.environ.get("COPILOT_CLI") == "1"
