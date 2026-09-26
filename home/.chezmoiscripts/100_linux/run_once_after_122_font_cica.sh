#!/bin/bash
# Cica フォントをインストールする
# cf. https://github.com/miiton/Cica

set -euo pipefail

# fontconfig が無い環境 (ヘッドレスの Raspberry Pi OS Lite など) では、
# fc-list が無いまま「未導入」と判定されて進み、末尾の fc-cache で
# command not found になる。set -e で apply 全体が止まるので先に降りる。
if ! command -v fc-cache >/dev/null 2>&1 || ! command -v fc-list >/dev/null 2>&1; then
    echo "fontconfig が無いので Cica フォントの導入を飛ばします"
    exit 0
fi

CICA_VERSION="v5.0.3"
CICA_URL="https://github.com/miiton/Cica/releases/download/${CICA_VERSION}/Cica_${CICA_VERSION}.zip"
FONT_DIR="$HOME/.local/share/fonts/Cica"

# すでにインストール済みならスキップ
if fc-list | grep -qi "Cica"; then
    echo "✅ Cica フォントはすでにインストールされています"
    exit 0
fi

echo "Cica フォント (${CICA_VERSION}) をインストールします..."

# 一時ディレクトリで作業
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

# ダウンロード・展開
wget -qO "$WORK_DIR/cica.zip" "$CICA_URL"
unzip -q "$WORK_DIR/cica.zip" -d "$WORK_DIR/cica"

# フォントディレクトリに配置
mkdir -p "$FONT_DIR"
cp "$WORK_DIR/cica/"*.ttf "$FONT_DIR/"

# フォントキャッシュを更新
fc-cache -fv "$FONT_DIR"

echo "✅ 完了：Cica フォントをインストールしました"
