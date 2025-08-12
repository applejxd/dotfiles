#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password="$1"
fi

# Mac OS X use bash 3.2, and process substitution is unable
tmp_file=$(mktemp)
# see https://tm.root-n.com/programming:shell_script:command:trap
trap 'rm -f "$tmp_file"' EXIT HUP INT QUIT TERM

# for x86_64 architecture
yes A | softwareupdate --install-rosetta

#---------------#
# Load Homebrew #
#---------------#

brew_path=""
if [[ $(uname -m) == arm64 ]]; then
    brew_path="/opt/homebrew/bin/brew"
elif [[ $(uname -m) == x86_64 ]]; then
    brew_path="/usr/local/bin/brew"
fi
eval "$($brew_path shellenv)"
brew update

#-------------#
# Brew bundle #
#-------------#

if [[ $(uname -m) == arm64 ]]; then
    # GUI apps
    curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx/brew_mas_cask.rb >"$tmp_file"
    brew bundle --file="$tmp_file"

    # Password required GUI apps
    echo "$password" | brew install avast-security
    # Needs Rosetta2
    echo "$password" | brew install google-japanese-ime
    echo "$password" | brew install karabiner-elements
    echo "$password" | brew install xquartz
    echo "$password" | brew install qlvideo
fi

#--------#
# Others #
#--------#

# System configurations
curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx/osx_defaults.sh >"$tmp_file"
# shellcheck source=/dev/null
echo "$password" | source "$tmp_file"

# iTerm2 Shell integration
if [ ! -e ~/.iterm2_shell_integration.zsh ]; then
    curl -L https://iterm2.com/shell_integration/install_shell_integration.sh | bash
fi

# For AtCoder (bits/stdc++.h)
if [[ $(which gcc) != "/opt/homebrew/bin/gcc" ]]; then
    brew install gcc
    gcc_path=$(ls /opt/homebrew/bin/gcc-[0-9]*)
    gpp_path=$(ls /opt/homebrew/bin/g++-[0-9]*)

    ln -fs "$gcc_path" /opt/homebrew/bin/gcc
    ln -fs "$gpp_path" /opt/homebrew/bin/g++
fi

# For AtCoder (ac-library)
if [[ ! -e /usr/local/include/ac-library ]]; then
    git clone https://github.com/atcoder/ac-library.git
    echo "$password" | sudo -S cp -r ./ac-library/atcoder /usr/local/include
    rm -rf ./ac-library
fi

# For LaTeX
# see https://texwiki.texjp.org/?TeX%20Live%2FMac
if [[ ! -e /usr/local/texlive ]]; then
    brew install mactex
    eval "$(/usr/libexec/path_helper)"
    echo "$password" | sudo -S tlmgr update --self --all
    echo "$password" | sudo -S tlmgr paper a4
fi
