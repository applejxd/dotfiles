#!/bin/sh
# install shells from Homebrew

# bash install
grep -q $(which bash) /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo $(which bash) >> /etc/shells"
fi

# zsh install
grep -q $(which zsh) /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo $(which zsh) >> /etc/shells"
    # change the default shell
    chsh -s $(which zsh)
fi

# fish install
grep -q $(which fish) /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo $(which fish) >> /etc/shells"
fi
