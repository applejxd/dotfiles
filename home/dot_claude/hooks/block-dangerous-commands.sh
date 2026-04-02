#!/usr/bin/env bash
set -eu

INPUT="$(cat)"
COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"

allow() {
  exit 0
}

deny() {
  REASON="$1"
  jq -n --arg reason "$REASON" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

case "$COMMAND" in
  git\ push*)
    deny "git push は Claude から直接実行しない方針です。lint/test と差分確認の後に手動実行してください。"
    ;;
  git\ reset\ --hard*|git\ clean\ -fd*|git\ clean\ -fdx*)
    deny "破壊的な Git 操作は禁止です。必要なら人手で確認して実行してください。"
    ;;
  rm\ -rf\ /*|sudo\ rm\ -rf\ /*)
    deny "危険すぎる削除コマンドなのでブロックしました。"
    ;;
  sudo\ *|su\ *)
    deny "昇格権限コマンドは Claude から実行しない方針です。"
    ;;
  terraform\ apply*|kubectl\ delete*|docker\ compose\ down*)
    deny "本番影響のある可能性があるため Claude からの直接実行をブロックしました。"
    ;;
  *)
    allow
    ;;
esac