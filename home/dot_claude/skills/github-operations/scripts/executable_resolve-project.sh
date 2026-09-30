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
#         "iterations": [ { "id", "title", "startDate", "duration" } ]  # iteration only (duration は日数)
#       }
#     }
#   }
#
# Requires: gh (with `read:project` scope or more), jq
set -eu

OWNER="${1:?usage: $0 <owner> <project-number>}"
NUMBER="${2:?usage: $0 <owner> <project-number>}"

command -v gh >/dev/null || { echo "gh not found" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found" >&2; exit 1; }

PROJECT_JSON="$(gh project view "${NUMBER}" --owner "${OWNER}" --format json)" \
  || { echo "gh project view failed" >&2; exit 1; }
FIELDS_JSON="$(gh project field-list "${NUMBER}" --owner "${OWNER}" --limit 200 --format json)" \
  || { echo "gh project field-list failed" >&2; exit 1; }

# 入力の形は gh のヘルプとソースからの推定（実 API 未検証, see references/gh-projects-cli.md）。
# 想定外の形は補完せず失敗させる。gh の既定 30 件打ち切りも取得数 < totalCount で検出する
jq -n \
  --argjson project "${PROJECT_JSON}" \
  --argjson fields "${FIELDS_JSON}" \
  '
  def need(c; msg): if c then . else error(msg) end;
  def nes: type == "string" and . != "";
  def need_str(v; msg): need(v | nes; msg);
  ($project | need_str(.id; "project id missing")) as $_
  | ($fields
    | need(type == "object"; "field-list: unexpected shape")
    | need((.totalCount | type) == "number" and .totalCount >= 0 and .totalCount == (.totalCount | floor);
           "field-list: totalCount missing or not a non-negative integer")
    | need((.fields | type) == "array"; "field-list: fields is not an array")
    | need((.fields | length) >= .totalCount;
           "field-list truncated: got \(.fields | length) of \(.totalCount); raise --limit")
    | need(all(.fields[]; type == "object"); "field-list: field is not an object")
    | need(([.fields[].name] | length) == ([.fields[].name] | unique | length);
           "field-list: duplicate field names")
    | .fields[]
    | need_str(.id; "field: id missing")
    | need_str(.name; "field: name missing")
    | need_str(.type; "field \(.name): type missing")
    | need((has("options") | not)
           or ((.options | type) == "array"
               and all(.options[]; (.id | nes) and (.name | type) == "string"));
           "field \(.name): unsupported options shape")
    | need(((.options // []) | map(.name) | length) == ((.options // []) | map(.name) | unique | length);
           "field \(.name): duplicate option names")
    | need(.type != "ProjectV2SingleSelectField" or has("options");
           "field \(.name): single select without options: unsupported shape")
    | need(.type != "ProjectV2IterationField"
           or ((.configuration.iterations | type) == "array"
               and all(.configuration.iterations[];
                       (.id | nes) and (.title | type) == "string"
                       and (.startDate | type) == "string" and (.duration | type) == "number"));
           "field \(.name): unsupported iteration shape (configuration.iterations)")
    | empty)
  ' >/dev/null || { echo "resolve-project: unexpected gh output" >&2; exit 1; }

jq -n \
  --argjson project "${PROJECT_JSON}" \
  --argjson fields "${FIELDS_JSON}" \
  --arg owner "${OWNER}" \
  --arg number "${NUMBER}" \
  '
  def opt_map:
    map({ key: .name, value: .id }) | from_entries;
  def iter_map:
    map({ id: .id, title: .title, startDate: .startDate, duration: .duration });
  {
    project_id: $project.id,
    owner: $owner,
    number: ($number | tonumber),
    fields: (
      $fields.fields | map(
        {
          key: .name,
          value: (
            { id: .id, type: .type }
            + (if has("options") then { options: (.options | opt_map) } else {} end)
            + (if .type == "ProjectV2IterationField"
               then { iterations: (.configuration.iterations | iter_map) } else {} end)
          )
        }
      ) | from_entries
    )
  }
  '
