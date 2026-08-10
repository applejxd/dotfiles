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
    local timestamp=$(date '+%H:%M:%S')
    TEST_RESULTS+=("[$timestamp] $step: $status $details")
    if [ "$status" = "FAILED" ] || [ "$status" = "TIMEOUT" ]; then
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
echo "🗂️  User=$(whoami)"
echo "🏠 HOME=$HOME"
echo "📦 Repo=/repo  APPLY=$APPLY"
echo "⚙️  CHEZMOI_ARGS=${CHEZMOI_ARGS}"
echo "⏱️  Started at: $(date)"

# HOMEディレクトリのセットアップ
sudo chown -R "$(whoami):$(id -gn)" "$HOME"
mkdir -p "$HOME/.config/chezmoi" "$HOME/.local/share"

# 方針A: テンプレートベースの初期化を試行
echo "🔧 Setting up chezmoi configuration..."

# 既存の設定を削除
rm -f "$HOME/.config/chezmoi/chezmoi.toml"

# テンプレートが存在するかチェック
if [ -f "/repo/home/.chezmoi.toml.tmpl" ]; then
    echo "📝 Found config template, using template-based initialization"
    # テンプレートを使って設定ファイル生成を試行
    template_content=$(chezmoi execute-template --init --source=/repo < /repo/home/.chezmoi.toml.tmpl 2>/dev/null || echo "")

    if [ -n "$template_content" ]; then
        echo "$template_content" > "$HOME/.config/chezmoi/chezmoi.toml"
        echo "✅ Template-based config generated"
    else
        echo "⚠️ Template generation failed, using fallback config"
        cat > "$HOME/.config/chezmoi/chezmoi.toml" << 'EOF'
# Fallback configuration for Docker test environment
sourceDir = "/repo"

[edit]
    command = "vim"

[data]
    # Docker test environment
EOF
    fi
else
    echo "📄 No template found, using simple config"
    cat > "$HOME/.config/chezmoi/chezmoi.toml" << 'EOF'
sourceDir = "/repo"
EOF
fi

# sourceDirを必ず設定（テンプレートに含まれていない場合のため）
if ! grep -q "sourceDir" "$HOME/.config/chezmoi/chezmoi.toml"; then
    echo 'sourceDir = "/repo"' >> "$HOME/.config/chezmoi/chezmoi.toml"
fi

echo "📁 Final chezmoi config:"
cat "$HOME/.config/chezmoi/chezmoi.toml"

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
echo "== chezmoi init (using pre-configured source) =="
# 設定ファイルでsourceDirを設定済みなので、引数不要
if chezmoi init --force; then
    log_result "init" "SUCCESS"
    echo "✅ Chezmoi initialized successfully"
else
    log_result "init" "FAILED"
    echo "❌ Chezmoi initialization failed"
    show_summary
fi

echo
echo "== chezmoi diff (dry-run) =="
echo "Checking which files will be modified..."
# diff は差分があると exit code 1, エラーは exit code > 1
set +e
diff_output=$(chezmoi diff ${CHEZMOI_ARGS} 2>/dev/null)
diff_exit_code=$?
set -e

# ファイル数をカウントして表示
if [ -n "$diff_output" ]; then
    file_count=$(echo "$diff_output" | grep -c "^diff --git" 2>/dev/null || echo 0)
    echo "📊 Found differences in $file_count files"
    if [ "$file_count" -gt 0 ]; then
        echo "First few files to be modified:"
        echo "$diff_output" | grep "^diff --git" | head -5 | sed 's/^diff --git a\//  - /' | sed 's/ b\/.*//' 2>/dev/null || echo "  (unable to parse filenames)"
        if [ "$file_count" -gt 5 ]; then
            echo "  ... and $((file_count - 5)) more files"
        fi
    else
        echo "No files found to modify"
    fi
    echo
else
    echo "No differences found"
    echo
fi

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
  echo "Note: This may take several minutes due to package installations..."
  echo "Progress will be shown in real-time below:"
  echo "----------------------------------------"

  # 重い処理や外部取得が走る場合はここで発火
  # プログレス表示のため、リアルタイムでアウトプットを表示
  if timeout 900 chezmoi apply --keep-going -v ${CHEZMOI_ARGS}; then
      echo "----------------------------------------"
      echo "✅ Apply completed successfully!"
      log_result "apply" "SUCCESS"
  else
      exit_code=$?
      echo "----------------------------------------"
      if [ $exit_code -eq 124 ]; then
          echo "⏰ Apply timed out after 15 minutes"
          log_result "apply" "TIMEOUT" "(apply timed out after 15 minutes)"
      else
          echo "❌ Apply failed with exit code: $exit_code"
          log_result "apply" "FAILED" "(apply command failed with exit code: $exit_code)"
      fi
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
