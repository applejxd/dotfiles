#!/bin/sh
# install shells

# bash install
grep -q $(which bash) /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo $(which bash) >> /etc/shells"
fi

# zsh install
grep -q $(which zsh) /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo $(which zsh) >> /etc/shells"
fi

# fish install
# grep -q $(which fish) /etc/shells
# if [ $? -ne 0 ]; then
#     sudo sh -c "echo $(which fish) >> /etc/shells"
# fi

# change the default shell
if [[ "$OSTYPE" == "linux-gnu" ]]; then
    sudo apt install -y zsh
    chsh -s /usr/bin/zsh
elif [[ "$OSTYPE" == "darwin"* ]]; then
    chsh -s $(which zsh)    
fi
