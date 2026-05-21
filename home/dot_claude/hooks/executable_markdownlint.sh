#!/usr/bin/env bash
# Agent (Claude Code / Copilot CLI) PostToolUse hook:
# Markdown ファイルに markdownlint を適用
#
# 動作:
#   - tool_input.file_path / tool_input.path が *.md / *.markdown のときのみ動く
#   - markdownlint-cli2 --fix で機械的に修正できる違反を自動修正
#   - 自動修正後も残った違反を hook_emit_posttool_warn で agent に返す
#     (Claude Code: stderr が agent にフィードバック / Copilot CLI: postToolUse
#      の output は処理されない仕様のため、警告は agent に届かない可能性あり)
#
# 想定される markdownlint-cli2 の入手元 (優先順):
#   1. PATH に直接置かれているもの (mise shim 経由 "npm:markdownlint-cli2" など)
#   2. npx --yes (フォールバック・初回のみ slow)
#   どちらも無ければ無音で skip。
set -eu

# 同一ディレクトリの lib/ にあるヘルパを読み込む (macOS の readlink には -f が
# ない場合があるため、Python の Path.resolve() 相当を bash 標準機能で代替)
__script_dir="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
# shellcheck source=/dev/null
. "$__script_dir/lib/agent_compat.sh"

INPUT="$(cat)"
FILE_PATH="$(hook_get_path "$INPUT")"

case "$FILE_PATH" in
  *.md|*.markdown) ;;
  *) exit 0 ;;
esac
[ -f "$FILE_PATH" ] || exit 0

if command -v markdownlint-cli2 >/dev/null 2>&1; then
  LINT="markdownlint-cli2"
elif command -v npx >/dev/null 2>&1; then
  LINT="npx --yes markdownlint-cli2"
else
  exit 0
fi

# 1) 自動修正できるものは修正 (MD009/MD010/MD012/MD030/MD034 など)
$LINT --fix "$FILE_PATH" >/dev/null 2>&1 || true

# 2) 残った違反を検出
LINT_OUT="$($LINT "$FILE_PATH" 2>&1 || true)"

if echo "$LINT_OUT" | grep -q "Summary: 0 error"; then
  exit 0
fi

# 警告を agent に返す
hook_emit_posttool_warn "$(cat <<EOF
[markdownlint] issues remain in: $FILE_PATH
$LINT_OUT

Auto-fix already applied. Please address remaining issues
(typically MD013 line-length / MD040 fenced-code-language / MD060 table style).
EOF
)"
