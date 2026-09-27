#!/bin/bash
# install shells

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password=$1
fi

#---------#
# Install #
#---------#

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get install -y zsh fish unzip
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
    echo "$password" | sudo -S sh -c "echo $(which bash) >> /etc/shells"
fi

# register fish
if command -v "fish" >/dev/null 2>&1; then
    if ! grep -q "$(which fish)" /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which fish) >> /etc/shells"
    fi
fi

# register zsh
if command -v "zsh" >/dev/null 2>&1; then
    if ! grep -q "$(which zsh)" /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which zsh) >> /etc/shells"
    fi
fi
