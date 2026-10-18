#!/bin/bash
# 制限付き docker run ラッパー。詳細は sbx-help。
# 使い方: sbx-run [--net=none|bridge] [--root] <image> [command...]
set -euo pipefail
memory=@MEMORY@
workdir=/home/@USER@/work
usage="usage: sbx-run [--net=none|bridge] [--root] <image> [command...]  (詳細: sbx-help)"
net=none
user=(--user "$(id -u):$(id -g)")
while [ $# -gt 0 ]; do
  case "$1" in
    --net=none | --net=bridge) net="${1#--net=}"; shift ;;
    --net=*) echo "sbx-run: --net は none か bridge のみ" >&2; exit 2 ;;
    --root) user=(); shift ;;
    --help | -h) echo "$usage"; exit 0 ;;
    -*) echo "sbx-run: 未対応のオプション $1 (docker オプションは渡せません。sbx-help 参照)" >&2; exit 2 ;;
    *) break ;;
  esac
done
[ $# -ge 1 ] || { echo "$usage" >&2; exit 2; }
mkdir -p "$workdir"
exec docker run --rm --gpus all --network "$net" "${user[@]}" \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --memory "$memory" \
  -v "$workdir:/work" -w /work "$@"
