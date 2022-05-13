# FROM ubuntu:20.04
FROM nvcr.io/nvidia/pytorch:22.04-py3
WORKDIR /root

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

#----------#
# Anaconda #
#----------#

RUN conda update conda
RUN cocnda update --all

RUN conda install pip
RUN pip install --upgrade pip

RUN pip install --upgrade tensorflow
#RUN conda install pytorch torchvision cudatoolkit=10.1 -c pytorch

#-----#
# SSH #
#-----#

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
    # Need to use X11 Forwarding via direct SSH
    # cf. https://blog.n-z.jp/blog/2018-07-27-sshd-in-docker.html
    echo 'AddressFamily inet'; \
  ) > /etc/ssh/sshd_config_user \
  && mkdir /run/sshd

# SSH login fix. Otherwise user is kicked off after login
# cf. https://qiita.com/YumaInaura/items/7509061e4b27e03ea538
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

# 手元の公開鍵をコピー
COPY docker.pub /root/.ssh/authorized_keys
# 公開鍵を使えるようにする (パーミッション変更など)
RUN chmod 0600 /root/.ssh/authorized_keys

# .bashrc を読み込み
RUN echo "if [ -f ~/.bashrc ]; then . ~/.bashrc; fi" >>~/.bash_profile
# 環境変数の書き込み
RUN echo "PATH=${PATH}" >> ~/.bashrc

#-----------------#
# Post processing #
#-----------------#

# for X11 forwarding debugging
RUN apt-get install -y x11-apps

RUN apt-get clean && apt-get autoremove

EXPOSE 2222
CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config_user"]
