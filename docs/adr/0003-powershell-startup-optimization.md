# 3. PowerShell Startup Optimization

Date: 2026-03-12

## Status

Accepted

## Context

PowerShell の起動時間を少しでも短縮し、日常のターミナル操作を快適にするため、プロファイル（`profile.ps1.tmpl`）の最適化が必要でした。初期化時に毎回実行される外部コマンドやモジュールのインポートが、ミリ秒以上の遅延を引き起こしていました。

特に、以下の2点が主なボトルネックまたは非効率な処理となっていました：
1. **Oh My Posh**: `oh-my-posh init pwsh ... | Invoke-Expression` のように、パイプライン経由での文字列評価は PowerShell においてオーバーヘッドが大きく、パフォーマンスの低下を招きの原因でした。
2. **Chocolatey Profile**: `Test-Path` を用いたファイルの存在確認と `Import-Module` を起動時に同期的におこなうと、ディスク I/O やモジュールのコンパイルによる遅延が発生します。

## Decision

確実に効果が見込める「一本道」の最適化として、以下の変更を実施しました：

1. **Invoke-Expression のパイプライン回避 (Oh My Posh)**:
   `oh-my-posh init pwsh --config ... | Invoke-Expression` を
   `Invoke-Expression (@(& oh-my-posh init pwsh --config ...) -join "\`n")` あるいは `Invoke-Expression (& oh-my-posh init pwsh --config ... | Out-String)` に相当する高速な呼び出しへ変更しました。より具体的には、オブジェクト生成などのパイプオーバーヘッドを減らす手法です。
   
2. **モジュールの遅延読み込み (Chocolatey Profile)**:
   起動直後に補完等の機能が即座に必要ではないため、`Register-EngineEvent -SourceIdentifier PowerShell.OnIdle` を用いて、シェルがアイドル状態になったバックグラウンドで `Test-Path` および `Import-Module` をおこなうよう変更しました。この際、`-Scope Global` を指定することで現在のセッションでグローバルに有効になるようにしています。

これにより、非同期に処理できるものはメインループから外し、結果として対話プロンプトが表示されるまでの時間（起動時間）を短縮しました。

## Consequences

- **ポジティブ**: PowerShell 起動時の体感待ち時間が減少する。重いモジュール読み込みがアイドル時に遅延されるため、ターミナル立ち上げ直後のレスポンスが改善される。
- **ネガティブ**: Chocolatey 関連のタブ補完などが、起動直後の最初の数百ミリ秒（アイドルになるまで）は利用できないが、実運用上は不都合なし。
