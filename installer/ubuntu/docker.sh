#!/usr/bin/env bash
set -euo pipefail

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

#=== まず rootless を試す ==============================================#
# 参考: https://docs.docker.com/engine/security/rootless/
#       https://matsuand.github.io/docs.docker.jp.onthefly/engine/security/rootless/
if pidof systemd >/dev/null 2>&1; then
  sudo apt-get install -y -qq uidmap dbus-user-session slirp4netns fuse-overlayfs
  sudo systemctl disable --now docker.service docker.socket >/dev/null 2>&1 || true

  if command -v dockerd-rootless-setuptool.sh >/dev/null 2>&1; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    mkdir -p "$XDG_RUNTIME_DIR"
    dockerd-rootless-setuptool.sh install
    systemctl --user enable --now docker.service
    # ブート時自動起動
    sudo loginctl enable-linger "$USER" >/dev/null 2>&1 || true

    echo "[完了] Rootless Docker を有効化しました。"
    echo "シェルに次を追記してください:"
    echo "  export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock"
    exit 0
  fi
fi

#=== rootless が使えない場合は rootful にフォールバック ================#
if getent group docker >/dev/null 2>&1 && ! id -nG "$USER" | grep -qw docker; then
  sudo gpasswd -a "$USER" docker
  echo "[info] ユーザーを docker グループに追加しました。再ログインか newgrp docker が必要です。"
fi

if pidof systemd >/dev/null 2>&1; then
  sudo systemctl enable --now docker.service
  echo "[完了] Rootful Docker サービスを有効化しました。"
else
  echo "[警告] systemd が無い環境です。必要な時に次を実行してください:"
  echo "       sudo dockerd -H unix:///var/run/docker.sock"
fi