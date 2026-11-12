# Dotfiles

[![linux](https://github.com/applejxd/dotfiles/actions/workflows/linux.yml/badge.svg)](https://github.com/applejxd/dotfiles/actions/workflows/linux.yml)
[![windows](https://github.com/applejxd/dotfiles/actions/workflows/windows.yml/badge.svg)](https://github.com/applejxd/dotfiles/actions/workflows/windows.yml)

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
> 引き継ぐ（[chezmoi 本体](docs/spec/cli-management.md#chezmoi-本体)）。

```powershell
# Windows (PowerShell)
winget install --id Python.Python.3.12 --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
winget install --id Git.Git --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
winget install --id twpayne.chezmoi --exact --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned   # Restricted のままだと chezmoi が .ps1 を実行できない
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

`apply` で入るツール（gh、Herdr、pi）と
その更新方法は [プロジェクト構造](docs/spec/structure.md) を参照。

- [mise による CLI 管理](docs/spec/cli-management.md#mise-による-cli-管理)（gh など）
- [pi の導入](docs/spec/cli-management.md#pi-の導入)
- [Herdr の管理](docs/spec/cli-management.md#herdr-の管理)
- [pi の設定の生成と所有権](docs/spec/agent-config-generation.md)・[pi の独自コマンド](docs/spec/pi-commands.md)

### Raspberry Pi (64bit / ヘッドレス)

手順は Ubuntu / WSL と同じ。Raspberry Pi かどうかは `apply` のたびに自動判定される
（`chezmoi init` は不要）。32bit (armhf) は対象外。

```bash
chezmoi execute-template '{{ includeTemplate "is-raspi" . }}'   # true なら分岐が有効
```

導入されないもの・判定の仕組み・入ってしまった GUI 一式の消し方は
[Raspberry Pi](docs/spec/platform-raspberry-pi.md#raspberry-pi) を参照。

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

### 囲い付きの pi（Ubuntu / WSL）

```bash
pib         # 囲いの内側で pi を起動する（作業ディレクトリ以外の書き込み・秘密の読み取りを OS が止める）
pi          # 通常起動（囲いなし。確認は permission-system が行う）
```

- 作業対象のディレクトリで起動する。起動のしかた・隠す場所と見せる場所・確かめ方（`pib --status`）は
  [pi-sandbox-runner](docs/spec/sandbox/pi-sandbox-runner.md)。

## 安全上の注意

- **`chezmoi apply` は境界の外で、人間が実行する。** `chezmoi diff` を最初の審査に
  使わない（テンプレートが外部コマンドを実行する。
  [`chezmoi apply` は人間が行う](docs/spec/security.md#chezmoi-apply-は人間が行う)）
- 境界（OS が強制するアクセス境界）が守るもの・守らないものは
  [何を守り、何を守らないか](docs/spec/security.md#何を守り何を守らないか)

## ドキュメント

詳細な仕様、運用手順、ADR、調査記録は [ドキュメント一覧](docs/index.md) から、
目的別には [目的から探す](docs/index.md#目的から探す) から参照できます。
テストの入口は [test/README.md](test/README.md)。

## FAQ

### Q. `chezmoi apply` / `chezmoi update` が途中で止まった

A. [トラブルシューティング](docs/spec/troubleshooting.md) で症状から探す。

### Q. 依存関係のスクリプトを飛ばして設定ファイルだけ反映したい

A. `chezmoi apply --exclude=scripts` を使う
（[スクリプトの無効化](docs/spec/development.md#スクリプトの無効化)）。
zinit などの external は除外されない。

### Q. sudo が使えない機械で apply / update したい

A. `CHEZMOI_NO_SUDO=1 chezmoi apply`（`update` も同じ）。Linux / WSL のみ。
root が要るスクリプトは飛ばし、sudo が使えるようになった次の apply で走る
（[sudo 無しモード](docs/spec/development.md#sudo-無しモード)）。

### Q. 「zinit が無いためプラグインを読み込みません」と出る

A. `chezmoi apply --refresh-externals` を実行する
（[external が取得されない](docs/spec/troubleshooting-bootstrap.md#apply-しても-zinit-などの-external-が取得されない)）。

### Q. PC ごとに違う設定（データセットの置き場・プロキシ・囲いの許可など）を、chezmoi の管理と分けて置きたい

A. 共有の設定はこのリポジトリ（chezmoi が管理）に置き、PC ごとの設定は **chezmoi の管理外のファイル**に書く。
後者は `chezmoi apply` で消えず、`chezmoi diff` にも出ない。生成された設定（`~/.pi/agent/settings.json` など）は、宣言した項目だけを `chezmoi apply` が更新する。
囲いの許可を足すもの（`runner.local.toml`）は、共有の設定に**足すだけ**で、
緩める指定は効かない（無視されるか、起動しない）。git の `config.local` のように、共有の設定を上書きできるものもある。

| 変えたいもの | このマシンだけの置き場 | 反映 |
| --- | --- | --- |
| 環境変数・プロキシ・データセットの置き場 | `~/.config/shell/userenv.sh`（同じ場所の `.example` から作る） | 次のシェルの起動 |
| chezmoi のテンプレートに渡す値 | `~/.config/chezmoi/chezmoi.toml` の `[data]` | `chezmoi apply` |
| git の設定 | `~/.config/git/config.local` | すぐ |
| mise の設定 | `~/.config/mise/conf.d/*.toml` | 次の mise の実行 |
| pi の囲い（`pib`）で、隠す場所・見せる場所（データセットなど）の追加（Linux / WSL） | `~/.config/pi-sandbox/runner.local.toml`（同じ場所の `.example` から作る）。効いているかは `pib --status` で確かめる（存在しない場所に `✗`） | 次のコマンドの実行 |
| pi の確認（YOLO など） | `/permission-system` | すぐ（`apply` で戻らない） |

置き場ごとの書き方と注意は
[マシン固有の設定の置き場](docs/spec/shell.md#マシン固有の設定の置き場)。

### Q. pi の設定を手で変えたい

A. 宣言した項目（`~/.pi/agent/settings.json`・`mcp.json` など）は `chezmoi apply` が更新し、宣言していない項目と利用者が足した項目は保つ。
変え方と所有権は [pi の設定の生成と所有権](docs/spec/agent-config-generation.md)。確認の設定（YOLO など）は `/permission-system`（機械ごとで、apply では戻らない）。

### Q. Bedrock だと Web 検索ができない

A. [AgentCore Web Search](docs/spec/mcp-servers.md#agentcore-web-search) を参照。

### Q. piで確認（ask）が出ない・出してほしい確認が出ない

A. YOLO が入っていると、確認は全部自動で承認される（deny だけが効く）。`/permission-system` で YOLO を OFF にする
（[YOLO mode](docs/spec/agent-config-generation.md#permission-system-の設定)。機械ごとの設定で、apply では戻らない）。

### Q. piの確認で、自律稼働が止まる（待たされる）

A. 誰も答えない確認は 5 分で拒否され、エージェントは先へ進む（`promptTimeoutMs`）。頻度を減らす方針と実測は
[確認で待たせない方針](docs/spec/agent-config-generation.md#permission-system-の設定)。YOLO を入れると確認は全部自動承認になる（強制 ask も効かない）。

### Q. piが作業ツリー外のデータセットを読むたびに確認される

A. プロジェクトごとに、読み取りだけを事前許可できる（`/tmp` はグローバルで許可済み）。`pib` で起動したときは、プロジェクトの `.pi/` の設定を読まない（`--no-approve`）ので、見せたい場所を `~/.config/pi-sandbox/runner.local.toml` の `[visible]` に足す。手順は
[プロジェクト単位でデータセットを読み取り専用にする](docs/spec/agent-config-generation.md#プロジェクト単位でデータセットを読み取り専用にする)。

### Q. 外出先から WSL に SSH したい

A. Tailscale 経由で、Windows で `tailscale serve --bg --tcp 50022 tcp://localhost:50022` を 1 回実行する
（WSL の sshd を 50022 にし、公開鍵を入れる前提。手順と復旧時の順番は
[リモートから WSL へ SSH する](docs/spec/platform-wsl.md#リモートから-wsl-へ-ssh-する)、
つながらないときは[切り分け](docs/spec/platform-wsl.md#接続できないときの切り分け)）。

## ライセンス

MIT License
