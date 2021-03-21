#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

# C++
echo "$password" | sudo -S apt install -y clang-format cpplint doxygen
echo "$password" | sudo -S apt install -y libboost-dev libeigen3-dev libceres-dev
echo "$password" | sudo -S apt install -y libboost-dev libopencv-dev libpcl-dev

# Python
echo "$password" | sudo -S apt install -y python3-pip 
pip3 install pipenv
pip3 install sphinx
pip3 install sphinx_rtd_theme

# TeX
echo "$password" | sudo -S apt install -y texlive-full
