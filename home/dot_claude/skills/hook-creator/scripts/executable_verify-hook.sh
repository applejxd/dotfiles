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
if [ -s "$STDOUT_TMP" ] && command -v jq >/dev/null 2>&1; then
    if jq . "$STDOUT_TMP" 2>/dev/null; then
        echo
        # 主要な decision フィールドを抽出
        DECISION=$(jq -r '
            .permissionDecision //
            .hookSpecificOutput.permissionDecision //
            .decision //
            empty
        ' "$STDOUT_TMP" 2>/dev/null)
        REASON=$(jq -r '
            .permissionDecisionReason //
            .hookSpecificOutput.permissionDecisionReason //
            .reason //
            .additionalContext //
            empty
        ' "$STDOUT_TMP" 2>/dev/null)
        if [ -n "$DECISION" ]; then
            echo "=== detected decision ==="
            echo "  decision: $DECISION"
            [ -n "$REASON" ] && echo "  reason  : $REASON"
        fi
    else
        echo "(stdout is not valid JSON)"
    fi
else
    echo "(empty stdout or jq not installed)"
fi
echo
echo "=== stderr ==="
cat "$STDERR_TMP"
echo
echo "=== verdict ==="
if [ "$EXIT_CODE" -eq 0 ] && [ -s "$STDOUT_TMP" ]; then
    echo "exit 0 + stdout JSON → both Claude Code and Copilot CLI accept this"
elif [ "$EXIT_CODE" -eq 2 ]; then
    echo "exit 2 → Claude Code blocks; Copilot CLI ignores stderr (needs JSON in stdout to block)"
elif [ "$EXIT_CODE" -eq 0 ] && [ ! -s "$STDOUT_TMP" ]; then
    echo "exit 0 + empty stdout → no-op (allow). Watch out: empty stdout in a parallel"
    echo "hook may override a deny from another hook in Copilot CLI."
else
    echo "exit $EXIT_CODE → non-blocking error. Both tools log this without affecting the tool call."
fi

exit "$EXIT_CODE"
