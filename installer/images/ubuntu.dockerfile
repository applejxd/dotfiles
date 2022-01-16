FROM ubuntu:20.04

WORKDIR /root

RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install -y git

# Install anyenv
ENV HOME /root
ENV ANYENV_HOME $HOME/.anyenv
ENV ANYENV_ENV  $ANYENV_HOME/envs
RUN git clone https://github.com/anyenv/anyenv ~/.anyenv
ENV PATH $ANYENV_HOME/bin:$PATH
RUN yes | anyenv install --init

RUN apt-get install -y curl build-essential libssl-dev zlib1g-dev
RUN anyenv install rbenv
ENV PATH /root/.anyenv/envs/rbenv/bin:$PATH
ENV PATH /root/.anyenv/envs/rbenv/shims:$PATH
ENV RBENV_ROOT $ANYENV/rbenv

# RUN rbenv install 2.7.0 
# RUN rbenv rehash 
# RUN rbenv global 3.7.0

# RUN gem install homesick
# RUN homesick clone applejxd/dotfiles
# RUN yes Y | homesick link dotfiles
