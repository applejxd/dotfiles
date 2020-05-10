#!/bin/bash

if !(type "brew" > /dev/null 2>&1); then
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/homebrew.sh)
fi

# for ruby-build in Ubuntu (cf. http://tinyurl.com/j6g67up)
if [[ -e /etc/lsb-release ]] && !(type "ruby-build" > /dev/null 2>&1); then
    sudo apt install -y autoconf bison build-essential libssl-dev libyaml-dev libreadline6-dev zlib1g-dev libncurses5-dev libffi-dev libgdbm6 libgdbm-dev libdb-dev
fi

# install rbenv (cf. http://tinyurl.com/yd8kcbq6)
if !(type "gem" > /dev/null 2>&1); then
    brew install rbenv
    eval "$(rbenv init -)"
    echo 'eval "$(rbenv init -)"' >> ~/.bashrc
    # install default version
    rbenv install 2.5.0
    rbenv rehash
    rbenv global 2.5.0
fi

if !(type "homesick" >/dev/null 2>&1); then
    gem install homesick
fi

homesick clone applejxd/dotfiles
homesick link dotfiles
