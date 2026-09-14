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

### 7. WindowsでCopilot hookが起動しない

生成済みhookがPowerShell用コマンドと `py -3` を使用しているか確認する。
詳細な切り分けは
[Copilot CLI: Windowsのhook起動](../../home/dot_copilot/README.md#windows-の-hook-起動)
を参照。

```powershell
Get-Content "$HOME\.copilot\hooks\from-claude.json"
'{"tool_name":"powershell","tool_input":{"command":"git status"}}' |
    py -3 -B -X utf8 "$HOME\.claude\hooks\check_bash.py"
$LASTEXITCODE
```

### 8. CLI 起動時に `Failed to load 1 skill.` と出る

SKILL.md の YAML frontmatter が壊れていると、CLI はそのスキルを黙って読み飛ばす。
バナーには件数しか出ないので、どのファイルかは CLI に聞く。

```bash
copilot skill list          # 末尾に "The following skills failed to load:" が出る
```

リポジトリ側で先に弾くには、pre-commit と同じ検証を全ファイルに掛ける。

```bash
uv run --with pyyaml --no-project python scripts/agents/validate_skills.py
```

よくある原因は `description` を引用符なしで書いた場合の以下 2 つ。どちらも
`description: "..."` と二重引用符で囲めば解消する。

- `undefined symbol: _ZNK3c10` のような **コロン+空白**（mapping value と解釈されパースエラー）
- `use # for comments` のような **空白+`#`**（以降がコメントとして無言で捨てられる）

### 9. Linux で sandbox がコマンドを 1 つも実行できない

bash だけでなく、ripgrep を使う `grep` / `glob` やサブエージェントまで、
**コマンドの中身に関係なく**同じエラーで即座に失敗する。

```text
Bubblewrap: network.enforcementMode='firewall' requires 'slirp4netns' on PATH:
No such file or directory (os error 2).
```

```text
Bubblewrap: network.enforcementMode='firewall' requires 'iptables' on PATH to
enforce firewall enforcement: No such file or directory (os error 2)
```

#### 原因

Copilot CLI / Claude Code の Linux sandbox は Microsoft MXC の bubblewrap
backend で動く。`network.enforcementMode` が `firewall` のとき、backend は
ホスト側の実行ファイルを probe し、**1 つでも欠けると起動を拒否する**。
sandbox の外で走るのは CLI 本体だけなので、結果として全ツールが死ぬ。

必要なものは次のとおり。

| 実行ファイル | Ubuntu パッケージ | 役割 |
| --- | --- | --- |
| `bwrap` | `bubblewrap` | 名前空間の構築（0.5.0 以上、一部モードは 0.8 以上） |
| `slirp4netns` | `slirp4netns` | 非特権ユーザでのネットワーク名前空間 |
| `unshare` / `nsenter` | `util-linux` | 名前空間の作成と参加（essential なので通常は導入済み） |
| `iptables` / `ip6tables` | `iptables` | 名前空間内での通信フィルタ |
| `iptables-restore` / `ip6tables-restore` | 同上 | ルールの一括適用 |

出典は MXC の `backends/bubblewrap/common/src/proxy_network.rs`
（各 probe と `run_probe` のエラー文言）。

#### 対処

不足は 1 つずつしか報告されない。1 つ入れるたびに再起動して次のエラーを
見るのは時間の無駄なので、**まとめて導入する**。

```bash
sudo apt-get install -y bubblewrap slirp4netns util-linux iptables
```

`run_once_after_121_ubuntu.sh.tmpl` が同じ一式を導入するので、新しい環境では
追加作業は要らない。既存環境でも**スクリプトの内容が変わった以上
`chezmoi apply` で再実行される**（`run_once_` の判定は内容のハッシュ）が、
同じスクリプトが `apt-get upgrade` や ClamAV の `freshclam` まで行うので、
上記の 1 行を直接叩くほうが速い。

反映には CLI の再起動が要る。

#### それでも起動しない場合

パッケージが揃っていても、次の 2 つはホスト側の状態に依存する。

- **`iptables` が legacy バックエンドを指している**: legacy は
  `/run/xtables.lock` を開くため root が要り、非特権 sandbox では失敗する。
  nft バックエンドなら同ファイルを使わない。Ubuntu 20.04 以降の既定は
  nft だが、切り替えられている場合は戻す。

  ```bash
  update-alternatives --display iptables
  sudo update-alternatives --set iptables /usr/sbin/iptables-nft
  ```

- **`nf_conntrack` が未ロード**: 接続状態マッチに必要で、非特権 sandbox は
  自力でロードできない。iptables はこれを `Invalid argument` としか報告
  しないため原因が分かりにくい。

  ```bash
  lsmod | grep nf_conntrack || sudo modprobe nf_conntrack
  ```

依存を導入できない環境では、`/sandbox` の **Network** タブで
`enforcementMode` を `firewall` 以外へ変更する。フィルタが不要になるぶん
`iptables` 系の probe も走らなくなる。

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

`bw: command not found` の場合、Windows では Winget の導入状態を確認する:

```powershell
winget install --id Bitwarden.CLI --exact
Get-Command bw
```

Unix では mise の shim が未生成の可能性がある:

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
詳細は [Secret管理セットアップ](sops-age.md) を参照してください。

### 3. chezmoi設定確認

```bash
# 設定値の確認
chezmoi data

# Bitwardenテンプレート関数テスト
chezmoi execute-template '{{ (bitwarden "item" "gitconfig").login.username }}'
```
