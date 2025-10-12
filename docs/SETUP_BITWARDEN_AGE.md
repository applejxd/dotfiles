# Bitwarden + Age暗号化セットアップ手順

## 概要

chezmoiでBitwardenからage暗号化鍵を自動取得する設定手順です。

## 前提条件

- Bitwarden CLIがインストール済み (`bw --version`で確認)
- age-keygenがインストール済み (`age-keygen --version`で確認)
- Bitwardenアカウントでログイン済み

## セットアップ手順

### 1. Age鍵の生成

```bash
# 一時的に鍵を生成
mkdir -p ~/.config/chezmoi
age-keygen -o ~/.config/chezmoi/key.txt.tmp
```

### 2. Bitwardenに鍵を保存

```bash
# Bitwardenにログイン・アンロック
bw login
export BW_SESSION="$(bw unlock --raw)"

# Base64エンコードしてSecure Noteとして保存
bw get template item | jq ".type = 2 | .name = \"chezmoi-age-key\" | .notes = \"$(base64 -w 0 ~/.config/chezmoi/key.txt.tmp)\" | .secureNote = {} " |  bw encode | bw create item

# 一時鍵ファイルを削除
rm ~/.config/chezmoi/key.txt.tmp
```

### 3. 初期化テスト

```bash
# chezmoi初期化（Bitwardenから鍵を取得）
chezmoi init

# 鍵ファイルが正しく作成されたか確認
ls -la ~/.config/chezmoi/key.txt
head -1 ~/.config/chezmoi/key.txt  # "# created: " で始まるはず
```

### 4. 暗号化ファイルのテスト

```bash
# テスト用の暗号化ファイル追加
echo "secret data" | chezmoi add --encrypt --stdin test_secret

# 復号化テスト
chezmoi cat test_secret
```

## 使用方法

### 新しいマシンでの初期化
```bash
# Bitwardenセットアップ
bw login
export BW_SESSION="$(bw unlock --raw)"

# chezmoi初期化（自動で鍵取得）
chezmoi init --apply https://github.com/your-username/dotfiles.git
```

### 日常使用
```bash
# Bitwardenアンロック（必要に応じて）
export BW_SESSION="$(bw unlock --raw)"

# 通常のchezmoiコマンドが使用可能
chezmoi apply
chezmoi add --encrypt ~/.ssh/private_key
```

## トラブルシューティング

### 鍵が見つからない場合
```bash
# Bitwardenアイテム確認
bw list items --search "chezmoi-age-key"

# テンプレート実行テスト
chezmoi execute-template "{{ (bitwarden \"item\" \"chezmoi-age-key\").notes | b64dec }}"
```

### 権限エラーの場合
```bash
# 鍵ファイルの権限設定
chmod 600 ~/.config/chezmoi/key.txt
```

## セキュリティ注意事項
- age鍵はBitwardenのSecure Noteに暗号化されて保存されます
- 鍵ファイルは600権限で作成されます
- `BW_SESSION`環境変数には注意してください
- 定期的にage鍵のローテーションを検討してください
