#!/bin/sh

# repository (emacs)
sudo add-apt-repository ppa:kelleyk/emacs

# refresh
sudo apt update
yes | sudo apt upgrade

# basics
yes | sudo apt install chromium-browser manpages-ja colordiff emacs26

# Git
yes | sudo apt install git tig

# LaTeX
yes | sudo apt install texlive texlive-lang-japanese

# Calc
yes | sudo apt install cadabra

# Emacs keybind
gsettings set org.gnome.desktop.interface gtk-key-theme Emacs
