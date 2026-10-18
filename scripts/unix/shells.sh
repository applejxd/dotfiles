#!/bin/bash
# install shells

sudo -v

#---------#
# Install #
#---------#

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    sudo apt-get update
    sudo apt-get install -y zsh unzip
fi

if [[ "$OSTYPE" =~ darwin ]]; then
    brew_path=""
    if [[ $(uname -m) == arm64 ]]; then
        brew_path="/opt/homebrew/bin/brew"
    elif [[ $(uname -m) == x86_64 ]]; then
        brew_path="/usr/local/bin/brew"
    fi
    eval "$($brew_path shellenv)"

    # shell environments
    brew update
    brew bundle --file="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../osx/brew_shell.rb" 2>/dev/null
fi

#----------#
# Register #
#----------#

# register bash
if ! grep -q "$(which bash)" /etc/shells; then
    sudo sh -c "echo $(which bash) >> /etc/shells"
fi

# register zsh
if command -v "zsh" >/dev/null 2>&1; then
    if ! grep -q "$(which zsh)" /etc/shells; then
        sudo sh -c "echo $(which zsh) >> /etc/shells"
    fi
fi
