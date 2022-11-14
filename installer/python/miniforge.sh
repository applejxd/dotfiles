#!/bin/bash

##########
# anyenv #
##########

if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == arm64 ]]; then
        export ANYENV_ROOT=$HOME/.anyenv_arm64
        export ANYENV_DEFINITION_ROOT=$HOME/.config/anyenv_arm64/anyenv-install
    elif [[ $(uname -m) == x86_64 ]]; then
        export ANYENV_ROOT=$HOME/.anyenv_x64
        export ANYENV_DEFINITION_ROOT=$HOME/.config/anyenv_x64/anyenv-install
    fi
else
    export ANYENV_ROOT=$HOME/.anyenv
fi
export PATH=$ANYENV_ROOT/bin:$PATH

if [[ ! -e $ANYENV_ROOT ]]; then
    git clone https://github.com/anyenv/anyenv "$ANYENV_ROOT"
fi

export PATH=$ANYENV_ROOT/bin:$PATH
# Refresh anyenv
eval "$(anyenv init -)"
# Make anyenv manifest directory
yes | anyenv install --init

if [[ ! -e $ANYENV_ROOT/envs/rbenv ]]; then
    anyenv install rbenv
    # Refresh anyenv
    eval "$(anyenv init -)"
fi

#########
# pyenv #
#########

if ! (type "pyenv" >/dev/null 2>&1); then
    # Python install
    anyenv install pyenv
    export PYENV_ROOT="$ANYENV_ROOT/envs/pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"
fi

##############
# miniforge3 #
##############

pyenv install miniforge3
pyenv global miniforge3
