#!/bin/bash

# 最初にパスワード確認
echo "設定を変更するため、パスワードを入力してください..."
sudo -v || exit 1

# 値の定義 (分かりやすく設定)
MEMLOCK_KB=524288
MEMLOCK_SYSTEMD="512M" # systemdはMやKのプレフィックスに対応している

echo "--- memlock 設定を開始します ---"

# # 1. limits.conf の更新 (.d ディレクトリを使用)
# echo "Updating /etc/security/limits.d/99-browser-memlock.conf..."
# sudo tee /etc/security/limits.d/99-browser-memlock.conf > /dev/null <<EOF
# * soft memlock $MEMLOCK_KB
# * hard memlock $MEMLOCK_KB
# EOF

# 2. systemd の更新 (.d ディレクトリを使用)
# system.conf.d と user.conf.d の両方に同じ設定を配置する
for DIR in "/etc/systemd/system.conf.d" "/etc/systemd/user.conf.d"; do
    sudo mkdir -p "$DIR"
    echo "Updating $DIR/99-browser-memlock.conf..."
    sudo tee "$DIR/99-browser-memlock.conf" > /dev/null <<EOF
[Manager]
DefaultLimitMEMLOCK=$MEMLOCK_SYSTEMD:$MEMLOCK_SYSTEMD
EOF
done

# systemdに設定変更を認識させる
sudo systemctl daemon-reload

echo "--- 設定完了！ ---"
echo "再起動後に完全に反映されます: sudo reboot"