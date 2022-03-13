#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# for x86_64 architecture
yes A | softwareupdate --install-rosetta

# fzf install
if [ ! -e ~/.fzf.zsh ]; then
    $(brew --prefix)/opt/fzf/install
fi

# iTerm2 Shell integration
if [ ! -e ~/.iterm2_shell_integration.zsh ]; then
    curl -L https://iterm2.com/shell_integration/install_shell_integration.sh | bash
fi

# LaTeX
if !(type "platex" > /dev/null 2>&1) && (type tlmgr > /dev/null 2>&1); then
    sudo tlmgr update --self --all
    sudo tlmgr paper a4
fi

# # Programming Font Ricty
# if [ ! -e ~/Library/fonts/Ricty\ Discord\ Regular\ for\ Powerline.ttf ]; then
#     cp -f /usr/local/opt/ricty/share/fonts/Ricty*.ttf ~/Library/Fonts/
#     fc-cache -vf
# fi

# # powerline, which needs powerline-font
# if !(type "powerline-daemon" > /dev/null 2>&1); then
#     pip3 install powerline-status
# fi
