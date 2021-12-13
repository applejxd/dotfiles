#!/bin/sh

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

################
# Requirements #
################

# for ruby-build in Ubuntu (cf. http://tinyurl.com/j6g67up)
if [[ -e /etc/lsb-release ]] && !(type "ruby-build" > /dev/null 2>&1); then
    # To prevent stopping at interactive mode (needs -E option for sudo)
    export DEBIAN_FRONTEND=noninteractive
    echo "$password" | sudo -S -E apt update
    echo "$password" | sudo -S -E apt upgrade -y
    echo "$password" | sudo -S -E apt install -y autoconf bison build-essential libssl-dev libyaml-dev libreadline-dev zlib1g-dev libncurses5-dev libffi-dev libgdbm5 libgdbm-dev libdb-dev
fi

if [[ "$OSTYPE" == "darwin"* ]] && !(type "brew" > /dev/null 2>&1); then
    # The altanative of process substitution for bash 3.2 that is installed to Mac OS X
    source /dev/stdin <<<"$( curl -sS https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh )"
    # enable brew command
    # eval "$(/opt/homebrew/bin/brew shellenv)"
fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == arm64 ]]; then
        export ANYENV_ROOT=~/.anyenv_arm64
    elif [[ $(uname -m) == x86_64 ]]; then
        export ANYENV_ROOT=~/.anyenv_x64
    fi
else
    export ANYENV_ROOT=~/.anyenv
fi
export PATH=$ANYENV_ROOT/bin:$PATH

if !(type "anyenv" > /dev/null 2>&1); then
    # install anyenv
    git clone https://github.com/anyenv/anyenv $ANYENV_ROOT
    anyenv init
    yes | anyenv install --init
fi

###################
# OS dependencies #
###################

# for Ubuntu (cf. http://bit.ly/37WjcWG)
if [[ -e /etc/lsb-release ]]; then
    echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu.sh)

elif [[ "$OSTYPE" == "darwin"* ]]; then
    if !(type "brew" > /dev/null 2>&1); then
        source /dev/stdin <<<"$( curl -sS https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh )"
        # enable brew command
        # eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    
    # update bash for process substitution
    brew install bash
    # shell commands
    brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/brew_shell.rb) 2>/dev/null

    if [[ $(uname -m) == arm64 ]]; then
        # GUI apps
        brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/brew_mas_cask.rb) 2>/dev/null
    fi

    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx.sh)
fi
