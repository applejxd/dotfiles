#!/bin/sh

if !(type "brew" > /dev/null 2>&1); then
    xcode-select --install
    /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
fi

# brew doctor
sudo chown -R $(whoami) /usr/local/share/man/man5
