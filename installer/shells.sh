#!/bin/sh
# install shells

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# bash install
grep -q $(which bash) /etc/shells
if [ $? -ne 0 ]; then
    echo "$password" | sudo -S sh -c "echo $(which bash) >> /etc/shells"
fi

# # fish install
# if type "fish" > /dev/null 2>&1; then
#     grep -q $(which fish) /etc/shells
#     if [ $? -ne 0 ]; then
#         echo "$password" | sudo -S sh -c "echo $(which fish) >> /etc/shells"
#     fi
# fi

#######
# zsh #
#######

# zsh install or update
if !(type "zsh" > /dev/null 2>&1) && [[ "$OSTYPE" == "linux-gnu" ]]; then
    echo "$password" | sudo -S apt install -y zsh
fi

# zsh install
if type "zsh" > /dev/null 2>&1; then
    grep -q $(which zsh) /etc/shells
    if [ $? -ne 0 ]; then
        echo "$password" | sudo -S sh -c "echo $(which zsh) >> /etc/shells"
    fi
fi

if [[ $SHELL != $(which zsh) ]]; then
    # change the default shell
    echo "$password" | sudo -S chsh -s $(which zsh)
fi
