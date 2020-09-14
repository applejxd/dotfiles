#!/bin/sh

# refresh
sudo apt -y update
sudo apt -y upgrade

# basics
sudo apt install -y manpages-ja unzip

# clipboard
sudo apt install -y xsel

# Developing
sudo apt install -y zsh

sudo apt install -y python3-pip

# LaTeX
sudo apt install -y texlive-full

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # GUI in WSL
    sudo apt install -y xfce4-terminal xfce4
else
    sudo apt install -y chromium-browser  
fi
