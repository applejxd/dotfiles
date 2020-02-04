#!/bin/sh

if !(type "brew" > /dev/null 2>&1); then
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/homebrew.sh)
fi

brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/brew_essence.rb) 2>/dev/null

# cf. http://bit.ly/37WjcWG
if [[ "$OSTYPE" == "darwin"* ]]; then
    brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/brew_osx.rb) 2>/dev/null
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/osx.sh)
elif [[ -e /etc/lsb-release ]]; then
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/ubuntu.sh)
fi

source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/shells.sh)