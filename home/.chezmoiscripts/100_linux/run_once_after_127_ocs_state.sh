#!/bin/sh
# 保護 ([sandbox] deny) が効く前に作られた ocs の承認・合格の記録を 1 回だけ捨てる。
# see docs/spec/opencode-sandbox.md#状態の置き場
set -eu

state="$HOME/.local/state/opencode-sandbox"
[ -d "$state" ] || exit 0

removed=0
for f in "$state/trusted.json" "$state/checked.json"; do
  if [ -e "$f" ] || [ -L "$f" ]; then
    rm -f "$f"
    removed=1
  fi
done
if [ -n "$(find "$state/" -mindepth 1 -maxdepth 1 -type l)" ]; then
  find "$state/" -mindepth 1 -maxdepth 1 -type l -exec rm -f {} +
  removed=1
fi
if [ "$removed" -eq 1 ]; then
  echo "ocs: 保護が効く前の承認と合格の記録を捨てた (次の起動で承認と境界チェックをやり直す)"
fi
