#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt-get -y update && apt-get -y upgrade

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]] && (! systemctl >/dev/null 2>&1); then
    # systemctl
    curl -L -O "https://raw.githubusercontent.com/nullpo-head/wsl-distrod/main/install.sh"
    echo "$password" | sudo -S bash -c "\
        chmod +x install.sh && \
        ./install.sh install && \
        /opt/distrod/bin/distrod enable --start-on-windows-boot"
    rm ./install.sh
fi

# Basics
echo "$password" | sudo -S apt-get install -y manpages-ja unzip zsh tree tig

# Clipboard
echo "$password" | sudo -S apt-get install -y xsel

# Filer
echo "$password" | sudo -S apt-get install -y xdg-utils

# GUI
# echo "$password" | sudo -S apt-get install -y ubuntu-desktop
echo "$password" | sudo -S apt-get install -y xubuntu-desktop

# docker
echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/docker.sh)

# Go
echo $password | sudo -S bash -c "\
    add-apt-repository ppa:longsleep/golang-backports && \
    apt-get update && \
    apt-get install golang"
go install github.com/x-motemen/ghq@latest

# ghq
go install github.com/x-motemen/ghq@latest

# Singularity
export VERSION=3.9.5 && \
    wget https://github.com/sylabs/singularity/releases/download/v${VERSION}/singularity-ce-${VERSION}.tar.gz && \
    tar -xzf singularity-ce-${VERSION}.tar.gz && \
    cd singularity-ce-${VERSION}
./mconfig && \
    make -C builddir && \
    sudo make -C builddir install

# Java
# echo "$password" | sudo -S apt-get install -y default-jre default-jdk

# LaTeX
# echo "$password" | sudo -S apt-get install -y texlive-full

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # WSL config
    if [ ! -L /etc/wsl.conf ]; then
        echo "$password" | sudo -S rm /etc/wsl.conf
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
    fi
fi

#######
# SSH #
#######

echo "$password" | sudo -S apt-get purge openssh-server && apt-get install openssh-server
if [ ! -L /etc/ssh/sshd_config ]; then
    if [ ! -f /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S rm /etc/ssh/sshd_config
    fi
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/sshd_config /etc/ssh/sshd_config
fi

#######
# GUI #
#######

# RDP
echo "$password" | sudo -S apt-get install -y xfce4 xrdp

# RDP settings
# cf. https://qiita.com/atomyah/items/887a5185ec9a8206c7c4#ubuntu%E3%81%ABxrdp%E3%82%92%E3%82%A4%E3%83%B3%E3%82%B9%E3%83%88%E3%83%BC%E3%83%AB

# xrdp.ini configuration
echo "$password" | sudo -S bash -c "\
    sed -i 's/3389/3390/g' /etc/xrdp/xrdp.ini && \
    sed -i 's/max_bpp=32/#max_bpp=32\nmax_bpp=128/g' /etc/xrdp/xrdp.ini && \
    sed -i 's/xserverbpp=24/#xserverbpp=24\nxserverbpp=128/g' /etc/xrdp/xrdp.ini"
echo xfce4-session > ~/.xsession

# startwm.sh configuration
echo "$password" | sudo -S sed -i 's|^\(test\s-x\s/etc/X11/Xsession.*\)|# \1|' /etc/xrdp/startwm.sh
echo "$password" | sudo -S sed -i 's|^\(exec\s/bin/sh.*\)|# \1|' /etc/xrdp/startwm.sh
if (! grep "startxfce4" /etc/xrdp/startwm.sh >/dev/null 2>&1); then
    echo "$password" | sudo -S tee -a /etc/xrdp/startwm.sh <<< "startxfce4"
fi

# to fix Authentication error
# cf. https://god-support.blogspot.com/2019/11/ubuntu1804-xrdp-authentication-is.html
if [ ! -L /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf ]; then
        if [ ! -f /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S rm /etc/ssh/sshd_config
    fi
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/02-allow-colord.conf /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf
fi
   
echo "$password" | sudo -S apt-get install -y chromium-browser  
