#!/bin/zsh
# 対話シェルでの cd 時に TMPDIR (repo-local .tmp) を追従させる
# 本体の _tmpdir_repo_local_update() は ~/.zshenv で定義済み
# (対話/非対話どちらの起動でも一度は反映される)。ここでは cd の度に
# 再評価するためのフックを追加するだけ。
# add-zsh-hook は重複登録を自動で防ぐため、.zshrc の再読み込みでも安全。
if (( ${+functions[_tmpdir_repo_local_update]} )); then
    autoload -Uz add-zsh-hook
    add-zsh-hook chpwd _tmpdir_repo_local_update
fi
