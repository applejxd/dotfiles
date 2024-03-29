#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt-get -y update && apt-get -y upgrade

# Basics
echo "$password" | sudo -S apt-get install -y manpages-ja unzip zsh tree tig

# Clipboard
echo "$password" | sudo -S apt-get install -y xsel

# Filer
echo "$password" | sudo -S apt-get install -y xdg-utils

# docker
# shellcheck source=/dev/null
echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu/docker.sh)

# Environment Modules
echo "$password" | sudo -S apt-get install -y tcl8.6-dev
git clone https://github.com/cea-hpc/modules.git "$HOME"/src/install/modules -b v5.2.0
cd "$HOME"/src/install/modules || exit
./configure && make -j"$(nproc)"
echo "$password" | sudo -S make install
cd "$HOME" || exit

# CUDA
if (type "nvidia-smi" >/dev/null 2>&1); then
    # shellcheck source=/dev/null
    echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu/cuda.sh)
fi

# asdf
if [[ ! -e ~/.asdf ]]; then
    git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.11.3
fi
# shellcheck source=/dev/null
source "$HOME/.asdf/asdf.sh"
if [[ ! -e "$HOME"/.asdf/ruby ]]; then
    echo "$password" | sudo -S apt-get install -y \
        autoconf bison build-essential \
        libssl-dev libyaml-dev libreadline6-dev zlib1g-dev libncurses5-dev \
        libffi-dev libgdbm6 libgdbm-dev libdb-dev
    asdf plugin add ruby https://github.com/asdf-vm/asdf-ruby.git
    # asdf list all ruby
    asdf install ruby 2.7.8
    asdf global ruby 2.7.8
fi
if [[ ! -e "$HOME"/.asdf/python ]]; then
    asdf plugin add python
    # asdf list all python
    asdf install python miniforge3-latest
    asdf global python miniforge3-latest
fi
if [[ ! -e "$HOME"/.asdf/nodejs ]]; then
    asdf plugin add nodejs https://github.com/asdf-vm/asdf-nodejs.git
fi

# Go
echo "$password" | sudo -S bash -c "\
    add-apt-repository -y ppa:longsleep/golang-backports && \
    apt-get update && \
    apt-get install -y golang"
export GOPATH=$HOME/.go

# ghq
go install github.com/x-motemen/ghq@latest

# Singularity
if ! (type "singularity" >/dev/null 2>&1); then
    export VERSION=3.9.5 &&
        wget https://github.com/sylabs/singularity/releases/download/v"$VERSION"/singularity-ce-"$VERSION".tar.gz &&
        tar -xzf singularity-ce-${VERSION}.tar.gz &&
        cd singularity-ce-${VERSION} || exit
    ./mconfig && make -C builddir
    echo "$password" | sudo -S make -C builddir install
    cd .. && rm -rf singularity-ce-*
fi

# Linter
echo "$password" | sudo -S apt-get install -y shellcheck
echo "$password" | sudo -S wget https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64 -O /usr/local/bin
echo "$password" | sudo -S chmod 777 /usr/loca/bin/hadolint

# Java
# echo "$password" | sudo -S apt-get install -y default-jre default-jdk

# LaTeX
# echo "$password" | sudo -S apt-get install -y texlive-full

if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    # WSL config
    if [ ! -L /etc/wsl.conf ]; then
        if [ -f /etc/wsl.conf ]; then
            echo "$password" | sudo -S mv /etc/wsl.conf /etc/wsl.conf.bk
        fi
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
    fi
    if [ ! -L /opt/distrod/conf/tcp4_ports ]; then
        echo "$password" | sudo -S rm /opt/distrod/conf/tcp4_ports
        echo "$password" | sudo -S ln -s "$HOME"/.homesick/repos/dotfiles/config/tcp4_ports /opt/distrod/conf/tcp4_ports
    fi
    # Be careful about anti-virus softwares (will be detect portproxy.exe as virus)
    echo "$password" | sudo -S systemctl enable --now portproxy.service
fi

# For AtCoder (ac-library)
if [[ ! -e /usr/local/include/ac-library ]]; then
    git clone https://github.com/atcoder/ac-library.git
    echo "$password" | sudo -S cp -r ./ac-library/atcoder /usr/local/include
    rm -rf ./ac-library
fi

#-----#
# SSH #
#-----#

echo "$password" | sudo -S bash -c "\
    apt-get purge -y openssh-server && \
    apt-get install -y openssh-server"
if [ ! -L /etc/ssh/sshd_config ]; then
    if [ -f /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S mv /etc/ssh/sshd_config /etc/ssh/sshd_config.bk
    fi
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/sshd_config /etc/ssh/sshd_config
fi

#-----#
# GUI #
#-----#

# GUI
#echo "$password" | sudo -S apt-get install -y ubuntu-desktop
#echo "$password" | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y xfce4
# Xfce + applications
echo "$password" | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y xubuntu-desktop

# RDP
echo "$password" | sudo -S apt-get install -y xrdp

# RDP settings
# cf. https://qiita.com/atomyah/items/887a5185ec9a8206c7c4#ubuntu%E3%81%ABxrdp%E3%82%92%E3%82%A4%E3%83%B3%E3%82%B9%E3%83%88%E3%83%BC%E3%83%AB

# xrdp.ini configuration
echo "$password" | sudo -S bash -c "\
    sed -i 's/3389/53389/g' /etc/xrdp/xrdp.ini && \
    sed -i 's/max_bpp=32/#max_bpp=32\nmax_bpp=128/g' /etc/xrdp/xrdp.ini && \
    sed -i 's/xserverbpp=24/#xserverbpp=24\nxserverbpp=128/g' /etc/xrdp/xrdp.ini"
echo xfce4-session >~/.xsession

# startwm.sh configuration
echo "$password" | sudo -S sed -i 's|^\(test\s-x\s/etc/X11/Xsession.*\)|# \1|' /etc/xrdp/startwm.sh
echo "$password" | sudo -S sed -i 's|^\(exec\s/bin/sh.*\)|# \1|' /etc/xrdp/startwm.sh
if (! grep "startxfce4" /etc/xrdp/startwm.sh >/dev/null 2>&1); then
    {
        echo "$password"
        echo "startxfce4"
    } | sudo -S -k tee -a /etc/xrdp/startwm.sh
fi

# to fix Authentication error
# cf. https://god-support.blogspot.com/2019/11/ubuntu1804-xrdp-authentication-is.html
if [ ! -L /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf ]; then
    if [ -f /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf ]; then
        echo "$password" | sudo -S mv \
            /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf \
            /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf.bk
    fi
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/02-allow-colord.conf /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf
fi

echo "$password" | sudo -S systemctl enable xrdp
echo "$password" | sudo -S systemctl start xrdp
