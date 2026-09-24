# Dotfiles

chezmoi を使用した個人用 dotfiles 管理リポジトリ。Windows/Ubuntu/WSL/macOS に対応。

## 特徴

- **クロスプラットフォーム対応**: Windows/Ubuntu/WSL/macOS で動作
- **自動セットアップ**: OS固有の依存関係を自動インストール
- **セキュアな設定管理**: Bitwarden 連携と sops (age) による機密情報保護

## クイックスタート

### インストール

```bash
# Ubuntu / WSL (公式インストーラ。sudo 不要)
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"

# macOS
brew install chezmoi
```

> **snap 版は使わない。** snap の confinement 下では
> [AI CLI の sandbox](docs/change/0004-opencode-sandbox.md) の内側で
> 起動できず、`chezmoi apply` が失敗する（実測）。
>
> **上記は初回の bootstrap だけ。** 以降は mise が
> `chezmoi = "latest"` で管理を引き継ぐ（`config.toml.tmpl`）。
> `chezmoi apply` 後は mise 版が使われるため、`~/.local/bin` の
> コピーは残さなくてよい。
>
> 既に snap 版が入っている場合は `sudo snap remove chezmoi` で外す。
> `/snap/bin` は PATH で mise の shim より前に来るため、**消さないと
> mise 管理版が使われない**。削除後は `hash -r` を実行する。

```powershell
# Windows (PowerShell)
winget install Python.Python.3.12 twpayne.chezmoi --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
```

Windows では chezmoi の設定生成と agent hook に **Python 3.11 以上**が必要。
`py -3` でインストール済みの最新 Python 3 を選ぶため、Python 3.10 以下だけの
環境では上記の Python 3.12 を先に導入する。追加の `pip install tomli` は不要。

> Bitwarden CLI (`bw`) は **事前インストール不要**。`chezmoi apply` 中に
> Windows では Winget (`Bitwarden.CLI`)、Unix では mise
> (`npm:@bitwarden/cli`) 経由で自動投入される。
> bw が必要なテンプレート展開は、bw 取得後に `chezmoi init` / `chezmoi apply`
> を再実行することでフェーズ 2 として反映される。Windows では gitconfig の
> user セクション、Unix では加えて sops の age 鍵が対象になる。

### 初期化と適用（2 フェーズ bootstrap）

```bash
# フェーズ 1: bw 不在のまま初期化・適用
chezmoi init applejxd     # bw 不在ガードにより bitwarden 関連はスキップされる
chezmoi apply             # bw を含むツール一式がここで入る

# フェーズ 2: bw が使えるようになったので Bitwarden 連携を有効化
bw login
# PowerShell: $env:BW_SESSION = bw unlock --raw
# POSIX shell: export BW_SESSION="$(bw unlock --raw)"
chezmoi init applejxd     # .chezmoi.toml を bw 有り状態で再生成 (bitwarden.unlock="auto")
chezmoi apply             # gitconfig user セクション、Unix では sops age 鍵も反映
```

依存関係スクリプトをスキップしたい場合は `chezmoi apply --exclude=scripts`。

### GitHub CLI の mise 管理

GitHub CLI (`gh`) は Windows / Linux / WSL / macOS 共通で
`~/.config/mise/config.toml` の `gh = "latest"` から導入します。
Ubuntu の個別 APT 導入処理は使わず、既存の一括 `mise install` に任せます。
更新はホームディレクトリで `mise upgrade gh` を実行してください。
認証設定は変更しません。Git 本体の導入方法も従来どおりです。

### AI CLI (Claude Code / Copilot CLI / OpenCode V2) の導入

3 つの AI CLI は **各社公式のインストーラー**で導入します。mise では管理しません。

| OS | Claude Code | Copilot CLI | OpenCode V2 |
| --- | --- | --- | --- |
| Linux / WSL / macOS | `curl -fsSL https://claude.ai/install.sh \| bash` | `curl -fsSL https://gh.io/copilot-install \| bash` | `curl -fsSL https://opencode.ai/v2/install \| bash` |
| Windows | `irm https://claude.ai/install.ps1 \| iex` | `winget install GitHub.Copilot` | `npm install -g @opencode/cli` |

Windows で手段が分かれるのは、Claude の `install.sh` が Windows を明示的に拒否し、
Copilot の公式スクリプトが Windows では winget へ委譲し、OpenCode V2 には
PowerShell インストーラーも Windows パッケージマネージャーも無いためです。

実行するのは `100_linux/126_agent_cli`、`200_mac/226_agent_cli`、
`300_windows/310_packages/314_agent_cli` です。
**既に入っている CLI は触りません**（`command -v` / `Get-Command` で判定）。

Linux / WSL / macOS は 3 つとも、Windows は Copilot CLI と OpenCode V2 を導入し、
`applejxd` 以外では Claude Code も導入します。既存の OS / username 別の
導入範囲は変えません。OpenCode のインストーラーは `--no-modify-path` で起動し、
`~/.opencode/bin` の PATH は `~/.config/shell/shellenv.sh` 側で通します
（インストーラーに `.zshrc` を書き換えさせないため）。

CLI 自身の自動更新は `common.toml` から無効化しています。更新は手動です。
（Claude は `env.DISABLE_AUTOUPDATER`、Copilot は `autoUpdate`、
OpenCode は `update = "disable"` へ展開されます。）

```bash
claude update                                          # Claude Code
curl -fsSL https://gh.io/copilot-install | bash        # Copilot CLI
opencode upgrade                                       # OpenCode V2
```

```powershell
claude update
winget upgrade --id GitHub.Copilot --exact
npm update -g '@opencode/cli'
```

旧 mise 版（`mise install claude-code` / `copilot`）からの移行手順は
[AI CLI の導入](docs/spec/structure.md#ai-cli-の導入)を参照してください。

### oh-my-pi (`omp`) — 試用中

Linux / WSL / macOS では `omp` も導入します（`curl -fsSL https://omp.sh/install | sh`）。
Pi のフォークで、LSP 統合・DAP・subagent を持ちます。

```bash
omp        # 起動。境界 (ocs) の外で動く
```

**`omp` は `~/.claude` を設定探索ルートに含みますが、他ツールのユーザ領域は
既定で 1 つも読みません**（`enabledProviders` の既定が空）。
`chezmoi apply` が次の 3 つを設定するので、既存の資産がそのまま使えます。

| 設定 | 繋がるもの |
| --- | --- |
| `skills.customDirectories` | `~/.claude/skills` の自作 skills 16 個 |
| `enabledProviders: [claude]` | `~/.claude.json` の MCP サーバ定義、`~/.claude/commands` |
| `commands.enableClaudeUser` | `/ask` `/commit` `/criticalthink` `/onboarding` |

あわせて `bashInterceptor.enabled` を有効にし、`cat` / `grep` / `sed -i` などを
`read` / `grep` / `edit` へ誘導します（他の CLI と挙動を揃えるため）。
**真偽値の 2 つは初回のみ設定**し、以後 `omp config set` や `/settings` で
変えた値は上書きしません（`~/.omp/agent/.chezmoi-seeded` で管理）。

> **permission 機構を持たない設計です。** Pi 系は安全性より利便性を取る方針で、
> 権限制御は拡張か外部の sandbox に委ねます。保護は「どこで起動するか」と
> git の使い方に依存します。**対象リポジトリ直下で起動し、開始前に作業を
> 区切ってコミットしてください。**
> 経緯と代償の一覧は [CHG-0006](docs/change/0006-pi-harness-trial.md) にあります。

### Herdr と agent integration

Windows native、Linux、WSL では、`chezmoi apply` 時に **mise** で Herdr を
ユーザースコープへ導入します。`~/.config/mise/config.toml` の `herdr = "latest"` を
使い、mise の aqua backend が公式 GitHub Releases のバイナリを取得します。
Windows ではこの設定に gh と Herdr を配備し、Unix 専用ツールは導入しません。
macOS は従来どおり Herdr の自動導入対象外です。

agent integration は設定ファイルの配備後に毎回冪等に再適用されます。

| chezmoi username | integration | 前提となる agent CLI |
| --- | --- | --- |
| `applejxd` | GitHub Copilot CLI | 公式インストーラーで導入 |
| その他 | Claude Code | 公式インストーラーで導入 |

Herdr は `~/.copilot/settings.json` または `~/.claude/settings.json` の既存設定を保持し、
Herdr 管理の hook entry だけを追加・更新します。現在の状態は次で確認できます。

```bash
herdr integration status
```

同じ `run_after` スクリプトが `herdr --skill` からリリース一致版の agent skill を生成し、
`~/.claude/skills/herdr/SKILL.md` に配置します。Copilot CLI は
`~/.copilot/skills` の symlink / junction を通じて同じスキルを参照します。
`chezmoi apply` のたびに再生成されるため、Herdr 本体の更新後もスキルが追従します。

初回適用後に `herdr` が見つからない場合は、新しいターミナルを開いてください。
以後は `herdr update` ではなく、mise で本体を更新してから integration と skill を
再生成します（ホームディレクトリで実行）。

```bash
mise upgrade herdr
chezmoi apply
```

旧インストーラー版が残っている場合の確認・移行手順は
[Herdr の管理](docs/spec/structure.md#herdr-の管理)を参照してください。

Windows ARM64 では、Herdr 公式の x86_64 ビルドが Windows のエミュレーション上で動作します。

### 更新

```bash
# 最新版に更新
chezmoi update

# または段階的に
chezmoi pull && chezmoi diff && chezmoi apply
```

`chezmoi update` 後に zinit 管理プラグイン (zeno.zsh など) も最新化したい場合は次のタスクを実行する。
chezmoi 自体はプラグインキャッシュに干渉しないため、手元の `~/.zinit/plugins/...` を refresh するための明示コマンド。zeno の deno モジュールキャッシュ再生成と zinit completions の宙ぶらりんリンク掃除も同時に行う。

```bash
mise run dotfiles-update
```

### 手動セットアップ (Linux / WSL2 で Claude Code を使う場合)

Claude Code の sandbox が使う seccomp フィルタだけは、chezmoi でも mise でも
導入できないため手で入れる。

```bash
npm install -g @anthropic-ai/sandbox-runtime
```

- **なぜ mise ではないか**: Claude はこのバイナリを npm のグローバル領域
  (`npm -g config get prefix` 配下の `lib/node_modules` など) でしか探さない。
  mise の `npm:` バックエンドはパッケージを独自ディレクトリへ隔離するため
  検出されない。
- **なぜ自動化しないか**: `npm install -g` はエージェントに対して
  `[bash] deny` で禁止している (システム全体を汚すため)。
- **入れないとどうなるか**: WSL2 では Windows バイナリ (`cmd.exe` や
  `/mnt/c/...`) の起動が Unix domain socket 経由になるので、フィルタが無いと
  sandbox 内から Windows 側のプロセスを起動して**脱出できる**。
  未導入時、Claude は起動時に `apply-seccomp binary not available -
  unix socket blocking disabled` を表示する。

詳細は [docs/spec/agent-permissions.md](docs/spec/agent-permissions.md) を参照。

## 基本的な使用方法

### 隔離版 OpenCode（Ubuntu / WSL）

OS のアクセス制御で囲った OpenCode を起動します。通常版と**併用**する段階で、
既定はまだ通常版です（[CHG-0004](docs/change/0004-opencode-sandbox.md)）。

```bash
ocs         # 境界の内側で起動する
opencode    # 素の OpenCode（境界なし）
```

`~/.local/bin` は PATH に入っているのでフルパスは要りません。
中身は `opencode --standalone` を境界の内側で起動するラッパーです。
`ocs` へ渡した引数はそのまま OpenCode へ届きます（`ocs --continue` など）。

> **起動ディレクトリで境界が決まります。** その配下が読み書き可能になるので、
> **作業対象のディレクトリで起動してください**。`~` や `/tmp` そのもので起動
> しようとすると、保護を打ち消すため**起動を断ります**。

起動前に境界チェックが走り、**1 つでも通ってはいけない操作が通ったら起動しません**。
同じ入力での合格は 24 時間だけ再利用します（`--recheck` でやり直し）。

起動のたびに、**作業ツリーを境界の外へ退避します**。

- 退避先は `~/.local/state/opencode-sandbox/backups/` で、**境界の内側から触れません**
- **作業ツリーは変更しません**（`git stash` とは別物。再開時に変更が巻き戻ることはない）
- `.gitignore` が効くので、隔離用 DB や `.tmp/` は入りません
- 内容が同じなら作り直さないので、中断と再開を繰り返しても溜まりません
- 退避できなかったときは**起動しません**（`--no-backup` で承知のうえ続行）

容量の上限は次のとおりです。

| 対象 | 上限 |
| --- | --- |
| 退避対象の作業ツリー | 256 MiB（超えたら退避せず、起動も断る） |
| 起動ディレクトリごと | 5 世代 / 128 MiB |
| **全体** | **1 GiB**（プロジェクトが増えても青天井にしない） |
| 保持期間 | 30 日 |

> 大きさは **`git add` の前に**測ります。作ってから間引くと、巨大なリポジトリで
> `.git` を肥大させたうえに時間を使うためです。

戻すときは tar として展開するだけです。`.git` は要りません。

```bash
tar xzf ~/.local/state/opencode-sandbox/backups/<リポジトリ>/<日時>-<tree>.tgz -C <復元先>
```

**起動ディレクトリ以下は無条件に読み書きできます。** どこで起動するかは利用者の
責務です。それ以外を開けたいときだけ、プロジェクトに要求ファイルを置きます。

```toml
# <プロジェクト>/.opencode/sandbox.toml
read = ["/mnt/d/datasets/example"]
write = ["/mnt/d/outputs/example"]
network_allow = ["api.example.com"]
```

要求は**そのままでは効きません**。初回起動時に内容が表示され、承認して初めて
通ります（記録は `~/.local/state/opencode-sandbox/trusted.json`）。
**要求が 1 文字でも変われば再承認**です。非対話で通すには `--trust` を付けます。

> リポジトリは「要求」できるが「付与」はできない、という形にしています。
> 要求だけで通すと、敵対的なリポジトリが `~/.ssh` を自分で開けられます。

| 守られるもの | 守られないもの |
| --- | --- |
| `~/.ssh` などホストの秘密、Windows 側（`/mnt`）、ホストの `/tmp` | **ワークスペースの中**（`.env`・`.git/hooks` は shell から届く） |
| 許可ドメイン以外への通信 | 未コミット作業とローカル履歴（失いうる） |

`~/.config/opencode-sandbox/` の設定は起動のたびに作り直されます。
**境界の内側からは書けません。**

> **`chezmoi apply` は境界の外で、人間が実行します。** 変更されたコードを
> ホスト権限へ移す操作なので、適用前に審査してください。
> **`chezmoi diff` を最初の審査に使わないこと。** テンプレートを評価するため、
> `output` 関数が外部コマンドを実行します。まずテンプレートを評価せずに読み、
> その後で `chezmoi diff` を使います。

### 設定ファイルの編集

```bash
# chezmoi経由での編集 (推奨)
chezmoi edit ~/.bashrc

# 実ファイルを直接編集した場合の反映
chezmoi add ~/.bashrc

# 管理対象ファイルのうち、実ファイル側で変更があったものをすべて更新 (re-add)
chezmoi re-add

# 変更の確認
chezmoi diff

# 適用
chezmoi apply
```

## ドキュメント

詳細な仕様、運用手順、ADR、調査記録は
[ドキュメント一覧](docs/index.md) から参照できます。

## ライセンス

MIT License
