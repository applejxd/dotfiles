# トラブルシューティング

## よくある問題

### 1. パスワード認証エラー

```bash
# 環境変数でパスワードを設定
export SUDO_PASSWORD="your_password"
chezmoi apply
```

### 2. スクリプト実行権限エラー

```bash
# chezmoi の状態を確認
chezmoi status

# 強制的に再実行
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

### 3. VS Code が見つからない

VS Code がインストールされていない場合、拡張機能のインストールはスキップされます。先に VS Code をインストールしてから再実行してください。

### 4. ネットワークエラー

インストールスクリプトはローカルファイルを参照するため、ネットワーク接続は主に外部パッケージのダウンロード時のみ必要です。

## ログの確認

```bash
# 詳細ログで実行
chezmoi apply --verbose

# 実行状態の確認
chezmoi status
```

## セキュリティ関連のトラブルシューティング

### 1. Bitwarden認証エラー

```bash
# セッション状態確認
bw status

# データ同期
bw sync

# 再ログイン
bw logout
bw login
bw sync
export BW_SESSION="$(bw unlock --raw)"
```

### 2. age復号化エラー

```bash
# キーファイルの確認
ls -la ~/.config/age/

# 手動復号化テスト
age --decrypt -i ~/.config/age/key.txt [暗号化ファイル]
```

### 3. chezmoi設定確認

```bash
# age設定確認
chezmoi data

# Bitwardenテンプレート関数テスト
chezmoi execute-template '{{ (bitwarden "item" "gitconfig").login.username }}'
```
