#!/usr/bin/env bash
set -euo pipefail

# 環境変数
: "${APPLY:=0}"                # 0=dry-run, 1=apply
: "${IS_RASPI:=0}"             # 1 なら Raspberry Pi 扱いを注入する
: "${SOURCE_MODE:=clone}"      # clone=追跡ファイルのみ / mount=作業ツリーそのまま
# NOTE: 変数名に CHEZMOI_ARGS は使えない。chezmoi 自身が予約しており、
#       `chezmoi cd` のサブシェル等では CHEZMOI_ARGS="chezmoi cd" が
#       export されている。これを diff/apply に渡すと不正な引数になる。
: "${CHEZMOI_TEST_ARGS:=}"     # 追加引数（例: "--include tag=linux --exclude tag=mac"）

# ソースの取り方は 2 通り。SOURCE_MODE で選ぶ。実体の解決は
# $HOME が書けるようになってから (resolve_source) 行う。
#
#   clone (既定): /repo から git clone して **追跡ファイルだけ**を使う。
#     新 PC が実際に受け取るものと同じになる。作業ツリーの汚れ
#     (ローカルの .venv、壊れた symlink、未 add のファイル) を持ち込まないので、
#     「コミットし忘れ」も検出できる。
#   mount: /repo をそのまま使う。未コミットの変更を試したいときに使う。
#
# `chezmoi init` は .chezmoi.toml.tmpl から設定ファイルを再生成するため、
# 設定ファイルに書いた sourceDir は init で失われる（テンプレートに sourceDir が
# 無いので既定値 ~/.local/share/chezmoi に戻ってしまう）。
# そのため全ての chezmoi 呼び出しで --source を明示する。
CHEZMOI_SOURCE=/repo
CZ=(chezmoi --source="$CHEZMOI_SOURCE")

resolve_source() {
    if [ "${SOURCE_MODE}" != "clone" ]; then
        echo "📂 作業ツリーをそのまま使います: $CHEZMOI_SOURCE"
        return 0
    fi
    CHEZMOI_SOURCE="$HOME/src/dotfiles"
    mkdir -p "$(dirname "$CHEZMOI_SOURCE")"
    if ! git clone --quiet /repo "$CHEZMOI_SOURCE"; then
        echo "❌ /repo の clone に失敗しました"
        log_result "clone" "FAILED"
        show_summary
    fi
    CZ=(chezmoi --source="$CHEZMOI_SOURCE")
    echo "📥 clone しました (追跡ファイルのみ): $CHEZMOI_SOURCE"
    echo "   commit: $(git -C "$CHEZMOI_SOURCE" rev-parse --short HEAD)"
    log_result "clone" "SUCCESS" "($(git -C "$CHEZMOI_SOURCE" rev-parse --short HEAD))"
}

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
echo "📦 SOURCE_MODE=${SOURCE_MODE}  APPLY=$APPLY  IS_RASPI=$IS_RASPI"
echo "⚙️  CHEZMOI_TEST_ARGS=${CHEZMOI_TEST_ARGS}"
# shellcheck source=/dev/null
echo "🖥️  OS=$(. /etc/os-release && echo "$PRETTY_NAME")  ARCH=$(uname -m)"
echo "⏱️  Started at: $(date)"

# HOMEディレクトリのセットアップ
sudo chown -R "$(whoami):$(id -gn)" "$HOME"
mkdir -p "$HOME/.config/chezmoi" "$HOME/.local/share"

# $HOME が書けるようになったのでソースを確定する (clone はここで走る)
resolve_source

# 方針A: テンプレートベースの初期化を試行
echo "🔧 Setting up chezmoi configuration..."

# 既存の設定を削除
rm -f "$HOME/.config/chezmoi/chezmoi.toml"

# テンプレートが存在するかチェック
if [ -f "${CHEZMOI_SOURCE}/home/.chezmoi.toml.tmpl" ]; then
    echo "📝 Found config template, using template-based initialization"
    # テンプレートを使って設定ファイル生成を試行
    # ★フォールバックを置かない。描画に失敗したら、それが検出したい不具合。
    #   代替 config を書いて続行すると、テンプレート破損を握り潰して
    #   「apply は通った」という偽陰性になる。実際に `*/` でコメントが
    #   壊れた事故がある。see docs/change/closed/0008-raspi-branching.md
    if ! template_content=$(chezmoi execute-template --init --source="$CHEZMOI_SOURCE" \
        < "${CHEZMOI_SOURCE}/home/.chezmoi.toml.tmpl" 2>&1); then
        echo "❌ 設定テンプレートの描画に失敗しました"
        echo "$template_content"
        log_result "config-template" "FAILED" "(.chezmoi.toml.tmpl の描画に失敗)"
        show_summary
    fi
    if [ -z "$template_content" ]; then
        echo "❌ 設定テンプレートの描画結果が空です"
        log_result "config-template" "FAILED" "(描画結果が空)"
        show_summary
    fi
    echo "$template_content" > "$HOME/.config/chezmoi/chezmoi.toml"
    log_result "config-template" "SUCCESS"
    echo "✅ Template-based config generated"
else
    echo "❌ ${CHEZMOI_SOURCE}/home/.chezmoi.toml.tmpl が見つかりません"
    log_result "config-template" "FAILED" "(テンプレートが無い)"
    show_summary
fi

# sourceDir は --source フラグで毎回明示するので、設定ファイル側は保険にとどめる
if ! grep -q "sourceDir" "$HOME/.config/chezmoi/chezmoi.toml"; then
    echo "sourceDir = \"${CHEZMOI_SOURCE}\"" >> "$HOME/.config/chezmoi/chezmoi.toml"
fi

# Raspberry Pi 扱いの注入。
# ★コンテナはホストのカーネルを共有するので、is-raspi の自動判定
#   (kernel.osrelease / /proc/device-tree/model) は原理的に再現できない。
#   分岐の「帰結」を見たいので、データ上書きで判定だけ与える。
#   判定ロジックそのものの検証は test/test_raspi_detection.py が担う。
if [ "${IS_RASPI}" = "1" ]; then
    cfg="$HOME/.config/chezmoi/chezmoi.toml"
    # [data] はテンプレート末尾の節なので、末尾追記でその中に入る。
    # 前提が崩れたら黙って効かなくなるので、節の数を確かめてから追記する。
    if [ "$(grep -c '^\[data\]' "$cfg")" -ne 1 ]; then
        echo "❌ [data] 節が 1 つではないので is_raspi を注入できません"
        log_result "inject-is-raspi" "FAILED" "([data] 節が 1 つではない)"
        show_summary
    fi
    printf '    is_raspi = true\n' >> "$cfg"
    # 注入が効いたかを実際に評価して確かめる (追記位置の前提が崩れたら落とす)
    injected=$(chezmoi --source="$CHEZMOI_SOURCE" execute-template \
        '{{ includeTemplate "is-raspi" . }}' 2>&1) || injected="<failed>"
    if [ "$injected" != "true" ]; then
        echo "❌ is_raspi の注入が効いていません (got: ${injected})"
        log_result "inject-is-raspi" "FAILED" "(got: ${injected})"
        show_summary
    fi
    log_result "inject-is-raspi" "SUCCESS" "(Raspberry Pi 扱いで検証する)"
    echo "🍓 Raspberry Pi 扱いを注入しました"
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
# init が設定を書き換えても --source が効いているかを確認する。
# ここが壊れると diff/apply が「差分なし」に見えてテストが偽陽性になる。
resolved_source=$("${CZ[@]}" source-path 2>&1) || resolved_source=""
echo "source-path = ${resolved_source:-<failed>}"
case "$resolved_source" in
    "$CHEZMOI_SOURCE"|"$CHEZMOI_SOURCE"/*)
        log_result "source-check" "SUCCESS" "($resolved_source)"
        ;;
    *)
        log_result "source-check" "FAILED" "(expected under ${CHEZMOI_SOURCE}, got: ${resolved_source:-<failed>})"
        echo "❌ source dir is not ${CHEZMOI_SOURCE} — diff/apply results would be meaningless"
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
    # ★apply モードでは diff の失敗で止めない。
    #   cold start では modify スクリプトが要る python3 などがまだ無く、
    #   それを用意するのは run_before_ スクリプト側。diff はスクリプトを
    #   走らせないので、素の機械では diff が先に落ちるのが正常な姿になる。
    #   ここで止めると apply に一度も到達できない。
    if [ "${APPLY}" = "1" ]; then
        log_result "diff" "UNDETERMINED" "(exit code: $diff_exit_code / apply で判定する)"
        echo "⏭️  apply モードなので続行します (diff は判定材料にしない)"
    else
        log_result "diff" "FAILED" "(exit code: $diff_exit_code)"
        show_summary
    fi
fi

# ファイル数をカウントして表示
# NOTE: `... | head -5` のように途中で打ち切るパイプは上流に SIGPIPE を返し、
#       `set -o pipefail` により失敗扱いになってスクリプトが中断する。
#       配列に読み込んでから bash のスライスで絞る。
mapfile -t diff_files < <(grep "^diff --git" <<< "$diff_output" \
    | sed 's/^diff --git a\//  - /; s/ b\/.*//')
file_count=${#diff_files[@]}

# 失敗した diff の件数は判定材料にならない (途中で止まっているため)。
# 上で UNDETERMINED を記録済みなので、ここでは二重に記録しない。
if [ "$diff_exit_code" -ne 0 ]; then
    echo "📊 (diff は途中で失敗したので件数は参考値: ${file_count})"
elif [ "$file_count" -gt 0 ]; then
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
