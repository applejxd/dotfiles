#!/bin/bash
# 1 回の隔離実行。<run-dir>/ws で <run-dir>/prompt.txt を opencode run に渡す。
# 使い方: run_isolated.sh <run-dir> <cfg-dir> <timeout 秒>
# 実 DB ($EVAL_SOURCE_DB) を読み取り専用で複製し、終わったら sessions.json へ書き出して消す。
# see scripts/model-eval/README.md#隔離の仕組み
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -ne 3 ]; then
  echo "usage: $0 <run-dir> <cfg-dir> <timeout-sec>" >&2
  exit 2
fi
RUN="$1"
CFG="$2"
TIMEOUT="$3"
SRC_DB="${EVAL_SOURCE_DB:-$HOME/.local/share/opencode/opencode.db}"
for f in "$CFG/opencode.json" "$RUN/prompt.txt"; do
  if [ ! -f "$f" ]; then
    echo "無い: $f" >&2
    exit 2
  fi
done
if [ ! -d "$RUN/ws" ]; then
  echo "無い: $RUN/ws" >&2
  exit 2
fi

mkdir -p "$RUN/xdg/data" "$RUN/xdg/state" "$RUN/xdg/cache" "$RUN/tmp"
trap 'rm -f "$RUN/seed.db" "$RUN/seed.db-wal" "$RUN/seed.db-shm" "$RUN/seed.db-journal"' EXIT
python3 "$HERE/seed_db.py" seed ${EVAL_ALLOW_NO_CREDENTIAL:+--allow-no-credential} "$SRC_DB" "$RUN/seed.db"

cd "$RUN/ws"
env -u OPENCODE_CONFIG -u OPENCODE_CONFIG_CONTENT \
  TMPDIR="$RUN/tmp" \
  XDG_DATA_HOME="$RUN/xdg/data" XDG_STATE_HOME="$RUN/xdg/state" XDG_CACHE_HOME="$RUN/xdg/cache" \
  OPENCODE_DB="$RUN/seed.db" OPENCODE_CONFIG_DIR="$CFG" \
  PROBE_LOG="$RUN/events.ndjson" \
  timeout "$TIMEOUT" opencode run --standalone --auto --format json "$(cat "$RUN/prompt.txt")" \
  >"$RUN/out.ndjson" 2>"$RUN/err.log" || echo "exit=$? ($(basename "$RUN"))"
find "$RUN/tmp" -type f >"$RUN/tmp-files.txt" || true
python3 "$HERE/seed_db.py" export "$RUN/seed.db" "$RUN/sessions.json"
