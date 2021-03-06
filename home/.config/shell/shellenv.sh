###############
# Environment #
###############

if [[ "$OSTYPE" == "darwin"* ]]; then
    export LANG=ja_JP.UTF-8
fi

# Defaul editor = vim
export EDITOR=vim

###################
# OS dependencies #
###################

if [[ "$OSTYPE" == "darwin"* ]]; then
    source $HOME/.config/shell/osxenv.sh
fi

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # for VcXsrv
    if [[ -e /etc/resolv.conf ]]; then
        # for WSL2
        export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0.0
    else
        # for WSL1
        export DISPLAY=:0.0
    fi
fi

########
# PATH #
########

# for anyenv
export PATH=~/.anyenv/bin:$PATH
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

