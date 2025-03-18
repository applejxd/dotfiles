##!/bin/bash

if [ $# -eq 0 ]; then
    # Save Password
    read -rsp "Password: " password
else
    password=$1
fi

# Refresh
echo "$password" | sudo -S apt-get -y update && apt-get -y upgrade

#--------#
# config #
#--------#

# locale 対策
echo "$password" | sudo -S locale-gen en_US.UTF-8

# Keybinding
gsettings set org.gnome.desktop.interface gtk-key-theme Emacs
# di# disable emoji shortcut
gsettings set org.freedesktop.ibus.panel.emoji hotkey "[]"
# use caps lock as ctrl
 "$password" | sudo -S sed -i "s|XKBOPTIONS.*|XKBOPTIONS=\"ctrl:nocaps\"|" /etc/default/keyboard
echo "$password" | sudo -S systemctl restart console-setup

# Known folders
LANG=C xdg-user-dirs-update --force
rm -rf デスクトップ ダウンロード テンプレート 公開 ドキュメント ミュージック ピクチャ ビデオ

# Basics
echo "$password" | sudo -S apt-get install -y \
    vim git unzip tree tig manpages-ja xsel xdg-utils

# Security
echo "$password" | sudo -S apt install clamav clamav-daemon
echo "$password" | sudo -S systemctl start clamav-daemon.service
echo "$password" | sudo -S systemctl start clamav-freshclam.service

#------#
# mise #
#------#

if [[ ! -e "$HOME/.local/bin/mise" ]]; then
    curl https://mise.run | sh
fi
eval "$(~/.local/bin/mise activate)"
export PATH="$HOME/.local/share/mise/shims:$PATH"

if ! type ruby >/dev/null 2>&1; then
    # see https://github.com/rbenv/ruby-build/wiki#ubuntudebianmint
    echo "$password" | sudo -S apt-get install -y \
        autoconf patch build-essential rustc libssl-dev libyaml-dev libreadline6-dev \
        zlib1g-dev libgmp-dev libncurses5-dev libffi-dev libgdbm6 libgdbm-dev libdb-dev \
        uuid-dev
    # for homesick
    mise use --global -y ruby@2.7.8
fi

if ! type python >/dev/null 2>&1; then
    # see https://github.com/pyenv/pyenv/wiki#suggested-build-environment
    echo "$password" | sudo -S apt-get install -y \
        build-essential libssl-dev zlib1g-dev \
        libbz2-dev libreadline-dev libsqlite3-dev curl git \
        libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
    mise use --global -y python@latest
fi

# https://qiita.com/arubaito/items/1fee363154b34663deea
mise use --global -y java@temurin

mise use --global -y ghq
mise use --global -y shellcheck
mise use --global -y hadolint

#-------#
# tools #
#-------#

# VSCode
# see https://code.visualstudio.com/docs/setup/linux
if ! (type "code" >/dev/null 2>&1); then
    echo "$password" | sudo -S apt-get install -y wget gpg
    wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor >packages.microsoft.gpg
    echo "$password" | sudo -S install -D -o root -g root -m 644 packages.microsoft.gpg /etc/apt/keyrings/packages.microsoft.gpg
    {
        echo "$password"
        echo "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main"
    } | sudo -k -S tee /etc/apt/sources.list.d/vscode.list >/dev/null
    rm -f packages.microsoft.gpg

    echo "$password" | sudo -S apt-get install -y apt-transport-https
    echo "$password" | sudo -S apt update
    echo "$password" | sudo -S apt install -y code
fi

# # Docker
# # shellcheck source=/dev/null
# echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu/docker.sh)

# # Environment Modules
# # https://modules.readthedocs.io/en/latest/INSTALL.html
# echo "$password" | sudo -S apt-get install -y automake autoconf autopoint tcl-dev tk-dev
# git clone https://github.com/cea-hpc/modules.git "$HOME"/src/install/modules -b v5.2.0
# cd "$HOME"/src/install/modules || exit
# ./configure && make -j"$(nproc)"
# echo "$password" | sudo -S make install
# cd "$HOME" || exit

# # CUDA
# if (type "nvidia-smi" >/dev/null 2>&1); then
#     # shellcheck source=/dev/null
#     echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu/cuda.sh)
# fi

# # Singularity
# if ! (type "singularity" >/dev/null 2>&1); then
#     export VERSION=3.9.5 &&
#         wget https://github.com/sylabs/singularity/releases/download/v"$VERSION"/singularity-ce-"$VERSION".tar.gz &&
#         tar -xzf singularity-ce-${VERSION}.tar.gz &&
#         cd singularity-ce-${VERSION} || exit
#     ./mconfig && make -C builddir
#     echo "$password" | sudo -S make -C builddir install
#     cd .. && rm -rf singularity-ce-*
# fi

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

    # if [ ! -L /opt/distrod/conf/tcp4_ports ]; then
    #     echo "$password" | sudo -S rm /opt/distrod/conf/tcp4_ports
    #     echo "$password" | sudo -S ln -s "$HOME"/.homesick/repos/dotfiles/config/tcp4_ports /opt/distrod/conf/tcp4_ports
    # fi
    # # Be careful about anti-virus softwares (will be detect portproxy.exe as virus)
    # echo "$password" | sudo -S systemctl enable --now portproxy.service
fi

# # For AtCoder (ac-library)
# if [[ ! -e /usr/local/include/ac-library ]]; then
#     git clone https://github.com/atcoder/ac-library.git
#     echo "$password" | sudo -S cp -r ./ac-library/atcoder /usr/local/include
#     rm -rf ./ac-library
# fi
