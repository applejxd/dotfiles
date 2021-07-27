#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

# ##########
# # Python #
# ##########

# for matplotlib-cpp
echo "$password" | sudo -S apt install -y python3-numpy python3-matplotlib

# echo "$password" | sudo -S apt install -y python3-pip
# pip3 install pipenv
# Sphinx (Document Generator)
# pip3 install sphinx
# pip3 install sphinx_rtd_theme

#######
# C++ #
#######

# Formatter, Linter, Document Generator
echo "$password" | sudo -S apt install -y clang-format cpplint doxygen
# Google OSS
echo "$password" | sudo -S apt install -y libgoogle-glog-dev libgflags-dev libgtest-dev
# Boost, Eigen3 (Linear Algebra), Ceres (Optimization)
echo "$password" | sudo -S apt install -y libboost-dev libeigen3-dev libceres-dev
# OpenCV (Computer Vision), Point Cloud Library
echo "$password" | sudo -S apt install -y libopencv-dev libpcl-dev

# echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/manual_install.sh)

#######
# TeX #
#######

# echo "$password" | sudo -S apt install -y texlive-full
