#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password="$1"
fi

echo "${password}" | sudo -S apt-get update
echo "${password}" | sudo -S apt-get -y upgrade

# Install CMake 3.21.6 for g2o
# CLion supports CMake 2.8.11~3.21.x
echo "${password}" | sudo -S apt-get install -y git build-essential libssl-dev
mkdir -p "${HOME}/src/install"
git clone https://gitlab.kitware.com/cmake/cmake.git -b v3.21.6 "${HOME}/src/install/cmake"
mkdir "${HOME}/src/install/cmake/build"
cd "${_}" || exit
../bootstrap && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# libboost-dev is not enough for PCL
echo "${password}" | sudo -S apt-get install -y libboost-all-dev libeigen3-dev

# glog
git clone https://github.com/google/glog.git -b v0.5.0 "${HOME}/src/install/glog"
mkdir "${HOME}/src/install/glog/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# gflags
git clone https://github.com/gflags/gflags.git -b v2.2.2 "${HOME}/src/install/gflags"
mkdir "${HOME}/src/install/gflags/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# gtest
git clone https://github.com/google/googletest.git -b release-1.11.0 "${HOME}/src/install/googletest"
mkdir "${HOME}/src/install/googletest/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# Sophus
git clone https://github.com/strasdat/Sophus.git "${HOME}/src/install/Sophus"
mkdir "${HOME}/src/install/Sophus/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# ceres-solver
echo "${password}" | sudo -S apt-get install -y libatlas-base-dev libsuitesparse-dev
git clone https://github.com/ceres-solver/ceres-solver.git -b 2.1.0 "${HOME}/src/install/ceres-solver"
mkdir "${HOME}/src/install/ceres-solver/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# g2o
echo "${password}" | sudo -S apt-get install -y libsuitesparse-dev qtdeclarative5-dev qt5-qmake libqglviewer-dev-qt5
git clone https://github.com/RainerKuemmerle/g2o.git "${HOME}/src/install/g2o"
mkdir "${HOME}/src/install/g2o/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# matplotlib-cpp
echo "${password}" | sudo -S apt-get install -y python3-matplotlib python3-numpy python3-dev wget
echo "${password}" | sudo -S wget https://github.com/lava/matplotlib-cpp/raw/master/matplotlibcpp.h -P /usr/local/include

echo "${password}" | sudo -S apt-get install -y libopencv-dev

# PCL
echo "${password}" | sudo -S apt-get install -y libusb-1.0-0-dev libflann-dev libvtk7-dev libpcap-dev
git clone https://github.com/PointCloudLibrary/pcl.git -b pcl-1.12.1 "${HOME}/src/install/pcl"
mkdir "${HOME}/src/install/pcl/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

# PROJ
echo "${password}" | sudo -S apt-get install -y sqlite3 libsqlite3-dev
git clone https://github.com/OSGeo/PROJ.git -b 9.0.0 "${HOME}/src/install/PROJ"
mkdir "${HOME}/src/install/PROJ/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
echo "${password}" | sudo -S make install
cd "${HOME}" || exit

#------#
# mise #
#------#

# mise
if [[ ! -e "${HOME}/.local/bin/mise" ]]; then
    curl https://mise.run | sh
fi
eval "$(~/.local/bin/mise activate)"
export PATH="${HOME}/.local/share/mise/shims:${PATH}"

mise use --global -y python@3.8
python3 -m venv slam
# shellcheck source=/dev/null
source "${HOME}/slam/bin/activate"

# Pangolin
echo "${password}" | sudo -S apt-get install -y libglew-dev libpython2.7-dev
# Bug fixed PR version
git clone https://github.com/bravech/pangolin "${HOME}/src/install/pangolin"
mkdir "${HOME}/src/install/pangolin/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
sed -i "s/install_dirs/install_dir/g" "${HOME}/src/install/panglin/setup.py"
cd "${HOME}/src/install/pangolin" || exit
python setup.py install
cd "${HOME}" || exit

# g2opy
echo "${password}" | sudo -S apt-get install -y libsuitesparse-dev qtdeclarative5-dev libqglviewer-dev-qt5
# Bug fixed PR version
git clone https://github.com/codegrafix/g2opy.git "${HOME}/src/install/g2opy"
mkdir "${HOME}/src/install/g2opy/build"
cd "${_}" || exit
cmake .. && make -j"$(nproc)"
cd "${HOME}/src/install/g2opy" || exit
python setup.py install
cd "${HOME}" || exit
