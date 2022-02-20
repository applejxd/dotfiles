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
    if !(type "brew" > /dev/null 2>&1); then
        source /dev/stdin <<<"$( curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh )"
        # enable brew command
        # eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    
    # update bash for process substitution
    brew install bash
    # shell commands
    brew bundle --file=<(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/brew_shell.rb) 2>/dev/null

    if [[ $(uname -m) == arm64 ]]; then
        # GUI apps
        brew bundle --file=<(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/brew_mas_cask.rb) 2>/dev/null
    fi

    source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx.sh)
fi
