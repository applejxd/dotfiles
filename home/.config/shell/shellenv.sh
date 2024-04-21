#!/bin/bash
# Defaul editor
export EDITOR=vim

#-----------------#
# OS dependencies #
#-----------------#

if [[ "$OSTYPE" == "darwin"* ]]; then
    # shellcheck source=/dev/null
    source "$HOME"/.config/shell/osxenv.sh
fi

# for WSL
if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    # shellcheck source=/dev/null
    source "$HOME"/.config/shell/wslenv.sh
fi

# for Ubuntu
if [[ "$OSTYPE" == "linux-gnu" ]]; then
    # for x11 forwarding of chromium
    # from https://qiita.com/kairi003/items/003c4a615317049e5b85
    export XAUTHORITY="$HOME"/.Xauthority
    if [[ -e "$HOME"/.local/share/JetBrains/Toolbox/scripts ]]; then
        export PATH="$HOME"/.local/share/JetBrains/Toolbox/scripts:$PATH
    fi
fi

#---------------#
# Specific root #
#---------------#

# ghq root
export GHQ_ROOT=~/src

#------#
# PATH #
#------#

# for original binaries
export PATH="$HOME"/bin:$PATH

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

#-----------#
# Japansese #
#-----------#

export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export DefaultIMModule=fcitx
if [[ $SHLVL = 1 ]]; then
    (fcitx-autostart >/dev/null 2>&1 &)
    xset -r 49 >/dev/null 2>&1
fi

#---------------#
# User settings #
#---------------#

# for Open3D visualizer
export LIBGL_ALWAYS_INDIRECT=0

if [[ -f "$HOME"/.config/shell/usrenv.sh ]]; then
    # shellcheck source=/dev/null
    source "$HOME"/.config/shell/usrenv.sh
fi
