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

### 12. Unix で `No module named 'tomllib'` が出て apply が止まる

```text
Traceback (most recent call last):
  File "~/.local/share/chezmoi/scripts/agents/generate.py", line 26, in <module>
    import tomllib
ModuleNotFoundError: No module named 'tomllib'
chezmoi: .claude/settings.json: exit status 1
```

`tomllib` は Python 3.11 以上の標準ライブラリ。chezmoi は project の uv 環境では
なく `[interpreters.py]` で指定した Python で modify script を実行するので、
**system の `python3` が 3.10 以下**だとここで落ちる。
Ubuntu 22.04 の既定は 3.10、20.04 は 3.8 なので該当する（24.04 は 3.12 で問題ない）。

現在は 2 段構えで防いでいるので、通常はこのエラーを見ない。

1. `000_unix/run_before_005_python.sh` が**ファイル適用より前に**走り、3.11 以上が
   無ければ uv をユーザ領域へ入れて `uv python install` する（sudo 不要）
2. ラッパー (`home/.chezmoitemplates/modify_json.py.tmpl`) が実行時に探し直す
   - 自分自身 → PATH の `python3.14` … `python3.11` → PATH の `python3` / `python`
   - `~/.local/share/mise/installs/python/*/bin/python3.*`
   - `~/.local/share/uv/python/*/bin/python3.*`

つまり **1 つでも 3.11 以上があれば `chezmoi apply` だけで通る**。
上のエラーが出るのは、どこにも無く、かつ 1 の自動取得も失敗した場合だけ
（オフライン環境など）。その場合は先に警告が出ている。

```text
⚠️  uv を導入できませんでした。3.11 以上の Python を手動で入れてください。
```

手元の状況を確認する。

```bash
python3 --version
ls ~/.local/share/mise/installs/python/*/bin/python3.* 2>/dev/null
ls ~/.local/share/uv/python/*/bin/python3.* 2>/dev/null
```

自分で入れる場合も **sudo は要らない**。

```bash
uv python install 3.13     # uv があるなら
mise use -g python@3.13    # mise があるなら
chezmoi apply
```

どちらも使えないときの最後の手段が system への導入。

```bash
sudo apt-get install -y python3.12
chezmoi apply
```

> [!NOTE]
> ツール一式を入れる `100_linux/run_onchange_after_125_mise.sh.tmpl` は
> `run_before_` へ移していない。あれが読む `~/.config/mise/config.toml` は
> ファイル適用で展開されるので前倒しできず、`all_compile = true` による
> Python のソースビルドと `sudo apt-get` が apply の冒頭に来てしまうため。
> 必要なのは Python 1 つなので、専用の小さな `run_before_` を分けている。

`tomli` は入れない。理由は
[ADR-0003](../adr/0003-require-python-311-for-agent-configuration.md) を参照。

### 13. AI CLI が mise に「global default version を指定しろ」と言う

`opencode` / `omp` / `claude` / `copilot` のどれでも起きる。

```text
mise ERROR No version is set for shim: opencode
Set a global default version with: mise use -g opencode@<version>
```

言われたとおり `mise use -g` すると今度はこうなる。

```text
configuration invalid at ...
```

> [!WARNING]
> `omp` はそもそも mise のレジストリに無い（`tool not found in registry: omp`）ので、
> `mise use -g omp` は成功しない。指示に従っても抜けられない。

#### 原因

CLI が公式の導入先ではなく **mise の残骸 shim** に解決されている。

AI CLI は `d0abd95` で mise 管理から各社公式インストーラーへ一本化したが、
**切り替え前の shim と installs は残る**。しかも PATH 上では mise の shims が
公式の導入先より前に来る（実測: shims が 50 番目、`~/.local/bin` が 60 番目）。

ここから抜けられない輪ができる。

1. shim だけが残っている
2. `chezmoi apply` が `~/.config/mise/config.toml` を上書きし、宣言が消える
   （このファイルは chezmoi 管理で、正本は `home/dot_config/mise/config.toml.tmpl`）
3. `opencode` → shim → 版を解決できず上のエラー
4. `mise use -g opencode@latest` すると宣言が復活して動く
5. 次の `chezmoi apply` でまた消える → 3 へ戻る

`configuration invalid` の方は**別物が入る**ために起きる。

```bash
mise registry opencode   # -> aqua:anomalyco/opencode
```

これは V1 系で、生成される `~/.config/opencode/opencode.json` は V2 スキーマ
（`permissions` は順序付きルール配列）。V1 のバイナリが V2 の設定を読んで弾く。
世代の違いは [V2 の仕様](../research/opencode/v2-capabilities.md) を参照。

#### 対処

`run_onchange_after_126_agent_cli.sh.tmpl`（Unix）が残骸を掃除し、shim を
「導入済み」と数えないようになったので、通常は `chezmoi apply` で解消する。

```bash
chezmoi apply
exec zsh                 # PATH を張り直す
command -v opencode      # ~/.opencode/bin/opencode であること
opencode --version       # v2.x であること
```

手で消す場合は次のとおり。`mise use -g` で足した宣言は `chezmoi apply` が戻す。

```bash
rm -f ~/.local/share/mise/shims/{claude,copilot,opencode,omp}
rm -rf ~/.local/share/mise/installs/{claude,claude-code,copilot,opencode,omp}
chezmoi apply
```

> [!NOTE]
> Windows 側（`run_onchange_after_314_agent_cli.ps1.tmpl`）は `Get-Command` で
> 判定しており、同じ掃除は入れていない。実機で確認できていないため。
> Windows で同じ症状が出たら `%LOCALAPPDATA%\mise\shims` を確認する。

### 14. `agent_cli.sh` が 403 で失敗する

```text
curl: (22) The requested URL returned error: 403
```

#### 原因

oh-my-pi のインストーラーが最新リリースを **GitHub API** から引くため。

```bash
curl -fsSL https://api.github.com/repos/${REPO}/releases/latest
```

未認証の GitHub API は **60 リクエスト/時**で、超えると 403 を返す。`-f` が
付いているので curl は失敗し、以前は呼び出し側の `set -euo pipefail` によって
**スクリプトごと中断**していた。その結果、後ろに並ぶ CLI が巻き添えで
入らなくなっていた。

#### 現在の挙動

`agent-cli-install.sh.tmpl` は CLI ごとに失敗を受け止めるので、1 つ 403 でも
残りは導入される。失敗した分は最後にまとめて報告される。

```text
⚠️  導入できなかった CLI: omp
⚠️  完了：一部の AI CLI が入っていません
```

**`chezmoi apply` 自体は成功する**（外部インストーラーの一時的な不調で
dotfiles の適用を止めないため）。

#### 対処

レート制限の残量を確認する。

```bash
curl -s https://api.github.com/rate_limit
```

`remaining` が 0 なら 1 時間ほどで戻る。待ってから再実行する。

```bash
chezmoi apply
```

急ぐなら手で入れる。

```bash
curl -fsSL https://omp.sh/install | sh
```

> [!NOTE]
> `run_onchange_` はスクリプト内容のハッシュで再実行を判定する。内容が変わって
> いないと再実行されないので、`chezmoi apply` で走らせ直したいときは
> `chezmoi state delete-bucket --bucket=scriptState` を使う（項目 2）。

### `apt update` が GitHub CLI で `NO_PUBKEY` 警告を出す

`gh` を mise 管理へ移す前に登録した APT リポジトリが残っていて、署名鍵が
失効している。症状は `apt update` のたびに次が出ること。

```text
GPG エラー: https://cli.github.com/packages stable InRelease:
  公開鍵を利用できないため、以下の署名は検証できませんでした: NO_PUBKEY ...
```

**chezmoi は自動で直さない。** 既存の APT 登録・鍵・認証設定は自動削除しない
方針のため（[mise による CLI 管理](structure.md#mise-による-cli-管理)）。
手で選ぶ。`gh` は mise から入るので、消しても困らない。

```bash
# 登録の場所を確認する
grep -rl 'cli\.github\.com' /etc/apt/sources.list.d/

# A) もう使わないので消す（mise 版の gh はそのまま使える）
sudo rm /etc/apt/sources.list.d/github-cli.list
sudo apt-get update

# B) APT 版の gh を使い続けるので鍵だけ入れ直す
wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg |
  sudo tee /usr/share/keyrings/githubcli-archive-keyring.gpg >/dev/null
sudo chmod 0644 /usr/share/keyrings/githubcli-archive-keyring.gpg
sudo apt-get update
```

どちらを選んでも `mise which gh` の結果は変わらない。

### `apt update` が VS Code のソース二重登録を警告する

`vscode.list`（`111_microsoft` が作る）と `vscode.sources`（`code` パッケージ
自身が置く deb822 形式）が競合している。**これは `chezmoi apply` が自動で直す**
（`121_ubuntu` が `.sources` のあるときに `.list` を削除する）。
手で消すなら次のとおり。

```bash
sudo rm -f /etc/apt/sources.list.d/vscode.list
sudo apt-get update
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
