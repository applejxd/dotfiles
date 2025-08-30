#!/usr/bin/env bash
set -euo pipefail

# 依存: curl（無ければ取得）
command -v curl >/dev/null 2>&1 || {
  sudo apt-get update -y
  sudo apt-get install -y curl ca-certificates
}

# nvm 導入（未導入時のみ）
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi

# nvm 読み込み（nounsetをこの範囲だけ一時解除）
set +u
# shellcheck disable=SC1090
. "$NVM_DIR/nvm.sh"
set -u

# 最新LTSを導入/更新（可能ならグローバルnpmを移行）
if [ "$(nvm current 2>/dev/null || true)" != "none" ]; then
  nvm install --lts --reinstall-packages-from=current >/dev/null
else
  nvm install --lts >/dev/null
fi

# 既定をLTSに統一
nvm alias default "lts/*" >/dev/null
nvm use default >/dev/null

# バージョン表示
echo "Node.js: $(node -v)"
echo "npm: $(npm -v)"
echo "nvm current: $(nvm current)"