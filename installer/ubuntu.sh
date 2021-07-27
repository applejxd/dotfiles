#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt -y update
echo "$password" | sudo -S apt -y upgrade

# Basics
echo "$password" | sudo -S apt install -y manpages-ja unzip zsh tree tig

# Clipboard
echo "$password" | sudo -S apt install -y xsel

# Build Tools
echo "$password" | sudo -S apt install -y cmake cmake-curses-gui gcc clang gdb build-essential

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # GUI in WSL
    echo "$password" | sudo -S apt install -y xfce4-terminal xfce4
    if [ ! -L /etc/wsl.conf ]; then
        echo "$password" | sudo -S rm /etc/wsl.conf
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
    fi
    
    # for JetBrains IDEs
    echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/jetbrains.sh)
else
    echo "$password" | sudo -S apt install -y chromium-browser  
fi
