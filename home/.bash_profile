#!/bin/bash
#.bash_profile>.bashrc

COMMON_ENV=$HOME/.config/shell/shellenv.sh
if [[ -e "$COMMON_ENV" ]]; then
    source "$COMMON_ENV"
fi

USER_ENV=$HOME/.config/shell/userenv.bash
if [[ -e "$USER_ENV" ]]; then
    source "$USER_ENV"
fi

# Get the aliases and functions
if [[ -f "$HOME"/.bashrc ]]; then
    source "$HOME"/.bashrc
fi
