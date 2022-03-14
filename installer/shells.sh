#!/bin/sh
# install shells

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
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

if  [[ "$OSTYPE" == "darwin"* ]] && (! type "brew" > /dev/null 2>&1); then
    # The altanative of process substitution for bash 3.2 that is installed to Mac OS X
    echo "$password" | source /dev/stdin <<<"$(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh)"
fi

############
# Register #
############

# register bash
if ! grep -q $(which bash) /etc/shells; then
    echo "$password" | sudo -S sh -c "echo $(which bash) >> /etc/shells"
fi

# register fish
if type "fish" > /dev/null 2>&1; then
    if ! grep -q $(which fish) /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which fish) >> /etc/shells"
    fi
fi

# register zsh
if type "zsh" > /dev/null 2>&1; then
    if ! grep -q $(which zsh) /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which zsh) >> /etc/shells"
    fi
fi

###########
# Distrod #
###########

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]] && (! systemctl >/dev/null 2>&1); then
    echo "$password" | sudo -S chsh -s $(which zsh) $USER

    curl -L -O "https://raw.githubusercontent.com/nullpo-head/wsl-distrod/main/install.sh"
    chmod +x install.sh
    echo "$password" | sudo -S ./install.sh install
    echo "$password" | sudo -S /opt/distrod/bin/distrod enable --start-on-windows-boot
    rm ./install.sh
    
    echo "$password" | sudo -S chsh -s /opt/distrod/alias/bin/bash $USER
fi
