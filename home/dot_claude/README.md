# Claude Code リファレンス

- [設定一覧](https://docs.claude.com/ja/docs/claude-code/settings)
  - Claude Code によるコミットの汚染を防ぐ: `includeCoAuthoredBy=false`
  - Agent Teams を有効化: `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
    - [Agent Teams ドキュメント](https://code.claude.com/docs/en/agent-teams)
    - 複数エージェントが並列で協調作業するチーム機能（実験的機能）
    - tmux 使用時はスプリットペインで各エージェントを表示可能

## settings.json の管理範囲

`~/.claude/settings.json` は chezmoi の `modify_settings.json.py.tmpl` が更新する。

| キー | 管理 |
| --- | --- |
| `permissions` | `home/dot_config/agents/common.toml` から生成（apply で全置換） |
| `hooks` | 同上。ただし `~/.claude/hooks/` を起動するエントリだけを差し替え、Orca など外部ツールが注入した hook は温存する |
| `env` / `enabledPlugins` / `includeCoAuthoredBy` | 手動管理（apply では触らず保持） |

## hook の追加手順

1. `home/dot_claude/hooks/executable_<name>.(py|sh)` にスクリプトを置く
   - パス取得やブロック出力は `lib/agent_compat.(py|sh)` を使うと両 CLI 対応になる
2. `home/dot_config/agents/common.toml` の `[[hooks]]` に 1 エントリ追加する
3. `chezmoi diff` で確認 → `chezmoi apply`
4. Claude Code を再起動（settings.json は起動時に読まれる）

`[[hooks]]` は `~/.claude/settings.json` と `~/.copilot/hooks/from-claude.json`
の両方に展開されるので、CLI ごとに二重管理しなくてよい。
詳細は [`docs/agents-permissions.md`](../../docs/agents-permissions.md)。

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
