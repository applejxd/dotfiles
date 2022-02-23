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

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    echo "$password" | sudo -S apt-get update
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

###########
# Distrod #
###########

echo "$password" | sudo -S chsh -s $(which zsh)

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]] && (! systemctl >/dev/null 2>&1); then
    curl -L -O "https://raw.githubusercontent.com/nullpo-head/wsl-distrod/main/install.sh"
    chmod +x install.sh
    echo "$password" | sudo -S ./install.sh install
    echo "$password" | sudo -S /opt/distrod/bin/distrod enable --start-on-windows-boot
    rm ./install.sh
fi

echo "$password" | sudo -S chsh -s $(which bash)

########################
# Change default shell #
########################

if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "$password" | sudo -S chsh -s $(which zsh)
fi
