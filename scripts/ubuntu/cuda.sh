#!/bin/bash

sudo -v

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
            # shellcheck source=/dev/null
            . /etc/os-release
            echo "$ID""$VERSION_ID" | sed -e 's/\.//g'
        )
        # The kernel headers and dev packages (Does not need to be performed for WSL)
        sudo apt-get -y install linux-headers-"$(uname -r)"
    fi

    # Install the new cuda-keyring package if not already installed
    if (! dpkg -l cuda-keyring >/dev/null 2>&1); then
        tmp_file=$(mktemp)
        curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/"$distribution"/x86_64/cuda-keyring_1.1-1_all.deb >"$tmp_file"
        sudo dpkg -i "$tmp_file"
        rm "$tmp_file"

        sudo apt-get update
    fi

    if [[ ! "$(uname -r)" =~ (M|m)icrosoft ]]; then
        # Do not install any Linux display driver in WSL
        # see https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch02-getting-started
        sudo apt-get install -y cuda-drivers
    fi

    # CUDA
    sudo apt-get -y install cuda-toolkit
    export PATH=/usr/local/cuda/bin${PATH:+:${PATH}}
    export LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
fi

#---------------#
# Nvidia Docker #
#---------------#

# Docker から GPU を使う設定は nvidia-container-toolkit.sh に分離した。
