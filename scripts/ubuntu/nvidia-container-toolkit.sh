#!/usr/bin/env bash
set -euo pipefail

# nvidia-container-toolkit を導入し、Docker (rootless / rootful) から GPU を使えるようにする。
# ホスト側の NVIDIA ドライバ (WSL は Windows 側) と Docker は導入済みであること。
# 参考: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
#       https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html#rootless-mode

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[エラー] nvidia-smi が見つかりません。ホストの NVIDIA ドライバを先に導入してください。" >&2
  exit 1
fi

sudo -v

#=== toolkit が未導入なら apt リポジトリ経由で導入 =======================#
if ! command -v nvidia-ctk >/dev/null 2>&1; then
  KEYRING=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
    sudo gpg --batch --yes --dearmor -o "$KEYRING"
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
    sed "s#deb https://#deb [signed-by=$KEYRING] https://#g" |
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  sudo apt-get update -y -qq
  sudo apt-get install -y -qq nvidia-container-toolkit
fi

#=== Docker に nvidia runtime を登録 ====================================#
if systemctl --user is-enabled docker.service >/dev/null 2>&1; then
  # rootless: ユーザーの daemon.json に書き、cgroup 操作を無効化する
  nvidia-ctk runtime configure --runtime=docker \
    --config="${XDG_CONFIG_HOME:-$HOME/.config}/docker/daemon.json"
  sudo nvidia-ctk config --set nvidia-container-cli.no-cgroups --in-place
  systemctl --user restart docker.service
else
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker.service
fi

#=== 動作確認 ===========================================================#
docker run --rm --gpus all ubuntu:24.04 nvidia-smi -L
