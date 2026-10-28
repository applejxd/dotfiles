# chezmoi スクリプトが作るキャッシュ・状態・一時ファイル

`home/.chezmoiscripts/` のスクリプト（と、それが取り込む `home/.chezmoitemplates/`）が**自分のコードで直接作る**
キャッシュ・状態ファイル・再実行の印・一時ファイル・バックアップの一覧。消すときに何が起きるかを知るための表で、
OS ごとに分けた。スクリプトの順序と役割は [プロジェクト構造](structure.md#自動実行スクリプト) を参照。

## 範囲

- **含める**: スクリプトのコードが直接作るもの。キャッシュを作り直させる・消す操作も、区別して載せる
- **含めない**: winget / Chocolatey / Scoop / apt / Homebrew / mise / npm / uv など、外部ツールが自分で作るキャッシュやダウンロード。
  chezmoi 自身の状態（`scriptState`）。chezmoi が配るだけの通常の管理対象ファイル
- 根拠はスクリプトの読解（2026-10-10）。実機で確かめていない挙動は「未確認」「推測」と書く
- **`run_once_` / `run_onchange_` は chezmoi の状態で再実行が決まる。** ここの「消すと再実行される」は、
  スクリプトの実行条件に依存し、ファイルを消しただけでは走り直さないものがある

## 再実行の印の仕組み

`run_onchange_` のスクリプトは、描画結果が前回と同じなら走らない。失敗しても次の apply で走り直したいもの
（AI CLI の導入 `126` / `226`、omp の設定の取得 `420_omp_skills` / `430_omp_claude_assets`）は、
失敗した回に印のファイルを書き直し、スクリプトの描画結果を変える。症状からの手順は
[スクリプトを走らせ直す](troubleshooting-bootstrap.md#スクリプトを走らせ直す)。

- 印は `~/.local/share/dotfiles/retry/` の下に置く（順に `agent-cli-failed` / `omp-skills-failed` /
  `omp-claude-assets-failed`）。スクリプトには印の**更新時刻だけ**を埋め込む。中身を埋め込まないのは、
  書き換えられたときにスクリプトへコードが入らないため。実装は `home/.chezmoitemplates/retry-marker.sh.tmpl`
- 成功した回は印に触れないので、その後は走り直さない
- 更新時刻は秒単位で埋め込まれる。前回の印と同じ秒のうちにまた失敗すると描画が変わらず、成功として
  記録されてしまう。そこで、書き直す前の時刻が前回の印の時刻以前なら、更新時刻を前回 + 1 秒に進める
- 印を置けないときは、警告して**スクリプトを非ゼロで終える**。0 で終えると成功として記録され、次の apply
  でも走らないため。置けないのは次のときで、どれも手で片付けるまで毎回止まる
  - 印の場所にディレクトリなどファイル以外がある
  - 親の経路（`~/.local` から `~/.local/share/dotfiles/retry` まで）のどれかが symlink か、ディレクトリでない。
    symlink を追うと別の場所へ書き、既存のファイルを書き潰しうるので、書く前に止める
- 置き場は、どのエージェントの sandbox からも書けない場所にする。印は apply（ホスト）が書くので、
  sandbox から書けると印を `~/.bashrc` への symlink に差し替えてホストの apply に書き潰させられる。
  同じ理由で、印は同じディレクトリの一時ファイルから `mv` で差し替え、既存の symlink を追わない。
  OS の境界を持たない実行（`ocs` を通さない OpenCode、omp）からは、この置き場でも守れない。
  背景は [記録](../research/chezmoi/rerun-scripts-notes.md)

## 共通（Ubuntu / WSL / macOS）

`000_unix/` と `400_unix/`、取り込まれるテンプレートは Linux と macOS の両方で動く。

| 作るスクリプト | 作られるもの | 種類 | 後始末・消すと |
| --- | --- | --- | --- |
| `retry-marker.sh.tmpl`（`420_omp_skills`・`430_omp_claude_assets`・`agent-cli-install.sh.tmpl` 経由の `126` / `226`） | `~/.local/share/dotfiles/retry/{omp-skills-failed,omp-claude-assets-failed,agent-cli-failed}` | 再実行の印（失敗理由を 1 行） | 成功しても自動では消えない。消すと次の apply で 1 回走り直す（[仕組み](#再実行の印の仕組み)。コードからの推測）。印の差し替え用に同じ場所へ一時ファイル `.retry.XXXXXX` を作り、`mv -f` で置き換える（異常終了時に残りうる。推測） |
| `430_omp_claude_assets.sh.tmpl` | `~/.omp/agent/.chezmoi-seeded` | 状態（初期値として置いた設定のキー名を追記） | 消すと次の apply で `commands.enableClaudeUser` などを再設定し、利用者が戻した値を上書きしうる。**消さない** |
| `000_unix/run_before_005_python.sh.tmpl` | `~/.local/bin/chezmoi-python3`（実体の Python への symlink） | 状態（`ln -sfn` で毎回張り直す） | 消すと次の apply で張り直す。その前の `modify_` スクリプトが一時的に失敗しうる |
| 同上 | `mktemp` の一時ファイル（uv のインストーラ） | 一時 | uv も Python も無いときだけ。使い終えたら `rm -f`（`trap` なし） |
| `400_unix/run_after_440_authorized_keys.sh.tmpl` | `~/.ssh/`（700）・`~/.ssh/authorized_keys`（600） | 生成物（追記のみ） | 消すと鍵認証が効かなくなる。次の apply（`BW_SESSION` あり）で戻す。[仕様](security.md#ssh-公開鍵の-authorized_keys-への追加) |
| `modify_json.py.tmpl`（約 17 本の `modify_*.json.py.tmpl` が使う。全 OS） | 一時ディレクトリ内の `common.toml`（描画済みの内容） | 一時 | `with tempfile.TemporaryDirectory()` で自動削除 |

## Ubuntu / WSL

| 作るスクリプト | 作られるもの | 種類 | 条件・後始末・消すと |
| --- | --- | --- | --- |
| `100_linux/run_once_after_122_font_cica.sh` | `~/.local/share/fonts/Cica/*.ttf` と、`fc-cache -fv` で更新するフォントキャッシュ | 生成物・キャッシュ（外部コマンドに作らせる） | fontconfig があり Cica が未導入のとき。ダウンロード用の `mktemp -d` は `trap` で削除する。フォントキャッシュは再生成できる |
| `100_linux/run_after_140_herdr_integration.sh.tmpl` | `~/.claude/skills/herdr/.herdr-skill.XXXXXX` | 一時 | 毎 apply。`trap` と `mv -f` で本体（`SKILL.md`）へ置き換え、残らない |
| `100_linux/run_once_after_120_wsl.sh.tmpl` | `/etc/wsl.conf` と、内容が変わるときの退避 `/etc/wsl.conf.bak.<日時>.<乱数>`。比較用の `mktemp` は `trap` で削除 | 生成物（`sudo install`）・バックアップ | 消すと systemd の有効化などが失われる。退避は世代を消さないので増える（不要なら手で消す） |
| `100_linux/run_once_after_121_ubuntu.sh.tmpl` | `/etc/default/zramswap`・`/etc/sysctl.d/99-zram.conf`・`/etc/default/earlyoom` | 生成物（`sudo tee`） | Raspberry Pi のみ。消すと zram と earlyoom の設定が既定に戻る |
| `100_linux/run_once_after_123_tailscale.sh.tmpl` | `/usr/share/keyrings/tailscale-archive-keyring.gpg`・`/etc/apt/sources.list.d/tailscale.list` | 生成物（`sudo install`。内容が変わったときだけ更新） | `applejxd` かつ WSL 以外（Raspberry Pi を含む）。消すと apt が tailscale を更新できない |
| `100_linux/110_native/run_once_after_111_microsoft.sh.tmpl` | `/usr/share/keyrings/microsoft.gpg`・`/etc/apt/sources.list.d/vscode.list` | 生成物 | Raspberry Pi 以外。`vscode.sources` があるときは `vscode.list` を作らない |

## macOS

共通の表のほかに、`200_mac/` が直接作るものは次だけ。

| 作るスクリプト | 作られるもの | 種類 | 条件・後始末 |
| --- | --- | --- | --- |
| `200_mac/run_once_after_210_osx.sh.tmpl` | `~/.iterm2_shell_integration.zsh` | 生成物（公式インストーラを `curl \| bash` で実行して作らせる） | 未存在のときだけ。残る。`run_once_` なので消しても自動では戻らない。インストーラの挙動は未確認 |

`sudo-keepalive.sh.tmpl`（`205` / `210` / `250`）はファイルを作らず、バックグラウンドのサブシェルで `sudo` を延命し、
`trap EXIT` で止める。

## Windows

| 作るスクリプト | 作られるもの | 種類 | 条件・後始末・消すと |
| --- | --- | --- | --- |
| `300_windows/run_after_348_authorized_keys.ps1.tmpl` | `%ProgramData%\dotfiles\admin-authorized-keys.fp` | 状態（処理済みの鍵の指紋を追記。Users は読み取りのみ） | 管理者グループの利用者のとき。残る。消すと次の apply で UAC を出し、`administrators_authorized_keys` へ再同期する（`DOTFILES_RESYNC_ADMIN_KEY=1` でも強制）。[仕様](security.md#ssh-公開鍵の-authorized_keys-への追加) |
| 同上 | `%ProgramData%\ssh\administrators_authorized_keys`・`~\.ssh\authorized_keys` | 生成物（追記のみ） | 消すと鍵認証が効かなくなる。指紋の記録が残っていると管理者側は再作成されないので、記録とあわせて消す |
| 同上・`310_packages/run_once_before_309_admin.ps1.tmpl` | `%TEMP%\chezmoi-348-<guid>.log`・`%TEMP%\chezmoi-309-<guid>.log` | 一時（昇格した子のログ） | 昇格するときだけ。`finally` で削除 |
| `300_windows/run_after_343_herdr_integration.ps1.tmpl` | `~\.claude\skills\herdr\.<guid>.tmp`・同 `.bak` | 一時・バックアップ（`File.Replace` が作る） | 毎 apply。`finally` で削除。異常終了時だけ残りうる（推測） |
| `300_windows/run_once_after_330_font.ps1` | `~\RictyDiminished-for-Powerline.ttf`・`~\Cica.zip`・`~\Cica\` | 一時（ダウンロードと展開先） | フォントが未導入のとき。使い終えたら削除。途中で失敗すると残りうる（`Remove-Item` が末尾にあるため。推測） |
| `300_windows/310_packages/run_once_after_315_keypirinha_extensions.ps1` | `%APPDATA%\Keypirinha\InstalledPackages\*.keypirinha-package.download` と、成果の `*.keypirinha-package` | 一時・生成物 | 未導入のものだけ。`.download` は `Move-Item` で本体へ置き、`finally` で削除。既存ファイルは上書きしない |
| `300_windows/run_after_345_powershell_profile.ps1.tmpl` | `MyDocuments` の実体の下の `PowerShell\profile.ps1`・`WindowsPowerShell\profile.ps1` | 生成物（OneDrive の既知フォルダー移動時だけ置く、BOM 付きのローダー） | 内容が違うときだけ上書き |
| `300_windows/run_after_342_copilot_skills.ps1.tmpl` | `~\.copilot\skills`（Junction） | 生成物 | 正しければ維持。空ディレクトリや意図しないものは `rmdir` して作り直す（実体は消さない） |

`320_regkey/` と `331_power`（毎回走る `run_after_`）はレジストリと `powercfg` の設定だけで、ファイルを作らない。

## 消す側（既存のキャッシュ・残骸を削除する）

| OS | スクリプト | 消すもの | 消すとどうなるか |
| --- | --- | --- | --- |
| Linux・macOS | `000_unix/run_onchange_after_020_zinit_completions.sh` | `${ZDOTDIR:-$HOME}/.zcompdump` と `.zcompdump.*`・`.zcompdump-*`（補完のダンプ。キャッシュ） | 次回のシェル起動で `compinit` が作り直す |
| Linux・macOS | 同上 | `~/.zinit/completions/` のうち ohmyzsh 由来の symlink | zinit が自動導入した補完リンクが消える |
| Linux・macOS | `agent-cli-install.sh.tmpl`（`126` / `226`） | `~/.local/share/mise/shims/{claude,copilot,opencode,omp}` と `installs/{claude,claude-code,copilot,opencode,omp}` | mise 版の AI CLI が消え、公式版の導入が妨げられなくなる |
| Linux | `100_linux/run_once_after_121_ubuntu.sh.tmpl` | `/etc/apt/sources.list.d/vscode.list`（`vscode.sources` と重複するとき） | apt の重複警告が消える |
| Linux | 同上 | `$HOME` 直下の `デスクトップ` `ダウンロード` `テンプレート` `公開` `ドキュメント` `ミュージック` `ピクチャ` `ビデオ`（**空のときだけ** `rmdir`） | `xdg-user-dirs-update` が英語名を作った直後に、日本語名の空フォルダを消す。中身があれば警告を出して残す |
| Windows | `300_windows/run_once_after_344_cleanup_agents_pycache.ps1` | `~\.config\agents\__pycache__` | 古い pyc が消える。Python が再生成する |

## modify_ スクリプトの一時ファイル

`modify_*.json.py.tmpl` は `modify_json.py.tmpl` を共有し、一時ディレクトリを自動で消す（共通の表を参照）。
このとき `scripts/agents/generate.py` を子プロセスで起動する。`-B`（`.pyc` を書かない）を付けていないので、
`scripts/agents/` に `__pycache__` ができる可能性がある（推測。`.gitignore` で git の管理外）。

## 確かめていないこと

- `retry-marker.sh.tmpl` の印を消したときの再実行は、コードからの推測で、実機では確かめていない
- Windows の指紋の記録（`.fp`）を消したときの挙動は、昇格なしの試験でだけ確かめた
- `is-raspi`・`llm-provider`・`powershell/profile-loader.ps1`・Keypirinha の `modify_*.ini` は精読していない（検索では該当なし）
