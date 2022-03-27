#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password="$1"
fi

echo "$password" | sudo -S apt-get update

if !(type "docker" > /dev/null 2>&1); then
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
           
    if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
        #################
        # Nvidia Docker #
        #################
        
        # cf. https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch05-running-containers
        # cf. https://unix.stackexchange.com/questions/391796/pipe-password-to-sudo-and-other-data-to-sudoed-command
        
        distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
        { echo "$password"; curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey; } | sudo -k -S apt-key add -
        { echo "$password"; curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list; } \
        | sudo -k -S tee /etc/apt/sources.list.d/nvidia-docker.list &>/dev/null
        echo "$password" | sudo -S apt-get update
        echo "$password" | sudo -S apt-get install -y nvidia-docker2
        
        ###################
        # Rootful Dockerd #
        ###################
        
        echo "$password" | sudo -S gpasswd -a $(whoami) docker
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

