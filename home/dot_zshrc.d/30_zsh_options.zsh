#!/bin/zsh
# zsh の基本オプション・cd 周りの挙動

# cd completion
# see https://qiita.com/yaotti/items/157ff0a46736ec793a91
setopt auto_cd
cdpath=(.. ~)
function chpwd() {
    # stdout が TTY でない場合はスキップ（Claude Code bash ツール等の自動化環境での副作用を防ぐ）
    [[ -t 1 ]] || return
    if command -v "lsd" >/dev/null 2>&1; then
        lsd
    else
        ls
    fi
}

# for glob expression
# see https://qiita.com/nisaji/items/f9eede2164a74bc08db7
setopt +o nomatch

# auto pushd & no history
setopt auto_pushd
setopt pushd_ignore_dups
