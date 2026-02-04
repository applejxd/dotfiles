#!/usr/bin/env bash

set -euo pipefail

sudo -v

sudo apt-get update && sudo apt-get -y upgrade

#-------#
# cmake #
#-------#

# use mise if you prefer newer version
# libncurses5-dev for ccmake
# see https://stackoverflow.com/questions/28110169/update-ccmake-on-ubuntu-when-building-from-source
sudo apt-get install -y git build-essential cmake libssl-dev libncurses5-dev

#-------#
# Basic #
#-------#

# C/C++ Build Tools
sudo apt-get install -y cmake-curses-gui gcc clang gdb clangd

# Formatter, Linter, Document Generator
sudo apt-get install -y clang-format cpplint doxygen graphviz

#--------#
# Google #
#--------#

# gflags
sudo apt-get install -y libgflags-dev

# gtest 1.13.0
mkdir -p "${HOME}/src/install"
git clone https://github.com/google/googletest.git -b v1.13.0 "${HOME}/src/install/gtest"
mkdir "${HOME}/src/install/gtest/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
sudo make install

# glog 0.5.0
mkdir -p "${HOME}/src/install"
git clone https://github.com/google/glog.git -b v0.5.0 "${HOME}/src/install/glog"
mkdir "${HOME}/src/install/glog/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
sudo make install

#------#
# Libs #
#------#

# Boost, Eigen3 (Linear Algebra), Ceres (Optimization)
sudo apt-get install -y libboost-dev libeigen3-dev libceres-dev

# OpenCV (Computer Vision), Point Cloud Library
sudo apt-get install -y libopencv-dev libpcl-dev

# matplotlib-cpp
sudo apt-get install -y python3-numpy python3-matplotlib
if [ ! -e /usr/include/matplotlibcpp.h ]; then
  sudo wget https://raw.githubusercontent.com/lava/matplotlib-cpp/master/matplotlibcpp.h -P /usr/include
  # echo "${password}" | sudo -S rm /usr/include/matplotlibcpp.h
fi
