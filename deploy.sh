#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

#########################
# Requirements (Global) #
#########################

# for ruby-build in Ubuntu (cf. https://github.com/rbenv/ruby-build/wiki)
if [[ -e /etc/lsb-release ]] && !(type "ruby-build" > /dev/null 2>&1); then
    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get upgrade -y
    echo "$password" | sudo -S apt-get install -y git curl build-essential libssl-dev zlib1g-dev
fi

if [[ "$OSTYPE" == "darwin"* ]] && !(type "brew" > /dev/null 2>&1); then
    # The altanative of process substitution for bash 3.2 that is installed to Mac OS X
    source /dev/stdin <<<"$( curl -sS https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh )"
    # enable brew command
    # eval "$(/opt/homebrew/bin/brew shellenv)"
fi

########################
# Requirements (Local) #
########################

# install anyenv (cf. https://github.com/rbenv/rbenv#homebrew-on-macoshttps://github.com/rbenv/rbenv#homebrew-on-macos)
if !(type "anyenv" > /dev/null 2>&1); then
    # install anyenv
    dir_name=anyenv
    if [[ -e /etc/lsb-release ]]; then
        dir_name=anyenv
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        if [[ $(uname -m) == arm64 ]]; then
            dir_name=anyenv_arm64
        elif [[ $(uname -m) == x86_64 ]]; then
            dir_name=anyenv_x64
        fi
    fi

    git clone https://github.com/anyenv/anyenv ~/.$dir_name
    ~/.$dir_name/bin/anyenv init
    export PATH="$HOME/.$dir_name/bin:$PATH"
    yes | anyenv install --init
fi

if !(type "rbenv" >/dev/null 2>&1); then
    anyenv install rbenv
    eval "$(anyenv init -)"
    rbenv install 2.7.0
    rbenv rehash
    rbenv global 2.7.0
fi

################
# Link configs #
################

if !(type "homesick" >/dev/null 2>&1); then
    gem install homesick
fi

# spacemacs install
if [ ! -e ~/.emacs.d ]; then
    git clone https://github.com/syl20bnr/spacemacs ~/.emacs.d
    # npm install --global tern
fi

if [[ ! -e ~/.homesick/repos/dotfiles ]]; then
    homesick clone applejxd/dotfiles
    homesick link dotfiles
    # for ghq
    if [[ ! -e ~/src ]]; then
        mkdir ~/src
    fi
    ln -s ~/.homesick/repos/dotfiles ~/src/
fi

echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/shells.sh)