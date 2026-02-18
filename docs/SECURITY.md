# セキュリティ機能

## 概要

個人情報と機密設定を安全に管理するため、Bitwarden と age 暗号化を使用します。

## Bitwarden連携

個人情報をBitwardenで安全に管理し、dotfilesを公開リポジトリで共有可能にします。

### 設定方法

#### 1. Bitwarden CLIのインストール

```bash
# Ubuntu
sudo snap install bw

# macOS
brew install bitwarden-cli
```

#### 2. Bitwardenアイテムの作成

```bash
bw login

# 最新データを同期
bw sync

# Login itemを作成（名前: gitconfig）
# Username: [GitHubユーザー名]
# Custom Fields:
#   - email: [GitHubメールアドレス]
```

#### 3. chezmoiでの使用

```bash
# Bitwardenにログイン
bw login

# データを同期（重要！）
bw sync

# セッション開始
export BW_SESSION="$(bw unlock --raw)"

# 設定ファイル適用
chezmoi apply
```

#### 日常的な使用パターン

```bash
# 一括実行
bw sync && export BW_SESSION="$(bw unlock --raw)" && chezmoi apply
```

## age暗号化

機密性の高い設定ファイルをage暗号化で保護します。

### 暗号化ファイルの復号化手順

#### 1. ageキーの準備

```bash
# 秘密鍵ファイルを安全な場所に配置
# 例: ~/.config/age/key.txt
```

#### 2. 暗号化ファイルの復号化

```bash
# 手動復号化
age --decrypt -i ~/.config/age/key.txt home/encrypted_dot_claude.json.age > ~/.claude.json

# またはchezmoiが自動的に復号化（ageキーが設定済みの場合）
chezmoi apply
```

#### 3. 新しいファイルの暗号化

```bash
# 公開鍵で暗号化
age --encrypt -R ~/.config/age/public_key.txt input.json > encrypted_file.age

# chezmoiに追加
chezmoi add --encrypt encrypted_file
```

## Bitwarden + Age 統合セットアップ

chezmoiでBitwardenからage暗号化鍵を自動取得する方法については、[SETUP_BITWARDEN_AGE.md](SETUP_BITWARDEN_AGE.md) を参照してください。

## セキュリティ要件

- Bitwardenマスターパスワードの安全な管理
- ageキーペアの適切な保管（秘密鍵は暗号化ストレージに保存推奨）
- 定期的なパスワード・キーのローテーション
- `BW_SESSION`環境変数の取り扱いに注意
