#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# for ruby-build in Ubuntu (cf. http://tinyurl.com/j6g67up)
if [[ -e /etc/lsb-release ]] && !(type "ruby-build" > /dev/null 2>&1); then
    echo "$password" | sudo -S apt update
    echo "$password" | sudo -S apt upgrade -y
    echo "$password" | sudo -S apt install -y autoconf bison build-essential libssl-dev libyaml-dev libreadline-dev zlib1g-dev libncurses5-dev libffi-dev libgdbm5 libgdbm-dev libdb-dev
fi

if [[ "$OSTYPE" == "darwin"* ]] && !(type "brew" > /dev/null 2>&1); then
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/homebrew.sh)
fi

# install rbenv (cf. http://tinyurl.com/yd8kcbq6)
if !(type "gem" > /dev/null 2>&1); then
    # install anyenv
    if [[ -e /etc/lsb-release ]]; then
        git clone https://github.com/anyenv/anyenv ~/.anyenv
        ~/.anyenv/bin/anyenv init
        export PATH="$HOME/.anyenv/bin:$PATH"
        yes | anyenv install --init
    fi
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install anyenv
        echo 'eval "$(anyenv init -)"' >> ~/.bashrc
        anyenv install --init
    fi
    
    # install rbenv
    anyenv install rbenv
    eval "$(anyenv init -)"
    rbenv install 2.7.0
    rbenv rehash
    rbenv global 2.7.0
fi

if !(type "homesick" >/dev/null 2>&1); then
    gem install homesick
fi

if [[ ! -e ~/.homesick/repos/dotfiles ]]; then
    homesick clone applejxd/dotfiles
    yes Y | homesick link dotfiles
    # for ghq
    ln -s ~/.homesick/repos/dotfiles ~/src/
fi
