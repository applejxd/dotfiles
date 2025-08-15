#!/bin/bash

set -eu

# Common function to get sudo password securely
get_sudo_password() {
    echo "This script requires sudo privileges for system setup." >&2
    read -rs -p "Enter sudo password: " password
    echo >&2  # 改行
    echo "$password"
}

# Get password securely
password=$(get_sudo_password)

# Validate password by testing sudo access
if echo "$password" | sudo -S true 2>/dev/null; then
    echo "Sudo password is valid." >&2
else
    echo "ERROR: Invalid sudo password" >&2
    exit 1
fi

# Refresh
echo "Starting Ubuntu system setup..." >&2
echo "$password" | sudo -S apt-get -y update && sudo -S apt-get -y upgrade

#--------#
# config #
#--------#

# locale 対策
echo "Setting locale to en_US.UTF-8..." >&2
echo "$password" | sudo -S locale-gen en_US.UTF-8

# Keybinding
echo "Setting keybindings..." >&2
gsettings set org.gnome.desktop.interface gtk-key-theme Emacs
# disable emoji shortcut
if gsettings list-schemas | grep -q '^org.freedesktop.ibus.panel.emoji$'; then
    gsettings set org.freedesktop.ibus.panel.emoji hotkey "[]"
fi

# use Caps Lock as ctrl
echo "$password" | sudo -S sed -i "s|XKBOPTIONS.*|XKBOPTIONS=\"ctrl:nocaps\"|" /etc/default/keyboard
echo "$password" | sudo -S systemctl restart console-setup

# Known folders
echo "Setting up known folders..." >&2
LANG=C xdg-user-dirs-update --force
rm -rf デスクトップ ダウンロード テンプレート 公開 ドキュメント ミュージック ピクチャ ビデオ

# Basics
echo "Installing basic packages..." >&2
echo "$password" | sudo -S apt-get install -y \
    vim git unzip tree tig manpages-ja xsel xdg-utils

# Security
echo "Installing security tools..." >&2
echo "$password" | sudo -S apt-get -y install clamav clamav-daemon
echo "$password" | sudo -S systemctl start clamav-daemon.service
echo "$password" | sudo -S systemctl start clamav-freshclam.service

#------#
# mise #
#------#

echo "Setting up mise..." >&2

# Install mise if not present
if [[ ! -e "${HOME}/.local/bin/mise" ]]; then
    curl https://mise.run | sh
fi
# Temporary activation for current script session
eval "$(~/.local/bin/mise activate)"

echo "Installing mise packages..." >&2

# Python
if ! type python >/dev/null 2>&1; then
    echo "Installing Python build dependencies..." >&2
    # see https://github.com/pyenv/pyenv/wiki#suggested-build-environment
    echo "$password" | sudo -S apt-get install -y \
        build-essential libssl-dev zlib1g-dev \
        libbz2-dev libreadline-dev libsqlite3-dev curl git \
        libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
    
    echo "Installing Python via mise..." >&2
    mise install python@latest
fi

# Development tools via mise
echo "Installing development tools via mise..." >&2

# see https://qiita.com/arubaito/items/1fee363154b34663deea
echo "Installing Java (Temurin)..." >&2
mise install java@temurin

echo "Installing development tools..." >&2
mise install ghq@latest
mise install shellcheck@latest
mise install hadolint@latest
mise install java@temurin
mise install ghq@latest
mise install shellcheck@latest
mise install hadolint@latest

#-------#
# tools #
#-------#

# VSCode
# see https://code.visualstudio.com/docs/setup/linux
if ! (type "code" >/dev/null 2>&1); then
    echo "Installing Visual Studio Code..." >&2

    echo "$password" | sudo -S apt-get install -y wget gpg
    wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /tmp/microsoft.gpg
    echo "$password" | sudo -S install -D -o root -g root -m 644 /tmp/microsoft.gpg /usr/share/keyrings/microsoft.gpg
    rm -f /tmp/microsoft.gpg

    echo "$password" | sudo -S apt-get install -y apt-transport-https
    echo "$password" | sudo -S apt update
    echo "$password" | sudo -S apt install -y code
fi

# WSL config
if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    if [ ! -L /etc/wsl.conf ]; then
        echo "Setting up WSL configuration..." >&2

        if [ -f /etc/wsl.conf ]; then
            echo "$password" | sudo -S mv /etc/wsl.conf /etc/wsl.conf.bk
        fi
        echo "$password" | sudo -S ln -s ~/config/wsl.conf /etc/wsl.conf
    fi
fi

# # LaTeX
# # echo "$password" | sudo -S apt-get install -y texlive-full

# # # Environment Modules
# # # https://modules.readthedocs.io/en/latest/INSTALL.html
# # echo "$password" | sudo -S apt-get install -y automake autoconf autopoint tcl-dev tk-dev
# # git clone https://github.com/cea-hpc/modules.git "$HOME"/src/install/modules -b v5.2.0
# # cd "$HOME"/src/install/modules || exit
# # ./configure && make -j"$(nproc)"
# # echo "$password" | sudo -S make install
# # cd "$HOME" || exit

# # # Singularity
# # if ! (type "singularity" >/dev/null 2>&1); then
# #     export VERSION=3.9.5 &&
# #         wget https://github.com/sylabs/singularity/releases/download/v"$VERSION"/singularity-ce-"$VERSION".tar.gz &&
# #         tar -xzf singularity-ce-${VERSION}.tar.gz &&
# #         cd singularity-ce-${VERSION} || exit
# #     ./mconfig && make -C builddir
# #     echo "$password" | sudo -S make -C builddir install
# #     cd .. && rm -rf singularity-ce-*
# # fi

# # # For AtCoder (ac-library)
# # if [[ ! -e /usr/local/include/ac-library ]]; then
# #     git clone https://github.com/atcoder/ac-library.git
# #     echo "$password" | sudo -S cp -r ./ac-library/atcoder /usr/local/include
# #     rm -rf ./ac-library
# # fi
