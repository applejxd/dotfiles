#!/usr/bin/env bash
set -euo pipefail

# Rootless Docker を導入する。NVIDIA GPU があれば nvidia-container-toolkit.sh で GPU も設定する。
# rootful が必要なときだけ DOCKER_ROOTFUL=1 を付ける。

#=== WSL + Docker Desktop の場合は何もしない ==========================#
# 参考: https://docs.docker.jp/desktop/windows/wsl.html#wsl-2-docker
DD_SOCK="/mnt/wsl/docker-desktop/run/guest-services/docker.sock"
if [[ "$(uname -r)" =~ microsoft ]] && [[ -S "$DD_SOCK" ]]; then
  echo "WSL上で Docker Desktop を検出しました。次を設定してください:"
  echo "  export DOCKER_HOST=unix://$DD_SOCK"
  exit 0
fi

#=== sudo 認証キャッシュ =================================================#
sudo -v
sudo apt-get update -y -qq

#=== Docker が未インストールなら導入 ====================================#
# 参考: https://docs.docker.com/engine/install/ubuntu/#install-using-the-convenience-script
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo -E sh
fi

#=== rootful を選んだ場合 ==============================================#
if [[ "${DOCKER_ROOTFUL:-0}" == "1" ]]; then
  if ! id -nG "$USER" | grep -qw docker; then
    sudo gpasswd -a "$USER" docker
    echo "[info] ユーザーを docker グループに追加しました。再ログインか newgrp docker が必要です。"
  fi
  sudo systemctl enable --now docker.service
  echo "[完了] Rootful Docker サービスを有効化しました。"
  exit 0
fi

#=== Rootless ==========================================================#
# 参考: https://docs.docker.com/engine/security/rootless/
if [[ ! -d /run/systemd/system ]]; then
  echo "[エラー] systemd が動いていません。rootless は systemd のユーザーサービスで常駐させます。" >&2
  echo "        WSL なら /etc/wsl.conf の [boot] systemd=true を有効にして wsl --shutdown してください。" >&2
  exit 1
fi

# overlay2 はカーネル 5.11 以降で非 root から使えるため fuse-overlayfs は不要
sudo apt-get install -y -qq uidmap dbus-user-session slirp4netns docker-ce-rootless-extras

# rootful を止める (rootless と同時に動かさない)
sudo systemctl disable --now docker.service docker.socket >/dev/null 2>&1 || true

# Ubuntu 24.04 以降は非特権 userns が AppArmor で制限され、rootlesskit が起動できない
# 参考: https://docs.docker.com/engine/security/rootless/#distribution-specific-hint
if [[ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" == "1" ]]; then
  PROFILE=/etc/apparmor.d/usr.bin.rootlesskit
  if [[ ! -e "$PROFILE" ]]; then
    sudo tee "$PROFILE" >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

/usr/bin/rootlesskit flags=(unconfined) {
  userns,

  include if exists <local/usr.bin.rootlesskit>
}
EOF
    sudo systemctl restart apparmor.service
  fi
fi

if ! command -v dockerd-rootless-setuptool.sh >/dev/null 2>&1; then
  echo "[エラー] dockerd-rootless-setuptool.sh が見つかりません (docker-ce-rootless-extras)。" >&2
  exit 1
fi

# 起動中の rootful が使うソケットと DOCKER_HOST が衝突すると setuptool が失敗する
unset DOCKER_HOST
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
dockerd-rootless-setuptool.sh install
systemctl --user enable --now docker.service
# ブート時 (ログイン前) から自動起動
sudo loginctl enable-linger "$USER"

echo "[完了] Rootless Docker を有効化しました。"
echo "setuptool が docker context 'rootless' を作成済みです。context を使わないなら次を追記してください:"
echo "  export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock"

#=== GPU ===============================================================#
if command -v nvidia-smi >/dev/null 2>&1; then
  bash "$(dirname "${BASH_SOURCE[0]}")/nvidia-container-toolkit.sh"
fi
