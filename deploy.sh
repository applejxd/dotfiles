#!/bin/sh

if !(type "brew" > /dev/null 2>&1); then
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/homebrew.sh)
fi

# cf. http://tinyurl.com/yd8kcbq6
if !(type "gem" > /dev/null 2>&1); then
    brew install rbenv
    echo 'eval "$(rbenv init -)"' >> ~/.bashrc
    source ~/.bashrc
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
