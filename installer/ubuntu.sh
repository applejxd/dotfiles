#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt-get -y update
echo "$password" | sudo -S apt-get -y upgrade

# Basics
echo "$password" | sudo -S apt-get install -y manpages-ja unzip zsh tree tig

# Clipboard
echo "$password" | sudo -S apt-get install -y xsel

# GUI
echo "$password" | sudo -S apt-get install -y xfce4-terminal

# RDP
echo "$password" | sudo -S apt-get install -y xrdp

# docker
echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/docker.sh)

# Java
# echo "$password" | sudo -S apt-get install -y default-jre default-jdk

# LaTeX
# echo "$password" | sudo -S apt-get install -y texlive-full

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # systemctl
    curl -L -O "https://raw.githubusercontent.com/nullpo-head/wsl-distrod/main/install.sh"
    echo "$password" | sudo -S chmod +x install.sh
    echo "$password" | sudo -S ./install.sh install
    echo "$password" | sudo -S /opt/distrod/bin/distrod enable --start-on-windows-boot
    rm ./install.sh
    
    # SSH settings
    echo "$password" | sudo -S apt-get purge openssh-server
    echo "$password" | sudo -S apt-get install openssh-server
    if [ ! -L /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S rm /etc/ssh/sshd_config
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/sshd_config /etc/ssh/sshd_config
    fi

    # WSL config
    if [ ! -L /etc/wsl.conf ]; then
        echo "$password" | sudo -S rm /etc/wsl.conf
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
    fi
else
    echo "$password" | sudo -S apt-get install -y chromium-browser  
fi
