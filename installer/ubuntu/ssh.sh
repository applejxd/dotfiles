#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt-get -y update && apt-get -y upgrade

echo "$password" | sudo -S bash -c "\
    apt-get purge -y openssh-server && \
    apt-get install -y openssh-server"

if [ ! -L /etc/ssh/sshd_config ]; then
    if [ -f /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S mv /etc/ssh/sshd_config /etc/ssh/sshd_config.bk
    fi
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/sshd_config /etc/ssh/sshd_config
fi
