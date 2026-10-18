#!/usr/bin/env bash

set -euo pipefail

echo "zsh をデフォルトシェルに設定します..."

sudo -v

sudo apt-get update && sudo apt-get install -y zsh

zsh_path=$(command -v zsh)
user_name=$(id -un)

# sudo 経由なら chsh は PAM のパスワード入力を求めない (sudo -v で認証済み)
if ! sudo chsh -s "$zsh_path" "$user_name"; then
    echo "❌ chsh に失敗しました。手動で実行してください: sudo chsh -s $zsh_path $user_name" >&2
    exit 1
fi

current_shell=$( (getent passwd "$user_name" || true) | cut -d: -f7)
if [[ "$current_shell" != "$zsh_path" ]]; then
    echo "❌ login shell が $zsh_path になっていません (現在: ${current_shell:-取得できず})。手動で実行してください: sudo chsh -s $zsh_path $user_name" >&2
    exit 1
fi

echo "✅ 完了：zsh をデフォルトシェルに設定しました"
