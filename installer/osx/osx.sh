#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# Mac OS X use bash 3.2, and process substitution is unable
tmp_file=$(mktemp)
# cf. https://tm.root-n.com/programming:shell_script:command:trap
trap 'rm -f "$tmp_file"' EXIT HUP INT QUIT TERM

# for x86_64 architecture
yes A | softwareupdate --install-rosetta

#################
# Load Homebrew #
#################

brew_path=""
if [[ $(uname -m) == arm64 ]]; then
    brew_path="/opt/homebrew/bin/brew"
elif [[ $(uname -m) == x86_64 ]]; then
    brew_path="/usr/local/bin/brew"
fi
eval "$($brew_path shellenv)"
brew update

###############
# Brew bundle #
###############

if [[ $(uname -m) == arm64 ]]; then
    # GUI apps
    curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx/brew_mas_cask.rb > tmp_file
    brew bundle --file=tmp_file
    
    # Password required GUI apps
    echo "$password" | brew install avast-security
    echo "$password" | brew install 
fi

##########
# Others #
##########

# System configurations
curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx/osx_defaults > tmp_file
echo "$password" | source tmp_file

# fzf install
if [ ! -e ~/.fzf.zsh ]; then
    $(brew --prefix)/opt/fzf/install
fi

# iTerm2 Shell integration
if [ ! -e ~/.iterm2_shell_integration.zsh ]; then
    curl -L https://iterm2.com/shell_integration/install_shell_integration.sh | bash
fi

# LaTeX
if !(type "platex" > /dev/null 2>&1) && (type tlmgr > /dev/null 2>&1); then
    echo "$password" | sudo -S tlmgr update --self --all
    echo "$password" | sudo -S tlmgr paper a4
fi

# Programming Font Ricty
if [ ! -e ~/Library/fonts/Ricty\ Discord\ Regular\ for\ Powerline.ttf ]; then
    cp -f /usr/local/opt/ricty/share/fonts/Ricty*.ttf ~/Library/Fonts/
    fc-cache -vf
fi

# powerline, which needs powerline-font
if !(type "powerline-daemon" > /dev/null 2>&1); then
    pip3 install powerline-status
fi
