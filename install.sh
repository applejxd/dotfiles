#!/bin/sh

sh installer/homebrew.sh
brew bundle --file=installer/brew_essence.rb
brew bundle --file=installer/brew_osx.rb

sh installer/osx.sh

homesick link dotfiles