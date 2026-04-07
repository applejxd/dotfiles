#!/usr/bin/env bash
set -eu

INPUT="$(cat)"
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')"

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