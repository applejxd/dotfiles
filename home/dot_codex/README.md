# Codex CLI リファレンス

## デフォルトのスラッシュコマンド

[マニュアル](https://developers.openai.com/codex/cli/slash-commands/)

- セッション管理
  - `/fork`：会話を分岐して新しいスレッドを作成
  - `/resume`：保存済みセッションを再開
  - `/copy`：最後の応答をクリップボードにコピー
  - `/diff`：作業ツリーの Git 差分を表示
  - `/compact`：会話履歴を要約してコンテキストを節約
  - `/status`：モデル・権限・トークン使用量などセッション情報を表示
- 計画・レビュー
  - `/plan`：計画モードに切り替え
  - `/review`：作業ツリーのレビュー（動作変更・テスト漏れの検出）
- 実行制御
  - `/agent`：エージェントスレッドの切り替え
  - `/permissions`：承認ポリシーの変更
- Codex 固有
  - `/personality`：応答スタイルの変更（friendly / pragmatic / none）
  - `/mention <path>`：ファイルを会話コンテキストに追加
  - `/apps`：利用可能なアプリを参照・挿入
  - `/experimental`：実験的機能のトグル
  - `/ps`：バックグラウンドターミナルの状態確認