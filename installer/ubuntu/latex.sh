#!/bin/bash

sudo -v

if [ ! -f /tmp/texlive.iso ]; then
  wget https://ftp.jaist.ac.jp/pub/CTAN/systems/texlive/Images/texlive.iso -P /tmp
fi

# mount iso
mkdir "${HOME}/install-tl"
sudo mount -o loop /tmp/texlive.iso "${HOME}/install-tl"

# install
# see https://www.tug.org/texlive/doc/install-tl.html
# see https://chatgpt.com/share/67e15e0c-9b40-8008-b3b5-d6d2f8dee813
cd "${HOME}/install-tl" || exit
./install-tl --profile="${HOME}/.local/share/chezmoi/config/unix/texlive.profile"

# refresh
cd "${HOME}" || exit
sudo umount "${HOME}/instalal-tl"
rm -rf "${HOME}/instalal-tl"
rm /tmp/texlive.iso

# # LaTeX
# sudo apt-get install -y texlive-full
