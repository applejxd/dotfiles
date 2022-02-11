#!/bin/sh

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt-get -y update
echo "$password" | sudo -S apt-get -y upgrade

# Basics
echo "$password" | sudo -S apt-get install -y manpages-ja unzip zsh tree tig

# Clipboard
echo "$password" | sudo -S apt-get install -y xsel

# Filer
echo "$password" | sudo -S apt-get install -y xdg-utils

# RDP
echo "$password" | sudo -S apt-get install -y xrdp

# GUI
# echo "$password" | sudo -S apt-get install -y ubuntu-desktop
echo "$password" | sudo -S apt-get install -y xubuntu-desktop

# docker
echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/docker.sh)

# Java
# echo "$password" | sudo -S apt-get install -y default-jre default-jdk

# LaTeX
# echo "$password" | sudo -S apt-get install -y texlive-full

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    # systemctl
    curl -L -O "https://raw.githubusercontent.com/nullpo-head/wsl-distrod/main/install.sh"
    echo "$password" | sudo -S chmod +x install.sh
    echo "$password" | sudo -S ./install.sh install
    echo "$password" | sudo -S /opt/distrod/bin/distrod enable --start-on-windows-boot
    rm ./install.sh
    
    # SSH settings
    echo "$password" | sudo -S apt-get purge openssh-server
    echo "$password" | sudo -S apt-get install openssh-server
    if [ ! -L /etc/ssh/sshd_config ]; then
        echo "$password" | sudo -S rm /etc/ssh/sshd_config
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/sshd_config /etc/ssh/sshd_config
    fi

    # RDP settings (cf. https://qiita.com/atomyah/items/887a5185ec9a8206c7c4#ubuntu%E3%81%ABxrdp%E3%82%92%E3%82%A4%E3%83%B3%E3%82%B9%E3%83%88%E3%83%BC%E3%83%AB)
    echo "$password" | sudo -S apt-get -y install xfce4 xrdp
    echo "$password" | sudo -S sed -i 's/3389/3390/g' /etc/xrdp/xrdp.ini
    echo "$password" | sudo -S sed -i 's/max_bpp=32/#max_bpp=32\nmax_bpp=128/g' /etc/xrdp/xrdp.ini
    echo "$password" | sudo -S sed -i 's/xserverbpp=24/#xserverbpp=24\nxserverbpp=128/g' /etc/xrdp/xrdp.ini
    echo xfce4-session > ~/.xsession
    echo "$password" | sudo -S sed -i 's|^\(test\s-x\s/etc/X11/Xsession.*\)|# \1|' /etc/xrdp/startwm.sh
    echo "$password" | sudo -S sed -i 's|^\(exec\s/bin/sh.*\)|# \1|' /etc/xrdp/startwm.sh
    grep "startxfce4" /etc/xrdp/startwm.sh
    if [ $? != 0 ]; then
        echo "$password" | sudo -S tee -a /etc/xrdp/startwm.sh <<< "startxfce4"
    fi
    # cf. https://god-support.blogspot.com/2019/11/ubuntu1804-xrdp-authentication-is.html
    echo "$password" | sudo -S tee /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf <<EOF >/dev/null
    polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.color-manager.create-device" ||
    action.id == "org.freedesktop.color-manager.create-profile" ||
    action.id == "org.freedesktop.color-manager.delete-device" ||
    action.id == "org.freedesktop.color-manager.delete-profile" ||
    action.id == "org.freedesktop.color-manager.modify-device" ||
    action.id == "org.freedesktop.color-manager.modify-profile") &&
    subject.isInGroup("{users}")) {
    return polkit.Result.YES;
    }
    });
    EOF

    # WSL config
    if [ ! -L /etc/wsl.conf ]; then
        echo "$password" | sudo -S rm /etc/wsl.conf
        echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
    fi
else
    echo "$password" | sudo -S apt-get install -y chromium-browser  
fi
