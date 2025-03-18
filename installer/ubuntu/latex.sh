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
cd "${HOME}/instalal-tl" || exit
echo "$password" | sudo -S ./install-tl

# refresh
cd "${HOME}" || exit
echo "$password" | sudo -S umount "${HOME}/instalal-tl"
rm -rf "${HOME}/instalal-tl"
rm /tmp/texlive.iso
