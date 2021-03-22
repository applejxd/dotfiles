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
  if [ ! -e ~/install/$2/build ]; then
    git clone $1 ~/install/$2
    mkdir ~/install/$2/build
    cd ~/install/$2/build
    cmake ..
    make
    echo "$password" | sudo -S make install
  fi
}

cmake_install https://github.com/google/googletest.git googletest
