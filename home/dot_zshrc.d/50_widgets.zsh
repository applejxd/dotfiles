#!/bin/zsh
# カスタム ZLE widget

# fg -> C-z
function fancy-ctrl-z() {
    if [[ $#BUFFER -eq 0 ]]; then
        BUFFER="fg"
        # Finish editing the buffer
        zle accept-line
    else
        # Push onto the buffer stack & Return to prompt
        zle push-input
        # Clear the screen
        zle clear-screen
    fi
}
zle -N fancy-ctrl-z
bindkey '^Z' fancy-ctrl-z
