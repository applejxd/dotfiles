#!/usr/bin/env bash

set -eu

# 旧構成の ~/.gitconfig (chezmoi が丸ごと管理していたもの) を退避する。
# 残すと XDG 側 (~/.config/git/config) より優先され、設定が二重になる。
# 無くなれば create_dot_gitconfig が空の ~/.gitconfig を作る。
# 目印の行が無いファイル (CLI が書いた設定) には触らない。
# see docs/spec/structure.md#gitconfig-の管理

target="${HOME}/.gitconfig"
marker='# for overwriting by local config'

[ -f "$target" ] || exit 0
grep -qxF "$marker" "$target" || exit 0

backup="${target}.chezmoi-old"
if [ -e "$backup" ]; then
    backup="${backup}.$(date +%Y%m%d%H%M%S)"
fi
mv "$target" "$backup"
echo "旧 ~/.gitconfig を退避しました: ${backup}"
echo "  CLI で足した設定があれば、必要な分を新しい ~/.gitconfig へ移してください。"
