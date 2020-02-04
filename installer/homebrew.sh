#!/bin/sh

if [[ "$OSTYPE" == "darwin"* ]]; then
    xcode-select --install
    /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
    # for brew doctor
    sudo chown -R $(whoami) /usr/local/share/man/man5
elif [[ "$OSTYPE" == "linux-gnu" ]]; then
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/Linuxbrew/install/master/install.sh)"
    echo 'eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)' >>~/.profile
fi

