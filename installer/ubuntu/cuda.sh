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
# cf. https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#wsl-installation
# cf. https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html#package-manager-metas

# Use CUDA Toolkit 11.2 for PyTorch and Tensorflow
# Use CUDA Toolkit 11.3 for PyTorch and RAPIDS
# cf. https://pytorch.org/get-started/locally/
# cf. https://rapids.ai/start.html#get-rapids
cuda_major_version=11
cuda_minor_version=2
cudnn_version=8.1.0
if [[ ! -e /usr/local/"$cuda_major_version"."$cuda_minor_version" ]]; then
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

    if (! dpkg -l cuda-drivers >/dev/null 2>&1); then
        # Install the new cuda-keyring package
        tmp_file=$(mktemp)
        curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/"$distribution"/x86_64/cuda-keyring_1.1-1_all.deb >"$tmp_file"
        sudo dpkg -i "$tmp_file"

        echo "$password" | sudo -S apt update
    fi

    if [[ ! "$(uname -r)" =~ (M|m)icrosoft ]]; then
        # Do not install any Linux display driver in WSL
        # cf. https://docs.nvidia.com/cuda/wsl-user-guide/index.html#ch02-getting-started
        echo "$password" | sudo -S apt-get install -y cuda-drivers
    fi

    # CUDA
    echo "$password" | sudo -S apt-get -y install cuda-toolkit-"$cuda_major_version"-"$cuda_minor_version"
    export PATH=/usr/local/cuda-"$cuda_major_version"."$cuda_minor_version"/bin${PATH:+:${PATH}}

    # cuDNN
    echo "$password" | sudo -S -E curl -L https://developer.download.nvidia.com/compute/cuda/repos/"${distribution}"/x86_64/cuda-"${distribution}".pin \
        -o /etc/apt/preferences.d/cuda-repository-pin-600
    echo "$password" | sudo -S apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/"${distribution}"/x86_64/3bf863cc.pub
    echo "$password" | sudo -S add-apt-repository 'deb https://developer.download.nvidia.com/compute/cuda/repos/"${distribution}"/x86_64/ /'
    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get install libcudnn8="${cudnn_version}".*-1+"$cuda_major_version"."$cuda_minor_version"
    echo "$password" | sudo -S apt-get install libcudnn8-dev="${cudnn_version}".*-1+"$cuda_major_version"."$cuda_minor_version"

    # Modulefile
    echo "$password" | sudo -S mkdir -p /usr/local/Modules/modulefiles/cuda
    echo "$password" | sudo -S ln -s "$HOME"/src/dotfiles/config/cuda-11.2.module /usr/local/Modules/modulefiles/cuda/11.2
    # whether the initial loadings are commented
    module_init_file="/usr/local/Modules/etc/initrc"
    if [[ $(grep "^.*\[is-saved default\].*" $module_init_file) =~ ^#.* ]]; then
        line_num=$(grep -n "^.*\[is-saved default\].*" $module_init_file | awk -F ':' '{print $1}')
        echo "$password" | sudo -S sed -i -e "$line_num,$((line_num + 4)) s/#//g" $module_init_file
    fi
    # append initial loading
    if [[ ! $(grep "^\s*module load.*" $module_init_file) =~ ^.*cuda/$cuda_major_version\.$cuda_minor_version.* ]]; then
        echo "$password" | sudo -S sed -i -e "s/\(^\s*module load.*\)/\1 cuda\/$cuda_major_version\.$cuda_minor_version/g" $module_init_file
    fi
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

if (type "docker" >/dev/null 2>&1) && [[ "$(uname -r)" =~ microsoft ]]; then
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
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' >"$tmp_file"

    {
        echo "$password"
        cat "$tmp_file"
    } | sudo -k -S tee /etc/apt/sources.list.d/nvidia-container-toolkit.list &>/dev/null

    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get install -y nvidia-container-tookit
    echo "$password" | sudo -S systemctl restart docker
fi
