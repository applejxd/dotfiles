#!/usr/bin/env bash

set -euo pipefail

echo "カスタムキーボード設定開始..." 

sudo -v

# IME & XKB ツール
sudo apt-get update -y
sudo apt-get install -y fcitx5 fcitx5-mozc fcitx5-config-qt xkb-data xkbcomp

# fcitx5 を既定 IM に（失敗時は .xinputrc）
im-config -n fcitx5 || echo 'run_im fcitx5' > "$HOME/.xinputrc"

# すでに chezmoi で ~/.xkb/symbols/jp_custom は配置済みの想定
# → 適用（即時）
setxkbmap -layout jp -variant custom -I"$HOME/.xkb"

# → 永続化（/etc/default/keyboard を更新）
sudo localectl set-x11-keymap jp pc105 custom

echo "✅ fcitx5 & XKB 適用完了（即時＋永続）"