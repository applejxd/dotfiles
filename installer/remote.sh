#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

echo "$password" | sudo -S apt update
echo "$password" | sudo -S apt install -y openssh-server
echo "$password" | sudo -S systemctl enable ssh
echo "$password" | sudo -S systemctl start ssh

####################
# for remote login #
####################

# change ssh port number to 2222
echo "$password" | sudo -S sed -i -e 's/^#*\s*Port.*$/Port 2222/' /etc/ssh/sshd_config
# enable X11 forwarding
echo "$password" | sudo -S sed -i -e 's/^#*\s*X11Forwarding.*$/X11Forwarding yes/' /etc/ssh/sshd_config
# use public key auth
echo "$password" | sudo -S sed -i -e 's/^#*\s*PubkeyAuthentication.*$/PubkeyAuthentication yes/' /etc/ssh/sshd_config

################
# for security #
################

# prohibit root login
echo "$password" | sudo -S sed -i -e 's/^#*\s*PermitRootLogin.*$/PermitRootLogin no/' /etc/ssh/sshd_config