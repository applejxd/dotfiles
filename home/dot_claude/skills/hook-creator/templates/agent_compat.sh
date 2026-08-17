#!/usr/bin/env bash
# Agent (Claude Code / Copilot CLI) hook 共通ユーティリティ (bash 版)
#
# Python ヘルパ (agent_compat.py) の bash 用最小実装。
# 既に ~/.claude/hooks/lib/agent_compat.sh があるならそちらを優先する。
#
# Usage:
#   . "$(cd "$(dirname "$0")" && pwd -P)/lib/agent_compat.sh"

# tool_input.path / tool_input.file_path のいずれかを取得
# Usage: HOOK_INPUT="$(cat)"; FILE_PATH="$(hook_get_path "$HOOK_INPUT")"
hook_get_path() {
    local input="$1"
    printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty'
}

# ツール名 (大文字小文字混在) を kind に正規化
# Usage: KIND="$(hook_normalize_tool_kind "$TOOL_NAME")"
# 戻り値: "bash" / "view" / "create" / "edit" / "grep" / "glob" / "" (未知)
hook_normalize_tool_kind() {
    case "$1" in
        Bash|bash) echo bash ;;
        Read|view) echo view ;;
        Write|create) echo create ;;
        Edit|MultiEdit|edit) echo edit ;;  # MultiEdit は Claude Code v2.0 系で削除済み
        Grep|grep) echo grep ;;
        Glob|glob) echo glob ;;
        *) echo "" ;;
    esac
}

# PreToolUse で deny を返す (両ツール対応の JSON を stdout に出して exit 0)
# Usage: hook_emit_pretool_deny "理由文"
hook_emit_pretool_deny() {
    local reason="$1"
    jq -n --arg r "$reason" '{
        permissionDecision: "deny",
        permissionDecisionReason: $r,
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: $r
        }
    }'
    exit 0
}

# Stop / agentStop で block を返す (両ツール共通)
# Usage: hook_emit_stop_block "次ターンに渡す追加プロンプト"
hook_emit_stop_block() {
    local reason="$1"
    jq -n --arg r "$reason" '{
        decision: "block",
        reason: $r
    }'
    exit 0
}

# SessionStart / PostToolUseFailure などで context 注入 (両ツール共通)
# Usage: hook_emit_additional_context "追加コンテキスト"
hook_emit_additional_context() {
    local context="$1"
    jq -n --arg c "$context" '{additionalContext: $c}'
    exit 0
}

# PostToolUse などの非ブロック警告
# - Claude Code: stderr + exit 2 で agent にフィードバック
# - Copilot CLI: 出力は LLM に渡らない (CLI UI 表示のみ)
hook_emit_posttool_warn() {
    local message="$1"
    echo "$message" >&2
    exit 2
}

# 現在の実行環境が Copilot CLI かどうかを判定
# Usage: if hook_is_copilot_cli; then ... fi
hook_is_copilot_cli() {
    [ "${COPILOT_CLI:-}" = "1" ]
}
