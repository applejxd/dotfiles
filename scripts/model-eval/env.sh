#!/bin/bash
# run.sh / batch.sh が source する。EVAL_OUT (出力先) を決めて export する。
# 出力には資格情報入りの DB が一時的に置かれるので、リポジトリの中なら .tmp/ の下に限る。
set -eu
EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL_REPO="$(cd "$EVAL_ROOT/../.." && pwd)"
EVAL_OUT="${EVAL_OUT:-$EVAL_REPO/.tmp/model-eval}"
case "$EVAL_OUT" in
/*) ;;
*) EVAL_OUT="$PWD/$EVAL_OUT" ;;
esac
case "$EVAL_OUT/" in
"$EVAL_REPO/.tmp/"*) ;;
"$EVAL_REPO/"*)
  echo "EVAL_OUT はリポジトリの中なら .tmp/ の下にする: $EVAL_OUT" >&2
  exit 2
  ;;
esac
mkdir -p "$EVAL_OUT"
export EVAL_OUT EVAL_ROOT EVAL_REPO
