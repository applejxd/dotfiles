#!/bin/sh

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

if [[ ! -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # Step 1: The kernel headers and dev packages
    echo "$password" | sudo -S apt-get install linux-headers-$(uname -r)
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

if [[ ! -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    echo "$password" | sudo -S apt install -y cuda-drivers
fi

echo "$password" | sudo -S apt install cuda-toolkit-11-6
