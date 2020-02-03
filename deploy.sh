#!/bin/sh

if !(type "brew" > /dev/null 2>&1); then
    bash -c "$(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/installer/homebrew.sh)"
fi

if !(type "gem" > /dev/null 2>&1); then
    brew install ruby
fi

if !(type "homesick" >/dev/null 2>&1); then
    gem install homesick
fi

homesick clone applejxd/dotfiles
homesick link dotfiles
