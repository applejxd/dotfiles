#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

# change port number before starting service not to conflict host sshd server for WSL
if [ ! -L /etc/ssh/sshd_config ]; then
    if [ -f /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S mv /etc/ssh/sshd_config /etc/ssh/sshd_config.bk
    fi
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/sshd_config /etc/ssh/sshd_config
fi

# Refresh
echo "$password" | sudo -S apt-get -y update && apt-get -y upgrade

# installation needed after configuration avoid the conflict
echo "$password" | sudo -S apt-get purge -y openssh-server
echo "$password" | sudo -S env DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
