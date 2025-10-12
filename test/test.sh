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

# 事前チェック関数
check_prerequisites() {
    echo "== Prerequisites Check =="

    # Dockerコマンドの確認
    if ! command -v docker &> /dev/null; then
        echo "ERROR: docker command not found"
        exit 1
    fi
    echo "✓ Docker command available"

    # Docker Composeの確認
    if ! docker compose version &> /dev/null; then
        echo "ERROR: docker compose command not available"
        exit 1
    fi
    echo "✓ Docker Compose available"

    # compose.yamlの存在確認
    if [ ! -f "test/compose.yaml" ]; then
        echo "ERROR: test/compose.yaml not found. Please run from repository root."
        exit 1
    fi
    echo "✓ compose.yaml found"

    # chezmoiリポジトリ構造の確認
    if [ ! -f ".chezmoiroot" ]; then
        echo "WARNING: .chezmoiroot not found. This might not be a chezmoi repository."
    else
        echo "✓ chezmoi repository structure detected"
    fi

    echo "== Prerequisites Check Complete =="
    echo
}

cmd="${1:-dryrun}"

# 事前チェック実行
check_prerequisites

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-chezmoi-test}"

case "$cmd" in
  dryrun)
    # APPLY=0（既定）で実行
    docker compose -f test/compose.yaml build
    APPLY=0 docker compose -f test/compose.yaml run --rm chezmoi
    ;;
  apply)
    docker compose -f test/compose.yaml build
    APPLY=1 docker compose -f test/compose.yaml run --rm chezmoi
    ;;
  shell)
    docker compose -f test/compose.yaml build
    # そのままコンテナに入って手動で試験
    docker compose -f test/compose.yaml run --rm chezmoi bash
    ;;
  *)
    usage
    exit 1
    ;;
esac