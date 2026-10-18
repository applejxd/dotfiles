#!/bin/bash

set -eu

sudo -v

if [ ! -f /tmp/texlive.iso ]; then
  wget https://ftp.jaist.ac.jp/pub/CTAN/systems/texlive/Images/texlive.iso -P /tmp
fi

# mount iso (専用の一時ディレクトリ。失敗時も trap でアンマウントして削除する)
mount_dir=$(mktemp -d "${HOME}/install-tl.XXXXXX")
cleanup() {
  cd "${HOME}" || true
  if mountpoint -q "${mount_dir}"; then
    sudo umount "${mount_dir}"
  fi
  rmdir "${mount_dir}" 2>/dev/null || true
}
trap cleanup EXIT
sudo mount -o loop /tmp/texlive.iso "${mount_dir}"

# install
# see https://www.tug.org/texlive/doc/install-tl.html
# see https://chatgpt.com/share/67e15e0c-9b40-8008-b3b5-d6d2f8dee813
cd "${mount_dir}"
./install-tl --profile="${HOME}/.local/share/chezmoi/config/unix/texlive.profile"

# refresh
cleanup
rm /tmp/texlive.iso

# # LaTeX
# sudo apt-get install -y texlive-full
