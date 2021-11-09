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

# C/C++ Build Tools
echo "$password" | sudo -S apt install -y cmake cmake-curses-gui gcc clang gdb build-essential

# Java
echo "$password" | sudo -S apt install -y default-jre default-jdk

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # GUI in WSL
    echo "$password" | sudo -S apt install -y xfce4-terminal xfce4
    
    # for SSH server
    echo "$password" | sudo -S apt purge openssh-server
    echo "$password" | sudo -S apt install openssh-server
    if [ ! -L /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S rm /etc/ssh/sshd_config
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/sshd_config /etc/ssh/sshd_config
    fi
    
    # Replace WSL config
    if [ ! -L /etc/wsl.conf ]; then
        echo "$password" | sudo -S rm /etc/wsl.conf
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
    fi
    
    # for JetBrains IDEs
    echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/jetbrains.sh)
else
    echo "$password" | sudo -S apt install -y chromium-browser  
fi
