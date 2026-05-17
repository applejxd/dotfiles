#!/usr/bin/env bash
# resolve-project.sh — GitHub Projects v2 の project_id / field id / option id /
# iteration id をまとめて JSON で出力する。
#
# Usage:
#   resolve-project.sh <owner> <project-number>
#
# Output (stdout): JSON
#   {
#     "project_id": "PVT_xxx",
#     "owner": "...",
#     "number": N,
#     "fields": {
#       "<FieldName>": {
#         "id": "PVTSSF_xxx" | "PVTIF_xxx" | ...,
#         "type": "ProjectV2SingleSelectField" | "ProjectV2IterationField" | ...,
#         "options":    { "<option name>": "<option id>" }     # single_select only
#         "iterations": { "<iteration title>": "<iteration id>" }  # iteration only
#       }
#     }
#   }
#
# Requires: gh (with `project` scope), jq
set -eu

OWNER="${1:?usage: $0 <owner> <project-number>}"
NUMBER="${2:?usage: $0 <owner> <project-number>}"

command -v gh >/dev/null || { echo "gh not found" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found" >&2; exit 1; }

PROJECT_JSON="$(gh project view "${NUMBER}" --owner "${OWNER}" --format json)"
FIELDS_JSON="$(gh project field-list "${NUMBER}" --owner "${OWNER}" --format json)"

# gh project field-list returns { "fields": [ ... ] }
# - SingleSelect: { id, name, type, options: [ {id, name}, ... ] }
# - Iteration:    { id, name, type, configuration: { iterations: [ {id, title, startDate, duration}, ... ] } }
# - Others:       { id, name, type }
jq -n \
  --argjson project "${PROJECT_JSON}" \
  --argjson fields "${FIELDS_JSON}" \
  --arg owner "${OWNER}" \
  --arg number "${NUMBER}" \
  '
  def opt_map(f):
    (f.options // []) | map({ key: .name, value: .id }) | from_entries;
  def iter_map(f):
    (f.configuration.iterations // []) | map({ key: .title, value: .id }) | from_entries;
  {
    project_id: $project.id,
    owner: $owner,
    number: ($number | tonumber),
    fields: (
      ($fields.fields // []) | map(
        {
          key: .name,
          value: (
            { id: .id, type: .type }
            + (if (.options // null) then { options: opt_map(.) } else {} end)
            + (if (.configuration.iterations // null) then { iterations: iter_map(.) } else {} end)
          )
        }
      ) | from_entries
    )
  }
  '
