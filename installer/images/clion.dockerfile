# CLion remote docker environment (How to build docker container, run and stop it)
#
# Build and run:
#   docker build -t clion/remote-cpp-env:0.5 -f Dockerfile.remote-cpp-env .
#   docker run -d --cap-add sys_ptrace -p127.0.0.1:2222:22 --name clion_remote_env clion/remote-cpp-env:0.5
#   ssh-keygen -f "$HOME/.ssh/known_hosts" -R "[localhost]:2222"
#
# stop:
#   docker stop clion_remote_env
# 
# ssh credentials (test user):
#   user@password 

FROM ubuntu:20.04

RUN DEBIAN_FRONTEND="noninteractive" apt-get update && apt-get -y install tzdata

RUN apt-get update \
  && apt-get install -y ssh \
      build-essential \
      gcc \
      g++ \
      gdb \
      clang \
      make \
      ninja-build \
      cmake \
      autoconf \
      automake \
      locales-all \
      dos2unix \
      rsync \
      tar \
      python \
  && apt-get clean

RUN apt-get install -y sudo git vim x11-apps

RUN ( \
    echo 'LogLevel DEBUG2'; \
    echo 'PermitRootLogin yes'; \
    echo 'PasswordAuthentication no'; \
    echo 'RSAAuthentication yes'; \
    echo 'PubkeyAuthentication yes'; \
    echo 'AuthorizedKeysFile .ssh/authorized_keys'; \
    echo 'Subsystem sftp /usr/lib/openssh/sftp-server'; \
    echo 'Port 22'; \
    echo 'X11Forwarding yes'; \
  ) > /etc/ssh/sshd_config_test_clion \
  && mkdir /run/sshd

# cf. https://qiita.com/YumaInaura/items/7509061e4b27e03ea538
# SSH login fix. Otherwise user is kicked off after login
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

# Dockerfile と同ディレクトリの公開鍵をコピー
COPY docker.pub /root/authorized_keys

RUN useradd -m user \
  && yes password | passwd user

RUN usermod -s /bin/bash user

# 公開鍵を使えるようにする (パーミッション変更など)
CMD mkdir ~/.ssh && \
    mv ~/authorized_keys ~/.ssh/authorized_keys && \
    chmod 0600 ~/.ssh/authorized_keys &&  \
    # 最後に ssh を起動
    /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config_test_clion
