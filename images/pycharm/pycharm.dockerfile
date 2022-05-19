# RAPIDS is compatible with cuda<=11.5
FROM nvidia/cuda:11.5.2-cudnn8-devel-ubuntu20.04

WORKDIR /root
RUN apt-get update && apt-get upgrade -y

#--------------#
# Localization #
#--------------#

RUN DEBIAN_FRONTEND="noninteractive" apt-get install -y tzdata
ENV TZ=Asia/Tokyo

RUN apt-get install -y locales fonts-takao && locale-gen ja_JP.UTF-8
ENV LANG=ja_JP.UTF-8
ENV LANGUAGE=ja_JP:ja
ENV LC_ALL=ja_JP.UTF-8
RUN localedef -f UTF-8 -i ja_JP ja_JP.utf8

#-------#
# pyenv #
#-------#

# cf. https://gist.github.com/mistymagich/fa9f0f4f05e0865e191e

RUN apt-get install -y git curl
RUN git clone https://github.com/anyenv/anyenv /root/.anyenv

ENV HOME /root
ENV ANYENV_HOME $HOME/.anyenv
ENV ANYENV_ENV  $ANYENV_HOME/envs
ENV PATH $ANYENV_HOME/bin:$PATH

RUN yes | anyenv install --init

RUN anyenv install pyenv
ENV PATH $ANYENV_ENV/pyenv/bin:$ANYENV_ENV/pyenv/shims:$PATH
ENV PYENV_ROOT $ANYENV_ENV/pyenv

RUN pyenv install miniforge3
RUN pyenv global miniforge3

#----------#
# Anaconda #
#----------#

# channels は conda-forge のみ
RUN conda update -y conda
RUN conda update -y --all

# cf. https://rapids.ai/start.html
RUN conda create -n pycharm -c rapidsai -c nvidia -c pytorch -c conda-forge \
python=3.9 cudatoolkit=11.3 rapids=22.04 dask-sql pytorch torchvision torchaudio

# Activate environment
ENV CONDA_DEFAULT_ENV pycharm

# Switch default environment
RUN echo "conda activate pycharm" >> /root/.bashrc
ENV PATH /opt/conda/envs/pycharm/bin:$PATH

# cf. https://pytorch.org/get-started/locally/
RUN conda install -y pip
RUN pip install --upgrade pip
RUN pip install --upgrade tensorflow

RUN conda install -y numpy pandas dask scipy scikit-learn matplotlib
RUN conda install -y lightgbm hyperopt

#-----#
# SSH #
#-----#

RUN apt-get install -y ssh
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

RUN apt-get clean && apt-get autoremove

CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config_user"]
