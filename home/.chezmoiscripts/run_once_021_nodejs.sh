#!/usr/bin/env bash
set -eo pipefail  # ← -u は外す or 一時的に無効化する

#=== util ===#
need() { command -v "$1" >/dev/null 2>&1; }
log()  { printf '[node-setup] %s\n' "$*" >&2; }

#=== ensure curl ===#
if ! need curl; then
  log "curl をインストールします（Ubuntu）。"
  sudo apt-get update -y
  sudo apt-get install -y curl ca-certificates
fi

#=== ensure nvm ===#
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  log "nvm が未インストールのため取得します。"
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi

#=== load nvm (disable -u only around sourcing) ===#
set +u
# shellcheck disable=SC1090
. "$NVM_DIR/nvm.sh"
set -u 2>/dev/null || true  # 環境により -u が無ければ無視

#=== detect versions ===#
latest_lts_full="$(nvm ls-remote --lts | tail -n1 | awk '{print $1}')"  # e.g., v22.19.0
latest_lts="${latest_lts_full#v}"

current_full=""
current=""
if need node; then
  current_full="$(node -v | tr -d '\r')"
  current="${current_full#v}"
fi

# a >= b ?
version_ge() { [ "$(printf '%s\n' "$1" "$2" | sort -V | tail -n1)" = "$1" ]; }

#=== act ===#
if [ -z "$current" ]; then
  log "Node.js 未インストール。最新LTS($latest_lts_full) を導入します。"
  nvm install --lts
  nvm alias default 'lts/*'
  nvm use default
elif version_ge "$current" "$latest_lts"; then
  log "最新LTS以上です（現在: $current_full / 最新LTS: $latest_lts_full）。何もしません。"
else
  log "Node.js を更新します（現在: $current_full → 最新LTS: $latest_lts_full）。"
  if [ "$(nvm current 2>/dev/null || true)" != "none" ]; then
    nvm install --lts --reinstall-packages-from=current
  else
    nvm install --lts
  fi
  nvm alias default 'lts/*'
  nvm use default
fi

echo "Node.js: $(node -v)"
echo "npm: $(npm -v)"
echo "nvm current: $(nvm current)"