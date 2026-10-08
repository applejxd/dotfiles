#!/usr/bin/env bash
# CHG-0019 段 4: 並列の ask を TUI で出す。tmux で pi の TUI を動かし、画面を写し取る。
# 引数 1: queue（順番待ちあり）| noqueue（なし。対照）
# 引数 2: direct（1 つの返答に tool call を 2 つ）| codemode（codemode の中で Promise.all）
# 引数 3: yes（Enter で Yes）| esc（Escape で取り消し）
# モデルは faux.ts の偽物。
# see docs/research/agents/pi-harness-spike.md
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
MODE=${1:-queue}
WORK=$(mktemp -d)
SESSION="pi-spike-$$"
trap 'tmux kill-session -t "$SESSION" 2>/dev/null || true; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/agent" "$WORK/proj"

VIA=${2:-direct}
KEY=Enter
[ "${3:-yes}" = esc ] && KEY=Escape
CALLS='[{"name":"guarded_bash","args":{"command":"touch first"}},{"name":"guarded_bash","args":{"command":"touch second"}}]'
EXTRA=""
if [ "$VIA" = codemode ]; then
  CALLS='[{"name":"codemode","args":{"code":"return await Promise.allSettled([tools.guarded_bash({command: \"touch first\"}), tools.guarded_bash({command: \"touch second\"})]);"}}]'
  EXTRA="-e builtin:codemode --tools +codemode"
fi
NOQUEUE=0
[ "$MODE" = noqueue ] && NOQUEUE=1

cat > "$WORK/start.sh" <<SH
cd "$WORK/proj"
export PI_CODING_AGENT_DIR="$WORK/agent" SPIKE_POLICY="$HERE/policy.py" SPIKE_RENAME=1 SPIKE_NO_QUEUE=$NOQUEUE SPIKE_ALLOW_TOOLS=codemode
export FAUX_TOOL_CALLS='$CALLS'
exec pi --no-session --model faux/spike -nbt -ne -e "$HERE/harness" -e "$HERE/faux.ts" $EXTRA
SH

tmux new-session -d -s "$SESSION" -x 140 -y 40 "bash $WORK/start.sh"

shot() {
  sleep "${2:-2}"
  echo "----- $1"
  tmux capture-pane -p -t "$SESSION" | sed -e 's/[[:space:]]*$//' | grep -v '^$' | tail -n 14
}

shot "起動" 4
tmux send-keys -t "$SESSION" "go" Enter
shot "go の後（確認 1 件目）" 3
tmux send-keys -t "$SESSION" "$KEY"
shot "$KEY の後" 3
tmux send-keys -t "$SESSION" "$KEY"
shot "もう一度 $KEY の後" 4
echo "----- 作られたファイル: $(cd "$WORK/proj" && ls)"
