#!/bin/zsh
# fzf と組み合わせる ZLE widget

# z-fzf, emacs-like key-bindings
# see https://github.com/junegunn/fzf/wiki/examples#z
# `_z` は補完関数の名前空間 (_*) と衝突するため、rupa/z の実体で判定する
if [ -r "${HOME}/.z/z.sh" ]; then
    function z-fzf() {
        local selected_dir=$(_z -l 2>&1 | fzf +s --tac | sed 's/^[0-9,.]* *//')
        if [[ -n "$selected_dir" ]]; then
            BUFFER="cd ${selected_dir}"
            zle accept-line
        fi
        zle reset-prompt
    }
    zle -N z-fzf
    bindkey "^X^F" z-fzf
fi

# ghq-fzf
# see https://blog.tsub.me/post/move-from-peco-to-fzf/
if command -v "ghq" >/dev/null 2>&1; then
    function ghq-fzf() {
        local selected_dir=$(ghq list | fzf --query="$LBUFFER")
        if [[ -n "$selected_dir" ]]; then
            BUFFER="cd $(ghq root)/${selected_dir}"
            zle accept-line
        fi
        zle reset-prompt
    }
    zle -N ghq-fzf
    bindkey "^X^G" ghq-fzf
fi
