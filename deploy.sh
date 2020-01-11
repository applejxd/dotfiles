#!/bin/sh

if type "homesick" >/dev/null 2>&1; then
    sudo gem install homesick
fi
homesick clone applejxd/dotfiles
homesick link dotfiles
