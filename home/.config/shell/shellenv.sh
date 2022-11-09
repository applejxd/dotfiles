# Defaul editor = vim
export EDITOR=vim

##########
# anyenv #
##########

if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == arm64 ]]; then
        export ANYENV_ROOT="$HOME"/.anyenv_arm64
        export ANYENV_DEFINITION_ROOT="$HOME"/.config/anyenv_arm64/anyenv-install
    elif [[ $(uname -m) == x86_64 ]]; then
        export ANYENV_ROOT="$HOME"/.anyenv_x64
        export ANYENV_DEFINITION_ROOT="$HOME"/.config/anyenv_x64/anyenv-install
    fi
else
    export ANYENV_ROOT="$HOME"/.anyenv
    export ANYENV_DEFINITION_ROOT="$HOME"/.config/anyenv/anyenv-install
fi

export PATH=$ANYENV_ROOT/bin${PATH:+:${PATH}}

if [[ -e $ANYENV_ROOT/envs/pyenv ]]; then
    export PYENV_ROOT="$ANYENV_ROOT"/envs/pyenv
    export PATH="$PYENV_ROOT"/bin:$PATH
    eval "$(pyenv init --path)"
fi

###################
# OS dependencies #
###################

if [[ "$OSTYPE" == "darwin"* ]]; then
    source "$HOME"/.config/shell/osxenv.sh
fi

# for WSL
if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    source "$HOME"/.config/shell/wslenv.sh
fi

########
# PATH #
########

# for original binaries
export PATH="$HOME"/bin:$PATH

# # cuda (nvcc)
# if [[ -e /usr/local/cuda-11.2 ]]; then
#     export PATH=/usr/local/cuda-11.2/bin${PATH:+:${PATH}}
# fi

# for Go lang
if [[ -e "$HOME"/.go ]]; then
    export GOPATH="$HOME"/.go
    export PATH=$PATH:"$GOPATH"/bin
fi

# for Haskell package Cabal
if [[ -e "$HOME"/.cabal ]]; then
    export PATH=~/.cabal/bin:$PATH
fi

# for YaTeX
if [[ -e "$HOME"/.emacs.d/private/yatex ]]; then
    export PATH="$HOME"/.emacs.d/private/yatex:$PATH
    export TEXINPUTS="$HOME"/.emacs.d/private/yatex${TEXINPUTS:+:${TEXINPUTS}}
    export BSTINPUTS="$HOME"/.emacs.d/private/yatex${BSTINPUTS:+:${BSTINPUTS}}
fi

# # for pipenv (for Ubuntu)
# export PATH=~/.local/bin:$PATH

#############
# Japansese #
#############

export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export DefaultIMModule=fcitx
if [ $SHLVL = 1 ] ; then
  (fcitx-autostart > /dev/null 2>&1 &)
  xset -r 49  > /dev/null 2>&1
fi

#################
# Specific root #
#################

# ghq root
export GHQ_ROOT=~/src

#################
# User settings #
#################

if [[ -f "$HOME"/.config/shell/usrenv.sh ]]; then
    source "$HOME"/.config/shell/usrenv.sh
fi
