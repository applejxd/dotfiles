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

### 5. Windows で `.copilot/skills` のリンク作成に失敗する

Windows では symlink 作成に Developer Mode または管理者権限が必要なため、
`run_after_342_copilot_skills.ps1` が通常権限で directory junction を作成する。
`.copilot/skills` が `chezmoi managed` に表示されないのは意図した動作。

既存の通常ディレクトリにファイルがある場合は自動削除しない。内容を確認して別の場所へ
移動してから再実行する。

```powershell
Get-Item "$HOME\.copilot\skills" -Force |
    Select-Object FullName, LinkType, Target
chezmoi apply
```

directory junction はローカルファイルシステム向けであり、ホームディレクトリが
UNC/network path の場合は作成できない。

### 6. Windows で `tomllib` または Python のエラーが出る

設定生成と agent hook は Python 3.11 以上の標準ライブラリ `tomllib` を使用する。
`tomli` の手動インストールは不要。次のコマンドで対応 Python を確認する。

```powershell
py -3 -c "import sys, tomllib; print(sys.version)"
```

Python 3.10 以下しかない場合は Python 3.12 を導入し、PowerShell を開き直してから
`chezmoi apply` を再実行する。

```powershell
winget install --id Python.Python.3.12 --exact --silent `
  --accept-package-agreements --accept-source-agreements
chezmoi apply
```

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

`bw: command not found` の場合は mise の shim が未生成の可能性がある:

```bash
mise install            # npm:@bitwarden/cli を含むツール一式を入れ直す
mise reshim             # shim を再生成
mise which bw           # 実体パスを確認 (~/.local/share/mise/installs/... 配下)
```

### 2. age復号化エラー

```bash
# 鍵ファイルの存在確認 (中身は表示しない)
ls -l ~/.config/sops/age/keys.txt

# 復号テスト
sops --decrypt [暗号化ファイル]
```

鍵が無い場合は `bw unlock` してから `chezmoi apply` で展開されます。
詳細は [SETUP_SOPS_AGE.md](SETUP_SOPS_AGE.md) を参照してください。

### 3. chezmoi設定確認

```bash
# 設定値の確認
chezmoi data

# Bitwardenテンプレート関数テスト
chezmoi execute-template '{{ (bitwarden "item" "gitconfig").login.username }}'
```
