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
