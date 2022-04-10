FROM ubuntu:20.04

WORKDIR /root

RUN DEBIAN_FRONTEND="noninteractive" apt-get update && apt-get -y install tzdata

# Install CMake 3.21.6 for manual library installation
# CLion supports CMake 2.8.11~3.21.x
RUN apt-get install -y git build-essential libssl-dev
RUN git clone https://gitlab.kitware.com/cmake/cmake.git -b v3.21.6
RUN mkdir /root/cmake/build
WORKDIR /root/cmake/build
RUN ../bootstrap && make -j$(nproc) && make install
WORKDIR /root

RUN apt-get install -y ssh \
      gcc \
      g++ \
      gdb \
      clang \
      make \
      ninja-build \
      autoconf \
      automake \
      locales-all \
      dos2unix \
      rsync \
      tar \
      python

# for vcpkg
# RUN apt-get install -y curl zip unzip pkg-config

#######################
# Manual installation #
#######################

# glog
RUN git clone https://github.com/google/glog.git -b v0.5.0
RUN mkdir /root/glog/build
WORKDIR /root/glog/build
RUN cmake .. && make -j$(nproc) && make install
WORKDIR /root

# gflags    
RUN git clone https://github.com/gflags/gflags.git -b v2.2.2
RUN mkdir /root/gflags/build
WORKDIR /root/gflags/build
RUN cmake .. && make -j$(nproc) && make install
WORKDIR /root

# gtest
RUN git clone https://github.com/google/googletest.git -b release-1.11.0
RUN mkdir /root/googletest/build
WORKDIR /root/googletest/build
RUN cmake .. && make -j$(nproc) && make install
WORKDIR /root

# Eigen & ceres
RUN apt-get install -y libeigen3-dev libatlas-base-dev libsuitesparse-dev
RUN git clone https://github.com/ceres-solver/ceres-solver.git -b 2.1.0
RUN mkdir /root/ceres-solver/build
WORKDIR /root/ceres-solver/build
RUN cmake .. && make -j$(nproc) && make install
WORKDIR /root

# g2o
RUN apt-get install -y libsuitesparse-dev qtdeclarative5-dev qt5-qmake libqglviewer-dev-qt5
RUN git clone https://github.com/RainerKuemmerle/g2o.git
RUN mkdir /root/g2o/build
WORKDIR /root/g2o/build
RUN cmake .. && make -j$(nproc) && make install
WORKDIR /root

# Sophus
RUN git clone https://github.com/strasdat/Sophus.git
RUN mkdir /root/Sophus/build
WORKDIR /root/Sophus/build
RUN cmake .. && make -j$(nproc) && make install
WORKDIR /root

# matplotlib-cpp
RUN apt-get install -y python3-matplotlib python3-numpy python3-dev
RUN wget https://github.com/lava/matplotlib-cpp/raw/master/matplotlibcpp.h -P /usr/local/include

RUN apt-get install -y libboost-dev libopencv-dev

#######
# gdb #
#######

# for OpenCV Mat debugger
RUN apt-get install -y python3-pip
RUN pip3 install numpy
# Place gdb scripts
COPY gdbinit.sh /root/.gdbinit
COPY gdb/ /root/gdb/

#######
# SSH #
#######

RUN ( \
    echo 'LogLevel DEBUG2'; \
    echo 'PermitRootLogin yes'; \
    echo 'PasswordAuthentication no'; \
    echo 'RSAAuthentication yes'; \
    echo 'PubkeyAuthentication yes'; \
    echo 'AuthorizedKeysFile .ssh/authorized_keys'; \
    echo 'Subsystem sftp /usr/lib/openssh/sftp-server'; \
    echo 'Port 2222'; \
    echo 'X11Forwarding yes'; \
  ) > /etc/ssh/sshd_config_user \
  && mkdir /run/sshd

# SSH login fix. Otherwise user is kicked off after login
# cf. https://qiita.com/YumaInaura/items/7509061e4b27e03ea538
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

# 手元の公開鍵をコピー
COPY docker.pub /root/.ssh/authorized_keys
# 公開鍵を使えるようにする (パーミッション変更など)
RUN chmod 0600 /root/.ssh/authorized_keys

RUN apt-get clean

CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config_user"]
