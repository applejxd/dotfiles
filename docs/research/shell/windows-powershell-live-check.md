# Windows PowerShell 5.1 での `copilot` 関数・プロファイル・読み取り判定の実機確認

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 E1 — 2026-10-05

- **対象**: Windows PowerShell 5.1.26100.8972（`powershell.exe`）、Windows の Python 3.12.10（`py -3`）。
  基準コミット bd822f8
- **環境**: WSL2 から `powershell.exe` / `py.exe` を呼んだ。`-ExecutionPolicy Bypass` はそのプロセスだけに付け、
  Windows の設定（実行ポリシー・環境変数・レジストリ・プロファイル）は変えていない。
  一時ファイルは `%TEMP%\cztest` に置き、終了後に削除した
- **未参照**: pwsh（7）は無い。本物の Copilot CLI（WinGet の 1.0.84）はインストール済みだが、
  実行したのは `copilot --version` だけ

### 問い

CI は静的テストしか通さない Windows 資産を、実際の PowerShell 5.1 / Windows の Python で動かしたとき、
意図どおりに振る舞うか。

### 方法

1. `chezmoi --source home execute-template < home/dot_config/powershell/profile.ps1.tmpl` で描画
   （`chezmoi.os` を差し替えなくても描画できた。プロファイルは OS 分岐を持たない）。
   `copilot` 関数だけを切り出し UTF-8 BOM 付きで保存し、`. <関数>.ps1` で読み込んだ
2. 偽の `copilot.exe` を `Add-Type -OutputAssembly` で作り（引数・3 変数・stdin の有無とデータを報告し、
   `FAKE_EXIT` で終了コード、`FAKE_THROW` で未処理例外を返す）、PATH の先頭に置いた
3. 描画したプロファイル全体（`cache.ps1` と `commands/` を並べて配置）を非対話で dot-source
4. `common.toml` を描画し、`command_policy.py` と hook（`executable_check_file_read.py` と `lib/`）を
   Windows 側へコピーして、`AGENTS_CONFIG_DIR` を指して実行

### 結果

#### 1. `copilot` 関数（実 PowerShell 5.1・偽 copilot.exe）

| # | 確認 | 結果 |
| --- | --- | --- |
| ① | 3 変数が未設定 → 子へ既定値 | `GCM_INTERACTIVE=never` / `GIT_EDITOR=false` / `GIT_TERMINAL_PROMPT=0` が入った |
| ② | 値ありはそのまま | `GIT_EDITOR=vim` は維持され、残りは既定値。なお Windows では `$env:X = ''` が変数を削除するため、「空文字が設定済み」の場合は確かめられない（未設定扱いで既定値が入った） |
| ③ | 終了後に親で戻る | 入れた分は未設定へ、元からあった値はそのまま |
| ④ | 終了コード | `FAKE_EXIT=7` → 親の `$LASTEXITCODE` が 7 |
| ⑤ | 引数 | 空白入り（`a b`）、`it's`、`--flag=x y` は正しく渡る。**`"` の入った引数・空文字・末尾が `\` の引数は壊れる**（下記） |
| ⑥ | パイプ入力 | `'hello pipe' \| copilot p` で `STDIN_DATA=[hello pipe]`。パイプ無しで呼んでも関数が空入力を流して閉じることはない（偽 copilot の stdin は関数経由でも直呼びでも同じ。下の制約を参照） |
| ⑦ | 失敗時も finally で戻る | 非ゼロ終了（3）・未処理例外（`LASTEXITCODE=-532462766`）・パイプ元の `throw`（`-ErrorAction Stop`）のどれでも 3 変数は未設定へ戻った |
| — | copilot が無いとき | `copilot: command not found` を `Write-Error` で出して `return`（`$LASTEXITCODE` は触らない） |
| — | `.cmd` の分類 | `fakecp.cmd` は `Get-Command -CommandType Application` で `Application` として見つかる |
| — | 本物 | `copilot --version`（関数経由）→ `GitHub Copilot CLI 1.0.84-8.`、終了コード 0、環境変数は戻る |

**⑤の詳細（PowerShell 5.1 のネイティブ引数渡しの挙動。関数の不具合ではない）**: 同じ引数を関数を通さず
`copilot.exe 'a b' 'say "hi"' '' 'C:\Program Files\x\'` と直接呼んでも同じ結果になった。

| 渡した引数 | 子が受け取った値 |
| --- | --- |
| `say "hi"` | `say hi`（引用符が消える） |
| `''`（空文字） | 引数ごと消える |
| `C:\Program Files\x\` | `C:\Program Files\x"`（末尾の `\` が閉じ引用符を escape する） |

`copilot -p 'say "hi"'` のようにプロンプトに `"` を含めると、5.1 ではそのままでは届かない。
`$PSNativeCommandArgumentPassing`（PowerShell 7.3+ の仕組み）は 5.1 に無い。

**⑥の制約**: 偽 copilot の標準入力は、この実験ではどの呼び方でも「リダイレクト済み・空」だった
（WSL から非 TTY で起動したため）。人が開いたコンソールの TTY が子へ引き継がれるか（対話 UI の標準入力が
閉じないか）は、この方法では確かめられていない。確かめられたのは「関数が `$MyInvocation.ExpectingInput`
の分岐で、パイプ無しのときは直呼びと同じ入力を子へ渡す」ところまで。

#### 2. プロファイルの対話判定

`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ". <profile>.ps1; Get-Command open,copilot,dclean -ErrorAction SilentlyContinue | Select Name"`

- 出力は `copilot.exe` の 1 件だけ。これは PATH 上の実体（WindowsApps の stub と WinGet の本物）で、
  `Get-Command copilot -CommandType Function` は `False`。`open` / `dclean` / `pbcopy` / `ccd` も定義されない
  → 非対話の `-Command` では関数が定義されない
- エラー・警告は出なかった。mise と oh-my-posh はこの機械に入っているが、非対話ブロックで走る mise の
  キャッシュ（`%LOCALAPPDATA%\PowerShellProfileCache`）は既存のもので、更新日時は変わらなかった
- `$PSDefaultParameterValues['*:Encoding']`=`utf8`、`[Console]::InputEncoding`=`utf-8`、`Add-EnvPathEntry` は定義済み
- 起動時間（`Measure-Command { . profile.ps1 }`、非対話）: 4 回で 144 / 136 / 127 / 125 ms
  （起動直後の 1 回目が最大。`powershell.exe` 自体の起動時間は含まない）

#### 3. Copilot の読み取り判定の大文字・小文字（Windows の Python）

`py -3 --version` → `Python 3.12.10`（`os.name == 'nt'`）。`python.exe` は WindowsApps の stub のみで使わなかった。
`command_policy.matches_read_deny` と、hook を本番の起動形（`py -3 -B -X utf8`）で実プロセス実行した結果が一致した。

| パス | 期待 | 判定（一致 glob） |
| --- | --- | --- |
| `C:\repo\.SSH\.env.example` | 拒否 | 拒否（`**/.ssh/**`） |
| `C:\repo\.ENV.PRODUCTION` | 拒否 | 拒否（`**/.env.*`） |
| `C:\repo\.env.example` | 許可 | 許可 |
| `C:\repo\.ENV.EXAMPLE` | 許可 | 許可（例外も大小文字を区別しない） |
| `C:\repo\.Env` | 拒否 | 拒否（`**/.env`） |
| `C:\repo\.ssh\id_rsa` | 拒否 | 拒否（`**/.ssh/**`） |
| `C:\repo\src\main.py` | 許可 | 許可 |

補足: `-X utf8` を付けずに hook を `subprocess.run(text=True, encoding="utf-8")` で読むと、拒否理由（日本語）が
cp932 で出力されて `UnicodeDecodeError` になった。`ensure_ascii=False` の出力は既定コードページに依存するため、
既存の `-X utf8` 指定が要る、という既知の前提（`docs/spec/agent-config-generation.md`）を裏づける観測。

### 本体の不具合

見つからなかった。`copilot` 関数の環境変数の出し入れ・終了コード・finally・パイプ判定は意図どおり。
⑤で見た引数の欠落は PowerShell 5.1 のネイティブコマンド共通の挙動で、関数が起こしたものではない。

### 確かめられなかったこと

- PowerShell 7（pwsh が無い）。7.3+ は `$PSNativeCommandArgumentPassing` により⑤の挙動が異なる
- 人が開いた対話シェル（TTY あり）でのプロファイル全体（`open` などの定義、oh-my-posh のテーマ、PSReadLine、
  OnIdle の読み込み）と、`copilot` 関数がパイプ無しのとき TTY の標準入力を保つこと
- 本物の Copilot CLI が `[agent_env]` の 3 変数を自分のシェルツールの子（git）へ引き継ぐこと
  （`--version` を通しただけ）
- Windows Terminal・コンソールホストを介した起動、`-NoExit` 付きの対話判定
- `*.ps1` の他の資産（`run_after_*` など）
