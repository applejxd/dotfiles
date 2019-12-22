#!/bin/sh

sh homebrew.sh
brew bundle
sh osx.sh
./install.fish
homesick link dotfiles