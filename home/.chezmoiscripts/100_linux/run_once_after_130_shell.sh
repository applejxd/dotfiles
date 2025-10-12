#!/usr/bin/env bash

set -euo pipefail

echo "zsh をデフォルトシェルに設定します..."

sudo -v

sudo apt-get update && sudo apt-get install -y zsh

command -v zsh >/dev/null 2>&1 && chsh -s "$(command -v zsh)" || true

echo "✅ 完了：zsh をデフォルトシェルに設定しました"