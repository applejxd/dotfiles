#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

if [ ! -e ~/install ]; then
  mkdir ~/install
fi

function cmake_install() {
  INSTALL_PATH=`echo $1 | sed -e 's/^https\:\/\/\(.*\)\.git$/\1/g'`
  if [ ! -e $INSTALL_PATH/build ]; then
    ghq get $1
    mkdir ~/$INSTALL_PATH/build
    cd ~/$INSTALL_PATH/build
    cmake ..
    make
    echo "$password" | sudo -S make install
  fi
}

function cmake_uninstall() {
  if [ -e ~/install/$2/build ]; then
    echo "$password" | sudo -S sh -c "xargs rm -rf < install_manifest.txt"
  fi
}

cmake_install https://github.com/google/googletest.git
# cmake_install https://github.com/google/glog.git

# matplotlib-cpp
if [ ! -e /usr/include/matplotlibcpp.h ]; then
  echo "$password" | sudo -S wget https://raw.githubusercontent.com/lava/matplotlib-cpp/master/matplotlibcpp.h -P /usr/include
  # echo "$password" | sudo -S rm /usr/include/matplotlibcpp.h
fi
