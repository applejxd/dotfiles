#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password="$1"
fi

echo "$password" | sudo -S apt-get update

if ! (type "docker" > /dev/null 2>&1); then
    ##########
    # Docker #
    ##########
    
    # cf. https://docs.docker.com/engine/install/ubuntu/
    # cf. https://zenn.dev/sprout2000/articles/95b125e3359694
    
    # Official Onliner script
    # echo "$password" | sudo -S bash -c "$(curl -fsSL https://get.docker.com)"
    
    echo "$password" | sudo -S apt-get -y install ca-certificates curl gnupg lsb-release
    # register GPG key of Docker official
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    # add stable repository
    { echo "$password"; echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"; } \
    | sudo -k -S tee /etc/apt/sources.list.d/docker.list &>/dev/null
    
    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose
           
    if [[ "$(uname -r)" =~ microsoft ]]; then     
        ###################
        # Rootful Dockerd #
        ###################
        
        echo "$password" | sudo -S gpasswd -a $USER docker
        # echo "$password" | sudo -S service docker start
        echo "$password" | sudo -S systemctl enable docker.service
        echo "$password" | sudo -S systemctl start docker.service
    else
        ####################
        # Rootless Dockerd #
        ####################
        
        # cf. https://matsuand.github.io/docs.docker.jp.onthefly/engine/security/rootless/
        
        echo "$password" | sudo -S apt-get install -y uidmap dbus-user-session
        dockerd-rootless-setuptool.sh install
        echo "$password" | sudo -S systemctl --user enable docker.service
        echo "$password" | sudo -S systemctl --user start docker.service
    fi
fi
