#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

# Control Driver and CUDA Toolkit separatelly
# cf. https://docs.nvidia.com/datacenter/tesla/tesla-installation-notes/index.html#ubuntu-lts
# cf. https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#package-manager-metas

distribution=$(. /etc/os-release;echo $ID$VERSION_ID | sed -e 's/\.//g')

if [[ ! "$(uname -r)" =~ (M|m)icrosoft ]]; then
    # Step 1: The kernel headers and dev packages
    echo "$password" | sudo -S apt-get -y install linux-headers-$(uname -r)
    # Step 2: Use the CUDA network repository
    wget https://developer.download.nvidia.com/compute/cuda/repos/$distribution/x86_64/cuda-$distribution.pin
    echo "$password" | sudo -S mv cuda-$distribution.pin /etc/apt/preferences.d/cuda-repository-pin-600
fi

if  (! dpkg -l cuda-drivers > /dev/null 2>&1); then
    # Step 3: The CUDA network repository public GPG key
    echo "$password" | sudo -S apt-key adv --fetch-keys \
    https://developer.download.nvidia.com/compute/cuda/repos/$distribution/x86_64/7fa2af80.pub

    # Step 4: Setup the CUDA network repository
    # cf. https://unix.stackexchange.com/questions/391796/pipe-password-to-sudo-and-other-data-to-sudoed-command
    { echo "$password"; echo "deb http://developer.download.nvidia.com/compute/cuda/repos/$distribution/x86_64 /"; } \
    | sudo -k -S tee /etc/apt/sources.list.d/cuda.list &>/dev/null

    # Step 5: Update and installation
    echo "$password" | sudo -S apt update
fi

if [[ ! "$(uname -r)" =~ (M|m)icrosoft ]]; then
    # Do not install any Linux display driver in WSL
    # cf. https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch02-getting-started
    echo "$password" | sudo -S apt-get install -y cuda-drivers
fi

echo "$password" | sudo -S apt-get -y install cuda-toolkit-11-6
export PATH=/usr/local/cuda-11.6/bin${PATH:+:${PATH}}

#################
# Nvidia Docker #
#################
      
# cf. https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch05-running-containers
# cf. https://unix.stackexchange.com/questions/391796/pipe-password-to-sudo-and-other-data-to-sudoed-command
        
if !(type "docker" > /dev/null 2>&1) && [[ "$(uname -r)" =~ microsoft ]]; then
        distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
        { echo "$password"; curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey; } | sudo -k -S apt-key add -
        { echo "$password"; curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list; } \
        | sudo -k -S tee /etc/apt/sources.list.d/nvidia-docker.list &>/dev/null
        echo "$password" | sudo -S apt-get update
        echo "$password" | sudo -S apt-get install -y nvidia-docker2
fi
