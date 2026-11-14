# プロジェクト構造

## ディレクトリ構成

```text
.
├── config/                    # アプリケーションへマージする共有設定
├── docs/
│   ├── adr/                   # アーキテクチャ決定記録
│   ├── research/              # 調査・比較・検証記録（対象ごとにサブディレクトリ）
│   ├── spec/                  # 現在有効な仕様と運用手順
│   └── index.md               # ドキュメント入口
├── home/                      # chezmoiのsource state（.chezmoirootで指定）
│   ├── .chezmoiscripts/       # `chezmoi apply` 時の自動実行
│   ├── .chezmoitemplates/     # スクリプト・modify処理の共有テンプレート
│   ├── dot_config/            # `~/.config/` 配下へ展開する設定
│   └── dot_local/bin/         # `~/.local/bin/` へ展開する手元のコマンド（`pk`、`pib`・`pib-shell`・`pi-sandbox-runner`）
├── scripts/                   # 個別用途の導入・生成・検証・保守用スクリプト
├── test/                      # pytest・コンテナ検証
├── mise.toml                  # 開発ツールとタスク
└── pyproject.toml             # Python依存とlint設定
```

chezmoiの管理対象は `home/` 配下です。リポジトリ直下の `config/`、
`scripts/`、`test/`、`docs/` は導入・生成処理・開発・説明資料に使用します。

## Git 設定の管理 {#gitconfig-の管理}

- chezmoi が管理するのは `~/.config/git/config`（`home/dot_config/git/config.tmpl`）。`~/.gitconfig` は管理しない。
- git は両方を読み、同じキーでは `~/.gitconfig` が勝つ。CLI の `git config --global` は `~/.gitconfig` が既にあればそこへ書く。
  XDG 側だけがあるとその管理ファイルへ書いてしまい、`chezmoi update` の上書き確認の原因になる。
- そのため `home/create_dot_gitconfig`（`create_` は無いときだけ作る）が空の `~/.gitconfig` を用意し、CLI の書き込み先を固定する。
- ローカルの上書きは `~/.config/git/config.local`、`[user]` は `~/.config/git/user`（Bitwarden 由来。[security.md](security.md)）。
- 旧構成の `~/.gitconfig` は `000_unix/run_once_before_006_gitconfig_migrate.sh`（Windows は `300_windows/run_once_before_300_gitconfig_migrate.ps1`）が
  `.chezmoi-old` へ退避する。目印の行が無いファイルには触らない。
- pi の書き込み禁止は `~/.gitconfig`・`~/.config/git/config`・`~/.config/git/config.local`（`pi-permission-policy.json` の `path_write`）。

## 自動実行スクリプト

`home/.chezmoiscripts/` はOSと実行順で分割しています。

| 範囲 | 対象 | 主な役割 |
| --- | --- | --- |
| `000_unix/` | Linux / macOS | Python 3.11 以上の確保と旧 `~/.gitconfig` の退避（ファイル適用より前）、zinit補完の保守 |
| `100_linux/` | Ubuntu / WSL | OSパッケージ、mise、shell、pi の導入 |
| `200_mac/` | macOS | sudo の Touch ID、Homebrew、mise、macOS defaults |
| `300_windows/` | Windows native | 旧 `~/.gitconfig` の退避、Winget/Scoop/Chocolatey、レジストリ、Terminal、pi の確認 |
| `400_unix/` | Linux / macOS | 鍵・認証の同期（authorized_keys・検索の鍵・Hugging Face） |

スクリプト名は `run_once_XXX_name`、`run_onchange_XXX_name`、
`run_after_XXX_name` などのchezmoi属性と3桁番号で順序を管理します。
同じ `before` / `after` 内ではディレクトリを含むパス順です。

- `run_once_`: 同じ内容が成功済みなら再実行しない
- `run_onchange_`: 内容が変わった場合に再実行する
- `run_after_`: ファイル展開後、applyのたびに実行する
- `.tmpl`: OS分岐、chezmoiデータ、秘密情報が必要な場合のみ使用する

## source 側の残骸の掃除

`home/.chezmoiremove` に載った対象（例 `.config/pi`）と同名の source ディレクトリ（`home/dot_config/pi/`）が、
Git 管理外の残骸（`__pycache__` など。`.gitignore` 済みで git が消さない）として残ると、
`chezmoi apply` / `update` は `inconsistent state (…, remove)` で全体が止まる（配備先に対象があるとき）。
`run_before_` のスクリプトでは、chezmoi の事前チェックが先に止まるため防げない。

`chezmoi.toml` の `[hooks.read-source-state.pre]` が、source を読む前に `scripts/clean_stale_source.py` を呼ぶ
（`home/.chezmoi.toml.tmpl` が生成する。スクリプトは source ルートの `scripts/` にあり、絶対パスで呼ぶ）。

- 対象は `.chezmoiremove` の全エントリ。`dot_`・`private_`・`exact_` などの接頭辞は無視して source を探す。
  テンプレート記法（`{{ }}`）・`!` 否定・glob の行は解釈できないので読み飛ばす（消さない側に倒す）
- 追跡ファイルも、未追跡で ignored でないファイルも無いディレクトリ (ignored な残骸だけ) を消す。残すべきファイルがあれば消さず、標準エラーへ警告する（exit 0）。`literal_` 以降の名前は解釈しない。git の呼び出しでは `GIT_*` 環境変数を除く。
  git で確かめられない・source が git 管理外のときも消さず警告だけ
- 消すのは `home/` 配下のディレクトリだけで、シンボリックリンクは辿らない。`--dry-run` で消さずに対象を表示できる
- フックが失敗しても apply は止めない（`|| true`）
- **既存のホストは `chezmoi init` を 1 回実行する**（フックは `chezmoi.toml` にあり、`update` は `init` を呼ばないため）。
  それまでは従来どおり、残骸を手で消す（`rm -rf ~/.local/share/chezmoi/home/dot_config/pi`）
- Windows は、フックを生成しない。実機で未検証のため（quoting と `py` の扱いを確かめてから足す）

標準機能に該当するものは無かった（chezmoi に source 側の無視・掃除の仕組みが無い。[ADR-0031](../adr/0031-evaluate-existing-extensions-first.md)）。
維持費は約 150 行の Python と試験（`test/test_clean_stale_source.py`）。
**撤去**: `.chezmoiremove` を廃止したとき、または chezmoi 本体が残骸を扱えるようになったとき、
スクリプト・試験・`verify.py` の規則・`.chezmoi.toml.tmpl` のフック・この節を消す。

## 対応環境

| 環境 | 主な導入経路 |
| --- | --- |
| Windows native | Winget、Scoop、Chocolatey、mise（gh / Herdr / node / uv / fzf / jq）、AI CLI の公式手段（[AI CLI の導入](cli-management.md#pi-の導入)）、PowerShell |
| Ubuntu | apt、mise |
| WSL | Windows連携設定、apt、mise |
| Raspberry Pi（64bit / ヘッドレス） | apt、mise（GUI・VS Code・ソースビルドを除く） |
| macOS | Homebrew、mise |

OSごとの差分は `.chezmoiignore.tmpl`、テンプレート条件、OS別スクリプトで
吸収します。秘密情報はソースへ直接書かず、Bitwardenとsops/ageを使用します。

## 話題別の文書

この文書は、ディレクトリ構成・自動実行スクリプトの順序・対応環境の地図です。話題ごとの仕様は次の文書にあります（2026-10-26 に、1 つの長い文書から分けた）。

| 話題 | 文書 |
| --- | --- |
| Raspberry Pi への導入（ruby のプレビルド・clang・OOM・GUI の削除） | [Raspberry Pi](platform-raspberry-pi.md) |
| WSL の時刻同期・リモートからの SSH（Tailscale） | [WSL](platform-wsl.md) |
| Windows の管理者権限を 1 回の UAC に集約する仕組み | [Windows の管理者権限](windows-admin.md) |
| Windows の設定（電源・Tailscale・7-Zip・広告・既定値・Windows Terminal） | [Windows の設定](windows-settings.md) |
| mise・AI CLI・Herdr・Envoy の導入と更新 | [CLI の導入と管理](cli-management.md) |
| シェルの起動契約・マシン固有の設定・zsh・PowerShell プロファイル | [シェル](shell.md) |
| C++ の単一ファイル実行・VS Code・code-exam | [開発環境](dev-environment.md) |

## 個人用カスタム指示

pi が全リポジトリで常時読む指示は `~/.pi/agent/AGENTS.md` です。本文は `home/.chezmoitemplates/agent-instructions-stock.md`
（ツール非依存の短い指示。応答・検証・書式・委譲・確認）で、`home/dot_pi/agent/AGENTS.md.tmpl` が埋め込みます。
自作 skill の置き場は `home/dot_agents/skills/`（`~/.agents/skills/` へ展開。pi が読む。旧い置き場 `~/.claude/skills` の配備は `.chezmoiremove` が消す）。

**リポジトリ直下の `AGENTS.md` は対象外**: 適用範囲（このリポジトリのみ）も内容（リポジトリ固有の約束）も別系統です。
Claude Code・Codex・Copilot CLI・OpenCode 向けの指示ファイルは、撤去しました（[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md)）。
