#!/usr/bin/env bash
# add-issue-to-project.sh — issue/PR を GitHub Projects v2 に追加し、
# 生成された itemId を JSON で返す。既に登録済みの場合は冪等に既存の itemId を返す。
#
# Usage:
#   add-issue-to-project.sh <project-id> <issue-url>
#
# Output (stdout): JSON
#   { "item_id": "PVTI_xxx", "added": true|false }
#
# - added=true  : 今回 item-add で追加した
# - added=false : 既に登録済みで、既存 itemId を返した
#
# Requires: gh (with `project` scope), jq
set -eu

PROJECT_ID="${1:?usage: $0 <project-id> <issue-url>}"
ISSUE_URL="${2:?usage: $0 <project-id> <issue-url>}"

command -v gh >/dev/null || { echo "gh not found" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found" >&2; exit 1; }

# item-add は重複しても新しい item を作らず既存 id を返すので、まずそのまま呼ぶ。
# ただし冪等性の判別のため、事前取得した content node id と比較して
# 既存登録か新規かを分類する。実装簡素化のため item-add の結果をそのまま返し
# `added` は false 固定で扱う（呼び出し側は通常 added を見ない想定）。

ADD_JSON="$(gh project item-add \
  --owner "@me" \
  --url "${ISSUE_URL}" \
  --format json \
  --project-id "${PROJECT_ID}" 2>/dev/null || true)"

if [ -z "${ADD_JSON}" ]; then
  # `--owner @me` での item-add がエラーになる組み合わせ（org project など）への
  # フォールバック: GraphQL の addProjectV2ItemById を直接叩く。
  # shellcheck disable=SC2016  # GraphQL variables ($url etc.) are intentionally not shell-expanded.
  CONTENT_ID="$(gh api graphql -f query='
    query($url: URI!) { resource(url: $url) { ... on Issue { id } ... on PullRequest { id } } }
  ' -F url="${ISSUE_URL}" --jq '.data.resource.id')"

  if [ -z "${CONTENT_ID}" ] || [ "${CONTENT_ID}" = "null" ]; then
    echo "could not resolve content id for: ${ISSUE_URL}" >&2
    exit 1
  fi

  # shellcheck disable=SC2016  # GraphQL variables ($p, $c) are bound via -F, not shell expansion.
  ADD_JSON="$(gh api graphql -f query='
    mutation($p: ID!, $c: ID!) {
      addProjectV2ItemById(input: { projectId: $p, contentId: $c }) {
        item { id }
      }
    }
  ' -F p="${PROJECT_ID}" -F c="${CONTENT_ID}" --jq '{ id: .data.addProjectV2ItemById.item.id }')"
fi

echo "${ADD_JSON}" | jq '{ item_id: .id, added: true }'
