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
│   └── dot_local/bin/         # `~/.local/bin/` へ展開する手元のコマンド（`ocs`、`oc-utils`）
├── scripts/                   # 個別用途の導入・生成・検証・保守用スクリプト
│   └── model-eval/            # OpenCode の階層に当てるモデルの計測（model-lineup-review.md）
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
- agent の書き込み禁止は `~/.gitconfig`・`~/.config/git/config`・`~/.config/git/config.local`（`common.toml.tmpl`）。

## 自動実行スクリプト

`home/.chezmoiscripts/` はOSと実行順で分割しています。

| 範囲 | 対象 | 主な役割 |
| --- | --- | --- |
| `000_unix/` | Linux / macOS | Python 3.11 以上の確保と旧 `~/.gitconfig` の退避（ファイル適用より前）、zinit補完の保守 |
| `100_linux/` | Ubuntu / WSL | OSパッケージ、mise、shell、Herdr |
| `200_mac/` | macOS | sudo の Touch ID、Homebrew、mise、macOS defaults |
| `300_windows/` | Windows native | 旧 `~/.gitconfig` の退避、Winget/Scoop/Chocolatey、レジストリ、Terminal、AI CLI統合、MCP登録 |
| `400_unix/` | Linux / macOS | mise 導入後の Claude Code への MCP 登録 |

スクリプト名は `run_once_XXX_name`、`run_onchange_XXX_name`、
`run_after_XXX_name` などのchezmoi属性と3桁番号で順序を管理します。
同じ `before` / `after` 内ではディレクトリを含むパス順です。

- `run_once_`: 同じ内容が成功済みなら再実行しない
- `run_onchange_`: 内容が変わった場合に再実行する
- `run_after_`: ファイル展開後、applyのたびに実行する
- `.tmpl`: OS分岐、chezmoiデータ、秘密情報が必要な場合のみ使用する

## 対応環境

| 環境 | 主な導入経路 |
| --- | --- |
| Windows native | Winget、Scoop、Chocolatey、mise（gh / Herdr / node / uv / fzf / jq）、AI CLI の公式手段（[AI CLI の導入](cli-management.md#ai-cli-の導入)）、PowerShell |
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

全リポジトリで常時読み込まれる指示は、CLI ごとに読む先のファイル名が違います。
本文はほぼ同じなので、共通部分を 1 ファイルに集約して埋め込みます。

| パス | 役割 |
| --- | --- |
| `home/.chezmoitemplates/agent-instructions.md` | 4 CLI 共通の本文（応答・設計と計画の姿勢・判断の仰ぎ方・停止と報告・検証・未知の不具合の調査・別モデルへの相談・子エージェントへの委譲）。全リポジトリ共通の作法だけを置き、リポジトリ固有の約束は各リポジトリの `AGENTS.md` へ置く |
| `home/dot_claude/CLAUDE.md.tmpl` | `~/.claude/CLAUDE.md`。共通本文のみ |
| `home/dot_codex/AGENTS.md.tmpl` | `~/.codex/AGENTS.md`。共通本文のみ |
| `home/dot_config/opencode/AGENTS.md.tmpl` | `~/.config/opencode/AGENTS.md`。共通本文 + 自動リマインダー節（提供元が差し込む著作権などの注意への言及を止め、出力トークンを節約する。起きたのが OpenCode なのでここだけ） + 文脈の引き継ぎ節（`checkpoint` スキルが OpenCode 専用のため） |
| `home/dot_copilot/copilot-instructions.md.tmpl` | `~/.copilot/copilot-instructions.md`。共通本文 + コミット節 |

OpenCode V2 が global 指示として読むのは `~/.config/opencode/AGENTS.md` だけで、
`CLAUDE.md` へのフォールバックはありません（公式 Instructions ガイド）。
同じホームに `~/.claude/CLAUDE.md` があっても読まれないため、専用の
埋め込み先を用意しています。

この構成には次の理由があります。

- **手で複製するとズレる**: 3 ファイルを個別に保守していたところ、「停止と報告」
  の機構名（hook / rules / 承認プロンプト）と「検証」のサンドボックス言及が
  実際にズレていました。共通本文を 1 ファイルにして埋め込み先を増やすだけに
  します。
- **CLI 固有の節だけを足す**: Copilot のコミット節は
  [github/copilot-cli#3590](https://github.com/github/copilot-cli/issues/3590)
  という Copilot 固有の事実を理由に書いているため、機械的強制がある
  Claude Code / Codex CLI には置きません（`docs/spec/guard/agent-command-policy.md` の
  CLI 別の表を参照）。
- **テンプレート内で分岐しない**: 固有の節は該当ファイルへ直接書き足します。
  `{{ if }}` を使わないので、テストは `includeTemplate` を展開するだけで
  出力内容を再現できます（`test_personal_instructions_share_one_source`）。
- **リポジトリ直下の `AGENTS.md` は対象外**: 適用範囲（このリポジトリのみ）も
  内容（リポジトリ固有の約束）も別系統です。判断の経緯は
  [ADR-0006](../adr/0006-instructions-to-mechanisms.md) にあります。
