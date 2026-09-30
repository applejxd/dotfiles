#!/usr/bin/env bash
# verify-hook.sh — hook を payload とともに発火させ、stdout/stderr/exit/decision
# を整形して表示する。Claude/Copilot 両方の hook デバッグに使える。
#
# Usage:
#   verify-hook.sh <hook-command-line> <payload-json>
#
# Examples:
#   # Python hook
#   verify-hook.sh "python ~/.claude/hooks/check_bash.py" \
#                  ~/.copilot/skills/hook-creator/examples/payloads/pretool-bash.json
#
#   # Bash hook
#   verify-hook.sh "bash ~/.claude/hooks/markdownlint.sh" \
#                  ~/.copilot/skills/hook-creator/examples/payloads/posttool-edit.json
set -eu

if [ $# -lt 2 ]; then
    cat <<EOF >&2
Usage: $0 <hook-command-line> <payload-json>

Runs the hook command with payload-json piped to its stdin.
Reports exit code, stdout (raw + parsed JSON), and stderr.
EOF
    exit 64
fi

HOOK_CMD="$1"
PAYLOAD_FILE="$2"

if [ ! -f "$PAYLOAD_FILE" ]; then
    echo "[verify-hook] payload file not found: $PAYLOAD_FILE" >&2
    exit 66
fi

# 一時ファイルに stdout / stderr を分離して保存
STDOUT_TMP="$(mktemp)"
STDERR_TMP="$(mktemp)"
trap 'rm -f "$STDOUT_TMP" "$STDERR_TMP"' EXIT

set +e
# shellcheck disable=SC2086  # HOOK_CMD は word split を意図
eval $HOOK_CMD < "$PAYLOAD_FILE" > "$STDOUT_TMP" 2> "$STDERR_TMP"
EXIT_CODE=$?
set -e

echo "=== hook command ==="
echo "$HOOK_CMD"
echo "=== payload ($PAYLOAD_FILE) ==="
cat "$PAYLOAD_FILE"
echo
echo "=== exit code ==="
echo "$EXIT_CODE"
echo
echo "=== stdout (raw) ==="
cat "$STDOUT_TMP"
echo
echo "=== stdout (parsed) ==="
JSON_STATE=empty   # empty | valid | invalid | unchecked
# 契約: stdout は単一の JSON object 1 個だけ (複数文書・配列・スカラーは invalid)。
# jq 版と python3 版で同じ判定・同じ抽出規則にする (null / false は「無し」扱い)。
show_decision() {
    if [ -n "$1" ]; then
        echo "=== detected decision ==="
        echo "  decision: $1"
        [ -n "$2" ] && echo "  reason  : $2"
    fi
    return 0
}
if [ -s "$STDOUT_TMP" ] && command -v jq >/dev/null 2>&1; then
    if jq -s -e 'length == 1 and (.[0] | type) == "object"' "$STDOUT_TMP" >/dev/null 2>&1; then
        JSON_STATE=valid
        jq . "$STDOUT_TMP" || true
        echo
        JQ_DEF='def g(o; k): if (o | type) == "object" then o[k] else null end;'
        DECISION=$(jq -r "$JQ_DEF"'
            (g(.; "permissionDecision") // g(g(.; "hookSpecificOutput"); "permissionDecision") // g(.; "decision") // empty)
            | if type == "string" then . else tojson end' "$STDOUT_TMP" 2>/dev/null) || DECISION=""
        REASON=$(jq -r "$JQ_DEF"'
            (g(.; "permissionDecisionReason") // g(g(.; "hookSpecificOutput"); "permissionDecisionReason") // g(.; "reason") // g(.; "additionalContext") // empty)
            | if type == "string" then . else tojson end' "$STDOUT_TMP" 2>/dev/null) || REASON=""
        show_decision "$DECISION" "$REASON"
    else
        JSON_STATE=invalid
        echo "(stdout is not a single valid JSON object)"
    fi
elif [ -s "$STDOUT_TMP" ] && command -v python3 >/dev/null 2>&1; then
    if python3 - "$STDOUT_TMP" <<'PY' 2>/dev/null
import json, sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.loads(f.read())
if not isinstance(data, dict):
    sys.exit(3)


def g(o, k):
    return o.get(k) if isinstance(o, dict) else None


def first(*vals):
    for v in vals:
        if v is not None and v is not False:
            return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return ""


hso = g(data, "hookSpecificOutput")
decision = first(g(data, "permissionDecision"), g(hso, "permissionDecision"), g(data, "decision"))
reason = first(g(data, "permissionDecisionReason"), g(hso, "permissionDecisionReason"),
               g(data, "reason"), g(data, "additionalContext"))
print(json.dumps(data, indent=2, ensure_ascii=False))
print()
# 表示は jq 版の show_decision と同じ書式 (行数による受け渡しはしない)
if decision:
    print("=== detected decision ===")
    print("  decision: " + decision)
    if reason:
        print("  reason  : " + reason)
PY
    then
        JSON_STATE=valid
    else
        JSON_STATE=invalid
        echo "(stdout is not a single valid JSON object)"
    fi
elif [ -s "$STDOUT_TMP" ]; then
    JSON_STATE=unchecked
    echo "(stdout not checked: neither jq nor python3 is installed)"
else
    echo "(empty stdout)"
fi
echo
echo "=== stderr ==="
cat "$STDERR_TMP"
echo
echo "=== verdict ==="
echo "(static check of the output format only; not a guarantee that either CLI accepts it)"
if [ "$JSON_STATE" = invalid ]; then
    echo "FAIL: stdout is not a single JSON object (debug output mixed in?). Write debug to stderr."
    [ "$EXIT_CODE" -ne 0 ] && exit "$EXIT_CODE"
    exit 1
fi
if [ "$EXIT_CODE" -eq 0 ] && [ "$JSON_STATE" = valid ]; then
    echo "exit 0 + valid JSON on stdout → output format looks well-formed"
elif [ "$EXIT_CODE" -eq 0 ] && [ "$JSON_STATE" = unchecked ]; then
    echo "exit 0 + non-empty stdout → JSON validity not checked"
elif [ "$EXIT_CODE" -eq 2 ]; then
    echo "exit 2 → Claude Code blocks; Copilot CLI ignores stderr (needs JSON in stdout to block)"
elif [ "$EXIT_CODE" -eq 0 ]; then
    echo "exit 0 + empty stdout → no-op (allow)"
else
    echo "exit $EXIT_CODE → non-blocking error. Both tools log this without affecting the tool call."
fi

exit "$EXIT_CODE"
