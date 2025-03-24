#!/bin/bash

if [ $# -eq 0 ]; then
  # Save Password
  read -rsp "Password: " password
else
  password=$1
fi

wget https://ftp.jaist.ac.jp/pub/CTAN/systems/texlive/Images/texlive.iso -P /tmp

# mount iso
mkdir "${HOME}/instalal-tl"
echo "$password" | sudo -S mount -o loop /tmp/texlive.iso "${HOME}/instalal-tl"

# install
# see https://www.tug.org/texlive/doc/install-tl.html
# see https://chatgpt.com/share/67e15e0c-9b40-8008-b3b5-d6d2f8dee813
cd "${HOME}/instalal-tl" || exit
./install-tl -profile "${HOME}/src/dotfiles/config/texlive.profile"

# refresh
cd "${HOME}" || exit
echo "$password" | sudo -S umount "${HOME}/instalal-tl"
rm -rf "${HOME}/instalal-tl"
rm /tmp/texlive.iso
