#!/bin/sh

if [ $# -eq 0 ]; then
    # save password
    printf "password: "
    read password
else
    password=$1
fi

# for Ubuntu (cf. http://bit.ly/37WjcWG)
if [[ -e /etc/lsb-release ]]; then
    echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/ubuntu.sh)
fi

# for Mac OS X
if [[ "$OSTYPE" == "darwin"* ]]; then
    if !(type "brew" > /dev/null 2>&1); then
        source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/homebrew.sh)
    fi
    brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/brew_essence.rb) 2>/dev/null
    brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/brew_osx.rb) 2>/dev/null
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/osx.sh)
fi

echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/shells.sh)
