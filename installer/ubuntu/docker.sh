#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password="$1"
fi

echo "$password" | sudo -S apt-get update

#--------#
# Docker #
#--------#

# not needed for WSL2 by Docker Desktop WSL integration
# see https://docs.docker.jp/desktop/windows/wsl.html#wsl-2-docker
if ! command -v docker >/dev/null 2>&1 && ! [[ "$(uname -r)" =~ microsoft ]]; then
    # Official Onliner script
    # see https://docs.docker.com/engine/install/ubuntu/#install-using-the-convenience-script
    echo "$password" | sudo -S bash -c "$(curl -fsSL https://get.docker.com)"

    # echo "$password" | sudo -S apt-get -y install ca-certificates curl gnupg lsb-release
    # # register GPG key of Docker official
    # curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    # # add stable repository
    # {
    #     echo "$password"
    #     echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    # } | sudo -k -S tee /etc/apt/sources.list.d/docker.list &>/dev/null

    # echo "$password" | sudo -S apt-get update
    # echo "$password" | sudo -S apt-get install -y docker-ce docker-ce-cli containerd.io

    # # Install docker-compose v2.4.0 for gpus option
    # echo "$password" | sudo -S -E curl -L "https://github.com/docker/compose/releases/download/v2.4.0/docker-compose-$(uname -s)-$(uname -m)" \
    #     -o /usr/local/bin/docker-compose
    # echo "$password" | sudo -S chmod +x /usr/local/bin/docker-compose
fi

#---------#
# Dockerd #
#---------#

if [[ "$(uname -r)" =~ microsoft ]]; then
    #-----------------#
    # Rootful Dockerd #
    #-----------------#

    echo "$password" | sudo -S gpasswd -a "$USER" docker
    # echo "$password" | sudo -S service docker start
    echo "$password" | sudo -S systemctl enable docker.service
    echo "$password" | sudo -S systemctl start docker.service
else
    #------------------#
    # Rootless Dockerd #
    #------------------#
    
    # https://docs.docker.com/engine/security/rootless/
    # https://matsuand.github.io/docs.docker.jp.onthefly/engine/security/rootless/

    # stops rootful docker
    echo "$password" | sudo -S systemctl disable --now docker.service docker.socket
    echo "$password" | sudo -S rm /var/run/docker.sock

    # enable rootless docker
    echo "$password" | sudo -S apt-get install -y uidmap dbus-user-session
    dockerd-rootless-setuptool.sh install
    echo "$password" | sudo -S systemctl --user enable docker.service
    echo "$password" | sudo -S systemctl --user start docker.service
fi
