#!/bin/bash
# worker の課題用の作業リポジトリを base/ から作る。
# 使い方: mkws.sh <dest> [venv]   venv を渡すと <dest>/.venv にリンクする (依頼文の確認方法が使う)
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  echo "usage: $0 <dest> [venv]" >&2
  exit 2
fi
DEST="$1"
VENV="${2:-}"
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -a "$HERE/base" "$DEST"
if [ -n "$VENV" ]; then
  ln -s "$VENV" "$DEST/.venv"
fi
cd "$DEST"
git init -q -b main
git config user.name probe
git config user.email probe@example.invalid
git config commit.gpgSign false
git add -A
git -c core.hooksPath=/dev/null commit -qm "chore: initial import"
