#!/usr/bin/env bash
# Agent (Claude Code / Copilot CLI) PostToolUse hook:
# 編集されたファイルを拡張子に応じて整形する
#
# 動作:
#   - tool_input.file_path / tool_input.path からパスを取得 (両ツール対応)
#   - フォーマッタが PATH に無い場合は無音で skip
set -eu

# 同一ディレクトリの lib/ にあるヘルパを読み込む
__script_dir="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
# shellcheck source=/dev/null
. "$__script_dir/lib/agent_compat.sh"

INPUT="$(cat)"
FILE_PATH="$(hook_get_path "$INPUT")"

[ -n "$FILE_PATH" ] || exit 0
[ -f "$FILE_PATH" ] || exit 0

run_ruff() {
  command -v ruff >/dev/null 2>&1 || return 0
  ruff format "$FILE_PATH"
}

run_clang_format() {
  command -v clang-format >/dev/null 2>&1 || return 0
  clang-format -i "$FILE_PATH"
}

run_prettier() {
  command -v prettier >/dev/null 2>&1 || return 0
  prettier --write "$FILE_PATH"
}

case "$FILE_PATH" in
  *.py)
    run_ruff
    ;;

  *.c|*.cc|*.cpp|*.cxx|*.h|*.hh|*.hpp|*.hxx)
    run_clang_format
    ;;

  *.html|*.css|*.js|*.jsx|*.ts|*.tsx|*.json|*.yaml|*.yml)
    run_prettier
    ;;

  *)
    ;;
esac

exit 0
