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
| `000_unix/` | Linux / macOS | Python 3.11 以上の確保（ファイル適用より前）、zinit補完の保守 |
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
| Windows native | Winget、Scoop、Chocolatey、mise（gh / Herdr）、AI CLI の公式手段（[AI CLI の導入](#ai-cli-の導入)）、PowerShell |
| Ubuntu | apt、mise |
| WSL | Windows連携設定、apt、mise |
| Raspberry Pi（64bit / ヘッドレス） | apt、mise（GUI・VS Code・ソースビルドを除く） |
| macOS | Homebrew、mise |

OSごとの差分は `.chezmoiignore.tmpl`、テンプレート条件、OS別スクリプトで
吸収します。秘密情報はソースへ直接書かず、Bitwardenとsops/ageを使用します。

### Raspberry Pi

64bit の Raspberry Pi OS（ヘッドレス）を対象にします。**32bit（armhf）は対象外**です。
Claude Code / Copilot CLI / OpenCode V2 / oh-my-pi の公式インストーラーはいずれも
x64 と arm64 しか受け付けず、`armv7l` を検出すると明示的に終了します。

判定は `home/.chezmoitemplates/is-raspi` が単一ソースです。次の 3 つの OR で
判定し、`"true"` か空文字を返します。単独ではどれも取りこぼします。

| 手がかり | 拾えるもの |
| --- | --- |
| `/proc/device-tree/model` の存在 | ハードウェアの申告。OS を問わず Raspberry Pi なら必ずある |
| `.chezmoi.kernel.osrelease` に `raspi` / `-rpi-` | Ubuntu for Raspberry Pi の `-raspi` フレーバー、Raspberry Pi OS の `+rpt-rpi-` |
| `/etc/rpi-issue` の存在 | Raspberry Pi OS のイメージ |

参照側はこう書きます。

```gotmpl
{{ $raspi := eq (includeTemplate "is-raspi" .) "true" }}
```

**`chezmoi.toml` の `[data]` には置きません。** `[data]` でも判定自体は動きますが、
値が書かれるのは `chezmoi init` のときだけです。普段の運用は `chezmoi update`
（`git pull` + `apply`）が中心で、**これは `init` を呼びません**。

`init` を都度実行すれば `[data]` 方式でも成立します。ただし忘れると判定が
生成されず、全分岐が「非 raspi」に倒れます。`apply` の警告
（`config file template has changed, run chezmoi init to regenerate config file`）は
**大量の出力に埋もれて見逃します**（実機で見逃した経過は
[CHG-0008](../change/closed/0008-raspi-branching.md#判定を-data-から-includetemplate-へ移した2-周目の教訓)）。

手順で守らせる設計をやめ、`includeTemplate` で `apply` のたびに評価する形に
しました。`init` を実行してもしなくても同じ結果になります。

データで上書きもできます。`is_raspi` を渡すと検出より優先されるので、
テスト（`lint_templates.py` の raspi 軸）と手動での強制に使えます。

**`/etc/rpi-issue` だけでは足りません。** このファイルは Raspberry Pi OS 専用で、
Ubuntu for Raspberry Pi には存在しません（実機がそうでした）。
64bit の Raspberry Pi OS は `/etc/os-release` が `ID=debian` になるので、
os-release でも判定できません（`raspbian` は 32bit 版のみ）。

| 対象 | Raspberry Pi での扱い |
| --- | --- |
| `100_linux/110_native/`（VS Code と拡張 20 個） | 導入しない |
| i3 / rofi / polybar / lxappearance / xsel | 導入しない |
| `.config/i3`、`.config/polybar`、`.Xmodmap`、`.xsession`、`.xsessionrc` | 展開しない |
| `xdg-user-dirs-update`、`systemctl --user mask` | 実行しない（ヘッドレスでは失敗して apply が止まる） |
| ClamAV | 導入しない（`clamd` が常駐で 1GB 超を占める） |
| `pipx:nvitop` | 宣言しない（NVIDIA GPU が前提） |
| `[settings.python] compile` | 宣言しない（Tkinter が要らない） |
| `[settings.ruby] compile` | `false` を宣言する（後述） |
| Cica フォント | fontconfig が無ければスクリプト側で早期終了 |
| zram-tools / earlyoom | **Raspberry Pi だけで導入する**（[後述](#メモリが尽きても-ssh-できるようにする)） |

`xdg-user-dirs-update` は Raspberry Pi 以外でも、コマンドが無ければ（Server 版・WSL・
コンテナなど Desktop 環境の無い機械）既知フォルダの整理ごと飛ばします。

### ruby はプレビルドで入れる

`ruby` と `gem:tmuxinator` は Raspberry Pi でも宣言します。mise は既定で
`jdx/ruby` のプレビルド版を落とし、**Linux arm64 (glibc) 向けも用意されています**。

ruby がソースビルドへ落ちるのは、`all_compile = true` が**全言語で**
プリコンパイル済みバイナリを禁じるためです（実機でビルドが失敗した経過は
[CHG-0008](../change/closed/0008-raspi-branching.md#ruby-のソースビルドが実機で失敗した--原因は-all_compile-だった)）。
この設定を `[settings.python] compile` へ絞ったことで、ruby はプレビルドに戻ります。

Raspberry Pi では加えて `[settings.ruby] compile = false` を宣言します。
mise の既定は「プレビルドが無ければ `ruby-build` へフォールバック」で、
Pi でそこに入ると十数分かけてから失敗します。`false` にすると
**プレビルドが無い時点で即エラー**になり、長時間の徒労を避けられます。

`libyaml-dev` は `121_ubuntu` の build tools に入れてあります。プレビルドを
使う限り不要ですが、x86 / WSL がソースビルドへ落ちたときの保険です
（`psych` 拡張のビルドに要ります）。

### ツール 1 個の失敗で apply を止めない

`125_mise` は `mise install` が失敗しても**警告に留めます**。非ゼロで抜けると、
ツール 1 個の失敗で後続の `126_agent_cli` / `140_herdr_integration` / `400_unix` が
丸ごと走らなくなるためです（実機で ruby が落ちたときに起きました）。
未導入のものは `mise ls --missing` で確認できます。

### メモリが尽きても SSH できるようにする

Raspberry Pi 4（RAM 3.7GB、SD カード）は swap が 0 だと、メモリが尽きても
OOM キラーがなかなか動きません。その間カーネルはプログラムのコードを追い出しては
SD から読み直すため、**sshd も応答しなくなり、電源を抜くしかなくなります**
（[実機で起きた経過](../research/testing/raspi-oom-ssh-freeze.md)）。
`121_ubuntu` が Raspberry Pi でだけ次を入れます。

| 設定 | 値 | 理由 |
| --- | --- | --- |
| zram（`/etc/default/zramswap`） | `zstd`、RAM の 50%、優先度 100 | RAM を圧縮して swap にする。SD に swap を置くと読み書きが遅く、溢れたときに結局固まるうえ、SD も傷む。既定の 256MB では足りない |
| `linux-modules-extra-raspi` | zram モジュールが無いときだけ入れる | Ubuntu for Raspberry Pi は zram を別パッケージに分けている（約 95MB）。無いと `zramswap` が `Module zram not found` で起動しない |
| `vm.swappiness` | 100 | zram は速いので、早めに使わせる |
| `vm.page-cluster` | 0 | zram では先読みの効果が無い |
| earlyoom（`/etc/default/earlyoom`） | 既定のしきい値（空きメモリと空き swap の両方が 10% 以下）で最大のプロセスを止める。sshd / systemd / tailscaled は対象外 | 固まる前に重い処理を止めて、SSH できる状態を保つ |

earlyoom の `--avoid` の正規表現に空白や引用符を入れてはいけません。
systemd は `$EARLYOOM_ARGS` を空白で分割するだけで、引用符を解釈しないためです。
効いているかは `swapon --show` と `journalctl -u earlyoom -b` で確認できます。
systemd が動いていない環境（Docker の検証コンテナなど）では、設定ファイルだけ置いて
サービスの再起動を飛ばします。

### 入ってしまった GUI 一式を消す

raspi 判定が効く前の `apply`（2026-02 の初回と、CHG-0008 の 2 周目）では、
上の表で「導入しない」としたものが入りました。`.chezmoiignore` は展開を
止めるだけで、**既に入ったものは消しません**。`scripts/raspi/uninstall_gui.sh`
でまとめて取り除きます。

```bash
chezmoi execute-template '{{ includeTemplate "is-raspi" . }}'   # true でないと次の apply で戻る
scripts/raspi/uninstall_gui.sh --dry-run   # 消すものを表示するだけ
scripts/raspi/uninstall_gui.sh
```

| 種類 | 消すもの |
| --- | --- |
| apt | `i3 rofi polybar lxappearance xsel`、`code`、`clamav clamav-daemon`、`xrdp xorgxrdp` と、それらを消すと孤立する依存（X サーバ、`i3-wm` など） |
| APT ソース | `vscode.list` / `vscode.sources` / `microsoft-edge.list`。他のソースが使っていなければ `microsoft.gpg` も |
| ファイル | `~/.vscode`、`~/.config/Code`、`~/.config/i3`、`~/.config/polybar`、X 系ドットファイル、Cica フォント、xrdp / ClamAV のログと定義 DB |
| その他 | `xdg-desktop-portal-gnome` の mask、空の `~/thinclient_drives` |

`xrdp` は chezmoi ではなく手動で入れたものですが、セッションが `~/.xsession`
（`exec i3`）前提なので一緒に消します。次のものは残します。

- `~/.vscode-server`（Remote-SSH で繋いだときに VS Code が使う）
- chromium / firefox / chromedriver（chezmoi 由来ではない）
- 実行前から `autoremove` の対象だったパッケージ
- GitHub CLI の APT 登録（`121_ubuntu` と同じく触らない）

Raspberry Pi と判定できないとき（手がかりは `is-raspi` と同じ）と、対象以外の
パッケージが依存で巻き込まれるときは、何も消さずに中止します。

Raspberry Pi 固有のシステム設定（memlock など）は chezmoi では管理せず、
`scripts/raspi/` に置いたまま手動で実行します。
詳細は [CHG-0008](../change/closed/0008-raspi-branching.md) を参照。

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
[MCP サーバ](agent-config-generation.md#mcp-サーバ)を参照。

### mise の settings

`[settings]` に置いている宣言と、その理由です。
`config.toml.tmpl` 側のコメントは参照だけに留めています。

| 設定 | 対象 | 理由 |
| --- | --- | --- |
| `experimental = true` | 全 OS | task runner を使うため |
| `sops.age_key_file` | 全 OS | API キーの復号先を固定するため |
| `[settings.python] compile = true` | raspi 以外 | プリコンパイル済みバイナリは Tkinter を含まないため。[参照](https://www.python.jp/install/ubuntu/index.html) |
| `[settings.ruby] compile = false` | raspi のみ | [ruby はプレビルドで入れる](#ruby-はプレビルドで入れる)を参照 |

**`all_compile` は使いません。** この設定は「**全言語で**プリコンパイル済み
バイナリを使わない」という意味で、Tkinter という目的に対して範囲が広すぎます。
以前は `all_compile = true` を置いていたため node と ruby までソースビルドに
なっていました。mise 側も `all_compile` の自動既定を非推奨化しており、
2027.8.0 で削除予定です。

### npm backend で入れている 2 つ

| ツール | 理由 |
| --- | --- |
| `npm:@bitwarden/cli` | snap 版が動作しなくなったため。bw 不在でも `apply` は完走し、その `apply` 中に入ります。[セキュリティ](security.md#bitwarden連携) |
| `npm:@anthropic-ai/sandbox-runtime` | Claude Code の sandbox が使う seccomp フィルタ。WSL2 では無いと sandbox から脱出できます。mise の隔離先を `settings.json` の `sandbox.seccomp.applyPath` へ橋渡しする必要があり、生成は `scripts/agents/generate.py` が行います。[WSL2 での抜け穴](agent-sandbox.md#wsl2-での抜け穴-seccomp-フィルタ) |

seccomp フィルタは手で `npm install -g` する必要はありません。導入先が実在する
ときだけ `~/.claude/settings.json` に設定が出るため、初回は mise の導入後に
もう一度 `chezmoi apply` します。

## AI CLI の導入

Claude Code / Copilot CLI / OpenCode V2 は**各社公式のインストーラー**で導入します。
実体は `home/.chezmoitemplates/agent-cli-install.sh.tmpl`（Unix 共通の本体）と、
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
Claude Code も導入します。Linux / WSL / macOS では加えて oh-my-pi (`omp`) も
公式インストーラーで入れます。

スクリプトは `run_onchange_after_` で、**既に PATH 上にある CLI には触りません**。
ただし mise の shim（`~/.local/share/mise/shims/` 配下）は導入済みと数えません。
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

`omp` は試用中です（[CHG-0006](../change/0006-pi-harness-trial.md)）。
Linux / WSL / macOS で `curl -fsSL https://omp.sh/install | sh` により導入します。
Pi のフォークで、LSP 統合・DAP・subagent を持ちます。起動は `omp` で、
境界（`ocs`）の外で動きます。

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
**真偽値の 2 つは初回のみ設定**し、以後 `omp config set` や `/settings` で
変えた値は上書きしません（`~/.omp/agent/.chezmoi-seeded` で管理）。

> **permission 機構を持たない設計です。** Pi 系は安全性より利便性を取る方針で、
> 権限制御は拡張か外部の sandbox に委ねます。保護は「どこで起動するか」と
> git の使い方に依存します。**対象リポジトリ直下で起動し、開始前に作業を
> 区切ってコミットしてください。**
> 経緯と代償の一覧は [CHG-0006](../change/0006-pi-harness-trial.md) にあります。

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

herdr が Claude の `settings.json` に足す hook（`~/.claude/hooks/herdr-agent-state.sh`）は、
chezmoi 側の生成処理が外部の hook として残します。仕組みは
[外部ツールとの共存](agent-config-generation.md#外部ツールとの共存-orca--herdr) を参照してください。

### 旧インストーラー版からの移行

旧インストーラーの `~/.local/bin/herdr`（Linux / WSL）や
`%LOCALAPPDATA%\Programs\Herdr\bin\herdr.exe`（Windows）は自動削除しません。
移行後は新しいターミナルで `mise which herdr` と、Linux なら `command -v herdr`、
PowerShell なら `Get-Command herdr` を確認し、mise の実体または shim が選ばれる
ことを確認してください。旧版が選ばれる場合は、Herdr を終了してから旧バイナリだけを
削除するか、mise の shim が先に見つかるよう PATH を整理します。
Herdr のユーザーデータ・設定は削除しません。

## シェルプラグインの取得

シェルの rc が読み込むプラグインは、起動時ではなく `chezmoi apply` が
`home/.chezmoiexternal.toml.tmpl` で取得します。rc は存在するときだけ読み込み、
無くてもシェルは起動します（zinit が無い場合は案内を 1 行出し、`zinit` を
何もしない関数にします）。

| 取得先 | 取得元 | 種類 |
| --- | --- | --- |
| `~/.z` | rupa/z | git-repo（`--depth 1`） |
| `~/.zinit/bin` | zdharma-continuum/zinit | git-repo |
| `~/.bash_it` | Bash-it/bash-it | git-repo（`--depth 1`） |
| `~/.tmux/plugins/tpm` | tmux-plugins/tpm | git-repo（`--depth 1`） |
| `~/.vim/colors/iceberg.vim` | cocopon/iceberg.vim | file |

Windows native では rc を配らないため対象外です。Linux / WSL / Raspberry Pi /
macOS では同じです。

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
prefix + U）。取り直すときはパスを消してから `chezmoi apply` します。
新しい機械では apply に git とネットワークが要り、取得に失敗すると apply が
エラーになります。

### fzf の関数

`~/.config/shell/fzf.sh` は、fzf がある場合だけ `.bashrc` / `.zshrc` から
読み込まれる入口です。同じ階層の `fzf/` にある次の 3 ファイルを順に読み込みます。

| ファイル | 中身 |
| --- | --- |
| `fzf/core.sh` | `FZF_*` のオプションと、移動・汎用の関数（`xf` / `xg` / `xgw` / `v` / `sshf` / `fgg` など） |
| `fzf/git.sh` | git の関数（`fbr` / `fbrm` / `fshow` / `cdworktree` / `fadd`） |
| `fzf/tools.sh` | mise / Singularity / Homebrew の関数 |

各ファイルの関数は、対応するコマンドがある場合だけ定義されます。Windows では
`.chezmoiignore` の `.config/*` によって `fzf/` ごと配られません。

## PowerShellプロファイル

設定の実体は `home/dot_config/powershell/` に置き、`$PROFILE`
（`Documents/PowerShell/` と `Documents/WindowsPowerShell/`）へは
それをdot-sourceするだけのローダーを配置します。

| パス | 役割 |
| --- | --- |
| `home/dot_config/powershell/profile.ps1.tmpl` | PowerShell 7 / 5.1 共通の本体 |
| `home/dot_config/powershell/cache.ps1` | init 出力のキャッシュ（`Get-CachedInitScript`）。本体がトップレベルで dot-source する |
| `home/dot_config/powershell/commands/*.ps1` | 用途別の関数（wsl、docker、fzf、pwgen） |
| `home/Documents/*/profile.ps1.tmpl` | `$PROFILE` から本体を呼ぶローダー |
| `home/.chezmoitemplates/powershell/profile-loader.ps1` | `$PROFILE` ローダーの本文。Documents 配下と `run_after_345` が共有する |
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
- **分割したファイルはトップレベルで dot-source する**: 関数の中から dot-source すると
  定義がその関数のスコープに閉じ、セッションから見えなくなります。
  `test_init_cache_is_dot_sourced_at_the_top_level` で固定します。
  `.chezmoitemplates/` 配下は他ファイルへ埋め込むため対象外です。
- **対話時と非対話時を分ける**: `profile.ps1` はAllHostsプロファイルのため、
  エージェントやスクリプトからの起動でも毎回読み込まれます。プロンプト
  （oh-my-posh）、キーバインド、モジュール読み込みは対話時だけ実行します。
  判定はstdioのリダイレクトに加え、起動引数（`-Command` / `-File` /
  `-EncodedCommand` / `-NonInteractive`。ただし `-NoExit` があれば対話）も見ます。
- **起動経路でcmdletを使わない**: `Microsoft.PowerShell.Management`
  （`Test-Path`、`Join-Path`）、`Microsoft.PowerShell.Utility`
  （`New-Object`、`Set-Alias`）、`Get-Command` のコマンド探索は、初回呼び出しに
  それぞれモジュールの読み込みが乗り、起動が目に見えて遅くなります
  （[計測](../research/shell/powershell-profile-startup.md)）。対話ブロックより前は
  同等の.NET APIで書きます。
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

この構成にしたときの起動時間の計測は
[PowerShell プロファイルの起動時間](../research/shell/powershell-profile-startup.md)
にあります。

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
  Claude Code / Codex CLI には置きません（`docs/spec/agent-command-policy.md` の
  CLI 別の表を参照）。
- **テンプレート内で分岐しない**: 固有の節は該当ファイルへ直接書き足します。
  `{{ if }}` を使わないので、テストは `includeTemplate` を展開するだけで
  実体を再現できます（`test_personal_instructions_share_one_source`）。
- **リポジトリ直下の `AGENTS.md` は対象外**: 適用範囲（このリポジトリのみ）も
  内容（リポジトリ固有の約束）も別系統です。判断の経緯は
  [ADR-0006](../adr/0006-instructions-to-mechanisms.md) にあります。
