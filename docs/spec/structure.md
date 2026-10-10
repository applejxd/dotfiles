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

### clang が C++ の標準ヘッダを見つけられるようにする

`121_ubuntu` は build tools の後で、**clang が選ぶ gcc の版**に合わせて
`libstdc++-<版>-dev` を入れます。版は `/usr/bin/clang -x c++ -E -v` の
`Selected GCC installation:` 行から取り（`14.2.0` のような形なら先頭の `14`）、
入れた後に `#include <cstdio>` が通ることを確かめます。版が判定できない・
パッケージが無い・確認が通らないときはエラーで止めます（黙って飛ばすと
`run_once_` が成功として記録され、やり直されないため）。

gcc の triplet から `/usr/lib/gcc/<triplet>/` の最新版を推測する方式は採りません。
clang の選択と一致する保証が無く、conda の gcc が PATH の先にあると
`gcc -dumpmachine` が `x86_64-conda-linux-gnu` を返して存在しないディレクトリを
探すためです（2026-10-05 に観測）。`/usr/bin/clang` を明示するのも、conda などの
clang ではなく apt の clang を直すためです。

clang（`clang-tidy` も）は、C++ の標準ヘッダを探すときに最も新しい gcc の版の
ディレクトリを選びます。そのディレクトリは `libgcc-<版>-dev` だけでも作られ、
別のパッケージ（例: `libgccjit0`）がそれを引き込むことがあります。その版の
`libstdc++-<版>-dev` が無いと、`#include <cstdio>` すら `file not found` になります。

2026-10-01 に WSL（Ubuntu 24.04）で観測しました。`libgcc-14-dev` があり
`libstdc++-14-dev` が無い状態で、Ubuntu の clang 18 も同じエラーを出しました。
版を決め打ちしないのは、Ubuntu の版ごとに gcc の版が違うためです。

`clang-tidy` は OpenCode の編集直後の lint で C/C++ に使います。

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

### WSL

`/etc/wsl.conf` は `100_linux/run_once_after_120_wsl.sh.tmpl` が丸ごと書き出します
（内容を変えると次の `apply` で再実行され、sudo を求めます）。反映には Windows 側で
`wsl --shutdown` が要ります。

`[automount] mountFsTab = false` で、`/etc/fstab` の処理を WSL の init ではなく
systemd（`systemd=true`）に任せます。WSL の init は起動直後に `mount -a` を一度だけ
実行するため、Tailscale の名前など起動直後に解決できないホストへの CIFS マウントが
`Processing /etc/fstab with mount -a failed.` で失敗します。systemd は CIFS を
ネットワーク FS として扱い、ネットワークの起動後にマウントするので、同じ行が
そのままマウントされます（NAS への CIFS マウントで確認済み）。
`/etc/fstab` 自体は chezmoi では管理しません。

## 管理者権限の集約

Windows で管理者権限が要る作業は `300_windows/310_packages/run_once_before_309_admin.ps1.tmpl` の 1 本に集約し、
chezmoi スクリプト自身が出す UAC を 1 回にする。通常ユーザーで `chezmoi apply` を実行する設計は変えない。
`310_winget` に残るパッケージは user scope で入る前提（[振り分け](#winget-パッケージの-user--machine-の振り分け)）。それでもインストーラーが UAC を出したら 309 へ移す。

| 項目 | 内容 |
| --- | --- |
| 対象（許可リストのキー） | `Chocolatey`（winget 経由）・`chocolateygui`・`Keypirinha`・`WinSCP`（machine scope）・`VSCode`（machine scope）・`LongPaths`・`RDP`・machine 版しかない winget パッケージ（[下記](#winget-パッケージの-user--machine-の振り分け)） |
| 流れ | 通常権限で不足を判定 → 不足があるときだけ UAC を 1 回 → 昇格子が不足分だけ実行 → 通常権限で再判定。導入済みなら UAC は出ない |
| 失敗 | UAC キャンセル・昇格子の非ゼロ終了・再判定の残りはすべて非ゼロで止める。失敗した回は `run_once` に記録されないので、直して `chezmoi apply` をやり直せば 309 は再実行される。成功後に消えたものは自動では直さない（内容を変えるか `chezmoi state delete-bucket --bucket=scriptState` で再実行） |
| 実行順 | 同じディレクトリで `309_admin` は `310_winget` より前（属性を除いた名前の昇順） |
| ユーザーの作業 | `340_vscode`（拡張）・`315_keypirinha_extensions` は通常権限のまま。VS Code が無ければ 340 は失敗する |

### 昇格の仕組み

- 昇格子は `-File` ではなく `-EncodedCommand`（UTF-16LE の Base64）で起動する。ブートストラップが 309 を**一度だけ**
  バイト列で読み、親が昇格前に計算した SHA-256 と照合し、一致したときだけそのメモリ上のテキストを実行する
  （承認待ち〜読込の間の差し替えを検出する）。パスなどの埋め込みは `'` を `''` に置換したリテラルにする
- 昇格子は許可リスト外・重複のキーを拒否する（終了コード 2）。ハッシュ不一致は終了コード 3
- 昇格子のコンソールは閉じるので、メッセージは親が作る一時ログへ追記し、失敗時に親が表示する
- 試験用の環境変数: `CHEZMOI_309_NO_UAC=1`（昇格せずに子を起動）、`CHEZMOI_309_FORCE_TARGETS=<csv>`（判定を上書き）

### winget パッケージの user / machine の振り分け

`winget show --id <ID> --exact --scope user|machine`（2026-10 実測）で、scope ごとに適用できるインストーラーがあるかを見て振り分けた。
winget の既定は user scope なので、user 版があるものは UAC なしで入る。user 版が無いものは winget が UAC を出す。

| 分類 | パッケージ | 扱い |
| --- | --- | --- |
| machine 版しかない（user 版なし） | Chrome・Google 日本語入力・7-Zip・Hack フォント・iTunes・Google Drive・Dropbox・Ditto・Tailscale・Steam・Wacom ドライバー | `309_admin` が `--scope machine` で導入（iTunes 以降は `applejxd` だけ） |
| scope 未宣言の MSI | Python Launcher（`launcher.msi`） | `309_admin` が `--scope` なしで導入。付けると `No applicable installer` になる。MSI の既定が全ユーザーかは**未確認**（導入後に UAC が出るか・導入先で確かめる） |
| 両 scope 対応 | PowerShell・fzf・jq・Obsidian・Oh My Posh・PowerToys・Git・Node.js・mise・Python 3.12・uv・Bitwarden（本体・CLI） | 既定（user）のまま `310_winget` |
| user 版しかない | QuickLook・Spotify・Discord | `310_winget` |
| scope 未宣言の NSIS | Orca | `310_winget`。Electron の NSIS は既定が per-user のはずだが**未確認**。UAC が出たら 309 へ移す |
| Microsoft Store | Keyhac・iCloud・Kindle・Codex App | `310_winget`（Store 版はユーザー単位） |

- 309 の導入判定は `winget list` の出力の ID 列に一致するか。これらは winget では user 版を入れられないので、入っていれば machine 版とみなす（Python Launcher は例外）。winget 以外の経路で入れた同名の user 版が残っていても「導入済み」とみなす（機能を満たすので許容。machine 版にしたいときは手でアンインストールして再実行）
- 両 scope 対応のものを machine にする理由は個人 PC では無い。必要になった（ドライバー・IME・他ツールが system-wide を要求）ものだけ 309 へ移す

### 保証しないこと

- 昇格前に、元ユーザー権限の別プロセスが temp の 309 やソースを書き換える攻撃は防がない（信頼の起点が無い。
  chezmoi 公式の昇格パターンと同じ前提）
- 昇格先が別アカウントのとき、309 自身の処理は元ユーザー・昇格先のホームへ書かない。ただし呼び出す
  `winget` / `choco` / インストーラーが昇格先に作るログ・状態・キャッシュは制御しない
- 昇格先アカウントで `winget`（App Installer）が使えない場合は Chocolatey・WinSCP・VS Code を導入できず、
  明示エラーで止まる（代替の導入経路は持たない）

### 個別の判断

- **VS Code**: machine 版でも user 版でも `Code.exe` があれば満たす（併存を許容。340 は `code` が使えればよい）
- **WinSCP**: Keypirinha が system-wide を要求するので machine 版だけを満たすとみなす。user 版などが残って
  winget が拒否した場合は失敗にし、`winget list --id WinSCP.WinSCP` で確認してアンインストールしてから再実行する
- **RDP**: `applejxd` かつ Pro / Enterprise / Education 系の SKU のときだけ。`fDenyTSConnections=0`、NLA（`UserAuthentication=1`）、
  `RemoteDesktop-UserMode-In-TCP` / `-UDP` を有効にして Profile を Domain・Private に限る（既定は Any で Public を含む）。
  判定は `Get-NetFirewallRule -PolicyStore ActiveStore`（ポリシー適用後）。Shadow 規則・`Remote Desktop Users`・`TermService` は触らない。
  設定後に実効状態が合わなければ失敗にする

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

### github backend で版を固定している Fence

`github:fencesandbox/fence` は OpenCode の隔離起動（`ocs`）が境界を張る道具です
（[OpenCode 隔離起動](opencode-sandbox.md)）。Linux / WSL だけに入れます。

- **版とチェックサムを固定しています。** 0.1.x で開発元が 1 社のため、`latest` で
  追わず、上げるときは Releases の `checksums.txt` の値を `platforms.<os>-<arch>.checksum`
  に写します（`linux-x64` と `linux-arm64`）。mise は落とした tar.gz の sha256 を照合し、
  違えば導入を止めます
- `ocs` は `~/.local/share/mise/installs/github-fencesandbox-fence/latest/fence` を
  絶対パスで呼びます（`[opencode.sandbox] runtime_path`）。境界の設定は実体の有無に
  関係なく生成され、実体が無ければ `ocs` が起動を断ります（`mise install` で入れる）
- Claude Code の sandbox は引き続き `npm:@anthropic-ai/sandbox-runtime` を使います

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
pi（`pi.dev/install.sh`）も公式インストーラーで入れます。pi は mise の Node.js が入っていないと
入れません（インストーラーが Node.js の導入を端末で聞くため。次の apply で走り直す）。
pi はハーネス付きの `pis` で起動する（[pi のハーネス](pi-harness.md#起動)）。

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
応答の人柄は `personality` を `friendly`（既定は `default`）にします。
**これら 3 つの初期値は初回のみ設定**し、以後 `omp config set` や `/settings` で
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
生成物なので source state には取り込まず、`.chezmoiignore` で `chezmoi add` の対象からも外しています。

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

## シェルの起動契約

シェルの主な利用者は AI エージェントである。OpenCode は `/usr/bin/zsh` を
非対話・非 TTY で起動し、`.zshenv` だけが読まれる。そのため、どのファイルが
どの起動形態で読まれるかを次のとおり固定する。

| ファイル | 読まれる起動 | 置いてよいもの |
| --- | --- | --- |
| `.zshenv` | 全 zsh（対話・非対話を問わない） | PATH と環境変数だけ（例外は表の下） |
| `.bash_profile` | login bash（非対話の login を含む。`bash -lc` など） | PATH と環境変数だけ |
| `~/.config/shell/shellenv.sh` | `.zshenv` と `.bash_profile` から読まれる（素の `bash -c` や非 login の bash は読まない） | PATH と環境変数だけ |
| `.bashrc` のガード前 | 対話 bash と、`.bash_profile` から読まれる login bash（素の `bash -c` は読まない） | `mise activate` と ROS の `setup.bash`（PATH のため） |
| `.zshrc`（先頭の `[[ -o interactive ]] \|\| return 0` の後）、`.bashrc` のガード後、`shellrc.sh` | 対話シェル | alias・関数・キー設定・補完・プラグイン・出力 |

`.zshenv` には環境変数のほかに例外が 1 つある。リポジトリ内にいる間 `TMPDIR` を
そのリポジトリの `.tmp` に向けるため、関数を 1 つ定義して `mkdir -p` を実行する
（出力はしない）。

`shellenv.sh` は mise の shims（`${MISE_DATA_DIR:-~/.local/share/mise}/shims`）を、
存在するときだけ PATH の先頭へ 1 回置く（継承した PATH に既にあれば先頭へ移す。venv の
`bin` が PATH にあればその直後）。非対話でも cwd の `mise.toml` の版で解決される。
版の再現性が要る操作（lint・ビルドなど）は shim ではなく `mise exec` を使う。
実測は[調査記録](../research/shell/mise-shims-resolution.md)。

WSL では `shellenv.sh` が `wslenv.sh` を読み、Windows 側のディレクトリ（`Windows` /
`System32`、PowerShell 5.1、PowerShell 7（`C:\Program Files\PowerShell\7` があるとき
だけ）、VS Code、Java）を PATH の先頭へ足す。`/etc/wsl.conf` の
`appendWindowsPath=false` で Windows の PATH は引き継がないため、`pwsh.exe` なども
ここで足したものしか名前で呼べない。入れ子のシェルで読み直しても重複しないよう、
PATH と `LD_LIBRARY_PATH`（`/usr/lib/wsl/lib`）は既にあれば足さない。足すための
補助関数は読み終えたら `unset -f` で消す（方針 1）。

Copilot CLI がツールとして起動するシェルへ渡す git の既定値（入力待ちにしない）は、
対話側の `shellrc.sh` にある `copilot()` 関数が、未設定の変数だけをコマンド前置きの
代入で入れる（空文字は空のまま、呼び出し元の環境は変えない）。値の正本は
`common.toml.tmpl` の `[agent_env]`（[詳細](agent-config-generation.md#shell-ツールの環境変数)）。

`.zshrc` の冒頭は `/etc/zsh/zshrc` の読み込みも含む（`.zshenv` の `no_global_rcs`
で自動では読まれないため、対話のときだけ読む）。

方針:

1. 非対話でも読まれる起動ファイル（表の `.zshenv` / `.bash_profile` /
   `shellenv.sh`、`.bashrc` のガード前）には alias・関数・出力・キー設定を置かない
   （`TMPDIR` の例外を除く）。
2. 対話判定は zsh の `[[ -o interactive ]]`、bash の `$-` で行う。TTY の有無は
   表示用の補助にとどめ、環境変数を並べて「人間か」を推測する判定は採らない。
3. 標準コマンドの意味を変える alias（`cat=bat`、`ls=eza`、`diff=colordiff`、
   `vi` / `vim` / `agent` など）は対話 rc（`shellrc.sh`）だけに置く。
4. 呼び出し元が明示した `LC_ALL` / `LANG` / `EDITOR` / `VISUAL` は上書きしない。
   未設定のときだけ既定値を決める。自動実行は入力待ちで止まらないようにするが、
   `EDITOR=true` のように成功を偽装する値は採らない。
5. 関数内の失敗は `exit` ではなく `return` で抜ける（`ccd` / `jcd` / `cdf`）。
   `zpack` は既存の出力先を上書きせず、一時ファイル経由で成功したときだけ移す。
6. 大きい関数は `~/.config/shell/functions/` に分け、`shellrc.sh` の末尾で読み込む
   （`archive.sh`: `extract` / `zpack` / `zunpack`、`cpp.sh`: `runcpp`）。
   テンプレート機能が要らないので素の `.sh` にし、pre-commit の shellcheck を効かせる。
   読み込み元が `shellrc.sh` だけなので、対話シェル専用であることは変わらない。
   小さい関数は `shellrc.sh` に残す。zsh の `autoload` は bash で使えないので採らない。

参考にした記事（tellme.tokyo の AI-first dotfiles）のうち、Nix 化・`rm` を `gomi`
に差し替える alias・`is_human` による人間判定は採らない。それぞれ、導入物の管理を
mise に統一している方針と合わない、標準コマンドの意味を変えない方針（3）と
合わない、判定を環境変数の列挙に頼るため（2）である。

検査は `test/test_shell_startup.py`（非対話 zsh / login bash の alias・環境変数・
出力、`.zshrc` の早期 return、`shellenv.sh` 単体、`functions/` の読み込み、`zpack`、
`runcpp`）。一時 HOME に描画結果を
置いて実行し、zinit・mise・fzf・ネットワークは使わない。実機の対話シェルの
起動（プロンプトまで）は検査しない。

## C++ の単一ファイル実行（runcpp）

コーディング試験・競技プログラミングの問題を解くための関数（`functions/cpp.sh`）。
1 ファイルをコンパイルして実行する。zsh では suffix alias（`60_suffix_alias.zsh.tmpl`）で
`.c` / `.cc` / `.cpp` を打つと呼ばれる。

```text
runcpp [オプション] <src.cpp> [オプション] [-- プログラム引数...]
```

| オプション | 意味 |
| --- | --- |
| `-d` / `--debug` | 間違いを見つけるモード（既定） |
| `-r` / `--release` | 提出環境に近いモード。速度の確認用 |
| `-c` / `--compile-only` | コンパイルだけ（警告の確認） |
| `-t` / `--time` | 実行時間を表示 |
| `--std=STD` | 言語規格（既定 `gnu++20`） |

| 環境変数 | 意味 |
| --- | --- |
| `RUNCPP_MODE` | オプションが無いときのモード（`debug` / `release`） |
| `RUNCPP_CXX` | コンパイラ（既定 `g++`。macOS では最新の `g++-N`） |
| `RUNCPP_STD` | `--std` の既定値 |
| `RUNCPP_FLAGS` | 追加フラグ（例 `-I$HOME/ac-library`）。空白で分割する |

suffix alias での使い方:

```zsh
a.cpp < in1.txt                # debug
a.cpp -r -t < big.txt          # release で時間計測
RUNCPP_MODE=release a.cpp      # 環境変数でも切り替えられる
a.cpp -- foo                   # プログラムに引数を渡す
```

設計:

- `--` より前は位置を問わず runcpp のオプションとして読む。suffix alias では
  `a.cpp -r` が `runcpp a.cpp -r` に展開されるため、ソースの後ろにも書けないと
  モードを切り替えられない。`--` の前に置いたオプションでない語もプログラム引数になる
- suffix alias はコマンド位置の語にしか効かない。`./a.cpp` ではなく `a.cpp` と打つ
- バイナリは `${XDG_CACHE_HOME:-~/.cache}/runcpp/<名前>-<モード>` に置く。
  作業ディレクトリを汚さず、debug と release を取り違えない。
  コンパイルに失敗したら実行しない（古いバイナリを動かさない）
- 実行はサブシェルで `ulimit -s 1048576`（1GiB。ハード上限が低ければその値）にする。
  深い再帰の DFS が手元だけでスタックオーバーフローするのを防ぐ

モードごとのフラグ:

| | debug | release |
| --- | --- | --- |
| 最適化 | `-O0 -g -fno-omit-frame-pointer` | `-O2` |
| 警告 | `-Wall -Wextra -Wshadow -Wformat=2 -Wfloat-equal -Wcast-qual`。gcc では `-Wduplicated-cond -Wlogical-op` も | `-Wall -Wextra` |
| 実行時検査 | `-fsanitize=address,undefined -fno-sanitize-recover=all` | なし |
| STL の検査 | `-D_GLIBCXX_DEBUG -D_GLIBCXX_DEBUG_PEDANTIC`（libstdc++）、`-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_DEBUG`（libc++） | なし |
| マクロ | `-DLOCAL` | `-DONLINE_JUDGE` |

- `-Wconversion` は `int` と `size_t` の比較などで警告が大量に出るので入れない。
  `-Wpedantic` は `__int128` や可変長配列でも警告が出るので入れない。
  必要なら `RUNCPP_FLAGS` で足す
- release でも `NDEBUG` は付けない。AtCoder などのジャッジでも `assert` は有効なため
- `ulimit -s unlimited` にしない。スタックの上限を無制限にすると Linux がメモリ配置を
  旧方式（mmap を低位アドレスから割り当てる）に切り替え、ASan のシャドウ領域と重なって
  起動時に `Shadow memory range interleaves with an existing memory mapping` で
  落ちることがある（2026-10-06 に Ubuntu 24.04 / g++ 13.3 で観測）
- `-t` の分岐ではサブシェル内で `exec` しない。bash の `time ( exec cmd )` は
  時間を表示しない（同日に bash 5.2 で観測）
- macOS の `g++` は Apple clang で、`bits/stdc++.h` が無く `_GLIBCXX_DEBUG` も効かない。
  そのため Homebrew の `g++-N`（`brew "gcc"`）を探して使う。Apple Silicon の
  Homebrew gcc は sanitizer を使えない可能性があり、その場合は
  `RUNCPP_CXX=clang++` に切り替える（`bits/stdc++.h` は使えなくなる）。macOS 実機では未検証

検査は `test/test_shell_startup.py`（bash / zsh の両方で、release の実行、debug での
範囲外アクセスの検出、`--` 以降の引数、コンパイル失敗時に実行しないこと、不正な入力）。

## コーディング試験の練習用 VS Code（code-exam）

HackerRank 以外の問題（AtCoder や手元の問題集）を、本番に近い条件で解くための関数。
`applejxd` のときだけ `shellrc.sh` に定義する。当日の `~/coding-test/YYYY-MM-DD/` を作り、
拡張を切った専用プロファイル `coding-test` の VS Code で開く。

```sh
code --disable-extensions --profile coding-test ~/coding-test/YYYY-MM-DD
```

プロファイルは初回の起動で空のものが作られる。拡張もプロファイルごとなので、WSL では
初回に「リモート ウィンドウを開くには、拡張機能 'WSL' が必要です」と出て接続できない。
通知の「インストールして再度読み込む」では入らなかった（`--disable-extensions` 下のため
と思われる）。Windows 側の `chezmoi apply` が
`300_windows/run_after_347_vscode_coding_test.ps1.tmpl` で WSL 拡張をこのプロファイルへ
入れるので、初回は `code-exam` で一度開いてプロファイルを作り、Windows で
`chezmoi apply` してから開き直す。手で入れるなら Windows の PowerShell で次を実行する。

```powershell
code --profile coding-test --install-extension ms-vscode-remote.remote-wsl
```

このスクリプトは `applejxd` のときだけ中身を持つ。VS Code の CLI は存在しない
プロファイルを扱えない（`Profile 'coding-test' not found.`）ため、`storage.json` の
`userDataProfiles` にプロファイルが無いうちは何もしない。プロファイルを作った後の
apply で拾えるよう `run_onchange` ではなく `run_after` にしている。入れる設定は
WSL 拡張だけで、AI 機能のオフ（右下のメニューか `settings.json`）とフォルダーの
信頼は手で行う。

制限モードになったら親フォルダーの `~/coding-test` を信頼する。

設定は chezmoi で管理しないので、
初回だけ、そのウィンドウでコマンドパレットの **Preferences: Open User Settings (JSON)**
を開いて次を書く。補完をどこまで切るかは本番のエディタの設定に合わせる。

```jsonc
{
    "chat.disableAIFeatures": true,
    "editor.inlineSuggest.enabled": false,
    "editor.quickSuggestions": { "other": false, "comments": false, "strings": false },
    "editor.parameterHints.enabled": false
}
```

ビルドと実行は統合ターミナルの `runcpp` で行う（HackerRank の Run Code の代わり）。

設計:

- HackerRank 本番では外部エディタからの貼り付けやタブの切り替えが記録されるため、
  本番は HackerRank のエディタで解く。この関数は練習専用
  （[Test Integrity](https://support.hackerrank.com/articles/1079706165-proctoring-hackerrank-tests)）
- `--user-data-dir` で設定ごと分ける案は採らない。WSL の `code` は
  remote CLI を経由し、`user-data-dir` を Windows 側へ渡さずに捨てる
  （VS Code の `src/vs/server/node/server.cli.ts` の `isSupportedForCmd`）。
  `Code.exe` を直接呼べば回避できるが、VS Code の内部の起動手順に依存する。
  `--profile` は WSL からも渡る
- `--disable-extensions` でも、WSL への接続に使う拡張（resolver）は有効のまま残る
  （`extensionEnablementService.ts` の `_isDisabledInEnv`）。ただし例外になるのは
  プロファイルに入っている拡張だけなので、上の初回手順が要る。厳密には
  「接続用以外の拡張を無効化」である
- WSL 側の Machine 設定（`~/.vscode-server/data/Machine/settings.json`）は
  ふだんの VS Code と共有する

検査は `test/test_shell_startup.py`（bash / zsh の両方で、偽の `code` に渡る引数と
作業ディレクトリの作成、`applejxd` 以外では定義されないこと）。実際に VS Code が開くかは
検査しない。

## シェルプラグインの取得

シェルの rc が読み込むプラグインのうち、下の表の 5 項目は起動時ではなく
`chezmoi apply` が `home/.chezmoiexternal.toml.tmpl` で取得します。rc は存在する
ときだけ読み込み、無くてもシェルは起動します（zinit が無い場合は案内を 1 行出し、
`zinit` を何もしない関数にします）。

zinit が管理するプラグイン（`yuki-yano/zeno.zsh`、`zsh-users/zsh-completions`、
`Aloxaf/fzf-tab` など）は apply では取得しません。`home/dot_zshrc.tmpl` の
`zinit light` / `zinit snippet` に任せており、zinit が起動時に未取得のものを
取得します。

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
prefix + U）。取り直すときはパスを消してから `chezmoi apply --refresh-externals` します
（`--refresh-externals` が無いと clone 済みの記録で飛ばされる。
[external が取得されない](troubleshooting-bootstrap.md#apply-しても-zinit-などの-external-が取得されない)）。
新しい機械では apply に git とネットワークが要り、取得に失敗すると apply が
エラーになります。

### zinit の遅延読み込みの順序

`home/dot_zshrc.tmpl` は重いプラグインを `wait` ice で遅延読み込みし、
`wait'0a'` → `'0b'` → `'0c'` の順に読み込ませます。

- 末尾の文字に使えるのは `a` / `b` / `c` か、何も付けないかだけ。新しい zinit は
  それ以外（`wait'0e'` など）に「`wait ice received invalid suffix letter`」と警告する
- 同じ文字のプラグインは書いた順に読み込まれる。4 段目以降が要るときは文字を
  増やさず、同じ文字の中で並べる（ohmyzsh の `lib/git.zsh` や docker 関連は
  `'0c'` で fzf-tab の後に置いている）

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
  （oh-my-posh）、キーバインド、モジュール読み込み、関数（`open` や
  `commands/*.ps1`）は対話時だけ定義・実行します。docker の `dclean` などは
  hookがコマンド名しか見ないため、非対話で定義すると権限規則を素通りします。
  cmdletの既定エンコーディング（`*:Encoding`）は非対話でも `utf8` にします。
  外すと5.1の既定（`Out-File` はUTF-16LE、`Set-Content` はANSI）に戻るためです。
  5.1では `utf8` がBOM付きになりますが、こちらを許容します。
  Consoleのエンコーディングは非対話でも設定し、失敗は無視します。
  判定はstdioのリダイレクトに加え、起動引数（`-Command` / `-File` /
  `-EncodedCommand` / `-NonInteractive`。ただし `-NoExit` があれば対話）も見ます。
- **`copilot` 関数**: 対話ブロックに置き、`common.toml.tmpl` の `[agent_env]` の値を
  未設定のものだけ環境変数へ入れてから本物の `copilot` を起動し、`finally` で入れた分だけ
  消します。PowerShellの環境変数はプロセス全体なので、Copilotの実行中は親の環境も
  変わります。Windowsは空文字の変数を保持できないため、親から空で渡された値は残し、
  シェル内で空を代入した変数は未設定と同じ扱いになります
  （[shell ツールの環境変数](agent-config-generation.md#shell-ツールの環境変数)）。
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

## Windows Terminal

`settings.json`（Store 版の `%LOCALAPPDATA%\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\`）は
GUI で設定を変えるたびに Windows Terminal が書き換えるため、ファイル全体は管理しません。
次の 2 つが既存の内容に足すだけの変更をします。

| パス | 役割 |
| --- | --- |
| `home/AppData/Local/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/modify_settings.json.py` | LANG2 キー（`vk(26)`）を何もしない操作に割り当てる |
| `home/.chezmoiscripts/300_windows/run_after_341_terminal.py.tmpl` | `config/windows/terminal.json` の配色と `profiles.defaults` を反映する |

### LANG2 キーの割り当て

Google 日本語入力 + PowerShell（PSReadLine）で、LANG2（英数、`VK_IME_OFF` = 0x1A）を
押すと `@` が入力される不具合があります
（[PSReadLine#2206](https://github.com/PowerShell/PSReadLine/issues/2206)）。
Windows Terminal 側でこのキーを `adjustOpacity`（`opacity: 0`、`relative: true`）に
割り当て、PowerShell へ渡さないようにします。IME オフ自体はそのまま効きます。

- **新形式**（トップレベルに `keybindings` 配列がある）: `actions` に
  `id: User.ignoreImeOff` の操作、`keybindings` に `vk(26)` の割り当てを足します。
- **旧形式**: `actions` に `keys: vk(26)` を持つ操作を足します。
- 足すのは無いものだけなので、何度 apply しても結果は変わりません。
- `vk(26)` が別の操作（`id: null` の解除を含む）に割り当て済みなら、変更せず
  `warning: Windows Terminal: ...` を表示します。
- JSONC（コメント・末尾カンマ）のまま読み、配列の末尾へ文字列として挿入します。
  コメント・キーの順序・インデント・改行コード・BOM は変えません。
  JSON としてどうしても読めないときは、警告して元の内容をそのまま返します。
- 非 Store 版（`%LOCALAPPDATA%\Microsoft\Windows Terminal\settings.json`）は対象外です。
- `run_after_341` は `json.load` で読み、変更があればコメントを落として書き直します。
  コメント入りの `settings.json` では 341 が失敗します。

検証は `test/test_windows_terminal_settings.py` です。

## 個人用カスタム指示

全リポジトリで常時読み込まれる指示は、CLI ごとに読む先のファイル名が違います。
本文はほぼ同じなので、共通部分を 1 ファイルに集約して埋め込みます。

| パス | 役割 |
| --- | --- |
| `home/.chezmoitemplates/agent-instructions.md` | 4 CLI 共通の本文（応答・停止と報告・検証） |
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
  Claude Code / Codex CLI には置きません（`docs/spec/agent-command-policy.md` の
  CLI 別の表を参照）。
- **テンプレート内で分岐しない**: 固有の節は該当ファイルへ直接書き足します。
  `{{ if }}` を使わないので、テストは `includeTemplate` を展開するだけで
  出力内容を再現できます（`test_personal_instructions_share_one_source`）。
- **リポジトリ直下の `AGENTS.md` は対象外**: 適用範囲（このリポジトリのみ）も
  内容（リポジトリ固有の約束）も別系統です。判断の経緯は
  [ADR-0006](../adr/0006-instructions-to-mechanisms.md) にあります。
