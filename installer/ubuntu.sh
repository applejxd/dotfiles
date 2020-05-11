#!/bin/sh

# repository (emacs)
sudo add-apt-repository ppa:kelleyk/emacs

# refresh
sudo apt -y update
sudo apt -y upgrade

# basics
sudo apt install -y manpages-ja emacs26 xsel

# LaTeX
sudo apt install -y texlive texlive-lang-japanese

# Calc
sudo apt install -y cadabra

# Emacs keybind
gsettings set org.gnome.desktop.interface gtk-key-theme Emacs

# GUI in WSL
if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    sudo apt install -y xfce4-terminal xfce4
else
    sudo apt install -y chromium-browser  
fi
