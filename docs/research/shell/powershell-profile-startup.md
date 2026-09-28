# PowerShell プロファイルの起動時間

- **観測日**: 2026-09-09（記録したコミット `cd1d7c6`）
- **対象**: このリポジトリの Windows 機。PowerShell 7（`pwsh`）と
  Windows PowerShell 5.1（`powershell`）。各版の細かい版番号・試行回数は記録が無い
- **一次情報**: コミット `cd1d7c6`（`refactor(windows): PowerShell プロファイルを
  Documents の外へ移す`）の本文と、同コミットで `docs/spec/structure.md` に書いた表。
  **計測に使ったコマンドは残っていない**

プロファイルの構成と、起動経路で守る規則は
[プロジェクト構造](../../spec/structure.md#powershellプロファイル) が正本。
ここには、その規則を決めたときの計測だけを残す。

## 条件

`cd1d7c6` で入れた変更の前後を比べた。変更後のプロファイルは次のとおり。

- 実体を `~/.config/powershell` に置き、`$PROFILE` にはローダーだけを置く
- 起動経路の cmdlet（`Test-Path` / `Join-Path` / `New-Object` / `Set-Alias`）と
  `Get-Command` を .NET API へ置き換える
- `mise activate` と `oh-my-posh init` の出力を `%LOCALAPPDATA%` にキャッシュする

**`oh-my-posh init` のキャッシュは後で外した**（テーマ設定がセッション ID に
紐付き、別セッションでは既定のテーマに戻るため）。そのため現在のプロファイルの
起動時間は、下の「変更後」と同じとは限らない。外した後は計っていない。

## 結果

起動時間の中央値:

| 起動 | 変更前 | 変更後 | `-NoProfile` |
| --- | ---: | ---: | ---: |
| `pwsh` | 1420 ms | 510 ms | 312 ms |
| `powershell` | 525 ms | 359 ms | 182 ms |

- `Microsoft.PowerShell.Management` / `Microsoft.PowerShell.Utility` の cmdlet と
  `Get-Command` のコマンド探索は、初回の呼び出しにそれぞれ 0.25 秒前後かかった
- `mise activate` が PATH の先頭へ足す重複は 5 件から 0 件になった
