#!/bin/bash
set -euo pipefail
sudo -v

#--- Detect WSL ---#
if uname -r | grep -qi microsoft || [ -e /proc/sys/fs/binfmt_misc/WSLInterop ]; then
  echo "Detected WSL. Skipping desktop/xrdp setup (use WSLg instead)."
  exit 0
fi

#--- Update & install ---#
sudo apt-get -y update
sudo apt-get install -y --no-install-recommends xfce4 xorgxrdp xrdp

sudo adduser xrdp ssl-cert || true
sudo usermod -aG xrdp "$USER"

#--- colord polkit rule ---#
sudo tee /etc/polkit-1/rules.d/02-allow-colord.rules >/dev/null <<'RULE'
polkit.addRule(function(action, subject) {
  if ((action.id == "org.freedesktop.color-manager.create-device" ||
       action.id == "org.freedesktop.color-manager.create-profile"||
       action.id == "org.freedesktop.color-manager.delete-device" ||
       action.id == "org.freedesktop.color-manager.delete-profile"||
       action.id == "org.freedesktop.color-manager.modify-device" ||
       action.id == "org.freedesktop.color-manager.modify-profile") &&
      subject.isInGroup("xrdp")) {
    return polkit.Result.YES;
  }
});
RULE

#--- Xfce セッション固定 ---#
sudo sed -i 's|^\(test -x /etc/X11/Xsession.*\)|# \1|' /etc/xrdp/startwm.sh
sudo sed -i 's|^\(exec /bin/sh /etc/X11/Xsession.*\)|# \1|' /etc/xrdp/startwm.sh
grep -q 'exec /usr/bin/startxfce4' /etc/xrdp/startwm.sh || \
  echo 'exec /usr/bin/startxfce4' | sudo tee -a /etc/xrdp/startwm.sh >/dev/null

#--- Enable service ---#
sudo systemctl enable --now xrdp
echo "Done. RDP client can connect."
