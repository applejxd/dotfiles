#!/bin/sh

# refresh
sudo apt -y update
sudo apt -y upgrade

# basics
sudo apt install -y manpages-ja unzip zsh cmake tree

# clipboard
sudo apt install -y xsel

sudo apt install -y zsh

# Developments
sudo apt install -y python3-pip libopencv-dev
sudo apt install -y texlive-full

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # GUI in WSL
    sudo apt install -y xfce4-terminal xfce4
else
    sudo apt install -y chromium-browser  
fi
