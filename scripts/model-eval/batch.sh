#!/bin/bash
# ジョブの一覧を並行に回す。1 行 1 実行で「<routine|worker> <run.sh の引数...>」。# で始まる行と空行は飛ばす。
# 使い方: batch.sh [-j 並行数] [-s] <jobs-file>   -s は行の順を乱数で混ぜる
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "${1:-}" = "--job" ]; then
  shift
  KIND="$1"
  shift
  case "$KIND" in
  routine | worker) exec bash "$HERE/$KIND/run.sh" "$@" ;;
  *)
    echo "未知の種類: $KIND" >&2
    exit 2
    ;;
  esac
fi
# shellcheck disable=SC1091
. "$HERE/env.sh"
usage() {
  echo "usage: $0 [-j jobs] [-s] <jobs-file>" >&2
  echo "  行の例: worker ws-medium bugfix 1 / routine -p routine/prompts/approved-long.txt -l ap rs-medium long 1" >&2
  exit 2
}
J=5
SHUFFLE=0
while getopts "j:sh" opt; do
  case "$opt" in
  j) J="$OPTARG" ;;
  s) SHUFFLE=1 ;;
  *) usage ;;
  esac
done
shift $((OPTIND - 1))
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  usage
fi
grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$1" |
  if [ "$SHUFFLE" = 1 ]; then
    python3 -c 'import random, sys; l = sys.stdin.readlines(); random.shuffle(l); sys.stdout.writelines(l)'
  else
    cat
  fi |
  (cd "$HERE" && xargs -P "$J" -L 1 bash "$HERE/batch.sh" --job)
echo "all done"
