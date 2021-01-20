#!/bin/sh

# save password
printf "password: "
read password

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
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
else
    echo "$password" | sudo -S apt install -y chromium-browser  
fi
