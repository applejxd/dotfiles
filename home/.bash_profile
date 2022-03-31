COMMON_ENV=$HOME/.config/shell/shellenv.sh

if [[ -e "$COMMON_ENV" ]]; then
    source "$COMMON_ENV"
fi

# Get the aliases and functions
if [[ -f "$HOME"/.bashrc ]]; then
    source "$HOME"/.bashrc
fi
