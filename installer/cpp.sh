if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

function cmake_install() {
  INSTALL_PATH=`echo $1 | sed -e 's/^https\:\/\/\(.*\)\.git$/\1/g'`
  if [ ! -e ~/src/$INSTALL_PATH/build ]; then
    ghq get $1
    mkdir ~/src/$INSTALL_PATH/build
    cd ~/src/$INSTALL_PATH/build
    cmake ..
    make
    echo "$password" | sudo -S make install
  fi
}

# C/C++ Build Tools
echo "$password" | sudo -S apt install -y cmake cmake-curses-gui gcc clang gdb build-essential

# Formatter, Linter, Document Generator
echo "$password" | sudo -S apt install -y clang-format cpplint doxygen

# Google OSS
echo "$password" | sudo -S apt install -y libgoogle-glog-dev libgflags-dev
cmake_install https://github.com/google/googletest.git

# Boost, Eigen3 (Linear Algebra), Ceres (Optimization)
echo "$password" | sudo -S apt install -y libboost-dev libeigen3-dev libceres-dev

# OpenCV (Computer Vision), Point Cloud Library
echo "$password" | sudo -S apt install -y libopencv-dev libpcl-dev

# matplotlib-cpp
echo "$password" | sudo -S apt install -y python3-numpy python3-matplotlib
if [ ! -e /usr/include/matplotlibcpp.h ]; then
  echo "$password" | sudo -S wget https://raw.githubusercontent.com/lava/matplotlib-cpp/master/matplotlibcpp.h -P /usr/include
  # echo "$password" | sudo -S rm /usr/include/matplotlibcpp.h
fi

function cmake_uninstall() {
  INSTALL_PATH=`echo $1 | sed -e 's/^https\:\/\/\(.*\)\.git$/\1/g'`
  if [ ! -e ~/src/$INSTALL_PATH/build ]; then
  cd ~/src/$INSTALL_PATH/build
    echo "$password" | sudo -S sh -c "xargs rm -rf < install_manifest.txt"
  fi
}