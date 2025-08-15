#!/bin/bash

# Common function to get sudo password securely
get_sudo_password() {
    if [[ -n "${SUDO_PASSWORD:-}" ]]; then
        echo "Using SUDO_PASSWORD from environment for automation" >&2
        echo "$SUDO_PASSWORD"
    else
        echo "This script requires sudo privileges for system setup." >&2
        read -s -p "Enter sudo password: " password
        echo >&2  # newline
        echo "$password"
    fi
}

# Get password securely
password=$(get_sudo_password)
# Validate password by testing sudo access
if ! echo "$password" | sudo -S true 2>/dev/null; then
    echo "ERROR: Invalid sudo password" >&2
    exit 1
fi

if [ ! -f /tmp/texlive.iso ]; then
  wget https://ftp.jaist.ac.jp/pub/CTAN/systems/texlive/Images/texlive.iso -P /tmp
fi

# mount iso
mkdir "${HOME}/install-tl"
echo "$password" | sudo -S mount -o loop /tmp/texlive.iso "${HOME}/install-tl"

# install
# see https://www.tug.org/texlive/doc/install-tl.html
# see https://chatgpt.com/share/67e15e0c-9b40-8008-b3b5-d6d2f8dee813
cd "${HOME}/install-tl" || exit
./install-tl --profile="${HOME}/src/dotfiles/config/texlive.profile"

# refresh
cd "${HOME}" || exit
echo "$password" | sudo -S umount "${HOME}/instalal-tl"
rm -rf "${HOME}/instalal-tl"
rm /tmp/texlive.iso

# # LaTeX
# echo "$password" | sudo -S apt-get install -y texlive-full
