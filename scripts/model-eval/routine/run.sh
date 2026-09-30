#!/bin/bash
# routine (commit) の 1 回の実行。
# 使い方: run.sh [-p <prompt-file>] [-l <run-label>] <cfg-label> <scenario> [回]
# 出力は $EVAL_OUT/runs/routine/<run-label (既定は cfg-label)>-<scenario>-<回>
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$HERE/../env.sh"
usage() {
  echo "usage: $0 [-p prompt-file] [-l run-label] <cfg-label> <scenario> [n]" >&2
  echo "  scenario: multi new delete long newdir   prompt: $HERE/prompts/*.txt" >&2
  exit 2
}
PROMPT_FILE="$HERE/prompts/default.txt"
LABEL=""
while getopts "p:l:h" opt; do
  case "$opt" in
  p) PROMPT_FILE="$OPTARG" ;;
  l) LABEL="$OPTARG" ;;
  *) usage ;;
  esac
done
shift $((OPTIND - 1))
if [ "$#" -lt 2 ]; then
  usage
fi
CFG="$1"
SCN="$2"
N="${3:-1}"
CFG_DIR="$EVAL_OUT/cfg/$CFG"
if [ ! -f "$CFG_DIR/opencode.json" ]; then
  echo "設定が無い: $CFG_DIR (gen_config.py $CFG で作る)" >&2
  exit 2
fi
if [ ! -f "$PROMPT_FILE" ]; then
  echo "依頼文が無い: $PROMPT_FILE" >&2
  exit 2
fi
NAME="${LABEL:-$CFG}-${SCN}-${N}"
RUN="$EVAL_OUT/runs/routine/$NAME"

rm -rf "$RUN"
START=$(date +%s)
bash "$HERE/mkscn.sh" "$SCN" "$RUN/ws"
cp "$PROMPT_FILE" "$RUN/prompt.txt"

bash "$HERE/../run_isolated.sh" "$RUN" "$CFG_DIR" "${EVAL_TIMEOUT:-1200}"
g() { git -C "$RUN/ws" -c core.fsmonitor=false -c core.hooksPath=/dev/null "$@"; }
g log --format='--- %s%n%b' main >"$RUN/log.txt"
g log --format='%B%x00' main >"$RUN/raw.txt"
g status --short >"$RUN/status.txt"
echo "$(($(date +%s) - START))" >"$RUN/wall.txt"
echo "done $NAME $(($(date +%s) - START))s"
