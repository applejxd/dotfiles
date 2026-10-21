# 一時対処の一覧

上流（外部ソフトウェア・プラットフォーム）の不具合を避けるために入れた、**いずれ消す**対処の台帳。
一時対処はここに 1 件ずつ登録し、撤去の条件を必ず書く。

## 約束

- コード側の対象（スクリプト・設定・テスト）には `TEMP-REMOVE` を付ける。
  棚卸しは `grep -rn TEMP-REMOVE .`（`.git` を除く）で一覧できる
- 一時対処を足したら、この文書に行と小節を足す。詳細（原因・出典・実測・撤去手順）は小節が正本で、
  コードのコメントは `TEMP-REMOVE` とこの文書への参照だけにする
- 上流が直ったか、不要になったら、コード・テスト・この文書の行と小節を全て消す

## 一覧

| 項目 | 対象 | 撤去の条件 |
| --- | --- | --- |
| [pwsh 7.6.x の更新通知クラッシュ](#pwsh-76x-の更新通知クラッシュ) | `300_windows/run_after_351_pwsh_update_check_off.ps1` | 修正版の pwsh が出て、通知が出ても落ちないと確認できたとき |

## pwsh 7.6.x の更新通知クラッシュ

PowerShell 7.6.6 は、新版（7.6.7）の更新通知を出すときに `PadRight` の幅が負になり、起動直後に落ちます
（`totalWidth ('-10') must be a non-negative value`）。日本語・中国語ロケールで起きます。落ちると
chezmoi の `.ps1` も走らず、プロファイルも読まれません。

`351_pwsh_update_check_off` が User の環境変数 `POWERSHELL_UPDATECHECK=Off` を設定します（冪等）。
これは更新通知だけを止め、pwsh の更新は止めません。起動済みのプロセスには効かないため、
Zed などは完全に再起動します。既に落ちる PC では、`powershell.exe`（5.1）で `setx POWERSHELL_UPDATECHECK Off` を
1 回実行してから `chezmoi apply` します。

- 出典（2026-10-21 取得）: <https://github.com/PowerShell/PowerShell/issues/28131>（ja-JP の報告と回避策）、
  [#28235](https://github.com/PowerShell/PowerShell/issues/28235)、
  [#28239](https://github.com/PowerShell/PowerShell/issues/28239)
- 実測: 家の PC（ja-JP、pwsh 7.6.6）で、`setx` 後に起動できることを確認。chezmoi スクリプトとしては Windows 実機で未検証
- 反例・未確認: 修正された版は未確認（7.6.7 のソースにも同じ計算が残るという報告が #28237 にある）
- **撤去**: `home/.chezmoiscripts/300_windows/run_after_351_pwsh_update_check_off.ps1`、
  `test_windows_assets.py` の `test_pwsh_update_check_is_disabled`、この小節と一覧の行を削除する。
  各 PC に残る User 環境変数は `[Environment]::SetEnvironmentVariable('POWERSHELL_UPDATECHECK', $null, 'User')` で消す
