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

    if [[ $(uname -m) == arm64 ]]; then
        export ANYENV_ROOT=~/.anyenv_arm64
    elif [[ $(uname -m) == x86_64 ]]; then
        export ANYENV_ROOT=~/.anyenv_x64
    fi

    export PATH=$ANYENV_ROOT/bin:$PATH
elif [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # for VcXsrv
    if [[ -e /etc/resolv.conf ]]; then
        # for WSL2
        export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0.0
    else
        # for WSL1
        export DISPLAY=:0.0
    fi

    # To prevent OpenGL error
    export LIBGL_ALWAYS_INDIRECT=1
fi

########
# PATH #
########

if [[ -e $HOME/.anyenv/envs/pyenv ]]; then
    export PYENV_ROOT="$HOME/.anyenv/envs/pyenv"
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

