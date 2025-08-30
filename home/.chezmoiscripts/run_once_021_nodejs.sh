#!/usr/bin/env bash
set -euo pipefail

#=== util ===#
need() { command -v "$1" >/dev/null 2>&1; }
log()  { printf '[node-setup] %s\n' "$*" >&2; }

#=== ensure curl ===#
if ! need curl; then
  log "curl が見つかりません。インストールします（Ubuntu想定: apt）。"
  sudo apt-get update -y
  sudo apt-get install -y curl ca-certificates
fi

#=== ensure nvm ===#
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  log "nvm が未インストールのため取得します。"
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi

# ロード（シェル再起動不要）
# shellcheck disable=SC1090
. "$NVM_DIR/nvm.sh"

#=== version detection ===#
latest_lts_full="$(nvm ls-remote --lts | tail -n1 | awk '{print $1}')"   # 例: v22.11.0
latest_lts="${latest_lts_full#v}"

current_full=""
current=""
if need node; then
  current_full="$(node -v)"        # 例: v20.17.0
  current="${current_full#v}"
else
  current=""
fi

#=== compare helper (returns 0 if a >= b) ===#
version_ge() { [ "$(printf '%s\n' "$1" "$2" | sort -V | tail -n1)" = "$1" ]; }

#=== decide & act ===#
if [ -z "$current" ]; then
  log "Node.js が未インストール。最新LTS ($latest_lts_full) を導入します。"
  nvm install --lts
  nvm alias default 'lts/*'
  nvm use default
elif version_ge "$current" "$latest_lts"; then
  log "既に最新LTS以上です（現在: $current_full / 最新LTS: $latest_lts_full）。何もしません。"
else
  log "Node.js が古いため更新します（現在: $current_full → 最新LTS: $latest_lts_full）。"
  # nvm 管理の Node が有効ならグローバル npm パッケージを引き継ぐ
  if [ "$(nvm current 2>/dev/null || true)" != "none" ]; then
    nvm install --lts --reinstall-packages-from=current
  else
    nvm install --lts
  fi
  nvm alias default 'lts/*'
  nvm use default
fi

#=== show versions ===#
echo "Node.js: $(node -v)"
echo "npm: $(npm -v)"
echo "nvm current: $(nvm current)"