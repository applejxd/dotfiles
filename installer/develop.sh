#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

#######
# C++ #
#######

# Formatter, Linter, Document Generator
echo "$password" | sudo -S apt install -y clang-format cpplint doxygen
# Boost, Eigen3 (Linear Algebra), Ceres (Optimization)
echo "$password" | sudo -S apt install -y libboost-dev libeigen3-dev libceres-dev
# OpenCV (Computer Vision), Point Cloud Library
echo "$password" | sudo -S apt install -y libopencv-dev libpcl-dev
# Google Tests
echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/cmake_install.sh)

# ##########
# # Python #
# ##########

# echo "$password" | sudo -S apt install -y python3-pip 
# pip3 install pipenv
# # Sphinx (Document Generator)
# pip3 install sphinx
# pip3 install sphinx_rtd_theme

#######
# TeX #
#######

# echo "$password" | sudo -S apt install -y texlive-full
