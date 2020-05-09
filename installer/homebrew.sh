#!/bin/sh

# Requirements
if [[ "$OSTYPE" == "darwin"* ]]; then
    xcode-select --install
elif [[ -e /etc/lsb-release ]]; then
    sudo apt update -y
    sudo apt upgrade -y
    # for Homebrew (cf. http://tinyurl.com/y5yh2vm3)
    sudo apt install -y build-essential curl file git
    # for ruby-build (cf. http://tinyurl.com/j6g67up)
    sudo apt install -y autoconf bison build-essential libssl-dev libyaml-dev libreadline6-dev zlib1g-dev libncurses5-dev libffi-dev libgdbm6 libgdbm-dev libdb-dev
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
    test -r ~/.bash_profile && echo "eval \$($(brew --prefix)/bin/brew shellenv)" >>~/.bash_profile
    echo "eval \$($(brew --prefix)/bin/brew shellenv)" >>~/.profile
fi


