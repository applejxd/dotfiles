#!/usr/bin/env bash
set -euo pipefail

# 環境変数
: "${APPLY:=0}"                # 0=dry-run, 1=apply
# NOTE: 変数名に CHEZMOI_ARGS は使えない。chezmoi 自身が予約しており、
#       `chezmoi cd` のサブシェル等では CHEZMOI_ARGS="chezmoi cd" が
#       export されている。これを diff/apply に渡すと不正な引数になる。
: "${CHEZMOI_TEST_ARGS:=}"     # 追加引数（例: "--include tag=linux --exclude tag=mac"）

# ソースディレクトリはコンテナ内では常に /repo。
# `chezmoi init` は .chezmoi.toml.tmpl から設定ファイルを再生成するため、
# 設定ファイルに書いた sourceDir は init で失われる（テンプレートに sourceDir が
# 無いので既定値 ~/.local/share/chezmoi に戻ってしまう）。
# そのため全ての chezmoi 呼び出しで --source を明示する。
CHEZMOI_SOURCE=/repo
CZ=(chezmoi --source="$CHEZMOI_SOURCE")

# CHEZMOI_TEST_ARGS は空白区切りの追加引数。意図的に分割するので配列に展開する。
read -r -a CHEZMOI_ARG_ARRAY <<< "${CHEZMOI_TEST_ARGS}"

# 実行結果追跡
TEST_RESULTS=()
TEST_STATUS="SUCCESS"

# 結果記録関数
log_result() {
    local step="$1"
    local status="$2"
    local details="${3:-}"
    local timestamp
    timestamp=$(date '+%H:%M:%S')
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
echo "⚙️  CHEZMOI_TEST_ARGS=${CHEZMOI_TEST_ARGS}"
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
    template_content=$(chezmoi execute-template --init --source="$CHEZMOI_SOURCE" \
        < /repo/home/.chezmoi.toml.tmpl 2>&1) || template_content=""

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

# sourceDir は --source フラグで毎回明示するので、設定ファイル側は保険にとどめる
if ! grep -q "sourceDir" "$HOME/.config/chezmoi/chezmoi.toml"; then
    echo 'sourceDir = "/repo"' >> "$HOME/.config/chezmoi/chezmoi.toml"
fi

echo "📁 Final chezmoi config:"
cat "$HOME/.config/chezmoi/chezmoi.toml"

chezmoi --version
git --version || true

echo
echo "== chezmoi doctor =="
if "${CZ[@]}" doctor; then
    log_result "doctor" "SUCCESS"
else
    log_result "doctor" "WARNING" "(doctor warnings are not fatal)"
fi

echo
echo "== chezmoi init (using --source=$CHEZMOI_SOURCE) =="
if "${CZ[@]}" init --force; then
    log_result "init" "SUCCESS"
    echo "✅ Chezmoi initialized successfully"
else
    log_result "init" "FAILED"
    echo "❌ Chezmoi initialization failed"
    show_summary
fi

echo
echo "== source resolution check =="
# init が設定を書き換えても --source で /repo を指せているかを確認する。
# ここが壊れると diff/apply が「差分なし」に見えてテストが偽陽性になる。
resolved_source=$("${CZ[@]}" source-path 2>&1) || resolved_source=""
echo "source-path = ${resolved_source:-<failed>}"
case "$resolved_source" in
    /repo|/repo/*)
        log_result "source-check" "SUCCESS" "($resolved_source)"
        ;;
    *)
        log_result "source-check" "FAILED" "(expected under /repo, got: ${resolved_source:-<failed>})"
        echo "❌ source dir is not /repo — diff/apply results would be meaningless"
        show_summary
        ;;
esac

echo
echo "== chezmoi diff (dry-run) =="
echo "Checking which files will be modified..."
# chezmoi diff は差分の有無に関わらず正常終了は 0。非 0 はエラーなので失敗扱いにする。
# stderr も取り込む (捨てるとテンプレートエラーを見逃す)。
set +e
diff_output=$("${CZ[@]}" diff "${CHEZMOI_ARG_ARRAY[@]}" 2>&1)
diff_exit_code=$?
set -e

if [ "$diff_exit_code" -ne 0 ]; then
    echo "❌ chezmoi diff failed (exit code: $diff_exit_code)"
    echo "$diff_output"
    log_result "diff" "FAILED" "(exit code: $diff_exit_code)"
    show_summary
fi

# ファイル数をカウントして表示
# NOTE: `... | head -5` のように途中で打ち切るパイプは上流に SIGPIPE を返し、
#       `set -o pipefail` により失敗扱いになってスクリプトが中断する。
#       配列に読み込んでから bash のスライスで絞る。
mapfile -t diff_files < <(grep "^diff --git" <<< "$diff_output" \
    | sed 's/^diff --git a\//  - /; s/ b\/.*//')
file_count=${#diff_files[@]}

if [ "$file_count" -gt 0 ]; then
    echo "📊 Found differences in $file_count files"
    echo "First few files to be modified:"
    printf '%s\n' "${diff_files[@]:0:5}"
    if [ "$file_count" -gt 5 ]; then
        echo "  ... and $((file_count - 5)) more files"
    fi
    log_result "diff" "SUCCESS" "($file_count files differ)"
else
    echo "No differences found"
    log_result "diff" "SUCCESS" "(no differences)"
fi
echo

if [ "${APPLY}" = "1" ]; then
  echo
  echo "== chezmoi apply (keep-going, verbose) =="
  echo "Note: This may take several minutes due to package installations..."
  echo "Progress will be shown in real-time below:"
  echo "----------------------------------------"

  # 重い処理や外部取得が走る場合はここで発火
  # プログレス表示のため、リアルタイムでアウトプットを表示
  if timeout 900 "${CZ[@]}" apply --keep-going -v "${CHEZMOI_ARG_ARRAY[@]}"; then
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
  if "${CZ[@]}" doctor; then
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
