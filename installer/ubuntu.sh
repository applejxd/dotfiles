#!/bin/sh

# refresh
sudo apt -y update
sudo apt -y upgrade

# basics
sudo apt install -y manpages-ja unzip zsh cmake tree

# clipboard
sudo apt install -y xsel

# Developments
sudo apt install -y texlive-full libopencv-dev

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # GUI in WSL
    sudo apt install -y xfce4-terminal xfce4
else
    sudo apt install -y chromium-browser  
fi
