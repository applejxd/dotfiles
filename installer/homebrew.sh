#!/bin/sh

# Requirements
if [[ "$OSTYPE" == "darwin"* ]]; then
    xcode-select --install
elif [[ -e /etc/lsb-release ]]; then
    sudo apt update -y
    sudo apt upgrade -y
    # for Homebrew (cf. http://tinyurl.com/y5yh2vm3)
    sudo apt install -y build-essential curl file git
fi

# Install Homebrew for Mac OS X or Linux
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"

if [[ "$OSTYPE" == "darwin"* ]]; then
    # for brew doctor
    sudo chown -R $(whoami) /usr/local/share/man/man5
elif [[ "$OSTYPE" == "linux-gnu" ]]; then
    # for Homebrew (cf. http://tinyurl.com/y5yh2vm3)
    test -d ~/.linuxbrew && eval $(~/.linuxbrew/bin/brew shellenv)
    test -d /home/linuxbrew/.linuxbrew && eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)
    test -r ~/.bashrc && echo "eval \$($(brew --prefix)/bin/brew shellenv)" >>~/.bashrc
fi


