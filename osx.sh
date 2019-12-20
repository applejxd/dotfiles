#!/bin/sh

# Python
pip3 install --upgrade setuptools
pip3 install matplotlib scipy sympy ipython[all]

# zsh install
grep -q /usr/local/bin/zsh /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo '/usr/local/bin/zsh\n' >> /etc/shells"
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

# LaTeX
sudo tlmgr update --self --all
sudo tlmgr paper a4
