#!/usr/bin/env bash
# CHG-0019 段 4: 伏字化の経路（途中経過・最終結果・退避ファイル・例外）と、codemode・MCP の経路を確かめる。
# モデルは faux.ts の偽物で、通信しない。
# see docs/research/agents/pi-harness-spike.md
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export PI_CODING_AGENT_DIR="$WORK/agent" SPIKE_POLICY="$HERE/policy.py" SPIKE_RENAME=1
mkdir -p "$PI_CODING_AGENT_DIR" "$WORK/proj"
SECRET=abc123rawsecret

# 途中経過が出るよう、秘密を出してから待ち、退避ファイルができる量を出す
cat > "$WORK/proj/big.py" <<PY
import sys, time
print("SPIKE_TOKEN=$SECRET", flush=True)
time.sleep(1.5)
for i in range(3000):
    print(f"line {i} " + "x" * 40)
print("SPIKE_TOKEN=$SECRET tail", flush=True)
PY

leaks() {
  # 偽のモデルの返答・JSON のイベント・セッション・退避ファイルに生の秘密が残っていないか
  label=$1
  n_stream=$(grep -c "$SECRET" "$WORK/stream.jsonl" || true)
  n_session=$(cat "$WORK"/sessions/*.jsonl 2>/dev/null | grep -c "$SECRET" || true)
  n_spill=0
  while read -r f; do
    [ -f "$f" ] && n_spill=$((n_spill + $(grep -c "$SECRET" "$f" || true)))
  done < <(grep -o '/[^" ]*pi-[^" ]*\.\(log\|txt\)' "$WORK/stream.jsonl" | sort -u)
  updates=$(grep -c '"tool_execution_update"' "$WORK/stream.jsonl" || true)
  echo "--- $label: 生の秘密の出現 stream=$n_stream session=$n_session spill=$n_spill（途中経過のイベント $updates 件）"
}

run() {
  label=$1
  shift
  echo "=== $label"
  rm -rf "$WORK/sessions"
  set +e
  (cd "$WORK/proj" && timeout 120 pi --mode json --session-dir "$WORK/sessions" --model faux/spike "$@" > "$WORK/stream.jsonl" 2> "$WORK/stderr.txt")
  echo "exit=$?"
  set -e
  python3 - "$WORK/stream.jsonl" <<'PY'
import json, sys
last = None
for line in open(sys.argv[1]):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get("type") == "message_end" and (e.get("message") or {}).get("role") == "assistant":
        last = e["message"]
if last:
    print("".join(c.get("text", "") for c in last.get("content", []) if c.get("type") == "text")[:600])
PY
  leaks "$label"
}

BASE=(-nbt -ne -e "$HERE/harness" -e "$HERE/faux.ts")

# 4. 伏字化
FAUX_TOOL_CALLS='[{"name":"guarded_bash","args":{"command":"python3 big.py"}}]' run "4a bash の伏字化（途中経過・最終・退避ファイル）" "${BASE[@]}" go
SPIKE_REDACT_FAULT=1 FAUX_TOOL_CALLS='[{"name":"guarded_bash","args":{"command":"python3 big.py"}}]' run "4b 伏字化が例外を投げる" "${BASE[@]}" go

# 5. codemode
CM_DENY='[{"name":"codemode","args":{"code":"return await tools.guarded_bash({command: \"rm -rf /nonexistent-pi-spike\"});"}}]'
CM_SECRET='[{"name":"codemode","args":{"code":"const r = await tools.guarded_bash({command: \"python3 big.py\"}); return {head: r.output.slice(0, 80), path: r.full_output_path};"}}]'
SPIKE_ALLOW_TOOLS=codemode FAUX_TOOL_CALLS=$CM_DENY run "5a codemode から deny のコマンド" "${BASE[@]}" -e builtin:codemode --tools +codemode go
SPIKE_ALLOW_TOOLS=codemode FAUX_TOOL_CALLS=$CM_SECRET run "5b codemode から秘密を出すコマンド" "${BASE[@]}" -e builtin:codemode --tools +codemode go
FAUX_TOOL_CALLS=$CM_DENY run "5c codemode を判定 API が許可しない" "${BASE[@]}" -e builtin:codemode --tools +codemode go

# 6. MCP（ハーネスから登録）
export SPIKE_MCP_SERVER="$HERE/mcp_server.py"
MCP_CALL='[{"name":"mcp__spike__echo_secret","args":{}}]'
SECRET=mcp-raw-secret
FAUX_TOOL_CALLS=$MCP_CALL run "6a MCP のツールを判定 API が許可しない（既定）" "${BASE[@]}" -e builtin:mcp go
SPIKE_ALLOW_TOOLS=mcp__spike__echo_secret FAUX_TOOL_CALLS=$MCP_CALL run "6b MCP のツールを許可。結果の伏字化" "${BASE[@]}" -e builtin:mcp go
SPIKE_REDACT_FAULT=1 SPIKE_ALLOW_TOOLS=mcp__spike__echo_secret FAUX_TOOL_CALLS=$MCP_CALL run "6c MCP の結果の伏字化が例外を投げる" "${BASE[@]}" -e builtin:mcp go
rm -rf "$WORK/harness" && cp -r "$HERE/harness" "$WORK/harness"
SPIKE_BREAK_MODE=delete SPIKE_BREAK_FILE="$WORK/harness/index.ts" SPIKE_ALLOW_TOOLS=mcp__spike__echo_secret FAUX_TOOL_CALLS=$MCP_CALL \
  run "6d /reload でハーネスが抜けた後の MCP" -nbt -ne -e "$WORK/harness" -e "$HERE/faux.ts" -e builtin:mcp /spike-reload go
