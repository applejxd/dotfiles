#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

echo "$password" | sudo -S apt-get update
echo "$password" | sudo -S apt-get -y upgrade

function cmake_install() {
  INSTALL_PATH=$(echo "$1" | sed -e 's/^https\:\/\/\(.*\)\.git$/\1/g')
  if [ ! -e ~/src/"$INSTALL_PATH"/build ]; then
    ghq get "$1"
    mkdir ~/src/"$INSTALL_PATH"/build
    cd ~/src/"$INSTALL_PATH"/build || exit
    cmake ..
    make -j"$(nproc)"
    echo "$password" | sudo -S make install
  fi
}

#-------#
# cmake #
#-------#

# older version
# echo "$password" | sudo -S apt-get install -y cmake

# libncurses5-dev for ccmake
# cf. https://stackoverflow.com/questions/28110169/update-ccmake-on-ubuntu-when-building-from-source
echo "$password" | sudo -S apt-get install -y git build-essential libssl-dev libncurses5-dev
mkdir -p "$HOME"/src/install
# Install CMake 3.21.6 (for g2o)
# CLion supports CMake 2.8.11~3.21.x
git clone https://gitlab.kitware.com/cmake/cmake.git -b v3.21.6 "$HOME"/src/install/cmake
mkdir "$HOME"/src/install/cmake/build; cd "$_" || exit
../bootstrap && make -j"$(nproc)"
echo "$password" | sudo -S make install
cd "$HOME" || exit


#-------#
# Basic #
#-------#

# C/C++ Build Tools
echo "$password" | sudo -S apt-get install -y cmake-curses-gui gcc clang gdb

# Formatter, Linter, Document Generator
echo "$password" | sudo -S apt-get install -y clang-format cpplint doxygen graphviz

#--------#
# Google #
#--------#

# gflags
echo "$password" | sudo -S apt-get install -y  libgflags-dev

# gtest
cmake_install https://github.com/google/googletest.git

# glog
mkdir -p "$HOME"/src/install
git clone https://github.com/google/glog.git -b v0.5.0 "$HOME"/src/install/glog
mkdir "$HOME"/src/install/glog/build; cd "$_" || exit
cmake .. && make -j"$(nproc)"
echo "$password" | sudo -S make install

#------#
# Libs #
#------#

# Boost, Eigen3 (Linear Algebra), Ceres (Optimization)
echo "$password" | sudo -S apt-get install -y libboost-dev libeigen3-dev libceres-dev

# OpenCV (Computer Vision), Point Cloud Library
echo "$password" | sudo -S apt-get install -y libopencv-dev libpcl-dev

# matplotlib-cpp
echo "$password" | sudo -S apt-get install -y python3-numpy python3-matplotlib
if [ ! -e /usr/include/matplotlibcpp.h ]; then
  echo "$password" | sudo -S wget https://raw.githubusercontent.com/lava/matplotlib-cpp/master/matplotlibcpp.h -P /usr/include
  # echo "$password" | sudo -S rm /usr/include/matplotlibcpp.h
fi

function cmake_uninstall() {
  INSTALL_PATH=$(echo "$1" | sed -e 's/^https\:\/\/\(.*\)\.git$/\1/g')
  if [ ! -e ~/src/"$INSTALL_PATH"/build ]; then
  cd ~/src/"$INSTALL_PATH"/build || exit
    echo "$password" | sudo -S sh -c "xargs rm -rf < install_manifest.txt"
  fi
}
