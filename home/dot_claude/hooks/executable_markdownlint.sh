#!/usr/bin/env bash
# Claude Code PostToolUse hook: Markdown ファイルに markdownlint を適用
#
# 動作:
#   - tool_input.file_path が *.md / *.markdown のときのみ動く
#   - markdownlint-cli2 --fix で機械的に修正できる違反を自動修正
#   - 自動修正後も残った違反は exit 2 で agent にフィードバック
#
# 想定される markdownlint-cli2 の入手元 (優先順):
#   1. PATH に直接置かれているもの (mise shim 経由 "npm:markdownlint-cli2" など)
#   2. npx --yes (フォールバック・初回のみ slow)
#   どちらも無ければ無音で skip。
set -eu

INPUT="$(cat)"
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')"

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

# blocking + agent へフィードバック
{
  echo "[markdownlint] issues remain in: $FILE_PATH"
  echo "$LINT_OUT"
  echo
  echo "Auto-fix already applied. Please address remaining issues"
  echo "(typically MD013 line-length / MD040 fenced-code-language / MD060 table style)."
} >&2
exit 2
