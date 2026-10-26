# Windows の管理者権限の集約

Windows の chezmoi セットアップで、管理者権限が要る作業を 1 回の UAC にまとめる仕組み（WSL 本体・GPU の電力上限・昇格・winget の scope・hostname による限定）。全体の構成は [プロジェクト構造](structure.md)。

## 管理者権限の集約

Windows で管理者権限が要る作業は `300_windows/310_packages/run_once_before_309_admin.ps1.tmpl` の 1 本に集約し、
chezmoi スクリプト自身が出す UAC を 1 回にする。通常ユーザーで `chezmoi apply` を実行する設計は変えない。
`310_winget` に残るパッケージは user scope で入る前提（[振り分け](#winget-パッケージの-user--machine-の振り分け)）。それでもインストーラーが UAC を出したら 309 へ移す。

| 項目 | 内容 |
| --- | --- |
| 対象（許可リストのキー） | `Chocolatey`（winget 経由）・`chocolateygui`・`Keypirinha`・`WinSCP`（machine scope）・`VSCode`（machine scope）・`LongPaths`・`RDP`・`OpenSSHServer`・`SshDefaultShell`・`Sudo`・`WslPlatform`・`GpuPowerLimit`（[下記](#gpu-の電力上限gpupowerlimit)）・machine 版しかない winget パッケージ（[下記](#winget-パッケージの-user--machine-の振り分け)） |
| 流れ | 通常権限で不足を判定 → 不足があるときだけ UAC を 1 回 → 昇格子が不足分だけ実行 → 通常権限で再判定。導入済みなら UAC は出ない |
| 失敗 | UAC キャンセル・昇格子の非ゼロ終了・再判定の残りはすべて非ゼロで止める。失敗した回は `run_once` に記録されないので、直して `chezmoi apply` をやり直せば 309 は再実行される。成功後に消えたものは自動では直さない（内容を変えるか `chezmoi state delete-bucket --bucket=scriptState` で再実行） |
| 実行順 | 同じディレクトリで `309_admin` は `310_winget` より前（属性を除いた名前の昇順） |
| ユーザーの作業 | `315_keypirinha_extensions` は通常権限のまま |

### WSL 本体（`WslPlatform`）

applejxd の全 PC で、**WSL 本体だけ**を入れる。ディストロは入れない（置き場所の方針は [CHG-0022](../change/0022-windows11-settings-review.md) の保留）。

- 判定は `wsl.exe --version` の終了コード（未導入だと inbox の `wsl.exe` が案内を出して 1 を返す）。導入済みなら何もしない
- 導入は `wsl.exe --install --no-distribution`（Windows の機能 `VirtualMachinePlatform` と WSL のパッケージ）のあと `wsl.exe --update`。昇格子の出力は UTF-16 なので、符号化を合わせて失敗の理由をログに残す
- 判定は `wsl.exe --version` に加えて `vmcompute` サービスの有無も見る（`wsl.exe` だけ入って `VirtualMachinePlatform` が無いと distro 起動が `HCS_E_SERVICE_NOT_AVAILABLE` で失敗する）。導入時は `dism` で機能を明示的に有効化し、`hypervisorlaunchtype` が Off なら `auto` にする
- 有効化直後は再起動するまで `vmcompute` が現れないので、導入後の再判定で `WslPlatform` が残っても失敗にせず「再起動して `mise run restore:wsl`」と警告する
- **`VirtualMachinePlatform` の有効化には再起動が要る。** 導入した直後でも `wsl --version` は成功するので、309 は再起動の要否を判定できない。導入したときは「再起動が要る」とログに出す
- `winget` の `Microsoft.WSL` は版が遅れているため使わず、`wsl --update`（Store）で最新にする。実測と「WSL 3」の意味は [記録](../research/chezmoi/structure-windows-notes.md)

### GPU の電力上限（`GpuPowerLimit`）

`heimdall-ufbs-010` の RTX 3070 だけ、電力上限を 150 W にする。RTX 3070 で起きたクラッシュへの対策（経過は [記録](../research/chezmoi/structure-windows-notes.md)）。

- **対象の限定**: テンプレートで `applejxd` かつ hostname `heimdall-ufbs-010` のときだけ有効にし、実行時にも `nvidia-smi --query-gpu=name` が `RTX 3070` を含むときだけ対象にする（GPU を替えた・ドライバが無い PC では何もしない）
- **永続しない**: Windows では電力上限（`nvidia-smi -pl`）が再起動・ドライバのリセット・スリープ復帰で既定値へ戻り、永続化の手段が無い（Linux の `-pm` は WDDM では使えない）。そこで SYSTEM のスケジュールタスク `gpu-power-limit` が設定し直す
- **トリガー（3 つ）**: 起動時（1 分遅延）・ログオン時・スリープ復帰時（`Microsoft-Windows-Power-Troubleshooter` の ID 1、10 秒遅延）。`-pl` は冪等なので重なっても問題ない
- **実行するスクリプト**: `%ProgramData%\gpu-power-limit\set-power-limit.ps1`（内容は 309 が生成する ASCII のみ）。ドライバが立ち上がるまで最大 2 分待ち、型番に合う GPU に `nvidia-smi -i <index> -pl 150` を実行する
- **昇格の抜け穴を作らない**: SYSTEM が実行するファイルを通常ユーザーが書き換えられると権限昇格になる（[常駐ヘルパー案の見送り](../change/0021-windows-admin-consolidation.md)と同じ理由）。ディレクトリは作り直して ACL を SYSTEM・Administrators のフルコントロールと Users の読み取りだけにする
- **判定**: スクリプトの内容が期待と一致するときに「設定済み」とする。昇格している場合は、さらにタスクが SYSTEM・最上位の権限で、トリガーが 3 つあることも見る。**通常権限では SYSTEM のタスクを読めない**（`Get-ScheduledTask` が無言で空を返す。実機で確認）ので、内容の一致だけで判定する（タスクを手で消しても検知しない）。現在の電力値は見ない（再起動直後にタスクが動く前でも UAC を出さないため）
- **検証（昇格後）**: タスクを即時実行し、最大 60 秒、`power.limit` が 150 W になることを確かめる。ならなければ失敗にする
- 150 W は `nvidia-smi -pl` で手動設定してクラッシュが止まった値。変える場合は 309 の `$GpuPowerLimitWatts`

実測（ダンプ・原因の切り分け）は [記録](../research/chezmoi/structure-windows-notes.md)。

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
| machine 版しかない（user 版なし） | Chrome・Google 日本語入力・7-Zip・Hack フォント・Google Drive・Dropbox・Ditto・Tailscale | `309_admin` が `--scope machine` で導入（Google Drive 以降は `applejxd` だけ） |
| scope 未宣言の MSI | Python Launcher（`launcher.msi`） | `309_admin` が `--scope` なしで導入。付けると `No applicable installer` になる。MSI の既定が全ユーザーかは**未確認**（導入後に UAC が出るか・導入先で確かめる） |
| machine 版しかない・特定の PC だけ | Elgato Stream Deck（`wix` の MSI。user 版なし）・Wacom ドライバー・Steam・iTunes | `309_admin` が `--scope machine` で導入。**applejxd かつ hostname が一致する PC だけ**（下の「hostname で限定するもの」） |
| 両 scope 対応 | PowerShell・Obsidian・Oh My Posh・PowerToys・Git・mise・Python 3.12・Bitwarden（本体・CLI） | 既定（user）のまま `310_winget` |
| user 版しかない | QuickLook・Spotify・Discord | `310_winget` |
| scope 未宣言の NSIS | Orca | `310_winget`。Electron の NSIS は既定が per-user のはずだが**未確認**。UAC が出たら 309 へ移す |
| Microsoft Store | Keyhac・iCloud・Kindle・Codex App | `310_winget`（Store 版はユーザー単位） |

- 309 の導入判定は `winget list` の出力の ID 列に一致するか。これらは winget では user 版を入れられないので、入っていれば machine 版とみなす（Python Launcher は例外）。winget 以外の経路で入れた同名の user 版が残っていても「導入済み」とみなす（機能を満たすので許容。machine 版にしたいときは手でアンインストールして再実行）

### hostname で限定するもの

ユーザー名（`applejxd`）だけでは足りず、**特定の PC にだけ要るもの**は、`.chezmoi.hostname` で限定する。
`.chezmoi.hostname` は `chezmoi.toml` の `[data]` ではなく **`apply` のたびに評価される組み込みの値**なので、`init` を呼び直さなくても効く。

- 書き方（`309_admin` の例）: `{{- if eq (lower .chezmoi.hostname) "heimdall-ufbs-010" }}`（`lower` は大文字小文字の違いを避けるため）
- 現在の対象（`heimdall-ufbs-010` だけ）: **Stream Deck**・**Wacom ドライバー**（どちらも本体をつないだ PC だけ）、**Steam**（ゲーム用）、**iTunes**（iPhone の同期用）、**GPU の電力上限**（RTX 3070 の不安定さへの対策。[下記](#gpu-の電力上限gpupowerlimit)）
- 他の PC では、これらは**入れない**（導入済みのものを消しはしない）
- 他の PC にも入れるときは、`or (eq …) (eq …)` と並べるか、`has (lower .chezmoi.hostname) (list "…" "…")` にする
- 実機で、この PC では `StreamDeck` が許可リストと導入対象に出て、hostname または user が違うと出ないことを描画で確かめた（`chezmoi execute-template`）

- 両 scope 対応のものを machine にする理由は個人 PC では無い。必要になった（ドライバー・IME・他ツールが system-wide を要求）ものだけ 309 へ移す

### 保証しないこと

- 昇格前に、元ユーザー権限の別プロセスが temp の 309 やソースを書き換える攻撃は防がない（信頼の起点が無い。
  chezmoi 公式の昇格パターンと同じ前提）
- 昇格先が別アカウントのとき、309 自身の処理は元ユーザー・昇格先のホームへ書かない。ただし呼び出す
  `winget` / `choco` / インストーラーが昇格先に作るログ・状態・キャッシュは制御しない
- 昇格先アカウントで `winget`（App Installer）が使えない場合は Chocolatey・WinSCP・VS Code を導入できず、
  明示エラーで止まる（代替の導入経路は持たない）

### 個別の判断

- **VS Code**: machine 版でも user 版でも `Code.exe` があれば満たす（併存を許容。347 は `code` が使えればよい）
- **WinSCP**: Keypirinha が system-wide を要求するので machine 版だけを満たすとみなす。user 版などが残って
  winget が拒否した場合は失敗にし、`winget list --id WinSCP.WinSCP` で確認してアンインストールしてから再実行する
- **RDP**: `applejxd` かつ Pro / Enterprise / Education 系の SKU のときだけ。`fDenyTSConnections=0`、NLA（`UserAuthentication=1`）、
  `RemoteDesktop-UserMode-In-TCP` / `-UDP` を有効にして Profile を Domain・Private に限る（既定は Any で Public を含む）。
  判定は `Get-NetFirewallRule -PolicyStore ActiveStore`（ポリシー適用後）。Shadow 規則・`Remote Desktop Users`・`TermService` は触らない。
  設定後に実効状態が合わなければ失敗にする
- **OpenSSH Server**: `applejxd` のときだけ（SKU は問わない）。Windows 機能 `OpenSSH.Server~~~~0.0.1.0` を追加し、`sshd` を自動起動にして起動する。
  組み込みの規則 `OpenSSH-Server-In-TCP`（既定は Profile=Any で Public を含む）を Domain・Private に絞って有効にする。
  不足判定は「`sshd` サービスが自動起動かつ実行中」かつ「規則が ActiveStore で有効・Public を含まない」。`ssh-agent` は触らない。
  機能の追加は Windows Update へ接続できることが前提で、再起動が要ると警告を出す。パスワード認証・既定シェルは変えない
  （公開鍵の追加は [SSH 公開鍵の authorized_keys への追加](security.md#ssh-公開鍵の-authorized_keys-への追加)。管理者グループの利用者は未対応）
- **標準の `sudo`**: `applejxd` のとき、`sudo config --enable forceNewWindow`（公式の手順）で有効にする（Windows 11 24H2 以降。`System32\sudo.exe` が無い機械と、ポリシー
  `HKLM\SOFTWARE\Policies\Microsoft\Windows\Sudo\Enabled = 0` で無効に固定された機械は飛ばす）。判定は `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Sudo\Enabled` が 1 以上か
  （0 = 無効 / 1 = forceNewWindow / 2 = disableInput / 3 = normal。`microsoft/sudo` のソースで確認）。**有効な方式は選び直さない**。
  chezmoi 自身は `sudo` を使わない。対話で管理者のコマンドを打つための便利機能で、`forceNewWindow` は新しい窓で実行し、`sudo` のたびに UAC の確認が出る
  （`normal` は、昇格していないプロセスが昇格したプロセスへ入力できる恐れがあると公式が警告しているので選ばない）。
  scoop の `sudo`（2020 年の近似実装）は導入しない。実機での確認は [記録](../research/chezmoi/structure-windows-notes.md)
- **sshd の既定シェル**: `applejxd` のとき、`HKLM\SOFTWARE\OpenSSH\DefaultShell` を `%ProgramFiles%\PowerShell\7\pwsh.exe` にする（未設定だと `cmd.exe`）。
  MSIX 版の `pwsh` は `WindowsApps` の版つきのパスで、更新のたびに変わり、指していると ssh のログインが全部失敗する。そのため
  `winget install Microsoft.PowerShell --installer-type wix --scope machine --force` で**固定パスの MSI 版**を別に入れる（MSIX 版と併存。`--force` が
  導入済みの確認を飛ばす。この組み合わせは実機で未確認）。MSI 版が無いときは `DefaultShell` を設定しない（無いシェルを指さない）。
  `DefaultShellCommandOption` は既定（`-c`）のまま。一発実行（`ssh host command`）は `pwsh -c` になり、プロファイルの対話判定が非対話と見なすため、
  PATH・文字コード・git の環境変数までが入る（対話ブロックは入らない）
