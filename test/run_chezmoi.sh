#!/usr/bin/env bash
set -euo pipefail

# 環境変数
: "${APPLY:=0}"                # 0=dry-run, 1=apply
: "${CHEZMOI_ARGS:=}"          # 追加引数（例: "--include tag=linux --exclude tag=mac"）

# 実行結果追跡
TEST_RESULTS=()
TEST_STATUS="SUCCESS"

# 結果記録関数
log_result() {
    local step="$1"
    local status="$2"
    local details="${3:-}"
    TEST_RESULTS+=("$step: $status $details")
    if [ "$status" = "FAILED" ]; then
        TEST_STATUS="FAILED"
    fi
}

# サマリー表示関数
show_summary() {
    echo
    echo "======================================"
    echo "== TEST EXECUTION SUMMARY =="
    echo "======================================"
    for result in "${TEST_RESULTS[@]}"; do
        echo "$result"
    done
    echo "======================================"
    echo "OVERALL STATUS: $TEST_STATUS"
    echo "======================================"

    if [ "$TEST_STATUS" = "FAILED" ]; then
        exit 1
    fi
}

echo "== Environment =="
echo "User=$(whoami)"
echo "HOME=$HOME"
echo "Repo=/repo  APPLY=$APPLY"
echo "CHEZMOI_ARGS=${CHEZMOI_ARGS}"

# HOMEディレクトリのセットアップ
sudo chown -R "$(whoami):$(id -gn)" "$HOME"
mkdir -p "$HOME/.config/chezmoi" "$HOME/.local/share"

# chezmoi設定ファイル作成（sourceDirを/repoに設定）
cat > "$HOME/.config/chezmoi/chezmoi.toml" << 'EOF'
sourceDir = "/repo"
EOF

chezmoi --version
git --version || true

echo
echo "== chezmoi doctor =="
if chezmoi doctor; then
    log_result "doctor" "SUCCESS"
else
    log_result "doctor" "WARNING" "(doctor warnings are not fatal)"
fi

echo
echo "== chezmoi init (no explicit source needed) =="
if chezmoi init; then
    log_result "init" "SUCCESS"
else
    log_result "init" "FAILED"
    show_summary
fi

echo
echo "== chezmoi diff (dry-run) =="
# diff は差分があると exit code 1, エラーは exit code > 1
set +e
chezmoi diff ${CHEZMOI_ARGS}
diff_exit_code=$?
set -e

case $diff_exit_code in
    0)
        log_result "diff" "SUCCESS" "(no differences)"
        ;;
    1)
        log_result "diff" "SUCCESS" "(differences found - this is expected)"
        ;;
    *)
        log_result "diff" "FAILED" "(exit code: $diff_exit_code)"
        ;;
esac

if [ "${APPLY}" = "1" ]; then
  echo
  echo "== chezmoi apply (keep-going, verbose) =="
  # 重い処理や外部取得が走る場合はここで発火
  if chezmoi apply --keep-going -v ${CHEZMOI_ARGS}; then
      log_result "apply" "SUCCESS"
  else
      log_result "apply" "FAILED" "(apply command failed)"
  fi

  echo
  echo "== Re-run doctor after apply =="
  if chezmoi doctor; then
      log_result "post-apply-doctor" "SUCCESS"
  else
      log_result "post-apply-doctor" "WARNING" "(doctor warnings are not fatal)"
  fi
else
  echo
  echo "== Skip apply (set APPLY=1 to enable) =="
  log_result "apply" "SKIPPED"
fi

# 最終サマリー表示
show_summary