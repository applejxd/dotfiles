###############
# Environment #
###############

if [[ "$OSTYPE" == "darwin"* ]]; then
    export LANG=ja_JP.UTF-8
fi

# Defaul editor = vim
export EDITOR=vim

########
# PATH #
########

# The default
export PATH=/usr/local/bin:/usr/local/sbin:/sw/bin:$PATH
# for TeX Live 2019
export PATH=/usr/local/texlive/2019/bin/x86_64-darwin:$PATH
# for Haskell package Cabal
export PATH=~/.cabal/bin:$PATH
# for wxMaxima
export PATH=/Applications/wxMaxima.app/bin:$PATH
# for YaTeX
export PATH=/Users/masashi/.emacs.d/private/yatex:$PATH
# for original binaries
export PATH=~/bin:$PATH

#################
# Specific root #
#################

# ghq root
export GHQ_ROOT=~/src

# for Maxima
export MAXIMA_USERDIR=/Applications/wxMaxima.app/.maxima

# for YaTeX
export TEXINPUTS=~/.emacs.d/private/yatex:$TEXINPUTS
export BSTINPUTS=~/.emacs.d/private/yatex:$BSTINPUTS
export BIBINPUTS=~/Dropbox/bib:$BIBINPUTS

# Initialization for FDK command line tools.Fri Jul 29 10:12:14 2016
## for Adobe Font Development Kit for OpenType
export PATH="/Users/masashi/bin/FDK/Tools/osx":$PATH
export FDK_EXE="/Users/masashi/bin/FDK/Tools/osx"

# export HOMEBREW_GITHUB_API_TOKEN=6ab4724f6d2c6706e5997b0794d487948c68f8bf
