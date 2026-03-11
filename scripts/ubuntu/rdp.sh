#!/bin/bash
set -euo pipefail
sudo -v

#--- Detect WSL ---#
if uname -r | grep -qi microsoft || [ -e /proc/sys/fs/binfmt_misc/WSLInterop ]; then
  echo "Detected WSL. Skipping desktop/xrdp setup (use WSLg instead)."
  exit 0
fi

#--- Update & install ---#
# see: https://qiita.com/atomyah/items/887a5185ec9a8206c7c4#ubuntu%E3%81%ABxrdp%E3%82%92%E3%82%A4%E3%83%B3%E3%82%B9%E3%83%88%E3%83%BC%E3%83%AB
sudo apt-get -y update
sudo apt-get install -y --no-install-recommends xfce4 xorgxrdp xrdp

sudo adduser xrdp ssl-cert || true
sudo usermod -aG xrdp "$USER"

#--- colord polkit rule ---#
# see: https://god-support.blogspot.com/2019/11/ubuntu1804-xrdp-authentication-is.html
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

# #--- /etc/xrdp/startwm.sh に環境変数をシバン直後へ、重複なく挿入 ---#
# # see https://taktak.jp/2025/02/22/4524/
# #   - 既に同一行がある場合は何もしません
# #   - 「先頭」= シバン直後（1行目の後ろ）
# if ! sudo grep -qF 'export GNOME_SHELL_SESSION_MODE=ubuntu' /etc/xrdp/startwm.sh; then
#   # 順序を保つために XDG を先に挿入 → 続けて GNOME_SHELL を挿入（sed の 1a は逆順になるため）
#   if ! sudo grep -qF 'export XDG_CURRENT_DESKTOP=ubuntu:GNOME' /etc/xrdp/startwm.sh; then
#     sudo sed -i '1a export XDG_CURRENT_DESKTOP=ubuntu:GNOME' /etc/xrdp/startwm.sh
#   fi
#   sudo sed -i '1a export GNOME_SHELL_SESSION_MODE=ubuntu' /etc/xrdp/startwm.sh
# else
#   # GNOME_SHELL の行はあるが XDG が無い場合にだけ XDG を追加
#   if ! sudo grep -qF 'export XDG_CURRENT_DESKTOP=ubuntu:GNOME' /etc/xrdp/startwm.sh; then
#     sudo sed -i '1a export XDG_CURRENT_DESKTOP=ubuntu:GNOME' /etc/xrdp/startwm.sh
#   fi
# fi

#--- Xfce セッション固定 ---#
# see: https://askubuntu.com/questions/1233088/xrdp-desktop-looks-different-when-connecting-remotely
sudo sed -i 's|^\(test -x /etc/X11/Xsession.*\)|# \1|' /etc/xrdp/startwm.sh
sudo sed -i 's|^\(exec /bin/sh /etc/X11/Xsession.*\)|# \1|' /etc/xrdp/startwm.sh
grep -q 'exec /usr/bin/startxfce4' /etc/xrdp/startwm.sh || \
  echo 'exec /usr/bin/startxfce4' | sudo tee -a /etc/xrdp/startwm.sh >/dev/null

#--- Enable service ---#
sudo systemctl enable --now xrdp
echo "Done. RDP client can connect."
