#!/bin/sh
# install shells

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    sudo apt install -y zsh
fi

# bash install
grep -q $(which bash) /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo $(which bash) >> /etc/shells"
fi

# zsh install
if type "zsh" > /dev/null 2>&1; then
    grep -q $(which zsh) /etc/shells
    if [ $? -ne 0 ]; then
        sudo sh -c "echo $(which zsh) >> /etc/shells"
    fi
fi

# fish install
if type "fish" > /dev/null 2>&1; then
    grep -q $(which fish) /etc/shells
    if [ $? -ne 0 ]; then
        sudo sh -c "echo $(which fish) >> /etc/shells"
    fi
fi

# change the default shell
chsh -s $(which zsh)
