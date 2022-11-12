#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password=$1
fi

if [[ ! -e /etc/lsb-release ]]; then
    echo "Your OS is not Ubuntu!"
    exit 1
fi

os_ver=$(lsb_release -r | awk '{ print $2 }')
if [[ "$os_ver" == "20.04" ]]; then
    ros_ver="noetic"
else
    echo "ROS installer for Ubuntu $os_ver is not defined!"
    exit 1
fi

#-----#
# ROS #
#-----#

if [[ ! -e /opt/ros/"$ros_ver"/setup.bash ]]; then
    echo "$password" | sudo -S sh -c 'echo "deb http://packages.ros.org/ros/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/ros-latest.list'

    echo "$password" | sudo -S apt-get install -y curl
    curl -s https://raw.githubusercontent.com/ros/rosdistro/master/ros.asc | sudo apt-key add -

    echo "$password" | sudo -S apt-get update
    echo "$password" | sudo -S apt-get install -y ros-"$ros_ver"-desktop-full

    source /opt/ros/"$ros_ver"/setup.bash

    echo "$password" | sudo -S apt-get install -y python3-rosdep python3-rosinstall python3-rosinstall-generator python3-wstool build-essential
    echo "$password" | sudo -S rosdep init
    rosdep update
else
    source /opt/ros/"$ros_ver"/setup.bash
fi
 
#--------------#
# catkin tools #
#--------------#

if [[ ! -e "$HOME"/catkin_ws/src ]]; then
    echo "$password" | sudo -S apt-get install -y python3-catkin-tools
    mkdir -p "$HOME"/catkin_ws/src
    cd "$HOME"/catkin_ws || exit
    catkin init
fi
