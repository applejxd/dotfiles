#!/bin/bash

sudo -v

if [[ ! -e /etc/lsb-release ]]; then
    echo "Your OS is not Ubuntu!"
    exit 1
fi

os_ver=$(lsb_release -r | awk '{ print $2 }')
if [[ "$os_ver" == "22.04" ]]; then
    export ROS_DISTRO="humble"
else
    echo "ROS installer for Ubuntu $os_ver is not defined!"
    exit 1
fi

#-----#
# ROS #
#-----#

# from https://docs.ros.org/en/foxy/Installation/Ubuntu-Install-Debians.html
if [[ ! -e /opt/ros/"${ROS_DISTRO}"/setup.bash ]]; then
    sudo apt install software-properties-common
    sudo add-apt-repository universe

    sudo apt-get update
    sudo apt-get install -y curl
    sudo curl \
        -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg

    # shellcheck source=/dev/null
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" |
        sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null

    sudo apt-get update
    sudo apt-get -y upgrade
    sudo apt install -y ros-"${ROS_DISTRO}"-desktop python3-argcomplete

    # shellcheck source=/dev/null
    source /opt/ros/"${ROS_DISTRO}"/setup.sh
else
    # shellcheck source=/dev/null
    source /opt/ros/"${ROS_DISTRO}"/setup.sh
fi
