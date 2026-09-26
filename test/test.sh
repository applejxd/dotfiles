#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash test/test.sh [service] [mode]

  service : ubuntu2404 (既定) | ubuntu2204 | raspi2204 | arm2404
  mode    : dryrun (既定) | apply | shell | place

  dryrun : doctor と diff まで (数十秒)
  place  : apply するがスクリプトを除外する (--exclude scripts)。配置だけ見る
  apply  : スクリプト込みの cold start (十数分。ネットワーク必須)
  shell  : コンテナへ入る

Examples:
  bash test/test.sh                      # 既定サービスで dry-run
  bash test/test.sh ubuntu2204 place     # 22.04 で配置だけ検証
  bash test/test.sh raspi2204 apply      # 実機 Pi に最も近い構成で cold start
  IS_RASPI=1 bash test/test.sh ubuntu2204 place   # 22.04 を Pi 扱いで検証

Notes:
  - リポジトリ直下から実行すること
  - raspi2204 / arm2404 は QEMU エミュレーションになるので遅い
  - コンテナはホストのカーネルを共有するため is-raspi の自動判定は
    再現できない。raspi2204 は IS_RASPI=1 で判定を注入する
USAGE
}

SERVICES="ubuntu2404 ubuntu2204 raspi2204 arm2404 chezmoi"
MODES="dryrun place apply shell"

check_prerequisites() {
    echo "== Prerequisites Check =="
    command -v docker >/dev/null 2>&1 || { echo "ERROR: docker command not found"; exit 1; }
    echo "✓ Docker command available"
    docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose not available"; exit 1; }
    echo "✓ Docker Compose available"
    [ -f "test/compose.yaml" ] || { echo "ERROR: test/compose.yaml not found. リポジトリ直下から実行してください"; exit 1; }
    echo "✓ compose.yaml found"
    [ -f ".chezmoiroot" ] || echo "WARNING: .chezmoiroot not found"
    echo "== Prerequisites Check Complete =="
    echo
}

service="ubuntu2404"
mode="dryrun"
for arg in "${@}"; do
    case " $SERVICES " in *" $arg "*) service="$arg"; continue ;; esac
    case " $MODES " in *" $arg "*) mode="$arg"; continue ;; esac
    case "$arg" in
        -h|--help|help) usage; exit 0 ;;
        *) echo "ERROR: 不明な引数: $arg"; echo; usage; exit 1 ;;
    esac
done

check_prerequisites

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-chezmoi-test}"
compose=(docker compose -f test/compose.yaml)

echo "== Target =="
echo "🧪 service = ${service}"
echo "🎛️  mode    = ${mode}"
echo "🍓 IS_RASPI = ${IS_RASPI:-（サービス既定）}"
echo

"${compose[@]}" build "$service"

case "$mode" in
  dryrun) APPLY=0 "${compose[@]}" run --rm "$service" ;;
  place)  APPLY=1 CHEZMOI_TEST_ARGS="${CHEZMOI_TEST_ARGS:---exclude scripts}" \
            "${compose[@]}" run --rm "$service" ;;
  apply)  APPLY=1 "${compose[@]}" run --rm "$service" ;;
  shell)  "${compose[@]}" run --rm "$service" bash ;;
esac
