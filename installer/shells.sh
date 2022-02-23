#!/bin/sh
# install shells

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

###########
# Install #
###########

# zsh install or update
if [[ "$OSTYPE" == "linux-gnu" ]]; then
    echo "$password" | sudo -S apt-get install -y zsh fish
fi

############
# Register #
############

# register bash
if ! grep -q $(which bash) /etc/shells; then
    echo "$password" | sudo -S sh -c "echo $(which bash) >> /etc/shells"
fi

# register fish
if type "fish" > /dev/null 2>&1; then
    if ! grep -q $(which fish) /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which fish) >> /etc/shells"
    fi
fi

# register zsh
if type "zsh" > /dev/null 2>&1; then
    if ! grep -q $(which zsh) /etc/shells; then
        echo "$password" | sudo -S sh -c "echo $(which zsh) >> /etc/shells"
    fi
fi

############
# Register #
############

# if [[ "$OSTYPE" != "darwin"* ]]; then
    # if [[ $SHELL != $(which zsh) ]]; then
    #     change the default shell
    #     echo "$password" | chsh -s $(which zsh)
    # fi
# fi
