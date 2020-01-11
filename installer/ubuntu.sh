#!/bin/sh

# repository (emacs)
sudo add-apt-repository ppa:kelleyk/emacs

# refresh
sudo apt update && sudo apt upgrade

# basics
sudo apt install -y chromium-browser manpages-ja colordiff emacs26

# Git
sudo apt install -y git tig

# LaTeX
sudo apt install -y texlive texlive-lang-japanese

# Calc
sudo apt install -y cadabra

# Emacs keybind
gsettings set org.gnome.desktop.interface gtk-key-theme Emacs
