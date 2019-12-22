#!/bin/sh

sh installer/homebrew.sh
brew bundle
sh installer/osx.sh
homesick link dotfiles