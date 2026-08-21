# セキュリティ機能

## 概要

個人情報と機密設定を安全に管理するため、Bitwarden と sops (age) を使用します。

## Bitwarden連携

個人情報をBitwardenで安全に管理し、dotfilesを公開リポジトリで共有可能にします。

### 設定方法

#### 1. Bitwarden CLIのインストール

通常は `chezmoi apply` 中に mise (`npm:@bitwarden/cli`) で自動投入されるため **明示インストール不要**。
クリーン環境では「2 フェーズ bootstrap」（[README](../README.md) 参照）で:

1. `chezmoi init applejxd && chezmoi apply` → mise が bw を含む全ツールを導入
2. `bw login && export BW_SESSION="$(bw unlock --raw)"` → `chezmoi init applejxd && chezmoi apply` で Bitwarden 連携を有効化

手動で先に入れたい / mise を使わない環境では:

```bash
# mise 経由（推奨・OS 共通）
mise use -g npm:@bitwarden/cli

# macOS (brew でも可。ただし mise 版と PATH 競合に注意)
brew install bitwarden-cli
```

> Ubuntu の `sudo snap install bw --classic` は動作不良のため非推奨。

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

## sops による API キー管理

API キーは平文の `.env` に置かず、sops (age) で暗号化したまま Git 管理し、
mise がプロジェクト入退場時に自動でロード・アンロードします。

### 役割分担

| ツール | 役割 |
| --- | --- |
| SOPS + age | API キーの暗号化 |
| mise | プロジェクト入退場時の自動ロード・アンロード |
| Bitwarden Password Manager | age 秘密鍵の保管 |
| chezmoi | 新しい環境で age 秘密鍵を Bitwarden から復元 |

Bitwarden Secrets Manager の `bws` は使用しません。

### 鍵の配置

age の秘密鍵は Bitwarden から自動で展開されます。

| 項目 | 値 |
| --- | --- |
| Bitwarden の項目名 | `SOPS age identity personal` |
| chezmoi のソース | `home/dot_config/sops/age/private_keys.txt.tmpl` |
| 展開先 | `~/.config/sops/age/keys.txt`（`private_` 接頭辞により mode 600） |
| mise の設定 | `sops.age_key_file = "~/.config/sops/age/keys.txt"` |

一度展開された後は `.chezmoiignore` により再展開されません。
毎回 Bitwarden を引くと `chezmoi diff` がマスターパスワードを要求するためです。

**SOPS 用の age 秘密鍵を、同じ age 鍵で chezmoi 暗号化してはいけません。**
復号に必要な鍵が暗号化ファイル内にある循環状態になります。

### 鍵が無い場合

`mise install` の直後に案内が出ます。次を実行してください。

```bash
bw login
export BW_SESSION="$(bw unlock --raw)"
chezmoi apply
```

### 詳細な手順

セットアップ、プロジェクトごとの設定、日常操作、新環境での復旧は
[SETUP_SOPS_AGE.md](SETUP_SOPS_AGE.md) にまとめています。

> **補足**: 以前は chezmoi 本体の age 暗号化（`~/.config/chezmoi/key.txt` と
> `encryption = "age"`）も設定していましたが、暗号化ファイルを一度も
> 運用しておらず、Bitwarden テンプレート方式と機能が重複していたため廃止しました。
> 既存マシンに `~/.config/chezmoi/key.txt` が残っている場合は手動で削除できます
> （`chezmoi apply` では削除されません）。

## セキュリティ要件

- Bitwardenマスターパスワードの安全な管理
- age鍵の適切な保管（秘密鍵は Bitwarden の Secure Note に保存）
- 定期的なパスワード・キーのローテーション
- `BW_SESSION`環境変数の取り扱いに注意
