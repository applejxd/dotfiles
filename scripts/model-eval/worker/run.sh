#!/bin/bash
# worker (fleet-worker) の 1 回の実行と採点。
# 使い方: run.sh <cfg-label> <task> [回]   出力は $EVAL_OUT/runs/worker/<cfg-label>-<task>-<回>
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$HERE/../env.sh"
if [ "$#" -lt 2 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  echo "usage: $0 <cfg-label> <task> [n]   task: feature bugfix refactor tests multi semver ini" >&2
  exit 2
fi
CFG="$1"
TASK="$2"
N="${3:-1}"
CFG_DIR="$EVAL_OUT/cfg/$CFG"
if [ ! -f "$HERE/briefs/$TASK.txt" ]; then
  echo "未知の課題: $TASK" >&2
  exit 2
fi
if [ ! -f "$CFG_DIR/opencode.json" ]; then
  echo "設定が無い: $CFG_DIR (gen_config.py $CFG で作る)" >&2
  exit 2
fi
NAME="${CFG}-${TASK}-${N}"
RUN="$EVAL_OUT/runs/worker/$NAME"
VENV="$EVAL_OUT/venv"

# 課題の確認方法 (.venv/bin/python -m pytest) が使う共有の venv。並行実行でも 1 回だけ作る
if [ ! -f "$VENV/.ready" ]; then
  until mkdir "$EVAL_OUT/venv.lock" 2>/dev/null; do sleep 1; done
  trap 'rmdir "$EVAL_OUT/venv.lock"' EXIT
  if [ ! -f "$VENV/.ready" ]; then
    rm -rf "$VENV"
    uv venv -q --python "${EVAL_WORKER_PYTHON:-3.12}" "$VENV"
    uv pip install -q --python "$VENV/bin/python" "pytest==${EVAL_PYTEST_VERSION:-9.1.1}"
    touch "$VENV/.ready"
  fi
  rmdir "$EVAL_OUT/venv.lock"
  trap - EXIT
fi

rm -rf "$RUN"
START=$(date +%s)
bash "$HERE/mkws.sh" "$RUN/ws" "$VENV"
BRIEF="$(sed "s|{WS}|$RUN/ws|" "$HERE/briefs/$TASK.txt")"
PROMPT="次の作業を fleet-worker に 1 件だけ任せてください。下の依頼文を一字も変えずに、そのまま subagent ツールで fleet-worker へ渡してください。あなた自身はファイルを読んだり編集したりコマンドを実行したりしないでください。fleet-worker の報告を受け取ったら、それをそのまま返して終わってください。

依頼文:

${BRIEF}"
printf '%s\n' "$PROMPT" >"$RUN/prompt.txt"

PROBE_APPROVE_ALL="${PROBE_APPROVE_ALL:-1}" \
  bash "$HERE/../run_isolated.sh" "$RUN" "$CFG_DIR" "${EVAL_TIMEOUT:-1800}"
git -C "$RUN/ws" -c core.fsmonitor=false -c core.hooksPath=/dev/null diff >"$RUN/diff.patch" || true
echo "$(($(date +%s) - START))" >"$RUN/wall.txt"
python3 "$HERE/grade.py" --python "$VENV/bin/python" "$RUN" "$TASK" >"$RUN/grade.line" 2>&1 ||
  echo "grade failed ($NAME)"
echo "done $NAME $(($(date +%s) - START))s $(python3 -c "import json,sys;g=json.load(open(sys.argv[1]));print('PASS' if g['passed'] else 'FAIL', 'oos=', g['out_of_scope'])" "$RUN/grade.json" 2>/dev/null)"
