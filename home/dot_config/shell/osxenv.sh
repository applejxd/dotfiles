#!/bin/bash

export LANG="${LANG:-ja_JP.UTF-8}"

#------#
# PATH #
#------#

# The default (lowest priority, first declaration)
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:${PATH}}"

# MacTeX (brew install mactex が作る固定のシンボリックリンク。no_global_rcs で path_helper が動かないので自分で通す)
[[ -d "/Library/TeX/texbin" ]] && export PATH="/Library/TeX/texbin:${PATH}"

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
