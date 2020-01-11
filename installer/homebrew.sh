#!/bin/sh

if [[ "$OSTYPE" == "darwin"* ]]; then
    xcode-select --install
    /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
    # for brew doctor
    sudo chown -R $(whoami) /usr/local/share/man/man5
fi
