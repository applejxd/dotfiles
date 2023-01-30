# cf. https://hub.docker.com/r/nvidia/cuda/tags?page=1&name=11.2.2-cudnn8-devel-ubuntu20.04
FROM nvidia/cuda:11.2.2-cudnn8-devel-ubuntu20.04

ENV HOME /root
WORKDIR "$HOME"

#--------------#
# Localization #
#--------------#

RUN apt-get update && apt-get upgrade -y
RUN DEBIAN_FRONTEND="noninteractive" apt-get install -y tzdata
ENV TZ=Asia/Tokyo

RUN apt-get install -y locales fonts-takao && locale-gen ja_JP.UTF-8
ENV LANG=ja_JP.UTF-8
ENV LANGUAGE=ja_JP:ja
ENV LC_ALL=ja_JP.UTF-8
RUN localedef -f UTF-8 -i ja_JP ja_JP.utf8

#-----------#
# Dev Tools #
#-----------#

# Install CMake 3.21.6 for g2o
# CLion supports CMake 2.8.11~3.21.x
RUN apt-get install -y git build-essential libssl-dev
RUN git clone https://gitlab.kitware.com/cmake/cmake.git -b v3.21.6
RUN mkdir "$HOME/cmake/build"
WORKDIR "$HOME/cmake/build"
RUN ../bootstrap && make -j"$(nproc)" && make install
WORKDIR "$HOME"

RUN apt-get install -y \
      gcc g++ gdb clang make \
      ninja-build autoconf automake \
      locales-all dos2unix rsync \
      tar python

#---------------#
# Source Builds #
#---------------#

# libboost-dev is not enough for PCL
RUN apt-get install -y libboost-all-dev libeigen3-dev 

# glog
RUN git clone https://github.com/google/glog.git -b v0.5.0
RUN mkdir "$HOME/glog/build"
WORKDIR "$HOME/glog/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR "$HOME"
RUN rm -rf "$HOME/glog"

# gflags    
RUN git clone https://github.com/gflags/gflags.git -b v2.2.2
RUN mkdir "$HOME/gflags/build"
WORKDIR "$HOME/gflags/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR "$HOME"
RUN rm -rf "$HOME/gflags"

# gtest
RUN git clone https://github.com/google/googletest.git -b release-1.11.0
RUN mkdir "$HOME/googletest/build"
WORKDIR "$HOME/googletest/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR "$HOME"
RUN rm -rf "$HOME/googletest"

# ceres-solver
RUN apt-get install -y libatlas-base-dev libsuitesparse-dev
RUN git clone https://github.com/ceres-solver/ceres-solver.git -b 2.1.0
RUN mkdir "$HOME/ceres-solver/build"
WORKDIR "$HOME/ceres-solver/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR "$HOME"
RUN rm -rf "$HOME/ceres-solver"

# g2o
RUN apt-get install -y libsuitesparse-dev qtdeclarative5-dev qt5-qmake libqglviewer-dev-qt5
RUN git clone https://github.com/RainerKuemmerle/g2o.git
RUN mkdir "$HOME/g2o/build"
WORKDIR "$HOME/g2o/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR "$HOME"
RUN rm -rf "$HOME/g2o"

# Sophus
RUN git clone https://github.com/strasdat/Sophus.git
RUN mkdir "$HOME/Sophus/build"
WORKDIR "$HOME/Sophus/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR $HOME
RUN rm -rf "$HOME/Sophus"

# matplotlib-cpp
RUN apt-get install -y python3-matplotlib python3-numpy python3-dev wget
RUN wget https://github.com/lava/matplotlib-cpp/raw/master/matplotlibcpp.h -P /usr/local/include

RUN apt-get install -y libopencv-dev

# PCL
RUN apt-get install -y libusb-1.0-0-dev libflann-dev libvtk7-dev libpcap-dev
RUN git clone https://github.com/PointCloudLibrary/pcl.git -b pcl-1.12.1
RUN mkdir "$HOME/pcl/build"
WORKDIR "$HOME/pcl/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR "$HOME"
RUN rm -rf "$HOME/pcl"

# pybind11
RUN git clone https://github.com/pybind/pybind11.git
RUN mkdir "$HOME/pybind11/build"
WORKDIR "$HOME/pybind11/build"
RUN cmake .. && make -j"$(nproc)" && make install
WORKDIR "$HOME"
RUN rm -rf "$HOME/pybind11"

#--------------#
# gdb printers #
#--------------#

# for OpenCV Mat debugger
RUN apt-get install -y python3-pip
RUN pip3 install numpy
# Place gdb scripts
COPY gdbinit.sh "$HOME/.gdbinit"
COPY gdb/ "$HOME/gdb/"

#----------------#
# anyenv + pyenv #
#----------------#

# cf. https://gist.github.com/mistymagich/fa9f0f4f05e0865e191e

RUN apt-get install -y \
      build-essential libffi-dev libssl-dev zlib1g-dev liblzma-dev \
      libbz2-dev libreadline-dev libsqlite3-dev libopencv-dev tk-dev git

ENV ANYENV_HOME "$HOME/.anyenv"
ENV ANYENV_ENV  "$ANYENV_HOME/envs"
RUN git clone https://github.com/anyenv/anyenv.git "$ANYENV_HOME"
ENV PATH "$ANYENV_HOME/bin:$PATH"
RUN mkdir -p "$ANYENV_ENV"

RUN eval "$(anyenv init -)"
RUN yes | anyenv install --init

RUN anyenv install pyenv
ENV PATH "$ANYENV_ENV/pyenv/bin:$ANYENV_ENV/pyenv/shims:$PATH"
ENV PYENV_ROOT "$ANYENV_ENV/pyenv"

RUN pyenv install 3.8.13
RUN pyenv global 3.8.13

#-------------#
# Python libs #
#-------------#

# Pangolin
RUN apt-get install -y libglew-dev libpython2.7-dev libeigen3-dev
# Bug fixed PR version
RUN git clone https://github.com/bravech/pangolin "$HOME/pangolin"
RUN mkdir "$HOME/pangolin/build"
WORKDIR "$HOME/pangolin/build"
RUN cmake .. && make -j"$(nproc)"
RUN sed -i "s/install_dirs/install_dir/g" "$HOME/pangolin/setup.py"
WORKDIR "$HOME/pangolin"
RUN python setup.py install
WORKDIR "$HOME"

# g2opy
RUN apt-get install -y libsuitesparse-dev qtdeclarative5-dev libqglviewer-dev-qt5
# Bug fixed PR version
RUN git clone https://github.com/codegrafix/g2opy.git "$HOME/g2opy"
RUN mkdir "$HOME/g2opy/build"
WORKDIR "$HOME/g2opy/build"
RUN cmake .. && make -j"$(nproc)"
WORKDIR "$HOME/g2opy"
RUN python setup.py install
WORKDIR "$HOME"

COPY requirements.txt "$HOME"
RUN pip install -r requirements.txt

RUN apt-get clean && apt-get autoremove