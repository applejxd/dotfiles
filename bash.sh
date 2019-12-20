#!/bin/sh

###################
# Package Manager #
###################

if !(type "brew" > /dev/null 2>&1); then
    xcode-select --install
    /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
fi

# brew doctor
if ! test -O /usr/local/share/man/man5; then
    sudo chown -R $(whoami) /usr/local/share/man/man5
fi

# Cask for Mac App
brew tap homebrew/cask

# For homebrew itself
brew cask install cakebrew

# Python
if !(type "pip3" > /dev/null 2>&1); then
    brew install python3 python@2 pipenv
    brew cask install pycharm
    pip3 install --upgrade setuptools
    pip3 install matplotlib scipy sympy ipython[all]
fi

################
# Fundamentals #
################

# Basic softwares
brew cask install google-chrome avast-security google-japanese-ime

# Online storages
brew cask install dropbox google-backup-and-sync

###############
# Environment #
###############

# VCS
brew install git git-flow tig
brew cask install sourcetree

# quicklook
brew cask install qlcolorcode qlstephen qlmarkdown quicklook-json qlimagesize webpquicklook suspicious-package quicklookase qlvideo

# system
brew cask install alfred hyperswitch karabiner-elements

# The shell emulator iTerm2
brew cask install iterm2

#####################
# zsh Configuration #
#####################

# zsh install
if test $(which zsh) != "/usr/local/bin/zsh"; then
    brew install zsh
    sudo sh -c "echo '/usr/local/bin/zsh\n' >> /etc/shells"
    # chsh -s /usr/local/bin/zsh
fi

# Package manager 'zplug'
brew install zplug

# fish-like auto-suggestions
brew install zsh-autosuggestions

# shell plugins
brew install z fzf ghq tmux

# Programming Font Ricty
if ! test -e ~/Library/Fonts/Ricty\ Discord\ Regular\ for\ Powerline.ttf; then
    brew tap sanemat/font
    brew install ricty --with-powerline
    cp -f /usr/local/opt/ricty/share/fonts/Ricty*.ttf ~/Library/Fonts/
    fc-cache -vf
fi

# powerline, which needs powerline-font
pip3 install powerline-status

# Programming Font Hack-Nerd-Font
brew cask install font-hack-nerd-font

##############
# Shell Apps #
##############

# basic command line tools
brew install vim m-cli nkf wget w3m ispell tree

# command cloning
brew install bat colordiff ripgrep lsd

# Emacs & Remote directory mounting
brew cask install emacs osxfuse
brew install sshfs

# spacemacs install
if ! test -d ~/.emacs.d; then
    git clone https://github.com/syl20bnr/spacemacs ~/.emacs.d
fi
npm install --global tern

###############
# Programming #
###############

# C++
brew cask install visual-studio-code
Brew install boost opencv

# LaTeX
if !(type "platex" > /dev/null 2>&1); then
    brew cask install mactex
    sudo tlmgr update --self --all
    sudo tlmgr paper a4
fi

# Web
brew cask install mamp

# R, Julia, Octave
brew cask install r julia
brew install octave

#################
# Synbolic Calc #
#################

# Cadabra2
brew tap kpeeters/repo
brew install cadabra2

# WxMaxima
brew install gnuplot
brew install maxima wxmaxima

# SageMath
# brew cask install sage

############
# Mac Apps #
############

# utilities
brew cask install evernote skype bitwarden
brew install bitwarden-cli

# media
brew cask install spotify kindle
brew install youtube-dl ffmpeg mediainfo

# Emulation
# brew cask install virtualbox virtualbox-extension-pack

# file manager
brew cask install cyberduck omnidisksweeper

# Research Tools
brew cask install mendeley-desktop mathpix-snipping-tool

# Reference
brew cask install dash

# graph
brew cask install xmind drawio

##################
# Entertainments #
##################

brew install screenfetch

# 元祖 rogue 日本語版
# https://leopard-gecko.github.io/jrogue/
brew tap leopard-gecko/game
brew install jrogue

# rogue-like game 'jnethack'
brew cask install xquartz
brew install jnethack
brew install cocot
