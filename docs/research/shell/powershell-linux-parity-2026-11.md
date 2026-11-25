# bash/zsh の機能を PowerShell へ取り入れた調査と実測（2026-11）

- **取得日**: 2026-11-25（基準コミット `4724f193`）
- **対象**: Windows 11 build 26300、PowerShell 7.6.10 と Windows PowerShell 5.1.26100.9818（PSReadLine 2.4.5 と 2.0.0）、PSFzf 2.7.12、fzf 0.74.5、mise 2026.11.13
- **依頼**: 「Ubuntu 版にあって Windows 側に無い機能で、自然なやり方で同等機能が再現できるものは、できるだけ取り入れて。特に bash/zsh → PowerShell」
- 仕様と対応表は [シェル](../../spec/shell.md#bashzsh-と-powershell-の対応)。ここには、確かめた事実（観察）と、決めた理由、未確認を残す。

## 洗い出し

Linux 側の `dot_bashrc`・`dot_zshrc.tmpl`・`dot_zshenv`・`dot_zshrc.d/`・`shellrc.sh.tmpl`・`shellenv.sh.tmpl`・`fzf/*.sh`・`functions/*.sh`・zeno の設定（`dot_config/zeno/*.yml`）を読み、Windows の `profile.ps1.tmpl` と `commands/*.ps1` と突き合わせた。
Windows に無かったのは、alias と小さい関数（`up`・`ll`・`sha1`・`search` など）、fzf の git 関数、圧縮・C++・pi の関数、`pk`、cd 周りの挙動（auto_cd・chpwd・TMPDIR）、履歴と autosuggestion、補完（compinit・zsh-completions・fzf-tab）、zeno の snippet。
Windows に既にあったもの: `z`（ZLocation）・`xf` / `xg` / `sshf`・fzf の Ctrl+t / Ctrl+r・docker と wsl の関数・pure テーマ・`pbcopy` など。

## 確かめた事実

### 起動時間（`scripts/windows/measure_pwsh_latency.py startup`。プロンプトまでの中央値、n=5）

- **`.ps1` を 1 つ dot-source するたびに 16〜20 ms**。小さい `commands/*.ps1`（`wsl`・`docker`・`chocolatey`）でも同じだった（`Measure` の計測。原因は未調査）。
- 最初の実装（新しい関数を `commands/` の 11 ファイルに分け、全部を起動で dot-source）は、基準の 1250 ms から **約 +150 ms（1400 ms）**。
- 関数を自動読み込みのモジュールへ移し、起動で読むファイルを `interactive.ps1` の 1 つにした版でも **+62 ms**（基準 1257〜1260 ms に対して 1320〜1322 ms。2 回ずつ交互に測定）。内訳の切り分けは下の「起動時間の内訳」。
- `Update-RepoLocalTemp` に、書き込みの試し（ファイルの作成と削除）を入れると +35 ms 前後、外すと 0〜+20 ms（ウイルス対策の走査と思われる。未確認）。そのため、書き込みの試しはしない。

### PowerShell の仕様の観察

- **外部の実行ファイルが、自動読み込みのモジュールの関数より先に解決される。** PATH に `cat.exe`（Git for Windows・scoop の gow）や、拡張子の無いファイル `~/.local/bin/pk` があると、モジュールの `cat` / `pk` は呼ばれず、外部のものが実行される（試験で再現）。`cat` と `pk` は、起動で定義する薄い関数にした。
- **`CommandNotFoundAction`** は、`Get-<名前>` を探したあと `<名前>` で呼ばれる（2 回）。ハンドラの出力（`Write-Output`）は捨てられる（見たいときは `Write-Host`）。`CommandOrigin` は、`-Command` の文字列と対話の入力の、トップレベルのコマンドだけが `Runspace`。スクリプトファイル・関数・`Invoke-Expression`・`& { }` の中は `Internal`。ディレクトリ名での取り違えを防ぐため、`Runspace` だけを対象にした。
- **`LocationChangedAction`** は PowerShell 7 にあり、5.1 には無い（プロパティが無い）。5.1 の PSReadLine 2.0.0 は `-PredictionSource` を持たない。**無いパラメーターを `try` / `catch` で受けても、`$Error` に 1 件残る**（起動エラーの検査が落ちた）ので、PSReadLine の版（2.1.0 以上）で判定する。
- **`CommandNotFoundAction` と `LocationChangedAction` は、読み戻すと、代入したスクリプトブロックではなく、変換されたデリゲート**（`EventHandler<…>`）が返る。スクリプトブロックと `ReferenceEquals` で比べても一致しないので、同じファイルを 2 回読み込む（プロファイルの再読み込み）と、前のハンドラとして自分自身を保持し、**スタックオーバーフロー**になった（試験で再現）。登録したあとに読み戻したデリゲートを控えて比べる。
- **`CommandNotFoundAction` のハンドラは、入力の引数を見られない**。差し替えた `CommandScriptBlock` が受け取る `$args` で、引数つきかどうかを判定し、引数があれば `CommandNotFoundException` を投げる（`build --help` が、同名のディレクトリへの移動にならない）。
- **mise の cache は、Windows では `%TEMP%` の下の `mise`**（`mise cache path` が `…\AppData\Local\Temp\mise` を返す。2026-11-25、mise 2026.11.13）。TEMP をリポジトリの `.tmp` へ向けた対話シェルで mise を動かすと、`<repo>/.tmp/mise/<ツール>/<版>` と `metadata-*.msgpack.z` が作られた（配備後の ConPTY で確認）。Linux の cache は `~/.cache/mise` で、TMPDIR の影響を受けない。対策として、`MISE_CACHE_DIR` が未指定なら、向ける前の TEMP の `mise` に固定した。
- `Set-Content` などの `-Path` はワイルドカード（`[ab].txt` は `a.txt` に一致する）。git の pathspec も同じ。`git --literal-pathspecs` と `-LiteralPath` を使う。
- **場所のスタック**（`Push-Location`・`Get-Location -Stack`）は SessionState ごと。モジュールの関数の中の `Get-Location -Stack` は、呼び出し元のスタックを見ない。
- **PSReadLine の `-Chord 'Space'` は不正**（`Unrecognized key 'Space'`）。`Spacebar` を使う。Space のハンドラが例外を出すと、空白が入らなくなる（キーボードが使えなくなる）ので、`try` / `catch` で、失敗しても空白を入れる。
- **ネイティブコマンドを、パイプラインの最後に置いた形では、`$LASTEXITCODE` が設定されないことがある**（試験の偽の fzf で、`@("a","b" | fzf)` の直後に空だった）。ループの終了は、終了コードではなく、出力の有無で判定する。
- **入れ子のクロージャは、外側のクロージャの変数を見ない**（`GetNewClosure()` の中で作った `GetNewClosure()`）。補完のスタブでは、いったんそのスコープの変数へ写してから捕まえる。
- PowerShell 7.4 以降は、空文字の引数を外部コマンドへ渡せる。5.1 は渡らないので、`fzf -q ''` のようなものは、値があるときだけ足す。

### 補完

- `gh completion -s powershell`・`chezmoi completion powershell`（cobra 製。10.7〜10.8 KB）、`mise completion powershell`（4.6 KB。`mise __complete_word__ --shell powershell --line …` を呼ぶ）、`uv generate-shell-completion powershell`（**753 KB**）、`uvx --generate-shell-completion powershell`（19 KB）、`rg --generate complete-powershell`（26 KB）、`fd --gen-completions powershell`（14 KB）、`herdr completion powershell`（50 KB）。`oh-my-posh completion powershell` は出力が空だった。
- cobra 製のスクリプトは、補助の **`function` と `filter`**（`__gh_debug`・`__gh_escapeStringWithSpecialChars`）を最上位で定義し、補完のブロックから呼ぶ。入れ子のスコープで読むときは、グローバルへ定義し直さないと、2 回目の呼び出しで失敗する（`filter` を見落として再現した）。
- **本物の `Register-ArgumentCompleter` でスタブを置き換える方式は、cobra 製では効かなかった**（clap 製の mise・uv・rg・fd・herdr では効いた）。登録先が別になると思われる（未確認）。スクリプトの内容はそのまま使い、スタブの中で `Register-ArgumentCompleter` を関数として上書きして、**ブロックを横取り**する方式にした。
- 補完のスクリプトを生成するコマンドへ、引数が渡らなかった事故が 1 度あった（入れ子のクロージャ）。使い方の表示を、キャッシュに書き込んで実行しかけたので、「`Register-ArgumentCompleter` を含む出力だけをキャッシュする」検査を足した。
- 初回の Tab: gh 366 ms・chezmoi 134 ms・mise 255 ms・uv 261 ms（生成とキャッシュを含む）。2 回目以降は 10〜100 ms。
- winget は Microsoft の公式の手順（`winget complete`。取得 2026-11-25 [Enabling tab completion with the winget tool](https://learn.microsoft.com/en-us/windows/package-manager/winget/tab-completion)）。

### tar と zstd

- PATH の tar は 2 種類。Git for Windows 同梱の **GNU tar**（`C:\Program Files\Git\usr\bin\tar.exe`）と、Windows 標準の **bsdtar**（`System32\tar.exe`、libarchive 3.8.9・libzstd 1.5.7）。
- GNU tar（MSYS）は、`-C C:\dir` の `\` を読み違えて開けない（`Cannot open`）。`/` 区切りにすると通る。`C:\x.tar` の `C:` はリモートのホスト名と読まれるので `--force-local`。zstd は `--use-compress-program`。
- bsdtar は、展開は zstd を自動判定する。圧縮は `--zstd --options zstd:compression-level=N,zstd:threads=0`。`--use-compress-program=zstd` では「Unrecognized archive format」で展開できない。
- PowerShell のパイプは、5.1 で外部コマンドのバイト列を壊す。tar に圧縮を任せる形にした。
- zstd は mise の registry に無い（`mise registry` で確認）。scoop の `zstd` 1.6.0 を使う。

### MinGW（scoop の `mingw-winlibs` 16.2.0）

`-fsanitize=address` と `-fsanitize=undefined` は、リンクで失敗する（`ld returned 1 exit status`）。`-D_GLIBCXX_DEBUG` と `-Wl,--stack,1073741824` は通る。

### 道具が Windows で入るか

使い捨ての `MISE_DATA_DIR` へ `mise install bat eza ripgrep yazi yt-dlp`（最新）が成功した（約 6 分。回線が遅かった）。eza は `--color=always --grid --width N` と `-T -L 2 -a -I …` が Windows で動く。

## 決めたこととその理由

- **関数は小さなモジュールにして自動読み込みする**: 起動時間のため（上の実測）。manifest の `FunctionsToExport` を実体と一致させる検査を足した。
- **標準のコマンドの意味を変えるものは足さない**: `ls`（`Get-ChildItem` はオブジェクトを流す）。`ll` などの別名で eza を使う。`cat` は bat があるときだけ、かつ単純な呼び出しだけ。
- **TEMP の追従は足した**（非対話を含む）: Linux の `.zshenv` と同じ位置づけ。起動の遅れが出ないよう、書き込みの試しを外した。所有者の確認は Windows には無いので、しない。
- **zeno の snippet は、YAML を二重に持たず、chezmoi のテンプレート（`include | fromYaml | toJson`）で生成する**。zeno の YAML に Windows 用の印を足すと、Linux の zeno の読み込みに影響しうる（未確認）ので足さない。
- **Enter での snippet 展開は足さない**: oh-my-posh が Enter のハンドラを持ち、置き換えると transient prompt が壊れる（[powershell-slow-2026-11](powershell-slow-2026-11.md)）。

## 起動時間の内訳

基準（develop）との差を、ConPTY のプロンプトまでの中央値（n=5 を、基準と交互に 3 回ずつ）で測った。測定のゆらぎは、同じ版で ±20 ms ほどある。

| 版 | 基準 | 新しい版 | 差 |
| --- | --- | --- | --- |
| 関数を `commands/` に分け、全部を起動で dot-source | 約 1250 ms | 約 1400 ms | 約 +150 ms |
| 関数をモジュールへ（起動で読むのは `interactive.ps1` の 1 つ） | 1257〜1260 ms | 1320〜1322 ms | 約 +62 ms |
| 上に加えて、Management モジュールの読み込みを避ける・クロージャを減らす・補完のスタブを 1 つに | 1255〜1282 ms | 1304〜1347 ms | 約 +25〜60 ms（中央値 約 +40 ms） |

内訳（プロセス内のストップウォッチ。最後の版）:

- `Update-RepoLocalTemp`（最初の呼び出しと `LocationChangedAction` の設定）: 約 15 ms（JIT と .NET の型の解決が主。書き込みの試しは外してある）。
- `interactive.ps1`: ファイルの読み込みから抜けるまでの全体で約 70 ms。そのうち、各区画の実行は約 26 ms（モジュールのパスと関数の定義 8、履歴 6、auto_cd 2.4、chpwd 1.6、snippet 3.2、補完 2.5 など）。残りはファイルの読み込み・解析・AMSI の走査と思われる（`.ps1` を 1 つ読むと 5〜15 ms かかる、既存の `commands/*.ps1` の実測と同じ性質。内訳は未確認）。
- ただし、`interactive.ps1` を読んだ後の oh-my-posh の初期化の区間は、読む前より約 30 ms 短くなった（先に読んだ処理の JIT が共有される）。プロンプトまでの差は、プロセス内の足し算より小さい。
- 効いた対策: `Test-Path` / `Remove-Item`（Management モジュールの読み込みを伴い、約 25〜35 ms）を、`$ExecutionContext.InvokeProvider.Item` の直接呼び出しに変えた。`GetNewClosure()` は 1 つにつき約 2 ms（補完のスタブをツールごとのクロージャから、全ツールで共有する 1 つに）。`$ExecutionContext.InvokeCommand.PSObject.Properties[...]` は初回に約 10 ms（版の判定に変えた）。
- 効かなかった実験: 全行コメントを除いた版（`profile.ps1` と `commands/*.ps1` すべて）は、むしろ 50 ms ほど遅かった（原因は未確認。内容の違うファイルの AMSI の結果が、まだ記憶されていなかった可能性）。コメントを減らす対策は採らない。
- 起動時間の目標は置かず、実測を docs に残す。重くなったと感じる場合は、`commands/interactive.ps1` の区画ごとに外して測る（手順は [スクリプト](../../../scripts/windows/measure_pwsh_latency.py) の `startup --profile-file`）。

## 未確認

- `superpi`（Windows の `sudo`）の実機の昇格。この機では `sudo` を実行していない（権限の方針で拒否される）。`sudo` の既定は新しいウィンドウで起動する（[Sudo for Windows](https://learn.microsoft.com/en-us/windows/advanced-settings/sudo/)。取得 2026-11-25）。
- Alt+C の fzf の選択画面。割り当てだけ確認した。Tab は、1 つだけの補完は挿入、複数は fzf の選択画面が出ることを確認した。
- posh-git による git の Tab 補完（この機に posh-git は未導入）。
- 実際の ssh 経由での動作。
- `chezmoi apply` による配備（`313_mise` の `mise install`、`311_scoop` の zstd、`310_winget` の posh-git）。
