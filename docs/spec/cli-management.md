# CLI の導入と管理

mise で入れる CLI、AI CLI（Claude Code・Copilot CLI・OpenCode・pi・omp）の導入と更新、Herdr、Envoy の取得。権限・hook の設定は [設定の生成と所有権](agent-config-generation.md)。全体の構成は [プロジェクト構造](structure.md)。

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

AWS CLI（`aws-cli`、aqua の `aws/aws-cli`）は Unix で `applejxd` 以外のユーザーにだけ宣言します。

`ruff` と `oxlint` は Unix で宣言します。どちらも OpenCode の編集直後の lint に使い、
`ruff` は Claude Code / Copilot CLI の `format-file.sh` と OpenCode 組み込みの整形
（`.py`）も使います。宣言する前は PATH に無く、どちらの整形も黙って何もしていませんでした。

ツールごとの導入コマンドは持たず、設定配備後にホームディレクトリを基準として
**引数なしの `mise install`** を実行します。

| 環境 | mise の一括導入 | 後続の設定 |
| --- | --- | --- |
| Linux / WSL | OS 依存パッケージの後、`100_linux/125_mise` | `100_linux/126_agent_cli` → `100_linux/140_herdr_integration` → `400_unix/410_claude_mcp` |
| macOS | Homebrew の後、`200_mac/225_mise` | `200_mac/226_agent_cli` → `400_unix/410_claude_mcp` |
| Windows | `310_winget` で mise を導入し、設定配備後に `310_packages/313_mise` | `310_packages/314_agent_cli` → `343_herdr_integration` |

mise の各スクリプトは `run_onchange_after_` とし、設定テンプレートのハッシュを
含めます。ツール宣言が変われば一括導入が再実行されます。

### Windows の mise の更新

Windows の `313_mise` は `mise install` の前に `winget upgrade --id jdx.mise` を
実行します。`310_winget` は導入済みのパッケージを更新しないため、初回に入れた
古い mise が残り続け、その版の registry に無いツール（例: 2026.3.17 時点の
`herdr`）で `mise install` が `not found in mise tool registry` で失敗したためです。

winget の終了コードのうち、更新が無い（`0x8A15002B`）と winget 以外で導入された
（`0x8A150014`）は成功として扱い、`mise install` へ進みます。

### Windows の PATH の扱い

PATH を読み直す・永続化する処理は、`home/.chezmoitemplates/powershell/env-path.ps1` の共通関数を
`includeTemplate` で取り込んで使います（309 / 313 / 314 / 343 / 346）。手書きの複製をこれ以上増やさないでください。

| 関数 | 役割 |
| --- | --- |
| `Update-PathFromEnvironment` | レジストリの Machine → User と現在の順に並べて、このプロセスの PATH を更新する（重複は先頭だけ残す） |
| `Add-UserPathEntry` | User の PATH へ永続的に追記する。既にあれば追記しない。レジストリへ REG_EXPAND_SZ で直接書き、`WM_SETTINGCHANGE` を送る。既に REG_SZ へ降格している場合は、追記が無くても同じ値を REG_EXPAND_SZ で書き直す |

- `[Environment]::SetEnvironmentVariable` と `setx` で PATH を書かない。REG_EXPAND_SZ を REG_SZ に降格させ、
  PATH 内の `%USERPROFILE%` などが展開されなくなるという報告がある。
  試験でこの書き方の再導入を止めている（`test_env_path_template_writes_user_path_as_expand_string`）
- GUI の環境変数エディタは 1 変数 2047 文字までで、超えた PATH は末尾が無警告で切れるという報告がある。
  PATH を長くしすぎない。長さを根本から減らす手段は、ツールごとの PATH 追加をまとめる shim ディレクトリ（mise の shims など）へ寄せること
- 上の報告の出典（URL・取得日）、Zed の統合ターミナルの報告、未確認・未検証の事項は [記録](../research/chezmoi/structure-windows-notes.md)

### Windows の node / uv / fzf / jq

Windows でも `node` / `uv` / `fzf` / `jq` は mise が管理します（`310_winget` からは外しました）。
winget 版 node は `run_once_` で初回の版のまま残り、PATH 上で mise 版より先に解決されて
pi の導入（Node.js 22.19 以上が必要）が失敗したためです。`314_agent_cli` は `mise where node`
の場所を PATH の先頭に置いてから npm を実行します。winget に残るのは mise 自体（bootstrap）、
Git・Python 3.12（chezmoi が要る）、GUI アプリです。既に winget 版が入っている PC は
`winget uninstall OpenJS.NodeJS astral-sh.uv junegunn.fzf jqlang.jq` で外せます。
mise の node（zip 版）の npm の global prefix は node の版付きフォルダなので、そのままだと npm で入れる CLI（opencode）は PATH に出ず、版を上げると消えます（Sandbox で確認）。`314` は `NPM_CONFIG_PREFIX=%APPDATA%\npm` を設定してから npm を実行し、そのフォルダを User PATH に保証します。

### chezmoi 本体

README の公式インストーラ（`get.chezmoi.io`、Windows は winget）は初回の
bootstrap だけに使います。以降は mise が `chezmoi = "latest"` で管理を引き継ぎ
（`config.toml.tmpl`）、`chezmoi apply` 後は mise 版が使われるため、
`~/.local/bin` のコピーは残さなくてよいです。

**snap 版は使いません。** snap の confinement 下では
[AI CLI の sandbox](../change/closed/0004-opencode-sandbox.md) の内側で
起動できず、`chezmoi apply` が失敗します（実測）。
既に snap 版が入っている場合は `sudo snap remove chezmoi` で外します。
`/snap/bin` は PATH で mise の shim より前に来るため、**消さないと
mise 管理版が使われません**。削除後は `hash -r` を実行します。

Unix の MCP 登録は `common.toml` の `[[mcp]]` のうち `.claude.json` の
user scope に未登録のものだけを対象にし、既存のカスタム設定は上書きしません。
壊れた JSON はエラーで停止します。詳細は
[MCP サーバ](mcp-servers.md#mcp-サーバ)を参照。

### mise の settings

`[settings]` に置いている宣言と、その理由です。
`config.toml.tmpl` 側のコメントは参照だけに留めています。

| 設定 | 対象 | 理由 |
| --- | --- | --- |
| `experimental = true` | 全 OS | task runner を使うため |
| `sops.age_key_file` | 全 OS | API キーの復号先を固定するため |
| `[settings.python] compile = true` | raspi 以外 | プリコンパイル済みバイナリは Tkinter を含まないため。[参照](https://www.python.jp/install/ubuntu/index.html) |
| `[settings.ruby] compile = false` | raspi のみ | [ruby はプレビルドで入れる](platform-raspberry-pi.md#ruby-はプレビルドで入れる)を参照 |

**`all_compile` は使いません。** この設定は「**全言語で**プリコンパイル済み
バイナリを使わない」という意味で、Tkinter という目的に対して範囲が広すぎます。
以前は `all_compile = true` を置いていたため node と ruby までソースビルドに
なっていました。mise 側も `all_compile` の自動既定を非推奨化しており、
2027.8.0 で削除予定です。

### npm backend で入れている 2 つ

| ツール | 理由 |
| --- | --- |
| `npm:@bitwarden/cli` | snap 版が動作しなくなったため。bw 不在でも `apply` は完走し、その `apply` 中に入ります。[セキュリティ](security.md#bitwarden連携) |
| `npm:@anthropic-ai/sandbox-runtime` | Claude Code の sandbox が使う seccomp フィルタ。WSL2 では無いと sandbox から脱出できます。mise の隔離先を `settings.json` の `sandbox.seccomp.applyPath` へ橋渡しする必要があり、生成は `scripts/agents/generate.py` が行います。[WSL2 での抜け穴](sandbox/cli-sandbox-network.md#wsl2-での抜け穴-seccomp-フィルタ) |

seccomp フィルタは手で `npm install -g` する必要はありません。導入先が実在する
ときだけ `~/.claude/settings.json` に設定が出るため、初回は mise の導入後に
もう一度 `chezmoi apply` します。

### github backend で版を固定している Fence

`github:fencesandbox/fence` は、`ocs`（OpenCode の隔離起動。[OpenCode 隔離起動](sandbox/opencode-sandbox.md)）と
`pis`（pi のサンドボックス起動。[pi のガード](guard/pi-guard.md#起動)）が境界を張る道具です。Linux / WSL だけに入れます。

- **版とチェックサムを固定しています。** 0.1.x で開発元が 1 社のため、`latest` で
  追わず、上げるときは Releases の `checksums.txt` の値を `platforms.<os>-<arch>.checksum`
  に写します（`linux-x64` と `linux-arm64`）。mise は落とした tar.gz の sha256 を照合し、
  違えば導入を止めます
- （OpenCode 専用。撤去予定。CHG-0020 段 6 は保留中）`ocs` は `~/.local/share/mise/installs/github-fencesandbox-fence/latest/fence` を
絶対パスで呼びます（`[opencode.sandbox] runtime_path`）。境界の設定は実体の有無に
  関係なく生成され、実体が無ければ `ocs` が起動を断ります（`mise install` で入れる）
- Claude Code の sandbox は引き続き `npm:@anthropic-ai/sandbox-runtime` を使います

### Windows の pi

Windows の pi は、mise の `aqua:earendil-works/pi`（ビルド済みバイナリ。bun 製、約 230 MB）で導入します。
`config.toml.tmpl` に版を明示で固定し（`latest` は `minimum_release_age` で最新版が隠れる）、`313_mise` の
`mise install` が入れます。`314_agent_cli` は、旧方式の npm 版が残っていれば `npm uninstall -g` で外し、
`mise exec -- pi --version` で起動を確かめます。更新は版を書き換えて `chezmoi apply` です（`pi update` では更新しません）。

- 選んだ理由: npm 版は node の解決順に左右される。Machine PATH に古い node があると、pi の導入も起動も失敗する
  （Sandbox で再現）。バイナリ版は node を使わないので、この種の障害が起きない。WSL / Linux の `~/.pi/agent/bin/pi`
  と同じバイナリでもある。公式の `install.ps1` は `Read-Host` で確認を聞き、apply では答えられない
- バイナリ版は `process.argv[1]` が仮想パス（`B:/~BUN/root/pi.exe`）で、CLI ファイルではない。
  `subagents` はこれを子の引数に渡さないようにした（`childArgs`、試験あり）
- 導入・起動の実測と未確認事項は [記録](../research/chezmoi/structure-windows-notes.md)
- 旧 npm 版が残る PC は、`npm uninstall -g @earendil-works/pi-coding-agent` で外す（`314` が自動で行う）

## AI CLI の導入

Claude Code / Copilot CLI / OpenCode V2 は**各社公式のインストーラー**で導入します。
導入処理の本体は `home/.chezmoitemplates/agent-cli-install.sh.tmpl`（Unix 共通）と、
それを `template` で取り込む OS 別スクリプトです。

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
Claude Code も導入します。Linux / WSL / macOS では加えて oh-my-pi (`omp`) と
pi（`pi.dev/install.sh`）も公式インストーラーで入れます（Windows の pi は mise が入れる。[Windows の pi](#windows-の-pi)）。pi は mise の Node.js が入っていないと
入れません（インストーラーが Node.js の導入を端末で聞くため。次の apply で走り直す）。
pi はフルガード付きの `pis` で起動する（[pi のガード](guard/pi-guard.md#起動)）。

スクリプトは `run_onchange_after_` で、**既に PATH 上にある CLI には触りません**。
ただし mise の shim（`~/.local/share/mise/shims/` 配下）は導入済みと数えません。
CLI を足したときだけ内容が変わって再実行され、その CLI だけが入ります。
例外として、導入に失敗した回は再実行の印（`~/.local/share/dotfiles/retry/agent-cli-failed`）を
書き直すので、次の apply でも走り直して入っていないものだけを導入します
（[スクリプトを走らせ直す](troubleshooting-bootstrap.md#スクリプトを走らせ直す)）。
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
OpenCode も含めた生成先のキーは
[CLI 本体の更新](agent-config-generation.md#cli-本体の更新)を参照。

| CLI | Unix | Windows |
| --- | --- | --- |
| Claude Code | `claude update` | `claude update` |
| Copilot CLI | `curl -fsSL https://gh.io/copilot-install \| bash` | `winget upgrade --id GitHub.Copilot --exact` |
| OpenCode V2 | `opencode upgrade` | `npm update -g '@opencode/cli'` |

### mise 版からの移行

Unix（Linux / WSL / macOS）では、`126_agent_cli` / `226_agent_cli` が実行されるたびに
mise の残骸を自動で削除します。対象は shim の `claude` / `copilot` / `opencode` / `omp` と、
`installs/` の `claude` / `claude-code` / `copilot` / `opencode` / `omp` です
（shim が公式版より先に PATH で見つかり、起動を横取りするため。経緯は
[AI CLI が mise に global default version を指定しろと言う](troubleshooting-bootstrap.md#ai-cli-が-mise-に-global-default-version-を指定しろと言う)）。

Windows の `314_agent_cli` は削除しません。mise が入れた `claude-code` / `copilot` が
残っていれば、次で確認してから手で片付けてください。

```powershell
mise ls --installed | Select-String 'claude-code|copilot'
mise uninstall claude-code copilot   # 任意
mise prune
```

新しいターミナルで `command -v claude` / `command -v copilot`
（PowerShell なら `Get-Command`）が公式インストーラーの実体を指すことを確認します。
mise の shim が残って優先される場合は `mise reshim` を実行してください。
`~/.claude/`、`~/.claude.json`、`~/.copilot/` の設定・認証・履歴は削除しません。

### oh-my-pi（`omp`）の設定

`omp` は試用の案件（[CHG-0006](../change/closed/0006-pi-harness-trial.md)。閉じた案件で、第一サポートは pi。
`omp` は導入と設定の取り込みまでで、以後は使っていない）で入れたもので、導入は続けています。
Linux / WSL / macOS で `curl -fsSL https://omp.sh/install | sh` により導入します。
Pi のフォークで、LSP 統合・DAP・subagent を持ちます。起動は `omp` で、
境界（`ocs` / `pis` の Fence）の外で動きます。

**`omp` は `~/.claude` を設定探索ルートに含みますが、他ツールのユーザ領域は
既定で 1 つも読みません**（`enabledProviders` の既定が空）。
`chezmoi apply` が次の 3 つを設定するので、既存の資産がそのまま使えます。

| 設定 | 繋がるもの |
| --- | --- |
| `skills.customDirectories` | `~/.claude/skills` の自作 skills 15 個 |
| `enabledProviders: [claude]` | `~/.claude.json` の MCP サーバ定義、`~/.claude/commands` |
| `commands.enableClaudeUser` | `~/.claude/commands` の `/criticalthink`（chezmoi が配るのはこれだけ） |

あわせて `bashInterceptor.enabled` を有効にし、`cat` / `grep` / `sed -i` などを
`read` / `grep` / `edit` へ誘導します（他の CLI と挙動を揃えるため）。
応答の人柄は `personality` を `friendly`（既定は `default`）にします。
**これら 3 つの初期値は初回のみ設定**し、以後 `omp config set` や `/settings` で
変えた値は上書きしません（`~/.omp/agent/.chezmoi-seeded` で管理）。

> **permission 機構を持たない設計です。** Pi 系は安全性より利便性を取る方針で、
> 権限制御は拡張か外部の sandbox に委ねます。保護は「どこで起動するか」と
> git の使い方に依存します。**対象リポジトリ直下で起動し、開始前に作業を
> 区切ってコミットしてください。**
> 経緯と代償の一覧は [CHG-0006](../change/closed/0006-pi-harness-trial.md) にあります。

## Herdr の管理

Herdr は `home/dot_config/mise/config.toml.tmpl` の `herdr = "latest"` で管理します。
mise の aqua backend が公式 GitHub Releases のバイナリをユーザースコープへ取得します。
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

```bash
mise upgrade herdr
chezmoi apply
```

初回適用後に `herdr` が見つからない場合は、新しいターミナルを開いてください。
Windows ARM64 では、Herdr 公式の x86_64 ビルドが Windows のエミュレーション上で動作します。

### agent integration と skill

agent integration は設定ファイルの配備後に毎回冪等に再適用されます。

| chezmoi username | integration | 前提となる agent CLI |
| --- | --- | --- |
| `applejxd` | GitHub Copilot CLI | 公式インストーラーで導入 |
| その他 | Claude Code | 公式インストーラーで導入 |

Herdr は `~/.copilot/settings.json` または `~/.claude/settings.json` の既存設定を保持し、
Herdr 管理の hook entry だけを追加・更新します。現在の状態は `herdr integration status`
で確認できます。

同じ `run_after` スクリプトが `herdr --skill` からリリース一致版の agent skill を生成し、
`~/.claude/skills/herdr/SKILL.md` に配置します。Copilot CLI は
`~/.copilot/skills` の symlink / junction を通じて同じスキルを参照します。
`chezmoi apply` のたびに再生成されるため、Herdr 本体の更新後もスキルが追従します。
生成物なので source state には取り込まず、`.chezmoiignore` で `chezmoi add` の対象からも外しています。

herdr が Claude の `settings.json` に足す hook（`~/.claude/hooks/herdr-agent-state.sh`）は、
chezmoi 側の生成処理が外部の hook として残します。仕組みは
[外部ツールとの共存](agent-hooks-generation.md#外部ツールとの共存-orca--herdr) を参照してください。

### 旧インストーラー版からの移行

旧インストーラーの `~/.local/bin/herdr`（Linux / WSL）や
`%LOCALAPPDATA%\Programs\Herdr\bin\herdr.exe`（Windows）は自動削除しません。
移行後は新しいターミナルで `mise which herdr` と、Linux なら `command -v herdr`、
PowerShell なら `Get-Command herdr` を確認し、mise の実体または shim が選ばれる
ことを確認してください。旧版が選ばれる場合は、Herdr を終了してから旧バイナリだけを
削除するか、mise の shim が先に見つかるよう PATH を整理します。
Herdr のユーザーデータ・設定は削除しません。

## Envoy の取得

`pis` の Copilot ブローカー（[認証ブローカー](sandbox/broker.md#copilot-ブローカー)）が使う Envoy は、
`chezmoi apply` が `home/.chezmoiexternal.toml.tmpl` で `~/.local/bin/envoy` へ取得します。
固定版（v1.40.1）の公式リリースのバイナリを、`checksum.sha256` で照合します（chezmoi が検証）。

- **対象**: Linux / WSL で、`llm-provider` が `github-copilot` の機、Raspberry Pi 以外、amd64 と arm64 だけ
  （Envoy は macOS・Windows のバイナリを配布していない。制約のある環境の機（Bedrock を使う機）は、Bedrock の対応（[CHG-0037](../change/0037-pis-usability-and-telemetry.md)）まで対象外）
- **更新手順**: 公式リリースの `checksums.txt.asc` から、`envoy-<版>-linux-x86_64` と `envoy-<版>-linux-aarch_64` の
  sha256 を取り、`.chezmoiexternal.toml.tmpl` の版・URL・sha256 を 3 つ同時に書き換える（署名の検証は任意）
- **sha256 の限界**: 同じリリースの checksums との一致で、改ざん検知の根拠は弱い（署名の検証は未実施）

各項目は**パスがまだ無いときだけ宣言します**（`stat` で判定）。chezmoi 2.72 の
git-repo external には次の挙動があり、既に clone 済みの機械を壊すためです。

- 記録の無いパスが既にあると、`refreshPeriod` に関係なく初回の apply で
  `git pull` を実行する
- pull に失敗すると記録が残らず、apply のたびに失敗する
  （`bash-it update` の後は detached HEAD なので必ず失敗する）
- 同じパスにファイルがあると削除してから pull し、失敗する
  （rupa/z の既定のデータファイル `~/.z` が消える）
- Git 管理でないディレクトリだと、外側のリポジトリで pull が走る

このため chezmoi は取得後の更新をしません。更新は各ツールに任せます
（zinit は `mise run dotfiles-update`、bash-it は `bash-it update`、tpm は tmux の
prefix + U）。取り直すときはパスを消してから `chezmoi apply --refresh-externals` します
（`--refresh-externals` が無いと clone 済みの記録で飛ばされる。
[external が取得されない](troubleshooting-bootstrap.md#apply-しても-zinit-などの-external-が取得されない)）。
新しい機械では apply に git とネットワークが要り、取得に失敗すると apply が
エラーになります。
