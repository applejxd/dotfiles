###############
# Environment #
###############

# Defaul editor = vim
export EDITOR=vim

###################
# OS dependencies #
###################

if [[ "$OSTYPE" == "darwin"* ]]; then
    source $HOME/.config/shell/osxenv.sh
else
    export ANYENV_ROOT=~/.anyenv

    # for WSL
    if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
        source $HOME/.config/shell/wslenv.sh
    fi
fi

export PATH=$ANYENV_ROOT/bin:$PATH

########
# PATH #
########

if [[ -e $ANYENV_ROOT/envs/pyenv ]]; then
    export PYENV_ROOT="$ANYENV_ROOT/envs/pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init --path)"
fi

# for pipenv (for Ubuntu)
export PATH=~/.local/bin:$PATH
# for YaTeX
export PATH=~/.emacs.d/private/yatex:$PATH
# for Haskell package Cabal
export PATH=~/.cabal/bin:$PATH
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

