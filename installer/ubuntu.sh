#!/bin/sh

if [ $# -eq 0 ]; then
    # save password
    printf "password: "
    read password
else
    password=$1
fi

# refresh
echo "$password" | sudo -S apt -y update
echo "$password" | sudo -S apt -y upgrade

# basics
echo "$password" | sudo -S apt install -y manpages-ja unzip zsh tree tig

# clipboard
echo "$password" | sudo -S apt install -y xsel

# C++
echo "$password" | sudo -S apt install -y cmake gdb clang-format cpplint libeigen3-dev libopencv-dev doxygen

# Python
echo "$password" | sudo -S apt install -y python3-pip 
pip3 install sphinx
pip3 install sphinx_rtd_theme

# TeX
echo "$password" | sudo -S apt install -y texlive-full

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # GUI in WSL
    echo "$password" | sudo -S apt install -y xfce4-terminal xfce4
    if [ ! -L /etc/wsl.conf ]; then
        echo "$password" | sudo -S rm /etc/wsl.conf
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
    fi
    # for JetBrains IDEs
    echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/jetbrains.sh)
else
    echo "$password" | sudo -S apt install -y chromium-browser  
fi
