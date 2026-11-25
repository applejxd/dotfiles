# PowerShell が遅いことがある件の原因分析と対策（2026-11）

- **観測日**: 2026-11-25（基準コミット `9d239e68`）
- **対象**: この機（Windows 11 build 26300）の PowerShell 7.6.10（`pwsh`）と Windows PowerShell 5.1.26100.9818（`powershell`）。
  oh-my-posh 33.4.0（winget の MSIX 版）、PSReadLine 2.4.5、PSFzf 2.7.12、ZLocation 1.4.3、Chocolatey。ウイルス対策は Defender のみ
- **背景**: 利用者の申告は「動作・起動が遅いことがある」。2026-09 の[起動時間の計測](powershell-profile-startup.md)で
  cmdlet の初回呼び出しなどは直してあるが、oh-my-posh の init のキャッシュを外した後は計っていなかった
- **測り方**: 対話セッションの実測は ConPTY（`scripts/windows/measure_pwsh_latency.py`）。起動時の内訳はプロファイルへ
  `Stopwatch` の印を挿した複製を `-NoProfile -NoExit` で動かして取った。計測中も別のアプリは動いていた（下の「揺れ」）

## 結論

「遅い」は 4 つの別々の原因に分かれた。2 つは直せた。2 つは残る（残りの原因と候補は末尾）。

| # | 症状 | 原因 | 対策 | 結果（pwsh / 5.1、中央値） |
| --- | --- | --- | --- | --- |
| 1 | プロンプトは出たのに、打った文字が 0.3〜1.1 秒の間、画面に出ない | 起動後の `PowerShell.OnIdle` の処理（Chocolatey・PSFzf・ZLocation の読み込み。合わせて約 1 秒）が、PSReadLine の入力ループと同じスレッドで走る | Chocolatey と PSFzf は使うときまで読み込まない（仮の定義だけ置く）。ZLocation だけ idle で読む | プロンプトの 0.4 秒後に打った 1 文字の反映: 676→364 ms / 444→317 ms。0.8 秒後: 301→17 ms / 40→17 ms |
| 2 | コマンドを実行するたびに、次のプロンプトが出るまで待たされる（git の作業ツリーでは特に） | プロンプトごとに `oh-my-posh.exe` を起動する（MSIX の別名経由で約 65 ms）＋ git の状態取得 | テーマに `"streaming": 100`（常駐の `oh-my-posh serve`）。pwsh のみ | Enter→次のプロンプト: 非 git 146→48 ms、git（この repo）269→142 ms。5.1 は不変（143 / 270 ms） |
| 3 | 起動してからプロンプトが出るまでが長い（約 1.2 秒） | プロファイルが約 0.46 秒＋最初のプロンプトの描画。うち oh-my-posh の init が約 0.33 秒 | 直せていない（候補と見送った案は末尾） | 1181→1185 ms / 992→1007 ms（不変） |
| 4 | 日によって・同時に開いたときに特に遅い | 外部プロセスの起動と CPU 競合が上の 1〜3 を増幅する | 1・2 でプロセス起動と同期の処理を減らした | 同時 4 セッション: プロンプト 1.3〜1.5 秒、打鍵の停止 0.7〜1.1 秒（修正前のみ測定） |

副産物として、**プロファイルの順序の不具合**を 1 件見つけて直した（[下記](#見つけた不具合-editmode-が-enter-ハンドラを消していた)）。

## 計測

### 起動からプロンプトまで（ConPTY、n=6）

| 起動 | `-NoProfile` | 修正前 | 修正後 |
| --- | ---: | ---: | ---: |
| `pwsh` | 526 ms | 1181 ms | 1185 ms |
| `powershell` | 322 ms | 992 ms | 1007 ms |

プロファイルとその後の最初の描画が、素の起動に約 0.65 秒を足している。プロファイルの内訳は次のとおり（pwsh、対話、
プロセス内の `Stopwatch`、3 回とも同じ。非対話の起動では約 0.09 秒で、対話ブロックの手前で `return` する）。

| 区間 | 時間 |
| --- | ---: |
| 文字コード・`GIT_CONFIG_*`・`cache.ps1` の読み込み | 約 20 ms |
| mise（キャッシュの検証と dot-source） | 約 35 ms |
| PATH の追加と重複除去 | 約 25 ms |
| 関数定義と `commands/*.ps1` の dot-source | 約 30 ms |
| **oh-my-posh（`Get-Command` 9 ms、`init` の実行 115 ms、init スクリプトの実行 215 ms）** | **約 340 ms** |
| 合計 | 約 465 ms |

oh-my-posh の init スクリプトは 1435 行で、実行中に `oh-my-posh print secondary` などを 1 回起動する（約 65〜100 ms）。
MSIX 版の `oh-my-posh.exe`（`WindowsApps` の別名）は、起動のたびに同じ版の単体の exe より 35〜50 ms 遅い。

| 起動する処理（8 回、2 回目以降の中央値） | MSIX の別名 | 公式リリースの単体 exe |
| --- | ---: | ---: |
| `--version` | 66 ms | 32 ms |
| `print secondary` | 69 ms | 31 ms |
| `init pwsh --config …` | 116 ms | 64 ms |

単体 exe は GitHub の公式リリース（`posh-windows-amd64.exe` v33.4.0）を取得し、`checksums.txt` の SHA256 と一致することを確かめて、
`.tmp/` で計測にだけ使った。他の exe は `whoami` 23 ms、`git` 28 ms、`fzf` 30 ms。初回（冷えた状態）の別名は 238 ms だった。

### 起動後の入力の停止（原因 1）

起動後の idle の処理を、PSReadLine から切り離して 1 つずつ測った（pwsh）。

| 処理 | 時間 |
| --- | ---: |
| Chocolatey のプロファイル（`refreshenv` と `choco` の補完） | 約 340 ms |
| PSFzf の読み込みと `Set-PsFzfOption` | 約 250 ms |
| ZLocation の読み込み（LiteDB の読み込みを含む） | 約 370 ms |
| `Register-FzfKeyHandler` | 約 15 ms |

`PowerShell.OnIdle` は、キー入力が 0.3 秒途切れるたびに PSReadLine が起こすイベントで、`-Action` は入力ループと同じスレッドで走る。
だから action の実行中は打った文字が反映されない。ConPTY で、最初のプロンプトの後に 1 文字を打って画面に出るまでを測った
（n=6）。

| 打つ時刻（プロンプトの後） | pwsh 修正前 | pwsh 修正後 | 5.1 修正前 | 5.1 修正後 |
| --- | ---: | ---: | ---: | ---: |
| +0.0 秒 | 32 ms | 32 ms | 50 ms | 50 ms |
| +0.4 秒 | 676 ms | 364 ms | 444 ms | 317 ms |
| +0.8 秒 | 301 ms | 17 ms | 40 ms | 17 ms |

止まる区間は、pwsh で約 0.3〜1.1 秒だったのが約 0.3〜0.7 秒になった。残りは ZLocation の読み込みで、
ZLocation はプロンプトごとに現在のディレクトリの重みを書き込む（`prompt` を包む）ので、使うときまで遅らせると履歴が欠ける。
そのため idle で読むままにした。

### 1 コマンドごとのプロンプトの遅延（原因 2）

起動して idle の処理が終わるのを待ち、`'M0'` などを Enter で送ってから、次のプロンプトが出るまでを測った（n=10、中央値）。

| 場所 | pwsh 修正前 | pwsh 修正後 | 5.1 修正前 | 5.1 修正後 |
| --- | ---: | ---: | ---: | ---: |
| git でない場所 | 146 ms | 48 ms | 143 ms | 143 ms |
| git の作業ツリー（この repo） | 269 ms | 142 ms | 267 ms | 274 ms |

- 修正前は、プロンプトごとに `oh-my-posh print primary` を起動していた（git の場所では `git status` も待つ）。
  streaming は常駐の `oh-my-posh serve` が毎回の起動を省き、遅い区画（git）は 100 ms で打ち切って `...` を出し、
  結果が出たらその場で描き直す（[公式の説明](https://ohmyposh.dev/docs/configuration/streaming)。2026-11-25 取得）。
  git の場所の 142 ms は、この 100 ms の打ち切り＋描画。
- **5.1 では streaming を切った**。5.1 は常駐プロセスが使えず、プロンプトごとに `oh-my-posh stream` を起動する経路になる。
  この機では非 git で 175 ms、git で 291 ms と、streaming なしの 143 / 270 ms より遅かった。
  また、init スクリプトを読むと、その経路は最初のレコードを待つ処理（`while ($output.Count -eq 0) { Start-Sleep -Milliseconds 1 }`）に上限が無い。
- 修正後の pwsh でも、最初の 1 回（起動直後の最初のプロンプト）は 100 ms の打ち切りのぶん長い。

### 揺れ（原因 4）

- 計測中の CPU 使用率は約 70% だった（Discord・StreamDeck・Dropbox・タスクマネージャなどが常駐）。同じ設定でも、
  別の計測のあいだにプロンプト到達が 1.19 秒から 1.86 秒（中央値）に増える回があった。
- 同時に 4 セッションを起動すると、プロンプトまで 1.3〜1.5 秒、打鍵の停止が 0.7〜1.1 秒だった。
- 非対話の `pwsh -Command exit` は、プロファイルありで約 385 ms、`-NoProfile` で約 240 ms（初回だけ 618 / 396 ms）。
  エージェントが毎回起動する経路では、プロファイルが約 0.15 秒を足す。

プロセスの起動が高く付く状態ほど、毎プロンプトの起動（原因 2）と idle の読み込み（原因 1）の影響が大きくなる。
そのため、プロセスの起動と同期の処理を減らす今回の対策は、「ときどき遅い」にも効くと考えている（**推測**。負荷をかけた状態での
修正後の再測定はしていない）。

## 原因ではなかったもの

| 候補 | 確認 | 結果 |
| --- | --- | --- |
| PATH にネットワーク・UNC・切断された場所がある | 56 要素を `Directory.Exists` で確認 | 無し（存在しない 5 件は 0 ms で判定） |
| 存在しないコマンドの探索が遅い | `Get-Command` で存在しない名前を 3 回 | 約 30 ms |
| oh-my-posh の更新確認（通信） | 公式の docs（`upgrade.notice` の既定は `false`）。テーマに指定なし | 無効 |
| oh-my-posh のセッションのキャッシュの蓄積 | 92 ファイル・4.8 MB、最古は 1 週間前 | 自動で掃除されている |
| ほかのプロファイル（`CurrentUserCurrentHost`・全ユーザー）や WinGet の `CommandNotFound` モジュール | 全部のパスの存在確認と `Get-Module -ListAvailable` | 無し |
| ZLocation のプロンプトごとの書き込み | idle の処理が終わった後のプロンプトを 6 回ずつ測定 | 約 10 ms 以内 |
| Defender の影響 | リアルタイム保護は有効。除外の一覧は管理者でないと読めない | **未確認**（除外を足す案は計測できていない） |

## 見つけた不具合 EditMode が Enter ハンドラを消していた

`Set-PSReadLineOption -EditMode Emacs` は、キーの割り当てを初期化する。プロファイルでは oh-my-posh の init の**後**にこれを
実行していたため、init が足した Enter と Ctrl+c のハンドラ（`OhMyPoshEnterKeyHandler` など）が消えていた
（`Get-PSReadLineKeyHandler -Bound` で、Enter が `AcceptLine` になっていた）。

- 影響: テーマの `transient_prompt` が効かない（過去のプロンプトが 2 行のまま残る）。streaming を有効にしても、Enter のハンドラが
  状態を戻さないので、**プロンプトが最初の 1 回の表示のまま更新されない**（`cd` しても変わらない）ことを、ConPTY で `cd` を
  続けて確かめて見つけた。
- 直し方: キーバインドの設定を init の前に移した。これで transient prompt が有効になる（pwsh）。streaming が無い場合
  （5.1・PSES・`POSH_THEMES_PATH` のテーマ）は、Enter ごとに `oh-my-posh` を起動して遅くなる（5.1 で非 git 295 ms、git 393 ms を
  測った）ので、`$global:_ompTransientPrompt = $false` で切り、これまでの見た目と速さを保つ。

## 対策の中身

実装は `home/dot_config/powershell/` 配下。仕様は [PowerShell プロファイル](../../spec/shell.md#powershellプロファイル)。

- `themes/pure.omp.json`: `"streaming": 100`。
- `profile.ps1.tmpl`: キーバインドを init の前へ。pwsh の ConsoleHost 以外（5.1・PSES・ISE）は `POSH_DISABLE_STREAMING` を init の間だけ立て
  （`try` / `finally` で、init が異常終了しても子へ残さない）、streaming が無いときは transient prompt を切る。
  idle の処理は ZLocation と `Register-FzfKeyHandler` だけ。
- `commands/fzf.ps1`: Ctrl+t / Ctrl+r の仮のハンドラ（`PSFzf (lazy)`）。初めて押されたときに PSFzf を読み込んで本物へ差し替え、
  そのまま処理を続ける。読み込みに失敗したら（未導入・壊れている）警告して、標準の割り当て（Ctrl+r は履歴の逆方向の検索、
  Ctrl+t は文字の入れ替え）へ戻す。PSFzf の読み込みを壊した状態で、標準の検索（`bck-i-search`）が動くことを ConPTY で確かめた。
- `commands/chocolatey.ps1`: `refreshenv` の仮の関数と、`choco` の補完の仮の登録。使われたときに Chocolatey のプロファイルを読み込み、
  補完は入力全体をもう一度補完させる。読み込み済みなら仮の定義を置かない（プロファイルの再読み込みで、本物の補完を
  仮のもので上書きして、自分自身へ戻って止まらなくなるのを避ける。仮の補完の `Import-Module` は `-Force`）。
  PowerShell 7 と 5.1 で、仮の補完が本物と同じ候補を返すこと、再読み込みの後も止まらないことを確かめた。
- 試験: `test/test_windows_assets.py`（字面）、`test/test_powershell_interactive.py`（ConPTY。仮の定義・streaming の有無・
  Enter ハンドラ・Ctrl+r で PSFzf が読み込まれること）。

**副作用**（利用者に見える変化）:

- pwsh で transient prompt が有効になる（実行したコマンドの行が `❯ コマンド` に畳まれる）。テーマに元からある設定が効くようになっただけ。
- git の作業ツリーで、プロンプトが git の欄を `...` にして先に出て、結果が出たらその場で描き直される。
- Ctrl+r・Ctrl+t を初めて押すとき約 0.25 秒、`refreshenv`・`choco` の補完を初めて使うとき約 0.3 秒かかる。

## 残ったもの・候補（未実施）

- **起動の約 1.2 秒**（oh-my-posh が約 0.33 秒）。候補は次のとおりで、どれも実施していない。
  - MSIX でない単体の exe にする: 上の表から、起動で約 0.1 秒（init 約 50 ms＋`print secondary` 約 37 ms＋`serve` の起動）、5.1 のプロンプトごとに約 37 ms 縮む見込み。
    winget の `JanDeDobbeleer.OhMyPosh` は MSIX だけ（2026-11-25 の `winget show`）で、scoop や mise の shim を挟むと shim の起動が足されるので、
    導入方法の変更になる（未計測）。
  - init の出力のキャッシュ: 2026-09 に外した。セッション ID は init が採番し、init のスクリプトは oh-my-posh が自分の版で書き出すので、
    版が変わっても古いスクリプトを使い続ける恐れがある。MSIX の別名からは版を安く取れない。
  - 最初のプロンプトを標準のものにして、oh-my-posh を idle で読み込む: 起動は約 0.3 秒縮むが、プロンプトの見た目が途中で変わる。
  - init の実行（115 ms）を、その後の `commands/*.ps1` の dot-source などと並行させる: 縮むのは約 40 ms。
- **ZLocation の約 0.37 秒の停止**（起動後に 1 回）。
- **Defender の除外**（pwsh・`oh-my-posh`・`~/.config/powershell`）の効果は、管理者の権限が要るので未測定。
- **5.1 のプロンプトごとの約 0.14 秒**（git で約 0.27 秒）は、常駐プロセスが使えないので残る。

## 再現

```powershell
# 配備済みのプロファイルを測る（pywinpty は ConPTY を Python から扱う依存）
uv run --with pywinpty --no-project python scripts/windows/measure_pwsh_latency.py startup --shell pwsh --n 6
uv run --with pywinpty --no-project python scripts/windows/measure_pwsh_latency.py enter --shell pwsh --n 10
# 適用前の変更を測る: 描画したプロファイルを -NoProfile 起動の後に dot-source する
# （cmd の `>` は BOM をそのまま書く。PowerShell の `>` は文字コードを変えて、5.1 で日本語のコメントが壊れる）
cmd /c "chezmoi execute-template --source home --file home\dot_config\powershell\profile.ps1.tmpl > .tmp\new\profile.ps1"
# （cache.ps1・commands\・themes\ も .tmp\new\ へ写す）
uv run --with pywinpty --no-project python scripts/windows/measure_pwsh_latency.py enter --profile-file .tmp/new/profile.ps1
```

## 出典（2026-11-25 取得）

- [Streaming | Oh My Posh](https://ohmyposh.dev/docs/configuration/streaming): 常駐プロセスで「プロンプトごとのプロセス起動（Windows で最大のコスト）」を省く。PowerShell 6+ のみ。
  PSES は並行実行が衝突するので `POSH_DISABLE_STREAMING` で切る。ベータ機能
- [Upgrade | Oh My Posh](https://ohmyposh.dev/docs/installation/upgrade): `notice` の既定は `false`
- [General | Oh My Posh](https://ohmyposh.dev/docs/configuration/general): `async`・`streaming` の設定
