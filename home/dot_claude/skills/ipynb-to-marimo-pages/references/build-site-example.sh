#!/usr/bin/env bash
#
# marimo notebook を静的HTMLへエクスポートするスクリプトの雛形。
#
# `marimo export html` は各ノートブックを**実際に実行する**。有料APIを呼ぶ
# ノートブックでは課金が発生する。環境変数が必要なら、それを注入する仕組み
# （mise + SOPS など）を通して実行すること。
#
# 使い方の例:
#   bash scripts/build-site.sh
#   mise exec -- bash scripts/build-site.sh   # 復号した環境変数を渡す場合

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

site_dir="site"
log_dir="$(mktemp -d)"
trap 'rm -rf "$log_dir"' EXIT

# 公開するノートブックと、index に載せるタイトル。
notebooks=(
    notebook_a.py
    notebook_b.py
)

titles=(
    "ノートブックA のタイトル"
    "ノートブックB のタイトル"
)

mkdir -p "$site_dir"
# Jekyll による加工を止め、エクスポートした資産をそのまま配信する。
touch "$site_dir/.nojekyll"

failed=0

for i in "${!notebooks[@]}"; do
    notebook="${notebooks[$i]}"
    output="$site_dir/${notebook%.py}.html"
    log="$log_dir/${notebook%.py}.log"

    echo "==> exporting $notebook"

    # --sandbox は付けない。ノートブックが PEP 723 のインライン依存を持たない
    # 場合、隔離環境で依存を解決できずに失敗する。
    if ! uv run marimo export html "$notebook" -o "$output" --force >"$log" 2>&1; then
        echo "    FAILED: marimo export returned a non-zero status" >&2
        sed 's/^/    /' "$log" >&2
        # 部分的に書き出された HTML を残さない。
        rm -f "$output"
        failed=1
        continue
    fi

    # `marimo export html` はセルが例外を投げても exit 0 を返し、しかも
    # HTML を書き出してから終了する。ログを検査して壊れた成果物を破棄する。
    # 外部サイトの一時的な不調もここに現れる（再実行で解消することが多い）。
    if grep -q "some cells failed to execute" "$log"; then
        echo "    FAILED: some cells raised during execution" >&2
        grep -E "MarimoExceptionRaisedError|Error:" "$log" | sort -u | sed 's/^/    /' >&2
        rm -f "$output"
        failed=1
        continue
    fi

    echo "    wrote $output"
done

if [[ $failed -ne 0 ]]; then
    echo "Export failed; the affected HTML was discarded rather than published." >&2
    exit 1
fi

# エクスポートされた HTML は画像を相対パス `imgs/...` で参照する。
# site/imgs/ を gitignore する運用なら、デプロイ時に CI 側でも復元する。
if [[ -d imgs ]]; then
    rm -rf "${site_dir:?}/imgs"
    cp -r imgs "$site_dir/imgs"
fi

{
    cat <<'HEADER'
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Notebooks</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 44rem; margin: 3rem auto; padding: 0 1rem; line-height: 1.7; }
li { margin-bottom: 0.5rem; }
</style>
</head>
<body>
<h1>Notebooks</h1>
<ul>
HEADER

    for i in "${!notebooks[@]}"; do
        notebook="${notebooks[$i]}"
        printf '<li><a href="%s.html">%s</a></li>\n' "${notebook%.py}" "${titles[$i]}"
    done

    cat <<'FOOTER'
</ul>
</body>
</html>
FOOTER
} >"$site_dir/index.html"

echo "==> wrote $site_dir/index.html"
echo "Done. Preview with: python -m http.server --directory $site_dir"
