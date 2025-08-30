#!/usr/bin/env bash
set -euo pipefail

# --help
if [[ "${1:-}" =~ ^(-h|--help)$ ]]; then
  cat <<'EOF'
Usage: [ENV_VARS...] ./setup-sshd-min.sh

Environment variables:
  PORT=22                  # SSH ポート（既定: 22）
  PASSWORD_AUTH=no          # yes/no（既定: no）
  PUBKEY_AUTH=yes           # yes/no（既定: yes）
  PERMIT_ROOT_LOGIN=prohibit-password
                           # yes/no/prohibit-password（既定: prohibit-password）
  ALLOW_USERS="user1 user2" # 空なら未設定（AllowUsers）

Examples:
  PASSWORD_AUTH=yes ./setup-sshd-min.sh
  ALLOW_USERS="alice bob" ./setup-sshd-min.sh
  PORT=2222 PASSWORD_AUTH=yes ./setup-sshd-min.sh  # 先に設定→後でインストール（競合回避）
EOF
  exit 0
fi

# === 可変パラメータ（環境変数で上書き可） ===
PORT="${PORT:-22}"
PASSWORD_AUTH="${PASSWORD_AUTH:-no}"
PUBKEY_AUTH="${PUBKEY_AUTH:-yes}"
PERMIT_ROOT_LOGIN="${PERMIT_ROOT_LOGIN:-prohibit-password}"
ALLOW_USERS="${ALLOW_USERS:-}"
CONF_NAME="${CONF_NAME:-10-override.conf}"
# ============================================

sudo -v

# (1) まず設定ファイル（drop-in）を作る：インストール前でも OK
sudo mkdir -p /etc/ssh/sshd_config.d
TMP="$(mktemp)"
{
  echo "# Managed by $(basename "$0")"
  echo "Port ${PORT}"
  echo "PasswordAuthentication ${PASSWORD_AUTH}"
  echo "PubkeyAuthentication ${PUBKEY_AUTH}"
  echo "PermitRootLogin ${PERMIT_ROOT_LOGIN}"
  [ -n "${ALLOW_USERS}" ] && echo "AllowUsers ${ALLOW_USERS}"
} >"${TMP}"

DST="/etc/ssh/sshd_config.d/${CONF_NAME}"
CHANGED=0
if ! sudo cmp -s "${TMP}" "${DST}" 2>/dev/null; then
  [ -e "${DST}" ] && sudo cp -a "${DST}" "${DST}.bk.$(date +%Y%m%d%H%M%S)"
  sudo mv "${TMP}" "${DST}"
  sudo chmod 0644 "${DST}"
  CHANGED=1
else
  rm -f "${TMP}"
fi

# (2) その後で openssh-server をインストール（postinst が起動を試みても新ポートで上がる）
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends openssh-server

# (3) ランタイムが欠けていた場合の保険（/run/sshd）
if [ ! -d /run/sshd ]; then
  sudo mkdir -p /run/sshd
  sudo chown root:root /run/sshd
  sudo chmod 0755 /run/sshd
fi

# (4) 構文チェック → 起動/有効化 → 変更時のみ reload
if command -v sshd >/dev/null 2>&1; then
  sudo sshd -t
fi

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl enable --now ssh
  [ "$CHANGED" -eq 1 ] && sudo systemctl reload ssh || true
else
  [ "$CHANGED" -eq 1 ] && ( sudo service ssh reload || sudo service ssh restart || true )
fi

echo "sshd ready on port ${PORT}."