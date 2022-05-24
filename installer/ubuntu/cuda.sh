#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

########
# CUDA #
########

# Control Driver and CUDA Toolkit separatelly
# cf. https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#wsl-installation
# cf. https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#package-manager-metas

# Use CUDA Toolkit 11.3 for PyTorch and RAPIDS
# cf. https://pytorch.org/get-started/locally/
# cf. https://rapids.ai/start.html#get-rapids

if [[ ! -e /usr/local/cuda-11.3 ]];then
    if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
        distribution="wsl-ubuntu"
    else
        distribution=$(. /etc/os-release; echo "$ID""$VERSION_ID" | sed -e 's/\.//g')
        # The kernel headers and dev packages (Does not need to be performed for WSL)
        echo "$password" | sudo -S apt-get -y install linux-headers-"$(uname -r)"
    fi

    if  (! dpkg -l cuda-drivers > /dev/null 2>&1); then
        # Install the new cuda-keyring package
        tmp_file=$(mktemp)
        curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/$distribution/x86_64/cuda-keyring_1.0-1_all.deb > "$tmp_file"
        sudo dpkg -i "$tmp_file"

        echo "$password" | sudo -S apt update
    fi

    if [[ ! "$(uname -r)" =~ (M|m)icrosoft ]]; then
        # Do not install any Linux display driver in WSL
        # cf. https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch02-getting-started
        echo "$password" | sudo -S apt-get install -y cuda-drivers
    fi

    echo "$password" | sudo -S apt-get -y install cuda-toolkit-11-3
    export PATH=/usr/local/cuda-11.3/bin${PATH:+:${PATH}}
fi 

#################
# Nvidia Docker #
#################
      
# cf. https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch05-running-containers
# cf. https://unix.stackexchange.com/questions/391796/pipe-password-to-sudo-and-other-data-to-sudoed-command
        
if (type "docker" > /dev/null 2>&1) && [[ "$(uname -r)" =~ microsoft ]]; then
        distribution=$(. /etc/os-release; echo "$ID""$VERSION_ID")
        { echo "$password"; curl -fsSL https://nvidia.github.io/nvidia-docker/gpgkey; } | sudo -k -S apt-key add -
        { echo "$password"; curl -fsSL https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list; } \
        | sudo -k -S tee /etc/apt/sources.list.d/nvidia-docker.list &>/dev/null
        echo "$password" | sudo -S apt-get update
        echo "$password" | sudo -S apt-get install -y nvidia-docker2
        echo "$password" | sudo -S systemctl restart docker
fi
