# Dotfiles

chezmoi を使用した個人用 dotfiles 管理リポジトリ。Windows/Ubuntu/WSL/macOS に対応。

## 特徴

- **クロスプラットフォーム対応**: Windows/Ubuntu/WSL/macOS で動作
- **自動セットアップ**: OS固有の依存関係を自動インストール
- **セキュアな設定管理**: Bitwarden 連携と sops (age) による秘密情報の保護

## クイックスタート

### インストール

```bash
# Ubuntu / WSL (公式インストーラ。sudo 不要)
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"

# macOS
brew install chezmoi
```

> **snap 版は使わない。** 既に入っている場合は `sudo snap remove chezmoi` で外し、
> `hash -r` を実行する。上記は初回の bootstrap だけで、以降は mise が管理を
> 引き継ぐ（[chezmoi 本体](docs/spec/structure.md#chezmoi-本体)）。

```powershell
# Windows (PowerShell)
winget install Python.Python.3.12 twpayne.chezmoi --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
```

Windows では **Python 3.11 以上**が必要（`py -3` で最新の Python 3 を選ぶ。
[ADR-0003](docs/adr/0003-require-python-311-for-agent-configuration.md)）。
3.10 以下しか無い環境では、上記で Python 3.12 を先に入れる。

### 初期化と適用（2 フェーズ bootstrap）

Bitwarden CLI (`bw`) は事前インストール不要で、1 回目の `apply` 中に入る。
Bitwarden 由来のファイル（Git の user 情報、sops の age 鍵）は 2 回目で入る。
対象は個人用ユーザの機械で、Windows native で入るのは Git の user 情報だけ
（[Bitwarden 連携](docs/spec/security.md#bitwarden連携)）。

```bash
# フェーズ 1: bw 不在のまま初期化・適用
chezmoi init applejxd     # Bitwarden 由来のファイルはスキップされる
chezmoi apply             # bw を含むツール一式がここで入る

# フェーズ 2: セッションを渡して Bitwarden 由来のファイルを反映
bw login
export BW_SESSION="$(bw unlock --raw)"   # PowerShell: $env:BW_SESSION = bw unlock --raw
chezmoi init applejxd     # bw がある状態で設定を作り直す (bitwarden.unlock="auto")
chezmoi apply
```

鍵の復旧条件と確認方法は [秘密情報の管理セットアップ](docs/spec/sops-age.md#8-新しい-pcwsl-環境で復旧する)。

依存関係スクリプトを飛ばす方法は [スクリプトの無効化](docs/spec/development.md#スクリプトの無効化)。

`apply` で入るツール（gh、Herdr、AI CLI、oh-my-pi、Claude Code の seccomp フィルタ）と
その更新方法は [プロジェクト構造](docs/spec/structure.md) を参照。

- [mise による CLI 管理](docs/spec/structure.md#mise-による-cli-管理)（gh、seccomp フィルタ）
- [AI CLI の導入](docs/spec/structure.md#ai-cli-の導入)（Claude Code / Copilot CLI / OpenCode V2、oh-my-pi）
- [Herdr の管理](docs/spec/structure.md#herdr-の管理)

### Raspberry Pi (64bit / ヘッドレス)

手順は Ubuntu / WSL と同じ。Raspberry Pi かどうかは `apply` のたびに自動判定される
（`chezmoi init` は不要）。32bit (armhf) は対象外。

```bash
chezmoi execute-template '{{ includeTemplate "is-raspi" . }}'   # true なら分岐が有効
```

導入されないもの・判定の仕組み・入ってしまった GUI 一式の消し方は
[Raspberry Pi](docs/spec/structure.md#raspberry-pi) を参照。

### 更新

```bash
# 最新版に更新
chezmoi update

# または段階的に
chezmoi pull && chezmoi diff && chezmoi apply
```

zinit 管理のプラグイン (zeno.zsh など) も最新化したい場合は次のタスクを実行する
（zinit 本体は `chezmoi apply` が初回だけ取得し、以降の更新はしない）。

```bash
mise run dotfiles-update
```

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

### 隔離版 OpenCode（Ubuntu / WSL）

```bash
ocs         # 隔離起動（境界の内側で起動する）
opencode    # 通常起動（境界なし）
```

- **作業対象のディレクトリで起動する。** その配下が読み書き可能になる。
  `~` や `/tmp` そのものでは起動を断る
- 境界は Fence（mise が入れる）で張る。入っていなければ `mise install` の後に
  `chezmoi apply` する。境界を確かめるときは `ocs --check`
- 履歴は通常起動と共有する。内側のセッションは外の `opencode -s <ID>` で再開できる。
  起動のたびに作業ツリーを境界の外へ退避する（復元は
  [OpenCode 隔離起動](docs/spec/opencode-sandbox.md) を参照）
- 起動ディレクトリの外を開けたいときは、プロジェクトに `.opencode/sandbox.toml` を置く
  （書き方は[プロジェクトごとの追加](docs/spec/opencode-sandbox.md#プロジェクトごとの追加)）

## 安全上の注意

- **`chezmoi apply` は境界の外で、人間が実行する。** `chezmoi diff` を最初の審査に
  使わない（テンプレートが外部コマンドを実行する。
  [`chezmoi apply` は人間が行う](docs/spec/security.md#chezmoi-apply-は人間が行う)）
- 境界（OS が強制するアクセス境界）が守るもの・守らないものは
  [何を守り、何を守らないか](docs/spec/security.md#何を守り何を守らないか)
- **`omp`（oh-my-pi、試用中）は permission 機構を持たない。** 対象リポジトリ直下で
  起動し、開始前に作業を区切ってコミットする
  （[oh-my-pi の設定](docs/spec/structure.md#oh-my-piompの設定)）

## ドキュメント

詳細な仕様、運用手順、ADR、調査記録は [ドキュメント一覧](docs/index.md) から、
目的別には [目的から探す](docs/index.md#目的から探す) から参照できます。
テストの入口は [test/README.md](test/README.md)。

## FAQ

### Q. `chezmoi apply` / `chezmoi update` が途中で止まった

A. [トラブルシューティング](docs/spec/troubleshooting.md) で症状から探す。

### Q. AI CLI の設定（OpenCode のモデル・プロバイダを含む）を手で変えたい

A. 生成された設定ファイルは直接編集せず、次のどちらかで変える。

- 全マシン共通: `home/dot_config/agents/common.toml.tmpl` を編集する
  （[設定の生成と所有権](docs/spec/agent-config-generation.md)）
- このマシンだけ: プロバイダは `chezmoi.toml` の `[data]` に `llm_provider` を書く
  （[プロバイダの判定](docs/spec/agent-config-generation.md#プロバイダの判定)）。
  sandbox の許可は `~/.config/agents/local.toml` に足す
  （[このマシンだけで許可を足す](docs/spec/agent-sandbox.md#このマシンだけで許可を足す-chezmoi-管理に影響を与えない)）

### Q. Bedrock だとハーネスで Web 検索ができない

A. [AgentCore Web Search](docs/spec/agent-config-generation.md#agentcore-web-search) を参照。

### Q. OpenCode で確認されるはずの操作が確認なしで実行される

A. 以前「常に許可」した承認が残っている。
[保存した承認の確認とリセット](docs/spec/agent-permissions.md#保存した承認の確認とリセット) を参照。

## ライセンス

MIT License
