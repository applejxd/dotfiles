#!/bin/sh

# $(dirname $0) でこのファイルまでの相対パスを取得
# cd で移動後に pwd で絶対パスを取得
THIS_DIR=$(
    cd $(dirname $0)
    pwd
)

cd $THIS_DIR

# config
sudo rm -rf ~/.config
ln -s /Users/masashi/Documents/home/config ~/.config

# bash
ln -s /Users/masashi/Documents/home/bash_profile ~/.bash_profile
ln -s /Users/masashi/Documents/home/bashrc ~/.bashrc

# zsh
ln -s /Users/masashi/Documents/home/zshrc ~/.zshrc
ln -s /Users/masashi/Documents/home/zshenv ~/.zshenv

# tmux
ln -s /Users/masashi/Documents/home/tmux.conf ~/.tmux.conf

# latexmk
ln -s /Users/masashi/Documents/home/latexmkrc ~/.latexmkrc

# Emacs setup
rm -rf ~/.emacs.d/private
ln -s /Users/masashi/Documents/home/private ~/.emacs.d/private
rm ~/.spacemacs
ln -s /Users/masashi/Documents/home/spacemacs ~/.spacemacs
