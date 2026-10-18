#!/bin/bash
# sandbox ディストロの中で root として実行する。create.ps1 が呼ぶ。
# usage: setup.sh <user> <tailnet-host> <memory> <tailscale|skip>
# see docs/spec/wsl-sandbox.md
set -euo pipefail

user=$1
host=$2
memory=$3
tailscale=$4
src=$(cd "$(dirname "$0")" && pwd)

export DEBIAN_FRONTEND=noninteractive
# shellcheck disable=SC1091
. /etc/os-release

apt-get update
apt-get install -y ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  >/etc/apt/sources.list.d/docker.list

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
  gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    >/etc/apt/sources.list.d/nvidia-container-toolkit.list

packages=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit)
if [ "$tailscale" = tailscale ]; then
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg" \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.tailscale-keyring.list" \
    -o /etc/apt/sources.list.d/tailscale.list
  packages+=(tailscale)
fi
apt-get update
apt-get install -y "${packages[@]}"

# 作業ユーザー (パスワードなし。docker グループ)
id "$user" >/dev/null 2>&1 || useradd -m -s /bin/bash "$user"
usermod -aG docker "$user"
install -d -o "$user" -g "$user" "/home/$user/work"

nvidia-ctk runtime configure --runtime=docker
systemctl enable --now docker
systemctl restart docker
if [ "$tailscale" = tailscale ]; then
  systemctl enable --now tailscaled
fi

# ラッパーと agent 向けガイド。@...@ を値に置き換えて配置する
render() {
  sed -e "s#@USER@#$user#g" -e "s#@HOST@#$host#g" -e "s#@MEMORY@#$memory#g" "$1"
}
render "$src/sbx-run.sh" >/usr/local/bin/sbx-run
render "$src/sbx-help.sh" >/usr/local/bin/sbx-help
chmod 0755 /usr/local/bin/sbx-run /usr/local/bin/sbx-help
render "$src/sbx-AGENTS.md" >"/home/$user/AGENTS.md"
chown "$user:$user" "/home/$user/AGENTS.md"

echo "setup.sh: 完了"
