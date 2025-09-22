#!/usr/bin/env bash
set -euo pipefail

# 環境変数
: "${APPLY:=0}"                # 0=dry-run, 1=apply
: "${CHEZMOI_ARGS:=}"          # 追加引数（例: "--include tag=linux --exclude tag=mac"）

echo "== Environment =="
echo "User=$(whoami)"
echo "HOME=$HOME"
echo "Repo=/repo  APPLY=$APPLY"
echo "CHEZMOI_ARGS=${CHEZMOI_ARGS}"
chezmoi --version
git --version || true

echo
echo "== chezmoi doctor =="
chezmoi doctor || true

echo
echo "== chezmoi init (source=/repo) =="
chezmoi init --source=/repo

echo
echo "== chezmoi diff (dry-run) =="
# diff は差分があると非0終了になり得るので、観察優先で || true
chezmoi diff ${CHEZMOI_ARGS} || true

if [ "${APPLY}" = "1" ]; then
  echo
  echo "== chezmoi apply (keep-going, verbose) =="
  # 重い処理や外部取得が走る場合はここで発火
  chezmoi apply --keep-going -v ${CHEZMOI_ARGS}

  echo
  echo "== Re-run doctor after apply =="
  chezmoi doctor || true
else
  echo
  echo "== Skip apply (set APPLY=1 to enable) =="
fi