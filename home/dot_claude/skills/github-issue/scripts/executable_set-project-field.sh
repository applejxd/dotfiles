#!/usr/bin/env bash
# set-project-field.sh — GitHub Projects v2 の item に対し
# カスタムフィールド値を設定する。field 種別ごとに gh project item-edit の
# フラグを切り替える。
#
# Usage:
#   set-project-field.sh <project-id> <item-id> <field-id> <type> <value>
#
# <type>:
#   single_select : <value> = option ID (resolve-project.sh で取得)
#   iteration     : <value> = iteration ID (同上)
#   date          : <value> = YYYY-MM-DD
#   number        : <value> = numeric
#   text          : <value> = free-form string
#   clear         : <value> = (ignored) — フィールド値を消去
#
# Output (stdout): gh project item-edit の JSON 出力をそのまま流す。
#
# Requires: gh (with `project` scope)
set -eu

PROJECT_ID="${1:?usage: $0 <project-id> <item-id> <field-id> <type> <value>}"
ITEM_ID="${2:?usage: $0 <project-id> <item-id> <field-id> <type> <value>}"
FIELD_ID="${3:?usage: $0 <project-id> <item-id> <field-id> <type> <value>}"
TYPE="${4:?usage: $0 <project-id> <item-id> <field-id> <type> <value>}"
VALUE="${5-}"

command -v gh >/dev/null || { echo "gh not found" >&2; exit 1; }

case "${TYPE}" in
  single_select)
    : "${VALUE:?single_select requires option id}"
    exec gh project item-edit \
      --project-id "${PROJECT_ID}" \
      --id "${ITEM_ID}" \
      --field-id "${FIELD_ID}" \
      --single-select-option-id "${VALUE}" \
      --format json
    ;;
  iteration)
    : "${VALUE:?iteration requires iteration id}"
    exec gh project item-edit \
      --project-id "${PROJECT_ID}" \
      --id "${ITEM_ID}" \
      --field-id "${FIELD_ID}" \
      --iteration-id "${VALUE}" \
      --format json
    ;;
  date)
    : "${VALUE:?date requires YYYY-MM-DD}"
    exec gh project item-edit \
      --project-id "${PROJECT_ID}" \
      --id "${ITEM_ID}" \
      --field-id "${FIELD_ID}" \
      --date "${VALUE}" \
      --format json
    ;;
  number)
    : "${VALUE:?number requires numeric value}"
    exec gh project item-edit \
      --project-id "${PROJECT_ID}" \
      --id "${ITEM_ID}" \
      --field-id "${FIELD_ID}" \
      --number "${VALUE}" \
      --format json
    ;;
  text)
    : "${VALUE?text requires a string (use empty string explicitly)}"
    exec gh project item-edit \
      --project-id "${PROJECT_ID}" \
      --id "${ITEM_ID}" \
      --field-id "${FIELD_ID}" \
      --text "${VALUE}" \
      --format json
    ;;
  clear)
    exec gh project item-edit \
      --project-id "${PROJECT_ID}" \
      --id "${ITEM_ID}" \
      --field-id "${FIELD_ID}" \
      --clear \
      --format json
    ;;
  *)
    echo "unknown type: ${TYPE} (expected: single_select|iteration|date|number|text|clear)" >&2
    exit 2
    ;;
esac
