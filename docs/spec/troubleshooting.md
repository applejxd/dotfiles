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

### 10. mise の npm ツールが突然動かなくなる

`bw` / `markdownlint-cli2` など **npm backend で入れたツール**が、ある日
突然落ちるようになる。`mise ls` には正常に出るので気付きにくい。

観測された壊れ方は 2 通りあり、**症状は違うが対処は同じ**。

#### パターン A: キャッシュの実体が消えた

```text
Error: Cannot find module
  '~/.local/share/mise/installs/npm-bitwarden-cli/latest/node_modules/
   .mise/@bitwarden+cli@2026.7.0/node_modules/@bitwarden/cli/build/bw.js'
```

mise の npm backend は依存の実体を **`~/.cache/aube/virtual-store/`** に置き、
`installs/` 配下からそこへ symlink を張ることがある。`~/.cache` は本来
「消えてよい」場所なので、キャッシュ削除で **リンク先だけが消えて
symlink が宙ぶらりんになる**。

実測 (npm-bitwarden-cli 2026.7.0): `.mise/` 配下 213 個の symlink が全滅。
一方で依存の少ない `npm-anthropic-ai-sandbox-runtime` (6 件) は実体ディレクトリ
で入っており無傷だった。**キャッシュへ symlink したツールだけが壊れる。**

#### パターン B: 導入物の一部が欠けた

```text
exec: node: not found      # あるいは shim が解決できない
```

古い世代の導入物は `bin/` と `lib/` の 2 階層で、`bin/<tool>` が
`../lib/node_modules/...` を指す。ここで **`lib/` だけが失われる**ことがある。

実測 (npm-markdownlint-cli2 0.22.1、2026-04 導入): `bin/` は残っているのに
`lib/` が無くリンクが宙ぶらりん。同じ世代の `npm-google-gemini-cli`
(2026-03 導入) は無傷なので、一斉移行やバージョン差ではなく**個別の欠損**。

> [!NOTE]
> **どちらも「何が消したか」は特定できていない。** キャッシュ削除ツール、
> ディスク掃除、中断した導入などが候補だが、記録が残らないため確認できない。
> 分かっているのは「消えた結果こうなる」ところまで。

#### 対処 (共通)

ディレクトリごと消してから入れ直す。`mise install --force` だけでは
**使用中の `bin/` を削除できず `Read-only file system` で失敗する**
(PATH 上のディレクトリは sandbox が read-only で bind-mount するため。
項目 9 の下の節を参照)。

```bash
rm -rf ~/.local/share/mise/installs/npm-bitwarden-cli
mise install "npm:@bitwarden/cli"
bw --version
```

パターン A を洗い出すには、`.mise/` 配下の壊れた symlink を数えるのが早い。

```bash
find ~/.local/share/mise/installs -path '*/node_modules/.mise/*' \
     -maxdepth 6 -xtype l -printf '%h\n' | sort -u
```

> [!NOTE]
> この検索には **PATH に載っていない古い残骸**も出る。mise は以前
> `installs/<tool>/` という名前で入れており、現在の `installs/npm-<tool>/`
> とは別物として残る (実測: `installs/markdownlint-cli2/0.23.2` が壊れた
> まま残っていたが、PATH には `npm-markdownlint-cli2` しか無く無害だった)。
> `~/.config/mise/config.toml` とリポジトリの `mise.toml` に宣言が無ければ
> 残骸なので、そのまま消してよい。

#### 再発するか

入れ直した後の `.mise/` 配下は **symlink ではなく実体のディレクトリ**に
なっていた (bitwarden 214 件・markdownlint 87 件・sandbox-runtime 6 件とも
symlink 0)。この形ならキャッシュ削除では壊れない。
再び symlink 構造で入るようなら、`~/.cache` を消さない運用にするか、
消した直後に上記の入れ直しを行う。

### 11. 久しぶりの `chezmoi update` が Bitwarden で止まる

```text
chezmoi: warning: config file template has changed, run chezmoi init to regenerate config file
.config/git/ignore has changed since chezmoi last wrote it?
You are not logged in.
chezmoi: .config/git/user: template: ...: error calling bitwarden:
  ... bw unlock --raw: exit status 1
```

3 つが同時に起きているので、上から順に片付ける。

| 行 | 意味 | 対処 |
| --- | --- | --- |
| `config file template has changed` | `home/.chezmoi.toml.tmpl` が更新された。`~/.config/chezmoi/chezmoi.toml` は古いまま | `chezmoi init` |
| `... has changed since chezmoi last wrote it?` | 展開先が chezmoi の記録と食い違う。上書き可否を聞かれている | `chezmoi diff` で中身を見てから答える |
| `error calling bitwarden` | `bw` は入ったが未ログイン。`bw unlock` が失敗しテンプレートが落ちる | `bw login` してセッションを張る |

```bash
chezmoi init                                  # 設定ファイルを再生成
chezmoi diff ~/.config/git/ignore             # 上書きしてよいか確認
bw login && bw sync
export BW_SESSION="$(bw unlock --raw)"
chezmoi apply
```

`BW_SESSION` を張らないまま `chezmoi apply` しても止まらない。
`.chezmoiignore.tmpl` がセッションの無い間だけ `~/.config/git/user` と
`~/.config/sops/age/keys.txt` を無視するため、この 2 つは未展開のまま次回に回る。
Bitwarden を使わないマシンならそのままで構わない。

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
