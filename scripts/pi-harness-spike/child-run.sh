#!/usr/bin/env bash
# CHG-0019 段 4: 子エージェント（子の pi プロセス）の経路。モデルは faux.ts の偽物で、通信しない。
# see docs/research/agents/pi-harness-spike.md
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
SESSION="pi-spike-child-$$"
trap 'tmux kill-session -t "$SESSION" 2>/dev/null || true; rm -rf "$WORK"' EXIT
export PI_CODING_AGENT_DIR="$WORK/agent" SPIKE_POLICY="$HERE/policy.py" SPIKE_RENAME=1
export SPIKE_CHILD_EXTRA_EXT="$HERE/faux.ts"
mkdir -p "$PI_CODING_AGENT_DIR" "$WORK/proj"
TASK='[{"name":"guarded_task","args":{"task":"do it"}}]'
child_bash() { printf '[{"name":"guarded_bash","args":{"command":"%s"}}]' "$1"; }

run() {
  label=$1
  shift
  echo "=== $label"
  set +e
  (cd "$WORK/proj" && FAUX_TOOL_CALLS=$TASK timeout 120 pi -p --no-session --model faux/spike \
    -nbt -ne -e "$HERE/harness" -e "$HERE/faux.ts" "$@" go 2>&1)
  echo "--- exit=$? / 作業ツリー: $(find "$WORK/proj" -mindepth 1 -maxdepth 1 -printf '%f ')"
  set -e
}

SPIKE_CHILD_CALLS=$(child_bash "echo child-ok") run "7a 子が allow のコマンド"
SPIKE_CHILD_CALLS=$(child_bash "touch by-child") run "7b 子が ask のコマンド（子に UI は無い）"
SPIKE_BYPASS=1 SPIKE_CHILD_CALLS=$(child_bash "touch by-bypass-child") run "7c 親が bypass。子の ask"
SPIKE_BYPASS=1 SPIKE_CHILD_CALLS=$(child_bash "rm -rf /nonexistent-pi-spike") run "7d 親が bypass。子の deny"
SPIKE_CHILD_CALLS=$TASK run "7e 子がさらに子を起動しようとする"

# 7f 親の中断で子が残らないか（TUI で Escape）
cat > "$WORK/proj/sleep.py" <<'PY'
import os, time
open("child.pid", "w").write(str(os.getpid()))
time.sleep(60)
PY
cat > "$WORK/start.sh" <<SH
cd "$WORK/proj"
export PI_CODING_AGENT_DIR="$WORK/agent" SPIKE_POLICY="$HERE/policy.py" SPIKE_RENAME=1 SPIKE_CHILD_EXTRA_EXT="$HERE/faux.ts"
export FAUX_TOOL_CALLS='$TASK' SPIKE_CHILD_CALLS='$(child_bash "python3 sleep.py")'
exec pi --no-session --model faux/spike -nbt -ne -e "$HERE/harness" -e "$HERE/faux.ts"
SH
echo "=== 7f 親の中断（Escape）で子が残らないか"
tmux new-session -d -s "$SESSION" -x 140 -y 40 "bash $WORK/start.sh"
sleep 4
tmux send-keys -t "$SESSION" "go" Enter
sleep 6
pid=$(cat "$WORK/proj/child.pid" 2>/dev/null || echo none)
echo "孫（sleep.py）の pid: $pid、中断前: $(kill -0 "$pid" 2>/dev/null && echo 生きている || echo いない)"
tmux send-keys -t "$SESSION" Escape
sleep 3
echo "中断後: $(kill -0 "$pid" 2>/dev/null && echo 生きている || echo いない)"
echo "子の pi: $(pgrep -f "SPIKE_CHILD|$WORK/proj" -a | grep -c 'pi' || true) 件"
tmux capture-pane -p -t "$SESSION" | sed -e 's/[[:space:]]*$//' | grep -v '^$' | tail -n 8
