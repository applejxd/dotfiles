#!/usr/bin/env bash
# .chezmoiscripts/021_nodejs.sh
# 目的: Node.js が未導入 or 最新LTSより古い場合のみ、最新LTSへ更新（npmグローバルを引き継ぎ）

set -eo pipefail   # ← nounset(-u)はあえて使わない。nvm.shと相性が悪い

need() { command -v "$1" >/dev/null 2>&1; }
log()  { printf '[node-setup] %s\n' "$*" >&2; }

# curl が無ければ入れる（Ubuntu）
if ! need curl; then
  log "curl をインストールします（Ubuntu）。"
  sudo apt-get update -y
  sudo apt-get install -y curl ca-certificates
fi

# nvm を用意
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  log "nvm を取得します。"
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi

# 以降は **別シェル** で nounset を無効化して実行（nvm.sh保護）
bash --noprofile --norc -c '
  set -e
  export NVM_DIR="$HOME/.nvm"

  # nounset を確実に無効化した状態で source
  set +u
  # shellcheck disable=SC1090
  . "$NVM_DIR/nvm.sh"

  # バージョン検出
  latest_lts_full="$(nvm ls-remote --lts | tail -n1 | awk "{print \$1}")"   # e.g., v22.19.0
  latest_lts="${latest_lts_full#v}"
  if command -v node >/dev/null 2>&1; then
    cur_full="$(node -v | tr -d "\r")"   # e.g., v20.17.0
    cur="${cur_full#v}"
  else
    cur=""
  fi

  # a >= b ?
  version_ge() { [ "$(printf "%s\n" "$1" "$2" | sort -V | tail -n1)" = "$1" ]; }

  if [ -z "$cur" ]; then
    echo "[node-setup] Node.js 未導入。最新LTS ($latest_lts_full) を導入します。" >&2
    nvm install --lts
  elif version_ge "$cur" "$latest_lts"; then
    echo "[node-setup] 既に最新LTS以上（現在: $cur_full / 最新LTS: $latest_lts_full）。何もしません。" >&2
  else
    echo "[node-setup] 古いため更新（現在: $cur_full → 最新LTS: $latest_lts_full）。" >&2
    if [ "$(nvm current 2>/dev/null || true)" != "none" ]; then
      nvm install --lts --reinstall-packages-from=current
    else
      nvm install --lts
    fi
  fi

  nvm alias default "lts/*" >/dev/null
  nvm use default >/dev/null

  echo "Node.js: $(node -v)"
  echo "npm: $(npm -v)"
  echo "nvm current: $(nvm current)"
'