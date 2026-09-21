# プロジェクト構造

## ディレクトリ構成

```text
.
├── config/                    # アプリケーションへマージする共有設定
├── docs/
│   ├── adr/                   # アーキテクチャ決定記録
│   ├── research/              # 調査・比較・検証記録
│   ├── spec/                  # 現在有効な仕様と運用手順
│   └── index.md               # ドキュメント入口
├── home/                      # chezmoiのsource state（.chezmoirootで指定）
│   ├── .chezmoiscripts/       # `chezmoi apply` 時の自動実行
│   ├── .chezmoitemplates/     # スクリプト・modify処理の共有テンプレート
│   └── dot_config/            # `~/.config/` 配下へ展開する設定
├── scripts/                   # 個別用途の導入・生成・検証・保守用スクリプト
├── test/                      # pytest・コンテナ検証
├── mise.toml                  # 開発ツールとタスク
└── pyproject.toml             # Python依存とlint設定
```

chezmoiの管理対象は `home/` 配下です。リポジトリ直下の `config/`、
`scripts/`、`test/`、`docs/` は導入・生成処理・開発・説明資料に使用します。

## 自動実行スクリプト

`home/.chezmoiscripts/` はOSと実行順で分割しています。

| 範囲 | 対象 | 主な役割 |
| --- | --- | --- |
| `000_unix/` | Linux / macOS | zinit補完の保守 |
| `100_linux/` | Ubuntu / WSL | OSパッケージ、mise、shell、Herdr |
| `200_mac/` | macOS | Homebrew、mise、macOS defaults |
| `300_windows/` | Windows native | Winget/Scoop/Chocolatey、レジストリ、Terminal、AI CLI統合、MCP登録 |
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
| Windows native | Winget、Scoop、Chocolatey、mise（gh / Herdr / AI CLI）、PowerShell |
| Ubuntu | apt、mise |
| WSL | Windows連携設定、apt、mise |
| macOS | Homebrew、mise |

OSごとの差分は `.chezmoiignore.tmpl`、テンプレート条件、OS別スクリプトで
吸収します。秘密情報はソースへ直接書かず、Bitwardenとsops/ageを使用します。

## mise による CLI 管理

本体の宣言は `home/dot_config/mise/config.toml.tmpl` に集約します。
GitHub CLI は全 OS 共通で `gh = "latest"` を宣言し、aqua の `cli/cli` から導入します。
Windows 用設定には Unix 専用ツールや設定を含めません。
Unix の uv も同じ mise 設定で導入します。uv の重複導入と使用しなくなった
Codex CLI の自動インストールを持っていた `000_unix/010_tools` は廃止しました。
Codex の既存設定や Windows の Codex App はこの変更の対象外です。
AI CLI（Claude Code / Copilot CLI / OpenCode V2）は mise では管理しません。
[AI CLI の導入](#ai-cli-の導入)を参照。

`gh` の更新はホームディレクトリで `mise upgrade gh` を実行します。
Ubuntu の `121_ubuntu` では GitHub CLI 用の APT リポジトリ・鍵の登録と
`apt install gh` を行いません。Git 本体の APT 導入は維持します。
既存の APT 版や登録済みリポジトリ・鍵、認証設定は自動削除しません。
移行後は `mise which gh` と `command -v gh` / `Get-Command gh` を比較し、
mise の実体または shim が選ばれることを確認してください。

ツールごとの導入コマンドは持たず、設定配備後にホームディレクトリを基準として
**引数なしの `mise install`** を実行します。

| 環境 | mise の一括導入 | 後続の設定 |
| --- | --- | --- |
| Linux / WSL | OS 依存パッケージの後、`100_linux/125_mise` | `100_linux/126_agent_cli` → `100_linux/140_herdr_integration` → `400_unix/410_claude_mcp` |
| macOS | Homebrew の後、`200_mac/225_mise` | `200_mac/226_agent_cli` → `400_unix/410_claude_mcp` |
| Windows | `310_winget` で mise を導入し、設定配備後に `310_packages/313_mise` | `310_packages/314_agent_cli` → `343_herdr_integration` |

mise の各スクリプトは `run_onchange_after_` とし、設定テンプレートのハッシュを
含めます。ツール宣言が変われば一括導入が再実行されます。
Unix の MCP 登録は `common.toml` の `[[mcp]]` のうち `.claude.json` の
user scope に未登録のものだけを対象にし、既存のカスタム設定は上書きしません。
壊れた JSON はエラーで停止します。詳細は
[MCP サーバ](agent-permissions.md#mcp-サーバ)を参照。

## AI CLI の導入

Claude Code / Copilot CLI / OpenCode V2 は**各社公式のインストーラー**で導入します。
実体は `home/.chezmoitemplates/agent-cli-install.sh`（Unix 共通の本体）と、
それを `includeTemplate` する OS 別スクリプトです。

| OS | スクリプト | Claude Code | Copilot CLI | OpenCode V2 |
| --- | --- | --- | --- | --- |
| Linux / WSL | `100_linux/126_agent_cli` | `claude.ai/install.sh` | `gh.io/copilot-install` | `opencode.ai/v2/install` |
| macOS | `200_mac/226_agent_cli` | 同上 | 同上 | 同上 |
| Windows | `310_packages/314_agent_cli` | `claude.ai/install.ps1` | `winget install GitHub.Copilot` | `npm install -g @opencode/cli` |

Windows で手段が分かれるのは公式側の制約です。

- Claude の `install.sh` は `MINGW*/MSYS*/CYGWIN*` を検出して明示的に終了する
- Copilot の公式スクリプトは Windows を検出すると `winget install GitHub.Copilot`
  へ委譲する。つまり winget が公式手段そのもの
- OpenCode V2 は PowerShell インストーラーを提供せず、ドキュメントに
  「Windows package managers are not supported」と明記している。
  zip の直接展開を除けば npm が唯一のパッケージ手段

導入範囲は mise 版から変えていません。Linux / WSL / macOS は 3 つとも、
Windows は Copilot CLI と OpenCode V2 を導入し、`applejxd` 以外では
Claude Code も導入します。

スクリプトは `run_onchange_after_` で、**既に PATH 上にある CLI には触りません**。
CLI を足したときだけ内容が変わって再実行され、その CLI だけが入ります。
毎回ダウンロードしないので apply が遅くなりません。

### インストーラーに副作用を持たせない

OpenCode のインストーラーは既定で `.zshrc` / `.bashrc` / `.zshenv` などへ
PATH 行を追記します。これらは chezmoi 管理なので、追記されると
`chezmoi diff` に恒常的な差分が出ます。`--no-modify-path` を付けて止め、
`~/.opencode/bin` の PATH は `home/dot_config/shell/shellenv.sh.tmpl` で通します。

Copilot のインストーラーは導入先が PATH に無いと、rc ファイルへ追記してよいかを
`/dev/tty` から対話で尋ねます。`chezmoi apply` が入力待ちで止まるため、
スクリプト側で `~/.local/bin` を先に PATH へ入れて分岐に入らせません。

### 更新

自動更新は `common.toml` の `[claude] auto_update = false` /
`[copilot] auto_update = false` で止めたままです。更新は手動で行います。

| CLI | Unix | Windows |
| --- | --- | --- |
| Claude Code | `claude update` | `claude update` |
| Copilot CLI | `curl -fsSL https://gh.io/copilot-install \| bash` | `winget upgrade --id GitHub.Copilot --exact` |
| OpenCode V2 | `opencode upgrade` | `npm update -g '@opencode/cli'` |

### mise 版からの移行

mise が入れた `claude-code` / `copilot` は自動削除しません。
不要になったので、次で確認してから手で片付けてください。

```bash
mise ls --installed | grep -E 'claude-code|copilot'
mise uninstall claude-code copilot   # 任意
mise prune
```

新しいターミナルで `command -v claude` / `command -v copilot`
（PowerShell なら `Get-Command`）が公式インストーラーの実体を指すことを確認します。
mise の shim が残って優先される場合は `mise reshim` を実行してください。
`~/.claude/`、`~/.claude.json`、`~/.copilot/` の設定・認証・履歴は削除しません。

## Herdr の管理

Herdr は `home/dot_config/mise/config.toml.tmpl` の `herdr = "latest"` で管理します。
Linux / WSL と Windows native にのみ展開し、macOS は従来どおり自動導入しません。
Windows の `.config/mise/config.toml` は `.chezmoiignore.tmpl` の除外例外とし、
gh とともに宣言します。

Linux では `125`、Windows では `313` の `mise install` で Herdr も導入します。
後続の `140` / `343` の `run_after` は再インストールせず、
`mise which herdr` で解決した実体を使って agent integration とリリース一致版の
skill を生成します。agent CLI は mise 管理ではなくなったため、
`~/.local/bin` / `~/.opencode/bin`（Windows は machine / user の PATH）を
先頭へ置いてから `command -v` / `Get-Command` で解決します。
初回の shell activate 前でも連携できます。
どちらもホームディレクトリを基準に mise を実行するため、apply を起動した
プロジェクトのツール指定や PATH 上の旧 Herdr に依存しません。

本体の更新はホームディレクトリで `mise upgrade herdr` を実行し、続けて
`chezmoi apply` で integration と skill を再生成します。mise の管理情報と実体が
食い違うため、`herdr update` は使いません。

旧インストーラーの `~/.local/bin/herdr`（Linux / WSL）や
`%LOCALAPPDATA%\Programs\Herdr\bin\herdr.exe`（Windows）は自動削除しません。
移行後は新しいターミナルで `mise which herdr` と、Linux なら `command -v herdr`、
PowerShell なら `Get-Command herdr` を確認し、mise の実体または shim が選ばれる
ことを確認してください。旧版が選ばれる場合は、Herdr を終了してから旧バイナリだけを
削除するか、mise の shim が先に見つかるよう PATH を整理します。
Herdr のユーザーデータ・設定は削除しません。

## PowerShellプロファイル

設定の実体は `home/dot_config/powershell/` に置き、`$PROFILE`
（`Documents/PowerShell/` と `Documents/WindowsPowerShell/`）へは
それをdot-sourceする1行のローダーだけを配置します。

| パス | 役割 |
| --- | --- |
| `home/dot_config/powershell/profile.ps1.tmpl` | PowerShell 7 / 5.1 共通の本体 |
| `home/dot_config/powershell/commands/*.ps1` | 用途別の関数（wsl、docker、fzf、pwgen） |
| `home/Documents/*/profile.ps1.tmpl` | `$PROFILE` から本体を呼ぶローダー |
| `home/.chezmoitemplates/powershell/git-config-env.ps1` | プロファイルとScoopスクリプトで共有する `GIT_CONFIG_*` の正規化 |
| `home/.chezmoiscripts/300_windows/run_after_345_powershell_profile.ps1.tmpl` | `Documents` がリダイレクトされている場合のローダー再配置 |

この構成には次の理由があります。

- **実体を `Documents` の外に置く**: OneDriveの既知フォルダーリダイレクトが
  有効だと `$PROFILE` はOneDrive側を指し、`~/Documents` へ配置したファイルが
  読まれません。実体を `~/.config` に置き、ローダーだけを実際の `MyDocuments`
  へ再配置します。
- **パスは `{{ .chezmoi.homeDir }}` で埋め込む**: PowerShellの `$HOME` は
  `HOMEDRIVE`+`HOMEPATH` 由来で、ホームをリダイレクトしたドメイン参加機では
  chezmoiの `~`（`%USERPROFILE%`）と一致しません。
- **PowerShellソースにはUTF-8 BOMを付ける**: Windows PowerShell 5.1はBOMの無い
  `.ps1` をANSIコードページ（ja-JPならCP932）として読みます。日本語コメントの
  行末バイトが改行を飲み込み、**直後のコードがエラーも警告も無く実行されなく
  なります**。`test_powershell_sources_start_with_a_utf8_bom` で強制します。
  `.chezmoitemplates/` 配下は他ファイルへ埋め込むため対象外です。
- **対話時と非対話時を分ける**: `profile.ps1` はAllHostsプロファイルのため、
  エージェントやスクリプトからの起動でも毎回読み込まれます。プロンプト
  （oh-my-posh）、キーバインド、モジュール読み込みは対話時だけ実行します。
  判定はstdioのリダイレクトに加え、起動引数（`-Command` / `-File` /
  `-EncodedCommand` / `-NonInteractive`。ただし `-NoExit` があれば対話）も見ます。
- **起動経路でcmdletを使わない**: `Microsoft.PowerShell.Management`
  （`Test-Path`、`Join-Path`）、`Microsoft.PowerShell.Utility`
  （`New-Object`、`Set-Alias`）、`Get-Command` のコマンド探索は、初回呼び出しに
  それぞれ0.25秒前後かかります。対話ブロックより前は同等の.NET APIで書きます。
  `pbcopy` はエイリアスから関数へ変えたため、`$input` で明示的にパイプライン
  入力を渡します。
- **init出力をキャッシュする**: `mise activate` の外部プロセス起動を避けるため、
  出力を `%LOCALAPPDATA%\PowerShellProfileCache` へ保存し、実行ファイルのパス・
  サイズ・更新時刻が変わったときだけ再生成します。キャッシュは最適化なので、
  読み書きに失敗しても警告に留め、`mise` を直接実行するフォールバックへ回ります。
  一時ファイルは `.ps1` で終わらせます（dot-sourceは `.ps1` 以外を `Application`
  として扱い、実行しません）。
  なお **`oh-my-posh init` はキャッシュしません**。oh-my-posh はテーマ設定を
  セッションIDに紐付けて登録するため、別セッションでIDを採番し直すと設定を
  引けず、既定のpowerlineテーマに戻ります。
- **PATHを冪等に更新する**: `mise activate` は毎回PATHの先頭へ追加するため、
  追加後に重複を畳みます。

計測（このリポジトリのWindows機、中央値）:

| 起動 | プロファイルあり | `-NoProfile` |
| --- | --- | --- |
| `pwsh` | 510 ms | 312 ms |
| `powershell` | 359 ms | 182 ms |

## 個人用カスタム指示

全リポジトリで常時読み込まれる指示は、CLI ごとに読む先のファイル名が違います。
本文はほぼ同じなので、共通部分を 1 ファイルに集約して埋め込みます。

| パス | 役割 |
| --- | --- |
| `home/.chezmoitemplates/agent-instructions.md` | 4 CLI 共通の本文（応答・停止と報告・検証） |
| `home/dot_claude/CLAUDE.md.tmpl` | `~/.claude/CLAUDE.md`。共通本文のみ |
| `home/dot_codex/AGENTS.md.tmpl` | `~/.codex/AGENTS.md`。共通本文のみ |
| `home/dot_config/opencode/AGENTS.md.tmpl` | `~/.config/opencode/AGENTS.md`。共通本文のみ |
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
  Claude Code / Codex CLI には置きません（`docs/spec/agent-permissions.md` の
  CLI 別の表を参照）。
- **テンプレート内で分岐しない**: 固有の節は該当ファイルへ直接書き足します。
  `{{ if }}` を使わないので、テストは `includeTemplate` を展開するだけで
  実体を再現できます（`test_personal_instructions_share_one_source`）。
- **リポジトリ直下の `AGENTS.md` は対象外**: 適用範囲（このリポジトリのみ）も
  内容（リポジトリ固有の約束）も別系統です。判断の経緯は
  [ADR-0006](../adr/0006-instructions-to-mechanisms.md) にあります。
