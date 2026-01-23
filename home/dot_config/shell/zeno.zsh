#!/bin/zsh

export ZENO_HOME="$HOME/.config/zeno"

if type "bat" >/dev/null 2>&1; then
    ZENO_GIT_CAT="bat --color=always"
else
    ZENO_GIT_CAT="cat"
fi

if type "eza" >/dev/null 2>&1; then
    ZENO_GIT_TREE="eza --tree"
else
    ZENO_GIT_TREE="tree"
fi

if [[ -n $ZENO_LOADED ]]; then
    bindkey ' '  zeno-auto-snippet

    # fallback if snippet not matched (default: self-insert)
    # export ZENO_AUTO_SNIPPET_FALLBACK=self-insert

    # if you use zsh's incremental search
    # bindkey -M isearch ' ' self-insert

    bindkey '^m' zeno-auto-snippet-and-accept-line

    # TODO: check conflict with fzf.zsh 
    # bindkey '^i' zeno-completion

    bindkey '^xx' zeno-insert-snippet           # open snippet picker (fzf) and insert at cursor

    bindkey '^x '  zeno-insert-space
    bindkey '^x^m' accept-line
    bindkey '^x^z' zeno-toggle-auto-snippet

    # preprompt bindings
    bindkey '^xp' zeno-preprompt
    bindkey '^xs' zeno-preprompt-snippet
    # Outside ZLE you can run `zeno-preprompt git {{cmd}}` or `zeno-preprompt-snippet foo`
    # to set the next prompt prefix; invoking them with an empty argument resets the state.

    bindkey '^r' zeno-history-selection         # classic history widget
    # bindkey '^r' zeno-smart-history-selection # smart history widget

    # fallback if completion not matched
    # (default: fzf-completion if exists; otherwise expand-or-complete)
    # export ZENO_COMPLETION_FALLBACK=expand-or-complete
fi