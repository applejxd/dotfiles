#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

###################
# OS dependencies #
###################

# for Ubuntu (cf. http://bit.ly/37WjcWG)
if [[ -e /etc/lsb-release ]]; then
    echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu.sh)
    
elif [[ "$OSTYPE" == "darwin"* ]]; then 
    if [[ $(uname -m) == arm64 ]]; then
        # GUI apps
        brew bundle --file=<(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/brew_mas_cask.rb) 2>/dev/null
    fi
    echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx.sh)
fi
