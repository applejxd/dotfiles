###############
# Environment #
###############

# Defaul editor = vim
export EDITOR=vim

# User settings
if [[ -f $HOME/.config/shell/usrenv.sh ]]; then
    source $HOME/.config/shell/usrenv.sh
fi

###################
# OS dependencies #
###################

if [[ "$OSTYPE" == "darwin"* ]]; then
    source $HOME/.config/shell/osxenv.sh
    
    if [[ $(uname -m) == arm64 ]]; then
        export ANYENV_ROOT=~/.anyenv_arm64
    elif [[ $(uname -m) == x86_64 ]]; then
        export ANYENV_ROOT=~/.anyenv_x64
    fi
else
    export ANYENV_ROOT=~/.anyenv
fi

export PATH=$ANYENV_ROOT/bin${PATH:+:${PATH}}

# for WSL
if [[ "$(uname -r)" == *(M|m)icrosoft* ]]; then
    source $HOME/.config/shell/wslenv.sh
fi

########
# PATH #
########

if [[ -e $ANYENV_ROOT/envs/pyenv ]]; then
    export PYENV_ROOT="$ANYENV_ROOT/envs/pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init --path)"
fi

# for Go lang
export GOPATH=$HOME/.go
export PATH=$PATH:$GOPATH/bin

# for Haskell package Cabal
export PATH=~/.cabal/bin:$PATH

# for pipenv (for Ubuntu)
export PATH=~/.local/bin:$PATH
# for YaTeX
export PATH=~/.emacs.d/private/yatex:$PATH
# for original binaries
export PATH=~/bin:$PATH

#################
# Specific root #
#################

# ghq root
export GHQ_ROOT=~/src

# for YaTeX
export TEXINPUTS=~/.emacs.d/private/yatex:$TEXINPUTS
export BSTINPUTS=~/.emacs.d/private/yatex:$BSTINPUTS
