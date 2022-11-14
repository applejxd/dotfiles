#!/bin/bash
# install shells

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password=$1
fi

###########
# Install #
###########

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get install -y zsh fish
fi

if  [[ "$OSTYPE" =~ darwin ]]; then
    brew_path=""
    if [[ $(uname -m) == arm64 ]]; then
        brew_path="/opt/homebrew/bin/brew"
    elif [[ $(uname -m) == x86_64 ]]; then
        brew_path="/usr/local/bin/brew"
    fi
    eval "$($brew_path shellenv)"
    
    # Mac OS X use bash 3.2, and process substitution is unable
    shell_bundle=$(mktemp)
    # cf. https://tm.root-n.com/programming:shell_script:command:trap
    trap 'rm -f "$shell_bundle"' EXIT HUP INT QUIT TERM
    curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx/brew_shell.rb > shell_bundle
    # shell environments
    brew update
    brew bundle --file=shell_bundle 2>/dev/null
fi

############
# Register #
############

# register bash
if ! grep -q "$(which bash)" /etc/shells; then
    echo "$password" | sudo -S sh -c "echo $(which bash) >> /etc/shells"
fi

# register fish
if type "fish" > /dev/null 2>&1; then
    if ! grep -q "$(which fish)" /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which fish) >> /etc/shells"
    fi
fi

# register zsh
if type "zsh" > /dev/null 2>&1; then
    if ! grep -q "$(which zsh)" /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which zsh) >> /etc/shells"
    fi
fi

###########
# Distrod #
###########

if [[ "$(uname -r)" =~ (M|m)icrosoft ]] && (! systemctl >/dev/null 2>&1); then
    # To install distrod for zsh
    echo "$password" | sudo -S chsh -s "$(which zsh)" "$USER"

    curl -L -O "https://raw.githubusercontent.com/nullpo-head/wsl-distrod/main/install.sh"
    chmod +x install.sh
    echo "$password" | sudo -S ./install.sh install
    echo "$password" | sudo -S /opt/distrod/bin/distrod enable --start-on-windows-boot
    rm ./install.sh
    
    # Use bash for CLion toolchain
    # Use distrod for systemctl
    echo "$password" | sudo -S chsh -s /opt/distrod/alias/bin/bash "$USER"
fi
