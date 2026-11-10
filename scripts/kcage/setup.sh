#!/bin/sh
# kcage のホスト初期設定（root）。Incus の導入・初期化・subuid・配備コピー・許可表・sudoers を整える
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "root で実行する: sudo sh $0 $*（sudo のパスワードは sudo 自身が尋ねる。保存しない）" >&2
  exit 1
fi

here=$(cd "$(dirname "$0")" && pwd)
exec python3 "$here/setup.py" "$@"
