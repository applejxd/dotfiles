# CLI の導入と管理

mise で入れる CLI、pi の導入と更新、Herdr の管理。pi の設定は [pi の設定の生成と所有権](agent-config-generation.md)。

## mise による CLI 管理

本体の宣言は `home/dot_config/mise/config.toml.tmpl` に集約します。
GitHub CLI は全 OS 共通で `gh = "latest"` を宣言し、aqua の `cli/cli` から導入します。
Windows 用設定には Unix 専用ツールや設定を含めません。
Unix の uv も同じ mise 設定で導入します。uv の重複導入を持っていた `000_unix/010_tools` は廃止しました。
pi は、Linux / WSL / macOS では公式のインストーラーで導入し、Windows では mise が導入します
（[pi の導入](#pi-の導入)・[Windows の pi](#windows-の-pi)）。

`gh` の更新はホームディレクトリで `mise upgrade gh` を実行します。
Ubuntu の `121_ubuntu` では GitHub CLI 用の APT リポジトリ・鍵の登録と
`apt install gh` を行いません。Git 本体の APT 導入は維持します。
既存の APT 版や登録済みリポジトリ・鍵、認証設定は自動削除しません。
移行後は `mise which gh` と `command -v gh` / `Get-Command gh` を比較し、
mise の実体または shim が選ばれることを確認してください。

AWS CLI（`aws-cli`、aqua の `aws/aws-cli`）は Unix で `applejxd` 以外のユーザーにだけ宣言します。

`ruff` と `oxlint` は Unix で宣言します（pre-commit の lint と、編集後の整形に使う）。

ツールごとの導入コマンドは持たず、設定配備後にホームディレクトリを基準として
**引数なしの `mise install`** を実行します。

| 環境 | mise の一括導入 | 後続の設定 |
| --- | --- | --- |
| Linux / WSL | OS 依存パッケージの後、`100_linux/125_mise` | `100_linux/126_agent_cli`（pi） |
| macOS | Homebrew の後、`200_mac/225_mise` | `200_mac/226_agent_cli`（pi） |
| Windows | `310_winget` で mise を導入し、設定配備後に `310_packages/313_mise` | `310_packages/314_agent_cli`（npm 版 pi の撤去と起動の確認） |

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

### Windows のシェル補助ツール

PowerShell の補助（[bash/zsh と PowerShell の対応](shell.md#bashzsh-と-powershell-の対応)）が使う道具を、Windows でも入れる（2026-11-25）。
`bat`（`cat`・fzf の Ctrl+t のプレビュー）・`eza`（`ll` / `lt`・chpwd の一覧・fzf の Alt+C のプレビュー）・`ripgrep`（fzf の既定のコマンド）・`yazi`（`y`）は mise
（`config.toml.tmpl` の Windows の `[tools]`）、`yt-dlp`（`audio-dl` / `video-dl`）は個人 PC だけ mise、`zstd`（`zpack` / `zunpack`）は mise の registry に無いので scoop（`311_scoop`）、
`posh-git`（git の Tab 補完だけ。プロンプトは oh-my-posh のまま）は PSGallery（`310_winget`）。どの補助も、道具が無い機では標準の機能へ落ちる（`ll` は `Get-ChildItem`、`cat` は `Get-Content`）。
mise で入れる 5 つが、Windows で入ることは、使い捨ての `MISE_DATA_DIR` へ `mise install` して確かめた（2026-11-25。`gwq`（go バックエンド）・`tmux`・`neovim`・`deno`・`btop` などは入れない）。
実際の配備（`313_mise`）は未実行。

### chezmoi 本体

README の公式インストーラ（`get.chezmoi.io`、Windows は winget）は初回の
bootstrap だけに使います。以降は mise が `chezmoi = "latest"` で管理を引き継ぎ
（`config.toml.tmpl`）、`chezmoi apply` 後は mise 版が使われるため、
`~/.local/bin` のコピーは残さなくてよいです。

**snap 版は使いません。** snap の confinement 下では
pi の囲い（`pib`）の内側で
起動できず、`chezmoi apply` が失敗します（実測）。
既に snap 版が入っている場合は `sudo snap remove chezmoi` で外します。
`/snap/bin` は PATH で mise の shim より前に来るため、**消さないと
mise 管理版が使われません**。削除後は `hash -r` を実行します。

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

### npm backend で入れているもの

| ツール | 理由 |
| --- | --- |
| `npm:@bitwarden/cli` | snap 版が動作しなくなったため。bw 不在でも `apply` は完走し、その `apply` 中に入ります。[セキュリティ](security.md#bitwarden連携) |

### git flow（git-flow-next）

`github:gittower/git-flow-next` は、利用者が feature の起票・クローズを行う `git flow` の実体です（[CHG-0047](../change/0047-gitflow.md)。AI の `gitflow_*` 操作は CHG-0050 で撤去）。Linux / WSL / Windows に入れます（macOS は未確認なので入れない。Windows は 2026-11-21 に導入と `git flow init --help` の実行を確認した）。

- **版とチェックサムを固定しています**。公式の Releases の `checksums.txt` の値を `platforms.<os>-<arch>.checksum` に写します（`linux-x64`・`linux-arm64`・`windows-x64`）。上げるときは、`git-flow` が `.git/config` に書く設定の意味が変わりうるので、`scripts/gitflow-setup.sh` と動作を見直す
- **Windows**（2026-11-21 に確認）: `windows-x64` の zip（`git-flow.exe`）を mise が入れ、`git flow` として動く。入るのは `chezmoi apply`（`313_mise` が `mise install` と `reshim`。設定の hash が変わると走る）のあと。`config.toml.tmpl` では、Windows は先頭の `[tools]` と末尾のこのブロックだけが描画される（途中は `ne windows` の中）ので、宣言は末尾に置いている。`git flow init --preset=classic --defaults` と、`scripts/gitflow-setup.sh`（共有の `.gitflow` の取り込み）、`git flow feature start … --worktree` は、使い捨ての clone で動いた
- 実体は `git-flow` 1 つ。PATH にあれば `git flow` として動く。利用者が自分のシェルで実行する（bash の `git flow` の拒否は撤去した）
- リポジトリごとの設定は `.gitflow`（共有）。新しい clone では `git flow config sync` で有効にする。設定は、サンドボックスの外で、利用者が一度だけ行う（`.git/config` を書くため）

### Windows の pi

Windows の pi は、mise の `aqua:earendil-works/pi`（ビルド済みバイナリ。bun 製、約 230 MB）で導入します。
`config.toml.tmpl` に版を明示で固定し（`latest` は `minimum_release_age` で最新版が隠れる）、`313_mise` の
`mise install` が入れます。`314_agent_cli` は、旧方式の npm 版が残っていれば `npm uninstall -g` で外し、
`mise exec -- pi --version` で起動を確かめます。更新は版を書き換えて `chezmoi apply` です（`pi update` では更新しません）。

- 選んだ理由: npm 版は node の解決順に左右される。Machine PATH に古い node があると、pi の導入も起動も失敗する
  （Sandbox で再現）。バイナリ版は node を使わないので、この種の障害が起きない。公式の `install.ps1` は
  `Read-Host` で確認を聞き、apply では答えられない
- Linux / WSL と同じ公式インストーラーに統一しない理由は、[下の表](#linux--wsl--macos-と-windows-の違い)。
  Linux の `~/.pi/agent/bin/pi` は Node 製の launcher で、Windows のバイナリ版とは別物（以前ここに「同じバイナリ」と書いていたのは誤り）
- バイナリ版は `process.argv[1]` が仮想パス（`B:/~BUN/root/pi.exe`）で、CLI ファイルではない。
  `subagents` はこれを子の引数に渡さないようにした（`childArgs`、試験あり）
- 導入・起動の実測と未確認事項は [記録](../research/chezmoi/structure-windows-notes.md)
- 旧 npm 版が残る PC は、`npm uninstall -g @earendil-works/pi-coding-agent` で外す（`314` が自動で行う）
- 固定した版は、Linux / WSL の `pi --version` と揃える（2026-11-23 に、固定が 1.2.0・Linux が 1.5.2 とずれているのを見つけて 1.5.2 に上げた。ずれを検出する仕組みは無い）

#### Linux / WSL / macOS と Windows の違い

公式インストーラーの pi は Node 製で、実行時に PATH 上の `node` を使う。Linux ではそれが常に満たされ、Windows では満たされない場面がある。
根拠は `install.sh` / `install.ps1`・`shellenv.sh` を読んだ結果（2026-11-23）。**Windows での失敗の再現は未実施**（Sandbox を試したが、利用者のセッションが切断・ロック中で、起動後の処理が走らなかった。Sandbox は画面がつながった状態で実行する）。

| 観点 | Linux / WSL / macOS | Windows |
| --- | --- | --- |
| pi の実体 | Node 製。launcher が `~/.pi/agent/install/releases/<版>/node_modules/.bin/pi` を実行する | mise 経由の bun 製バイナリ（node 不要） |
| 実行時の node | PATH 上の `node`。インストーラーが入れた独自 Node があれば先頭に足す | `pi.cmd` が `node=node`（PATH 上）。固定されるのは独自 Node を入れた場合だけ |
| PATH の作り方 | `shellenv.sh` が mise の shims を先頭に置く（zsh は `.zshenv`、bash は `.bash_profile`）。優先順位は 1 本 | レジストリは Machine → User の順。shims は載らず、`mise activate` は PowerShell の profile だけ |
| 古い node | 先頭の shims が勝つ | Machine PATH の古い node が先に勝つ（旧 npm 版で再現した失敗） |
| node が見つからない場面 | ほぼ無い | profile を読まないシェルと、そこから起動するもの（例: `cmd`・Explorer） |
| 導入時の確認入力 | `/dev/tty` が開けなければ飛ばす。node が無ければ失敗にして次の apply で再実行 | `Read-Host`。端末が無ければ多くは飛ばすが、PATH 追加の確認は条件なしで、`-NonInteractive` ではエラー |
| bash | OS 標準 | Git Bash が必要（無ければインストーラーが聞く） |
| 更新 | `pi update` | 版を書き換えて `chezmoi apply` |

統一するなら、Windows の node を Machine PATH に置く、またはインストーラーの独自 Node（確認が要る）を使う必要がある。
どちらも現状の設計（mise が node を管理し、PATH を触らない）と合わないので、バイナリ版のままにしている。

## pi の導入

Linux / WSL / macOS の pi は**公式のインストーラー**（`pi.dev/install.sh`）で導入します（本体は `~/.pi/agent/install`、入口は `~/bin/pi`。更新は `pi update`）。
導入処理の本体は `home/.chezmoitemplates/agent-cli-install.sh.tmpl`（Unix 共通）と、
それを `template` で取り込む OS 別スクリプト（`100_linux/126_agent_cli`・`200_mac/226_agent_cli`）です。
Windows の pi は mise が入れます（[Windows の pi](#windows-の-pi)）。

- pi は mise の Node.js が入っていないと入れません（インストーラーが Node.js の導入を端末で聞くため。次の apply で走り直す）。
- スクリプトは `run_onchange_after_` で、**既に PATH 上にある pi には触りません**。ただし mise の shim（`~/.local/share/mise/shims/` 配下）は導入済みと数えません
  （shim が公式版より先に PATH で見つかり起動を横取りする。経緯は [AI CLI が mise に global default version を指定しろと言う](troubleshooting-bootstrap.md#ai-cli-が-mise-に-global-default-version-を指定しろと言う)）。
- 導入に失敗した回は再実行の印（`~/.local/share/dotfiles/retry/agent-cli-failed`）を書き直すので、次の apply でも走り直します
  （[スクリプトを走らせ直す](troubleshooting-bootstrap.md#スクリプトを走らせ直す)）。毎回ダウンロードしないので apply が遅くなりません。
- Claude Code・Copilot CLI・OpenCode・oh-my-pi は導入しません（[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md)）。すでに入っているものは触りません。
  設定を管理するのは Claude Code だけで、予備のハーネスとして、claude が PATH にある機に標準の設定だけを配ります（[Claude Code の設定](claude-code.md)・[ADR-0041](../adr/0041-claude-code-spare-harness-static-config.md)）。

## Herdr の管理

Herdr は `home/dot_config/mise/config.toml.tmpl` の `herdr = "latest"` で管理します。
mise の aqua backend が公式 GitHub Releases のバイナリをユーザースコープへ取得します。
Linux / WSL と Windows native にのみ展開し、macOS は従来どおり自動導入しません。
Windows の `.config/mise/config.toml` は `.chezmoiignore.tmpl` の除外例外とし、
gh とともに宣言します。

Linux では `125`、Windows では `313` の `mise install` で Herdr も導入します。
agent の統合（`herdr integration install` と、`herdr --skill` から生成する skill）は、pi 以外の AI CLI の設定を書くため行いません
（[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md)）。必要なら利用者が手で実行します。

本体の更新はホームディレクトリで `mise upgrade herdr` を実行します。mise の管理情報と実体が
食い違うため、`herdr update` は使いません。

初回適用後に `herdr` が見つからない場合は、新しいターミナルを開いてください。
Windows ARM64 では、Herdr 公式の x86_64 ビルドが Windows のエミュレーション上で動作します。

### 旧インストーラー版からの移行

旧インストーラーの `~/.local/bin/herdr`（Linux / WSL）や
`%LOCALAPPDATA%\Programs\Herdr\bin\herdr.exe`（Windows）は自動削除しません。
移行後は新しいターミナルで `mise which herdr` と、Linux なら `command -v herdr`、
PowerShell なら `Get-Command herdr` を確認し、mise の実体または shim が選ばれる
ことを確認してください。旧版が選ばれる場合は、Herdr を終了してから旧バイナリだけを
削除するか、mise の shim が先に見つかるよう PATH を整理します。
Herdr のユーザーデータ・設定は削除しません。

## 外部（external）の取得

`chezmoi apply` が `home/.chezmoiexternal.toml.tmpl` で取得するものの扱い。

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
