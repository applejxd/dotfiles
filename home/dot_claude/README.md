# Claude Code リファレンス

- [設定一覧](https://docs.claude.com/ja/docs/claude-code/settings)
  - Claude Code によるコミットの汚染を防ぐ: `includeCoAuthoredBy=false`
  - Agent Teams を有効化: `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
    - [Agent Teams ドキュメント](https://code.claude.com/docs/en/agent-teams)
    - 複数エージェントが並列で協調作業するチーム機能（実験的機能）
    - tmux 使用時はスプリットペインで各エージェントを表示可能

## デフォルトのスラッシュコマンド

[マニュアル](https://docs.claude.com/en/docs/claude-code/interactive-mode#built-in-commands)

- セッション管理
  - `/fork [name]`：会話を分岐して新しいセッションを作成
  - `/resume [session]`：過去のセッションを再開
  - `/rewind`：チェックポイントに巻き戻し
  - `/context`：コンテキストウィンドウの内容を表示
  - `/cost`：現在のセッションのトークン使用量とコストを表示
  - `/copy`：最後の応答をクリップボードにコピー
  - `/diff`：現在のセッションでの変更差分を表示
- 計画・レビュー
  - `/plan`：タスクの計画を立てる
  - `/security-review`：セキュリティレビューを実行
  - `/insights`：コードベースの洞察を表示
- 実行制御
  - `/sandbox`：サンドボックスモードの切り替え
  - `/agents`：サブエージェントの作成・管理

## 操作 Tips

- 選択肢の Yes で Tab を押すと追加指示ができる
- 処理中に C-b で並列で会話継続可能
