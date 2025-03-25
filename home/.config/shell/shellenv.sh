#!/bin/bash

# Defaul editor
export EDITOR=vim

# for Open3D visualizer
export LIBGL_ALWAYS_INDIRECT=0

#-----------#
# Japansese #
#-----------#

export LC_ALL=ja_JP.UTF-8
export LANG=ja_JP.UTF-8

#-----------------#
# OS dependencies #
#-----------------#

if [[ "$OSTYPE" == "darwin"* ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/.config/shell/osxenv.sh"
fi

# for WSL
if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/.config/shell/wslenv.sh"
fi

# for Ubuntu
if [[ "$OSTYPE" == "linux-gnu" ]]; then
    # for x11 forwarding of chromium
    # from https://qiita.com/kairi003/items/003c4a615317049e5b85
    export XAUTHORITY="${HOME}/.Xauthority"
    if [[ -e "${HOME}/.local/share/JetBrains/Toolbox/scripts" ]]; then
        export PATH="${HOME}/.local/share/JetBrains/Toolbox/scripts:${PATH}"
    fi
fi

#---------------#
# Specific root #
#---------------#

# ghq root
export GHQ_ROOT="${HOME}/src"

#------#
# PATH #
#------#

# for original binaries
export PATH="${HOME}/bin:${PATH}"

# for CUDA
if [[ -e "/usr/local/cuda" ]]; then
    export PATH="/usr/local/cuda/bin:${PATH}"
    export LD_LIBRARY_PATH="/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

# for Go lang
if [[ -e "${HOME}/.go" ]]; then
    export GOPATH="${HOME}/.go"
    export PATH="${PATH}:${GOPATH}/bin"
fi

# for Haskell package Cabal
if [[ -e "${HOME}/.cabal" ]]; then
    export PATH="${HOME}/.cabal/bin:${PATH}"
fi

# for TeX Live (local)
if [ -n "${HOME}/.texlive" ]; then
    export PATH="${HOME}/.texlive/main/bin/x86_64-linux:${PATH}"
    export MANPATH="${HOME}/.texlive/main/texmf-dist/doc/man${MANPATH:+:${MANPATH}}"
    export INFOPATH="${HOME}/.texlive/main/texmf-dist/doc/info${INFOPATH:+:${INFOPATH}}"
fi

#---------------#
# User settings #
#---------------#

if [[ -f "${HOME}/.config/shell/usrenv.sh" ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/.config/shell/usrenv.sh"
fi
