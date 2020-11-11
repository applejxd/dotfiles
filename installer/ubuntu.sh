#!/bin/sh

# refresh
sudo apt -y update
sudo apt -y upgrade

# basics
sudo apt install -y manpages-ja unzip zsh tree

# clipboard
sudo apt install -y xsel

# C++
sudo apt install -y cmake gdb clang-format cpplint libeigen3-dev libopencv-dev doxygen

# Python
sudo apt install -y python3-pip 
pip3 install sphinx
pip3 install sphinx_rtd_theme

# TeX
sudo apt install -y texlive-full

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # GUI in WSL
    sudo apt install -y xfce4-terminal xfce4
else
    sudo apt install -y chromium-browser  
fi
