#!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt-get -y update && apt-get -y upgrade

#-----#
# GUI #
#-----#

# Desktop environments
#echo "$password" | sudo -S apt-get install -y ubuntu-desktop
#echo "$password" | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y xfce4
# Xfce + applications
echo "$password" | sudo -S DEBIAN_FRONTEND=noninteractive apt-get install -y xubuntu-desktop

# RDP
echo "$password" | sudo -S apt-get install -y xrdp

# RDP settings
# https://qiita.com/atomyah/items/887a5185ec9a8206c7c4#ubuntu%E3%81%ABxrdp%E3%82%92%E3%82%A4%E3%83%B3%E3%82%B9%E3%83%88%E3%83%BC%E3%83%AB

# enable side bar
# https://askubuntu.com/questions/1233088/xrdp-desktop-looks-different-when-connecting-remotely
cat <<EOF >~/.xsessionrc
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_CONFIG_DIRS=/etc/xdg/xdg-ubuntu:/etc/xdg
EOF

# to fix Authentication error
# see https://god-support.blogspot.com/2019/11/ubuntu1804-xrdp-authentication-is.html
if [ ! -L /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf ]; then
    if [ -f /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf ]; then
        echo "$password" | sudo -S mv \
            /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf \
            /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf.bk
    fi
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/02-allow-colord.conf /etc/polkit-1/localauthority.conf.d/02-allow-colord.conf
fi

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

echo "$password" | sudo -S systemctl enable xrdp
echo "$password" | sudo -S systemctl start xrdp
