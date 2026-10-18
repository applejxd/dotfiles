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
# 停止後もソケットが残り、docker グループのユーザーには書き込み可能なため、
# setuptool が rootful 稼働中と誤判定する。残骸を消す。
rootful_active=false
rootful_enabled=false
if systemctl is-active --quiet docker.service || systemctl is-active --quiet docker.socket; then
  rootful_active=true
fi
if systemctl is-enabled --quiet docker.service || systemctl is-enabled --quiet docker.socket; then
  rootful_enabled=true
fi

# rootless は rootful と保存領域 (~/.local/share/docker) が別で、イメージもボリュームも引き継がない
# 照会できなかったときは "?" を返す (0 件と取り違えない)
count_rootful() {
  local out
  out="$(sudo docker "$@" 2>/dev/null)" || { echo "?"; return 0; }
  if [[ -z "$out" ]]; then echo 0; else printf '%s\n' "$out" | wc -l; fi
}
if $rootful_active; then
  n_images="$(count_rootful images -q)"
  n_volumes="$(count_rootful volume ls -q)"
  n_running="$(count_rootful ps -q)"
  unknown=""
  if [[ "$n_images$n_volumes$n_running" == *"?"* ]]; then unknown=" ('?' は照会できませんでした)"; fi
  if [[ -n "$unknown" ]] || (( n_images + n_volumes + n_running > 0 )); then
    echo "[警告] rootful Docker のイメージ ${n_images} 個・ボリューム ${n_volumes} 個・実行中のコンテナ ${n_running} 個${unknown}。" >&2
    echo "       rootless は保存領域が別で、これらは引き継がれません (/var/lib/docker に残ります)。" >&2
  fi
fi

# 以降で失敗したら、止めた rootful を元に戻す (どちらも動かない状態を残さない)
# もともと動いていたときだけ --now を付け、有効化だけされていたときは有効化を戻す
rootful_stopped=false
restore_rootful() {
  local rc=$?
  if [[ $rc -ne 0 ]] && $rootful_stopped; then
    local now=""
    if $rootful_active; then now="--now"; fi
    echo "[警告] rootless の導入に失敗したので rootful Docker を元に戻します" >&2
    # shellcheck disable=SC2086 # now は空か --now のみ
    sudo systemctl enable $now docker.socket docker.service \
      || echo "[警告] 戻せませんでした。手動で: sudo systemctl enable $now docker.socket docker.service" >&2
  fi
}
trap restore_rootful EXIT

if $rootful_active || $rootful_enabled; then
  rootful_stopped=true
fi
sudo systemctl disable --now docker.service docker.socket
sudo rm -f /var/run/docker.sock

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
# Docker Desktop (WSL 統合) が残した壊れた symlink (contexts 等) で setuptool の mkdir が失敗する
find "$HOME/.docker" -maxdepth 1 -xtype l -print -delete 2>/dev/null || true

# Docker Desktop 用の credential helper (desktop.exe) が残っていると pull が失敗する
DOCKER_CFG="$HOME/.docker/config.json"
if [[ -f "$DOCKER_CFG" ]] && grep -q '"desktop' "$DOCKER_CFG"; then
  python3 - "$DOCKER_CFG" <<'EOF'
import json, sys

path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)
if str(cfg.get("credsStore", "")).startswith("desktop"):
    del cfg["credsStore"]
helpers = cfg.get("credHelpers", {})
for k in [k for k, v in helpers.items() if str(v).startswith("desktop")]:
    del helpers[k]
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
EOF
fi

# systemd の Environment= は空白入りの PATH (WSL の Windows 側) を解釈できない。
# 過去に作られた壊れたユニットは作り直す (setuptool は既存ユニットを上書きしない)
UNIT="$HOME/.config/systemd/user/docker.service"
if [[ -f "$UNIT" ]] && grep -q '^Environment=PATH=.* ' "$UNIT"; then
  rm -f "$UNIT"
fi
CLEAN_PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v -e ' ' -e '^/mnt/' | paste -sd: -)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
PATH="$CLEAN_PATH" dockerd-rootless-setuptool.sh install
systemctl --user enable --now docker.service
# rootless が立ち上がったので、以降の失敗 (linger、GPU 設定など) では rootful を戻さない
rootful_stopped=false
# ブート時 (ログイン前) から自動起動
sudo loginctl enable-linger "$USER"

echo "[完了] Rootless Docker を有効化しました。"
echo "setuptool が docker context 'rootless' を作成済みです。context を使わないなら次を追記してください:"
echo "  export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock"

#=== GPU ===============================================================#
if command -v nvidia-smi >/dev/null 2>&1; then
  bash "$(dirname "${BASH_SOURCE[0]}")/nvidia-container-toolkit.sh"
fi
