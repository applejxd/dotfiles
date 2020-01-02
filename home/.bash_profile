# Get the aliases and functions
if [ -f ~/.bashrc ]; then
    . ~/.bashrc
fi

COMMON_ENV=$HOME/.config/shell/shellenv.sh

if [ -e $COMMON_ENV ]; then
    source $COMMON_ENV
fi