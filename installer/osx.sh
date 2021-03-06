#!/bin/bash

# Python
pip3 install --upgrade setuptools
pip3 install matplotlib scipy sympy ipython[all]

# fzf install
if [ ! -e ~/.fzf.zsh ]; then
    $(brew --prefix)/opt/fzf/install
fi

# iTerm2 Shell integration
if [ ! -e ~/.iterm2_shell_integration.zsh ]; then
    curl -L https://iterm2.com/shell_integration/install_shell_integration.sh | bash
fi

# LaTeX
if !(type "platex" > /dev/null 2>&1); then
    sudo tlmgr update --self --all
    sudo tlmgr paper a4
fi

# Programming Font Ricty
if [ ! -e ~/Library/fonts/Ricty\ Discord\ Regular\ for\ Powerline.ttf ]; then
    cp -f /usr/local/opt/ricty/share/fonts/Ricty*.ttf ~/Library/Fonts/
    fc-cache -vf
fi

# powerline, which needs powerline-font
if !(type "powerline-daemon" > /dev/null 2>&1); then
    pip3 install powerline-status
fi

# spacemacs install
if [ ! -e ~/.emacs.d ]; then
    git clone https://github.com/syl20bnr/spacemacs ~/.emacs.d
    npm install --global tern
fi
