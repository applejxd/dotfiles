# ssh では RedirectionGuard が junction を止める件の洗い出し（2026-11）

- **観測日**: 2026-11-25（基準コミット `b776d951`）
- **対象**: この機（Windows 11 build 26300、OpenSSH 9.5.6.4 の sshd。既定シェルは pwsh 7）。PowerShell 7.6.10、uv 0.12.24、mise 2026.11.13、scoop 0.6.0
- **きっかけ**: ssh で `vim` を起動すると `Shim: Could not determine if target is a GUI app` / `Could not create process` が出た。
  「ほかにも同じ原因で困るものは無いか」を洗い出した

## 結論

- **原因は RedirectionGuard**（Windows 11 のプロセスの緩和策 `ProcessRedirectionTrustPolicy`）。sshd が有効にして動き、子のシェルとプロセスも引き継ぐ。
  管理者でないユーザーが作った junction・シンボリックリンクは、有効なプロセスから辿れない（`ERROR_UNTRUSTED_MOUNT_POINT`、448）。
  この機で、保護を有効にしたプロセスから scoop の shim を呼んで、同じエラーを**再現した**。
- **影響を受けるもの**（この機、保護を有効にして実測）: scoop の shim 119 個すべてと、PATH にある `scoop\apps\*\current`（`gcc` など）、
  uv が管理する Python（`uv run`・`uvx`・`uv python`・その venv）、`~\.copilot\skills`（junction）。
- **影響を受けないもの**: mise の shim（`pi` を含む全部）、mise の `exec`、WinGet のパッケージ（`chezmoi`・`bw`・`mise`）、Git、`ssh`、`pwsh`、
  Windows の `sudo`、`tailscale`、`wsl`、`code`、`herdr`（単体の呼び出し）、`oh-my-posh`、`winget`。
- **直した**: scoop（profile が ssh のときだけ、`current` を実体のディレクトリで置き換える）と、`vim`（Git for Windows の実体を直接呼ぶ）。
  確認したのは、保護を有効にしたプロセスでの `ghq`・`gcc`・`make`・`7z`・`pdftk` の起動まで。shim 119 個は影響の範囲で、すべての実行はしていない。
- **残っている**: uv が管理する Python。`UV_PYTHON_PREFERENCE=only-system` で動くことは確かめたが、profile には入れていない。
  実際の ssh 経由での確認は、この機から localhost へ入れないので**していない**（保護を有効にしたプロセスでの再現だけ）。

## 仕組み（出典）

- RedirectionGuard は、junction・シンボリックリンクに、作成時の権限に応じた信頼の印を付け、有効なプロセスは信頼されないものを辿らない
  （[MSRC](https://www.microsoft.com/en-us/msrc/blog/2025/06/redirectionguard-mitigating-unsafe-junction-traversal-in-windows)。2026-11-25 取得）。
  管理者が作ったもの、または印が付く前（保護が入る前の更新より前）に作られたものは信頼される。
- sshd.exe は、この機の `HKLM\...\Image File Execution Options\sshd.exe` の `MitigationOptions` に値がある（読み取りのみ。管理者でなくても読める）。
  同じ指摘は herdr-core の
  [Issue #209](https://github.com/herdrdev/herdr-core/issues/209)（sshd が `EnforceRedirectionTrust` で、子が引き継ぐ）にある（取得は同日）。
- 報告された被害は、scoop の [#6594](https://github.com/ScoopInstaller/Scoop/issues/6594)・[#6612](https://github.com/ScoopInstaller/Scoop/issues/6612)、
  nvm-windows の `.nodejs`（[#1564](https://github.com/nvm-windows/nvm/issues/1564)）、fnm の multishells（[#1612](https://github.com/Schniz/fnm/issues/1612)）、
  uv の `%APPDATA%\uv\python` の junction（[windows-user-ai-sandbox #3](https://github.com/tkarabela/windows-user-ai-sandbox/issues/3)）、
  winget のパッケージ（[winget-cli #6454](https://github.com/microsoft/winget-cli/issues/6454)）、Inno Setup 6.7 以降のインストーラが起動したアプリ
  （[mcpproxy-go #1844](https://github.com/smart-mcp-proxy/mcpproxy-go/issues/1844)）。
  Inno Setup の件は ssh に限らず、インストーラが最後に起動したアプリが保護を引き継ぐ。この機で該当するものは未確認。

## 再現の方法

`scripts/windows/run-with-redirection-guard.ps1` が、自分のプロセスで `SetProcessMitigationPolicy(ProcessRedirectionTrustPolicy)` を有効にしてから、
引数のコマンドを実行する。有効にするのはそのプロセスと子孫だけで、レジストリ・sshd・システムは変えない（ssh で入らずに ssh のセッションの動作を調べられる）。

```powershell
pwsh -NoProfile -File scripts\windows\run-with-redirection-guard.ps1 ghq --version
# -> Shim: Could not create process with command '"…\scoop\apps\ghq\current\ghq.exe" --version'
pwsh -NoProfile -File scripts\windows\run-with-redirection-guard.ps1 "$env:ProgramFiles\Git\usr\bin\vim.exe" --version   # Git の vim は動く
```

## 洗い出しの結果

junction を持ちうる場所（`~` 直下、`scoop\apps`、`%APPDATA%\uv`、`mise\installs`、`WinGet`、`npm`、`.local`、`.pi`、`.claude`、`.copilot`、`.vscode`、
`.t3`、`.config`、`.cache`、`Programs`、`Git`、`chocolatey`）を走査した。リンクは 81 個（junction 80、ディレクトリのシンボリックリンク 0、Dropbox の 1 個）。
保護を有効にする前後で `GetFileSystemEntries` が通るかを比べた。

### 辿れなくなったもの（影響あり）

| 場所 | 中身 | 影響 |
| --- | --- | --- |
| `scoop\apps\{7zip,ghq,gow,innounp,mingw-winlibs,pdftk,sudo}\current` | scoop が作る。shim 119 個（gow 113、7zip 3、ghq・innounp・pdftk 各 1）と、PATH の `mingw-winlibs\current\bin`（`gcc`・`g++`）が通る | `vim`・`ls`・`grep`・`7z`・`ghq`・`make` などが `Shim: Could not create process`。`gcc` は見つからない |
| `scoop\apps\7zip\26.04\{Codecs,Formats}` | persist への junction | 7-Zip の拡張が読めない（未確認） |
| `%APPDATA%\uv\python\cpython-3.11-…`・`cpython-3.14-…` | uv が major.minor で作る junction | `uvx`・`uv run`・`uv python find` が `Failed to inspect Python interpreter`。管理 Python の venv も |
| `~\.copilot\skills` → `~\.claude\skills` | Copilot CLI のスキルの共有 | ssh の Copilot CLI がスキルを読めない（未確認。junction が辿れないことだけを確認） |
| `mise\installs\aqua-earendil-works-pi\{1,1.5,global,latest}` | mise が作る（pi を更新したとき） | **shim は動く**（pi は `1.5.2` の実体を直接使う）。`mise activate`（shim なし）の PATH が `latest` を使うと影響する |

### 辿れるもの（信頼されている）

`mise\installs\*\{latest,global,メジャー}` のうち、`fzf`・`gh`・`go`・`jq`・`node`・`uv`・`herdr`・`gitleaks`・`shellcheck` など約 50 個と、`~\src`（`E:\repos` への junction）。
保護が入る前に作られたもので、**今後の更新で作り直されると、信頼されないものになる**（pi の `latest` などがすでにそうなっている）。

### コマンドの実測（保護を有効にして `--version` など）

- **動く**: `chezmoi`・`git`・`gh`・`mise`・`node`・`npm`・`npx`・`bw`・`pi`・`fzf`・`jq`・`rg`・`fd`・`herdr`・`oh-my-posh`・`code`・`wsl`・`tailscale`・`winget`・
  `curl`・`tar`・`ssh-keygen`・`pwsh`・`powershell`・`copilot`・`hermes`・Windows の `sudo`・`python`・`py`（`Programs\Python\Python312`）。
  mise の shim は `fzf`・`gh`・`gitleaks`・`go`・`herdr`・`jq`・`markdownlint-cli2`・`node`・`npm`・`npx`・`pi`・`shellcheck`・`uv`・`uvx` を確認した。
- **動かない**: `ghq`・`make`・`7z`・`pdftk`（scoop の shim）、`gcc`・`g++`（PATH の `current`）、`uv`・`uvx` の既定の Python（上の表）。
- `docker`・`pre-commit`・`sops`・`age` は PATH に無い（影響の対象外）。mise の shim の `llama-*` などの `No version is set for shim` は、保護と無関係。

### 他に見ておくべきもの

- **`git commit`（ssh 経由）**: pre-commit の ruff が `mise exec -- uvx ruff@0.16.5` で、保護下の `mise exec -- uvx ruff@0.16.5 --version` は失敗した（上の uv）。
  ssh 経由でコミットすると、この hook が止まるはず（**推測**。実際の ssh では未確認）。
- **herdr を ssh から使う**: ssh のセッションが起動した core は保護を引き継ぎ、ペインがリンクを辿れない
  （[#209](https://github.com/herdrdev/herdr-core/issues/209)。回避は、core を手元で（ログオン時に）起動しておく）。この機で herdr を ssh から使うかは未確認。

## 対処

| 案 | 状態 | 内容 |
| --- | --- | --- |
| scoop: `current` を実体で置き換える | **実装済み**（`scoop-path.ps1`） | ssh のときだけ。PATH の `current` の項目はその位置で実体へ、shim の指す先は shims の直前へ。保護下で `ghq`・`gcc`・`make`・`7z`・`pdftk` が動くことを確認。約 50 ms |
| `vim` は Git for Windows の実体を直接呼ぶ | **実装済み** | gow の 7.4 より新しく、junction を通らない |
| uv: `UV_PYTHON_PREFERENCE=only-system` | 動作確認済み・**未実装** | 保護下で `uvx ruff@0.16.5`・`uv run --no-project python`・`mise exec -- uvx ruff`・`uv run --with pytest` が動いた（Python 3.12.10 の `Programs\Python\Python312`）。uv が管理する Python を使わなくなる |
| 管理者で junction を作り直す（`scoop reset`、`uv python install`） | 未検証 | 管理者が作ると信頼される。更新のたびに戻るという報告がある |
| sshd の RedirectionGuard を切る（`Image File Execution Options` の `MitigationOptions`） | 非推奨・未検証 | 管理者権限が要り、sshd の保護を弱める。公開の手順があるが（gist）、この機では試していない |
| scoop の gow をやめる | 未検討 | 古いツール（vim 7.4・awk 2008 年など）。Git の `usr\bin` と Windows 標準で足りるかは未確認 |
