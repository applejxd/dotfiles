#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

#------#
# CUDA #
#------#

# Control Driver and CUDA Toolkit separatelly
# see https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#wsl-installation
# see https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#package-manager-metas
if [[ ! -e /usr/local/cuda ]]; then
    if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
        distribution="wsl-ubuntu"
    else
        distribution=$(
            . /etc/os-release
            echo "$ID""$VERSION_ID" | sed -e 's/\.//g'
        )
        # The kernel headers and dev packages (Does not need to be performed for WSL)
        echo "$password" | sudo -S apt-get -y install linux-headers-"$(uname -r)"
    fi

    # Install the new cuda-keyring package if not already installed
    if (! dpkg -l cuda-keyring >/dev/null 2>&1); then
        tmp_file=$(mktemp)
        curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/"$distribution"/x86_64/cuda-keyring_1.1-1_all.deb >"$tmp_file"
        echo "$password" | sudo -S dpkg -i "$tmp_file"
        rm "$tmp_file"

        echo "$password" | sudo -S apt-get update
    fi

    if [[ ! "$(uname -r)" =~ (M|m)icrosoft ]]; then
        # Do not install any Linux display driver in WSL
        # see https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch02-getting-started
        echo "$password" | sudo -S apt-get install -y cuda-drivers
    fi

    # CUDA
    echo "$password" | sudo -S apt-get -y install cuda-toolkit
    export PATH=/usr/local/cuda/bin${PATH:+:${PATH}}
    export LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
fi

#---------------#
# Nvidia Docker #
#---------------#

# Documentation (nvidia-container-toolkit):
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

# nvidia-docker2 is not recommended:
# https://medium.com/nvidiajapan/nvidia-docker-%E3%81%A3%E3%81%A6%E4%BB%8A%E3%81%A9%E3%81%86%E3%81%AA%E3%81%A3%E3%81%A6%E3%82%8B%E3%81%AE-20-09-%E7%89%88-558fae883f44

# WSL support:
# https://docs.nvidia.com/cuda/wsl-user-guide/index.html

# sudo with pipe:
# https://unix.stackexchange.com/questions/391796/pipe-password-to-sudo-and-other-data-to-sudoed-command

if (command -v "docker" >/dev/null 2>&1) && [[ "$(uname -r)" =~ microsoft ]]; then
    # shellcheck source=/dev/null
    distribution=$(
        . /etc/os-release
        echo "$ID""$VERSION_ID"
    )

    {
        echo "$password"
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey
    } | sudo -k -S gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    tmp_file=$(mktemp)
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > "$tmp_file"

    {
        echo "$password"
        cat "$tmp_file"
    } | sudo -k -S tee /etc/apt/sources.list.d/nvidia-container-toolkit.list &>/dev/null

    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get install -y nvidia-container-toolkit
    echo "$password" | sudo -S systemctl restart docker

    # verify installation
    docker run --gpus all --rm nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 nvidia-smi
fi
