#!/bin/sh

# use local environment only (not use sudo) 

##########
# anyenv #
##########

if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == arm64 ]]; then
        export ANYENV_ROOT=~/.anyenv_arm64
    elif [[ $(uname -m) == x86_64 ]]; then
        export ANYENV_ROOT=~/.anyenv_x64
    fi
else
    export ANYENV_ROOT=~/.anyenv
fi
export PATH=$ANYENV_ROOT/bin:$PATH

if !(type "anyenv" > /dev/null 2>&1); then
    # install anyenv
    git clone https://github.com/anyenv/anyenv $ANYENV_ROOT
    anyenv init
    yes | anyenv install --init
fi

#########
# pyenv #
#########

if !(type "pyenv" >/dev/null 2>&1); then
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
