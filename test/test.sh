#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./test.sh         # ドライラン（diff/doctorまで）
  ./test.sh apply   # 実適用（コンテナ内HOMEにapply）
  ./test.sh shell   # コンテナ内にシェルで入る（デバッグ用）
USAGE
}

cmd="${1:-dryrun}"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-chezmoi-test}"

case "$cmd" in
  dryrun)
    # APPLY=0（既定）で実行
    docker compose build
    APPLY=0 docker compose run --rm chezmoi
    ;;
  apply)
    docker compose build
    APPLY=1 docker compose run --rm chezmoi
    ;;
  shell)
    docker compose build
    # そのままコンテナに入って手動で試験
    docker compose run --rm chezmoi bash
    ;;
  *)
    usage
    exit 1
    ;;
esac