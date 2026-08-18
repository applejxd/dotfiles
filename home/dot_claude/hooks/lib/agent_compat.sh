#!/usr/bin/env bash
# エージェント (Claude Code / Copilot CLI) hook 共通ユーティリティ (bash 版)
#
# Python ヘルパ (agent_compat.py) の bash 用最小実装。
# markdownlint.sh など bash 製 hook から source して使う。
#
# 検証ベースは agent_compat.py のコメント参照。

# tool_input.path / tool_input.file_path のいずれかを取得
# Usage: HOOK_INPUT="$(cat)"; FILE_PATH="$(hook_get_path "$HOOK_INPUT")"
hook_get_path() {
    local input="$1"
    printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty'
}

# ツール名 (大文字小文字混在) を kind に正規化
# Usage: KIND="$(hook_normalize_tool_kind "$TOOL_NAME")"
# 戻り値: "bash" / "view" / "create" / "edit" / "" (未知)
hook_normalize_tool_kind() {
    case "$1" in
        Bash|bash) echo bash ;;
        Read|view) echo view ;;
        Write|create) echo create ;;
        Edit|MultiEdit|edit) echo edit ;;  # MultiEdit は Claude Code v2.0 系で削除済み
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

# PostToolUse などの非ブロック警告 (両ツールとも stderr メッセージ + exit 2 で
# additionalContext として LLM に渡る)
# Usage: hook_emit_posttool_warn "警告文"
hook_emit_posttool_warn() {
    local message="$1"
    echo "$message" >&2
    exit 2
}
