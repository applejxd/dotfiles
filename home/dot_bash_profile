#!/bin/bash
#.bash_profile>.bashrc

COMMON_ENV="$HOME"/.config/shell/shellenv.sh
if [[ -e "$COMMON_ENV" ]]; then
    # shellcheck source=/dev/null
    source "$COMMON_ENV"
fi

USER_ENV="$HOME"/.config/shell/userenv.bash
if [[ -e "$USER_ENV" ]]; then
    # shellcheck source=/dev/null
    source "$USER_ENV"
fi

# Get the aliases and functions
if [[ -f "$HOME"/.bashrc ]]; then
    # shellcheck source=/dev/null
    source "$HOME"/.bashrc
fi
