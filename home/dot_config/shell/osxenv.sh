#!/bin/bash

export LANG=ja_JP.UTF-8

#------#
# PATH #
#------#

# The default (lowest priority, first declaration)
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:${PATH}}"

# for openssl
if [[ -e "/opt/homebrew/opt/openssl@1.1" ]]; then
  export PATH="/opt/homebrew/opt/openssl@1.1/bin:${PATH}"
  export LDFLAGS="-L/opt/homebrew/opt/openssl@1.1/lib"
  export CPPFLAGS="-I/opt/homebrew/opt/openssl@1.1/include"
  export PKG_CONFIG_PATH="/usr/local/opt/openssl@1.1/lib/pkgconfig"
fi

# MacTeX
if [[ -e "/usr/local/texlive" ]]; then
  prefix=$(find /usr/local/texlive -maxdepth 1 -type d | sed -n 2p)
  export PATH="${prefix}/bin/universal-darwin:${PATH}"
fi

#------------#
# BSD -> GNU #
#------------#

# coreutils
PATH="/opt/homebrew/opt/coreutils/libexec/gnubin:$PATH"
# ed
PATH="/opt/homebrew/opt/ed/libexec/gnubin:$PATH"
# findutils
PATH="/opt/homebrew/opt/findutils/libexec/gnubin:$PATH"
# gawk
PATH="/opt/homebrew/opt/gawk/libexec/gnubin:$PATH"
# gnu-sed
PATH="/opt/homebrew/opt/gnu-sed/libexec/gnubin:$PATH"
# gnu-tar
PATH="/opt/homebrew/opt/gnu-tar/libexec/gnubin:$PATH"
# grep
PATH="/opt/homebrew/opt/grep/libexec/gnubin:$PATH"

#---------------#
# Specific root #
#---------------#

# for Maxima
if [[ -e /Applications/wxMaxima.app/ ]]; then
  export PATH=/Applications/wxMaxima.app/bin:$PATH
  export MAXIMA_USERDIR=/Applications/wxMaxima.app/.maxima
fi
