# Windows 設定の実測・経緯メモ（structure.md から移設）

> `docs/spec/structure.md` の次の節から移した記録。移設時点で再測定していない。現在の仕様は各節（下記）を参照。

- **観測日**: 2026-10-11 〜 2026-10-21（各節の本文の日付が正）
- **問い**: Windows 向けの導入・設定（WSL 本体・GPU・sudo・PATH・pi・7-Zip・電源・ウィジェットなど）で観測した事実と経緯
- **根拠**: 各節の本文（元の文のまま。URL・コマンドを含む）

## WSL 本体の導入の実測と「WSL 3」

元の節: `docs/spec/structure.md` の「WSL 本体（WslPlatform）」

- 実測（2026-10-12、ビルド 26300）: 管理者の `cmd` で `wsl --install --no-distribution` を実行すると、`VirtualMachinePlatform` の有効化（要再起動）と WSL 3.0.1 の導入が済んだ。`wsl --version` は 3.0.1.0（カーネル 6.18.40.1）。
  `wslc`（WSL containers）の CLI は、再起動後の確認が残っている。winget の `Microsoft.WSL` は 2.7.13 で遅れているため使わず、`wsl --update`（Store）で最新にする
- 「WSL 3」は、WSL パッケージの版が 3.0 になったという意味で、新しい方式ではない（担当 PM は「WSL 3 というものは無い」と述べている）。3.0.1 は WSL containers（`wslc`）の一般提供（2026-09-29）

## GPU の電力上限を入れた経緯（クラッシュ）

元の節: `docs/spec/structure.md` の「GPU の電力上限（GpuPowerLimit）」

2026-10-17 から 18 にかけて 2 回止まり（Kernel-Power 41）、
電力上限を下げたらクラッシュしなくなった（下記「実測」）。

## GPU クラッシュのダンプの実測

元の節: `docs/spec/structure.md` の「GPU の電力上限（GpuPowerLimit）」

実測: ダンプ（`C:\Windows\Minidump\101726-11968-01.dmp`）の停止コードは 0x133（`DPC_QUEUE_EXECUTION_TIMEOUT_EXCEEDED`）、
スタックは `nvlddmkm`（NVIDIA ドライバ）の割り込み処理で、実行中のプロセスは `vmmemWSL` だった。2 回目は BSOD のダンプが無く、
直前に dxgkrnl の LiveKernelEvent 0x193 が出ていた。原因がドライバかハードかは未確定。

## 標準の `sudo` の実機確認

元の節: `docs/spec/structure.md` の「個別の判断」

実機で、検出（未有効 → 次の apply で UAC）と昇格なしの失敗の扱いを確かめ、**UAC の承認を通した有効化も確認した**（2026-10-12。`Enabled` が 1、`sudo config` が forceNewWindow を示した）

## Windows の PATH の扱い: 外部の報告と未確認事項

元の節: `docs/spec/structure.md` の「Windows の PATH の扱い」

- `[Environment]::SetEnvironmentVariable` と `setx` で PATH を書かない。REG_EXPAND_SZ を REG_SZ に降格させ、
  PATH 内の `%USERPROFILE%` などが展開されなくなるという報告がある
  （<https://stackoverflow.com/questions/714877/setting-windows-powershell-environment-variables>、
  <https://github.com/Gentleman-Programming/gentle-ai/issues/5581>、いずれも 2026-10-21 取得）。
  試験でこの書き方の再導入を止めている（`test_env_path_template_writes_user_path_as_expand_string`）
- 以前の `314` は `SetEnvironmentVariable('Path', …, 'User')` で追記していた。この書き方で実際に降格した PC が
  あるかは未確認。確かめるには `(Get-Item HKCU:\Environment).GetValueKind('Path')` が `ExpandString` かを見る
- GUI（システムの詳細設定）の環境変数エディタは 1 変数 2047 文字まで。超えた PATH を保存すると末尾が無警告で切れる
  という報告がある（<https://stackoverflow.com/questions/60231125/environment-variable-is-too-large>、
  <https://github.com/microsoft/winget-cli/issues/3601>）。PATH を長くしすぎない。長さを根本から減らす手段は、
  ツールごとの PATH 追加をまとめる shim ディレクトリ（mise の shims など）へ寄せること
- Zed の統合ターミナルで PATH が途中で切れる・更新が反映されない報告がある
  （<https://github.com/zed-industries/zed/issues/40837>、<https://github.com/zed-industries/zed/issues/51349>）。
  この repo の環境での原因は未確定
- 未検証: Windows 実機での共通関数の動作（この環境には pwsh がなく、構文検査もしていない）

## Windows の pi（バイナリ版）の実測

元の節: `docs/spec/structure.md` の「Windows の pi」

- 実測（Windows、隔離した mise 環境）: 導入は 3〜4 秒。起動は実体 0.45 秒、shim 経由 0.51 秒、npm 版 0.41 秒。
  自作の `.ts` 拡張を読み、Copilot モデルで応答する。起動引数（複数行・引用符・`%` `$` `&` `|`・日本語）は、
  実体も shim も欠けずに届く

## Windows の pi（バイナリ版）の未確認事項

元の節: `docs/spec/structure.md` の「Windows の pi」

- 未確認: 稼働中の `pi.exe` を更新できるか（ファイルロック）、Defender・制約のある環境の実行制限、全自作拡張のバイナリでの動作、
  `mise use -g` での shim と旧 `pi.cmd` の PATH 競合（`314` が旧版を外すので起きない想定）

## oh-my-posh の MSIX 版がテーマを見つけない観測

元の節: `docs/spec/structure.md` の「PowerShellプロファイル」

（2026-10 実測、31.7.0）

## ssh 経由のセッションで `%VAR%` が展開されない観測

元の節: `docs/spec/structure.md` の「PowerShellプロファイル」

（2026-10 実測。展開済みのパスを直接指せば実行できた）

## 電源設定の実機確認

元の節: `docs/spec/structure.md` の「電源設定」

- 実機の確認: 通常権限で 2 回実行し、2 回目も同じ値になること、`STANDBYIDLE` の AC が 0・DC が 600 になることを `powercfg /q` で確認した。
  蓋と無人時のスリープは、この機にその設定が無く、値を読み取れなかった（デスクトップ機。ノート PC での挙動は未確認）

## 7-Zip の関連付けの実測

元の節: `docs/spec/structure.md` の「7-Zip の関連付け」

- 実機（ビルド 26300）の `.zip` は、`UserChoice` が `CompressedFolder` のまま（2026-10-11 実測）。従来のスクリプトは ProgID のコマンドだけを書いており、
  この機の 7-Zip は ProgID も `RegisteredApplications` も登録しないため、選ぶ手段が無く、事実上効いていなかった
- 登録内容は 2 回目の実行で変化しない（値が揃っていれば何もしない）ことを実機で確かめた。設定画面の「既定のアプリ」に「7-Zip (extract)」が出ることを、目視で確認した（2026-10-12）

## ウィジェットをレジストリで止められない試行（2026-10-11、ビルド 26300）

元の節: `docs/spec/structure.md` の「広告と推奨の抑止」

実測（2026-10-11、ビルド 26300）:

- 対象の値は 2 つで、どちらも保護されており、次の書き込みがすべて拒否された:
  `HKCU\...\Explorer\Advanced\TaskbarDa`（通常権限）と `HKLM\SOFTWARE\Policies\Microsoft\Dsh\AllowNewsAndInterests`（管理者・SYSTEM）
- 試した方法: `Set-ItemProperty` / `New-ItemProperty`、.NET の `Registry.SetValue`、`reg add`、`reg import`、**SYSTEM のスケジュールタスクでの `reg add`**
  （HKCU は昇格なしで 4 方法、HKLM は管理者で 4 方法 + SYSTEM タスク。すべて「アクセスが拒否されました」）
- `Dsh` キー自体の ACL は普通（Administrators に FullControl）で、別名の値は書ける。**値名に対する保護**と見られる（公式資料に記載は無く、推測）

## LGPO による自動化の設計（未実施）

元の節: `docs/spec/structure.md` の「広告と推奨の抑止」

- 自動化するなら（未実施の設計）: 昇格子が `LGPO.zip`（`download.microsoft.com/download/8/5/c/85c25433-a1b0-4ffa-9429-7e023e7da8d8/LGPO.zip`、SHA-256 `cb7159d1…cc55`、
  Authenticode は Microsoft で有効）を管理者だけが書ける場所へ取得・検証して実行し、入力は固定内容にする。ユーザーが書ける場所の `.exe` は実行しない

## 広告と推奨の抑止の実機確認

元の節: `docs/spec/structure.md` の「広告と推奨の抑止」

- 実機の確認: HKCU の値は 2 回の実行で書き込まれ、警告は出なかった（保護されたキーは無かった）

## シェルの既定値の検証

元の節: `docs/spec/structure.md` の「シェルの既定値」

- 検証: 一時キーに向けた複製で、1 回目に設定、2 回目は変更なし、`Bypass` は維持されることを確認した。実機の `HKCU` は、実行ポリシーが既に `RemoteSigned` で、既定のターミナルは未設定だった

## Windows Sandbox の `wsb.exe` を WSL から動かした実測

元の節: `docs/spec/development.md` の「Windows Sandbox でのクリーン導入の検証」

（2026-11-23 実測。Windows 11 Pro 26300、Sandbox パッケージ 0.8.114.0。実行は WSL 経由の `powershell.exe`。最初の実測（1:25〜8:15）は、利用者のセッションが `query user` で `Disc`＝切断中。そのあと RDP で `Active` にして追試した）

### 確かめた事実

- `wsb.exe` は、アプリ実行エイリアス（`%LOCALAPPDATA%\Microsoft\WindowsApps\wsb.exe`）から起動する、パッケージ `MicrosoftWindows.WindowsSandbox` の `AppCli`。パッケージには `wsb.exe`・`WindowsSandboxServer.exe`・`WindowsSandboxRemoteSession.exe` が入り、`*.deps.json` の依存に `Grpc.Net.Client`（wsb）と `Grpc.AspNetCore.Server`（Server）がある。つまり wsb は、ローカルの Server への gRPC クライアント
- `wsb list`・`wsb start --config …` はどちらも、**約 30 秒で `Status(StatusCode="Cancelled")`（`OperationCanceledException`）**で失敗した（31・30・31 秒の 3 回。終了コード `0x80131500`）。呼ぶたびに `AppCli` が起動され（`AppModel-Runtime` のイベント 201/210/211）、Server が居なければ `WindowsSandboxServer.exe` が立ち上がる。Server は生きたままで、TCP の待ち受けは無く、RPC に応答しなかった
- `LogonCommand` 付きの `.wsb` を `Start-Process` で起動すると、`WindowsSandboxRemoteSession.exe` と Server は立ち上がったが、**ゲストの `LogonCommand` は走らず**、共有した結果フォルダは約 6 時間空のままだった
- **`WindowsSandboxServer.exe` が `STATUS_STACK_OVERFLOW`（0xc00000fd、`ntdll.dll`）で 2 回異常終了した**（アプリケーションログ。01:42:55 と 02:26:06）。1 回目は、最初の `wsb list` が起動した Server。2 回目は、`.wsb` で起動した Server。Server が落ちたあとも `WindowsSandboxRemoteSession.exe` だけが残った
- Sandbox 専用のイベントログのチャンネルは無い。パッケージの `LocalState` にもログは無かった

### 出典（外部の報告。いずれも 2026-11-23 取得）

- 公式（<https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli>）: `wsb exec` は終了コードだけを返し、出力は取れない。ユーザー側の実行（`-r ExistingLogin`）は、アクティブなセッションが要る（先に `wsb connect` する）
- LOLBAS（<https://lolbas-project.github.io/lolbas/OtherMSBinaries/Wsb/>）: `<LogonCommand>` は、ゲストの `WDAGUtilityAccount` がログオンしたときに初めて走る。それは RDP のセッションがつながった後で、`wsb start` だけではつながらない。`wsb start` ＋ `wsb exec -r System` なら、画面なしでも実行できる（出力は共有フォルダ経由）
- <https://github.com/curtisgalloway/oxbox/pull/34>（2026-09-05）: 非対話のセッション（SSH）から `wsb start` が約 30.6 秒で `Cancelled`、`wsb list` が gRPC のタイムアウトで失敗。「CLI は、対話的なデスクトップセッションを要るバックエンドへの薄いクライアント」と報告
- <https://github.com/Exoridus/exosnap/pull/435>（2026-09-27）: `wsb start` はユーザーセッションを作らず、`wsb exec -r ExistingLogin` は `ERROR_NO_SUCH_LOGON_SESSION` で失敗する。`wsb connect` を動かし続けると準備が約 20 秒になる
- 上の `STATUS_STACK_OVERFLOW` と同じ報告は、検索では見つからなかった（`microsoft/Windows-Sandbox` の issue #84・#101 は別の症状）

### 画面をつないだ状態（RDP で `Active`）の追加実測（同日 8:29〜8:45）

- `wsb list` は、RDP で `Active` でも約 30 秒で `Cancelled`（切断中と同じ）。呼ぶたびに Server が立ち上がるが、応答しない
- **Start メニューから設定なしで起動した Windows Sandbox も、`Windows サンドボックスを初期化できませんでした。アクセス許可で禁じられた方法でソケットにアクセスしようとしました。(0x8007271D)`（`WSAEACCES`）で失敗した**。私の設定や WSL 経由の問題ではなく、この機の Sandbox 自体が起動しない
- `.wsb` 方式は、設定の書き間違い（`LogonCommand` に `&` を直接書いた。XML では `&amp;`）が先に「構成ファイルが無効です」になった。直したあとは、ネットワークの有効（`quick.wsb`）・無効（`netoff.wsb`）のどちらも `Windows サンドボックスを初期化できませんでした。Exception of type 'System.Exception' was thrown.`（番号なし）で失敗した。ネットワークの無効化では直らない
- 失敗した間、Hyper-V の `Compute`・`Worker`・`VMMS`・`Hypervisor` のイベントは 1 件も無い。**VM が作られる前**の失敗
- 環境の確認: `HTTP_PROXY` 等のプロキシ環境変数は、Process / User / Machine のどれにも無い。WinHTTP は直接接続、IE のプロキシも無効。TCP の除外ポート範囲は 5357 だけ。UDP 53/67/68 の占有は無い。`hns`・`vmcompute`・`SharedAccess`・`CmService`・`WinNat` は動作中。WSL は `networkingMode=mirrored`（Hyper-V ファイアウォールが有効で、既定の受信は Block）で、仮想アダプターは `vEthernet (FSE HostVnic)` と `vSwitch (FSE Switch)` だけ（`Default Switch` は無い）
- **Windows の再起動後（8:49 起動、RDP で `Active`）も同じ**: `.wsb`（`quick.wsb`）は `System.Exception` で失敗した。`wsb list` の失敗だけ、`Status(StatusCode="Internal", Detail="Error starting gRPC call. HttpRequestException: The operation has timed out. (localhost:80)")` に変わった（oxbox の報告と同じ文面）。`127.0.0.1:80` への接続は、他の閉じたポートと同じく拒否され、待ち受けは Windows にも WSL にも無い。Server が待ち受けていない
- 画面のスクリーンショットは、WSL 経由の `powershell.exe` からは取れない（`CopyFromScreen` が「ハンドルが無効」）。エラーは利用者の画面の確認に頼る

### 出典の追加（取得 2026-11-23）

- <https://github.com/microsoft/Windows-Sandbox/issues/117>: 同じ `Exception of type 'System.Exception' was thrown.` の報告。**原因は `HTTP_PROXY` / `HTTPS_PROXY` の環境変数で、消したら直った**（この機には無いので当てはまらない）。別の報告者は、Hyper-V の `Compute` で `0xC0370106`、`Worker` で「ゲストが起動した」を見ており、この機とは様子が違う
- `0x8007271D` は `WSAEACCES`。Hyper-V のライブマイグレーションや WSL の登録でも出る。ポートの予約や排他的な占有が典型だが、この機の確認範囲では該当が無かった

### 解釈（推測。未検証）

- 「切断・ロック中のセッションが原因」という見立ては、**支持されない**。RDP で `Active` にしても、Start メニューの既定起動も失敗するため。この機では、セッションの状態に関わらず Sandbox が起動しない
- 候補: ① WSL の `mirrored` ネットワークとの干渉（Sandbox の NAT 用の `Default Switch` が作れない）、② Windows Sandbox のパッケージ（0.8.114.0）と OS（26300）の組み合わせの不具合（`WindowsSandboxServer` の `STATUS_STACK_OVERFLOW` が 2 回あるのと整合する）。どちらも確かめていない
- 無人で動かせる可能性があるのは、「`wsb start` ＋ `wsb share` ＋ `wsb exec -r System`」の経路だけ。この機では `wsb start` が通らず、試せていない

### まだ試していないこと

- 管理者権限での `hnsdiag list networks`・Hyper-V のイベントの確認、Sandbox 機能の再インストール（`Disable` / `Enable-WindowsOptionalFeature -FeatureName Containers-DisposableClientVM`）、`Reset-AppxPackage`（アプリのデータの初期化）。`winget show --id 9NSMXC3NB0HN` は版が `Unknown` で、最新版の有無は確かめられなかった
- WSL を `networkingMode=nat` に戻した場合、または `wsl --shutdown` の後で Sandbox が起動するか（この作業は WSL の中で動くセッションを止めるので、私は実行しない）
- `STATUS_STACK_OVERFLOW` の再現条件
