#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password="$1"
fi

#########################
# Requirements (Global) #
#########################

# for ruby-build in Ubuntu (cf. https://github.com/rbenv/ruby-build/wiki)
if [[ -e /etc/lsb-release ]] && (! type "ruby-build" > /dev/null 2>&1); then
    echo "$password" | sudo -S bash -c "\
        apt-get update && apt-get upgrade -y && \
        apt-get install -y git curl build-essential libssl-dev zlib1g-dev"
fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    if (! git --version > /dev/null 2>&1); then
        xcode-select --install
        echo "Rerun this script after completion to install the command line tools."
        exit 1
    fi

    if (! type "brew" > /dev/null 2>&1); then
        # Mac OS X use bash 3.2, and process substitution is unable
        brew_script=$(mktemp)
        # cf. https://tm.root-n.com/programming:shell_script:command:trap
        trap 'rm -f "$brew_script"' EXIT HUP INT QUIT TERM
        curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh > "$brew_script"
        echo "$password" | source "$brew_script"
    fi
fi

########################
# Requirements (Local) #
########################

# install anyenv 
# cf. https://github.com/rbenv/rbenv#homebrew-on-macoshttps://github.com/rbenv/rbenv#homebrew-on-macos

if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == arm64 ]]; then
        export ANYENV_ROOT=$HOME/.anyenv_arm64
        export ANYENV_DEFINITION_ROOT=$HOME/.config/anyenv_arm64/anyenv-install
    elif [[ $(uname -m) == x86_64 ]]; then
        export ANYENV_ROOT=$HOME/.anyenv_x64
        export ANYENV_DEFINITION_ROOT=$HOME/.config/anyenv_x64/anyenv-install
    fi
else
    export ANYENV_ROOT=$HOME/.anyenv
fi

if [[ ! -e $ANYENV_ROOT ]]; then
    git clone https://github.com/anyenv/anyenv "$ANYENV_ROOT"
fi

export PATH=$ANYENV_ROOT/bin:$PATH
# Refresh anyenv
eval "$(anyenv init -)"
# Make anyenv manifest directory
yes | anyenv install --init

if [[ ! -e $ANYENV_ROOT/envs/rbenv ]]; then
    anyenv install rbenv
    # Refresh anyenv
    eval "$(anyenv init -)"
fi

if (! type "ruby" > /dev/null 2>&1) || [[ $(which "ruby") != "$ANYENV_ROOT/envs/"* ]]; then
    rbenv install 2.7.5
    rbenv rehash
    rbenv global 2.7.5
fi

################
# Link configs #
################A

if (! type "homesick" >/dev/null 2>&1); then
    gem install homesick
fi

# spacemacs install
if [[ ! -e ~/.emacs.d ]]; then
    git clone https://github.com/syl20bnr/spacemacs ~/.emacs.d
fi

if [[ ! -e ~/.homesick/repos/dotfiles ]]; then
    homesick clone applejxd/dotfiles
    # for ghq
    if [[ ! -e ~/src ]]; then
        mkdir ~/src
    fi
    ln -s ~/.homesick/repos/dotfiles ~/src/
fi

if [[ ! -L ~/.bashrc ]]; then
    if [[ -f ~/.bashrc ]]; then
        mv ~/.bashrc ~/.bashrc_old
    fi
    homesick link dotfiles
fi

#################
# Write configs #
#################

if (type "git" >/dev/null 2>&1); then
    git config --global init.defaultBranch "main"

    git config --global core.editor "vim"
    # distinguish between uppercase and lowercase
    git config --global core.ignorecase "false"
    # to display Japanese files
    git config --global core.quotepath "false"

    git config --global ghq.root "$HOME/src"
    git config --global gitflow.branch.master "main"
    
    # for ssh push
    git config --global url."github:".pushInsteadOf https://github.com/
fi

# Mac OS X use bash 3.2, and process substitution is unable
shell_config=$(mktemp)
# cf. https://tm.root-n.com/programming:shell_script:command:trap
trap 'rm -f "$shell_config"' EXIT HUP INT QUIT TERM
curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/shells.sh > "$shell_config"
echo "$password" | source "$shell_config"
