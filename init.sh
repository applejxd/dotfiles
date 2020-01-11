#!/bin/sh

if !(type "brew" > /dev/null 2>&1); then
    bash installer/homebrew.sh
fi

brew bundle --file=installer/brew_essence.rb

if [[ "$OSTYPE" == "darwin"* ]]; then
    brew bundle --file=installer/brew_osx.rb
    bash installer/osx.sh
fi
