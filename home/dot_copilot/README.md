# Copilot CLI リファレンス

- カスタムスラッシュコマンドは claude のものを読み取れる
- ユーザ設定は `~/.copilot/settings.json`（旧 `config.json` から自動移行済み。`config.json` は認証等の自動管理状態のみ）
- [設定ディレクトリ / settings.json 仕様](https://docs.github.com/ja/copilot/reference/copilot-cli-reference/cli-config-dir-reference#configuration-file-settings)
- `includeCoAuthoredBy=false` を chezmoi で強制し、Copilot が作成するコミットへ共同著者 trailer を追加しない

## `trustedFolders` が `chezmoi diff` に出続ける

`common.toml` の `trusted_folders` は `modify_private_settings.json.py.tmpl` が
`settings.json` の `trustedFolders` へ書き込む。ところが CLI 側はこのキーを
**読むだけで書き戻さない**ため、`copilot` を 1 回でも起動すると
`settings.json` の再シリアライズで消える（他のキーは残る）。

```bash
chezmoi apply ~/.copilot/settings.json   # trustedFolders が入る
copilot mcp get deepwiki                 # これだけで消える
```

CLI は自前のフォルダ信頼ストアを先に見て、無い場合に `trustedFolders` を
fallback として参照する実装になっている（1.0.84-1 時点）。したがって

- `chezmoi diff` にこの差分が出るのは**想定内のドリフト**で、追跡しなくてよい
- キー自体は fallback として有効なので `common.toml` からは外さない

同じ理由で `chezmoi apply` 直後にも `settings.json` の差分が残る。`run_after_140_herdr_integration.sh.tmpl`
が呼ぶ `herdr integration install copilot` が、chezmoi の書き込みの後に
settings.json を**末尾改行なし**で書き直すため。差分は `\ No newline at end of file`
の 1 行だけで、内容は一致している。

## デフォルトのスラッシュコマンド

[マニュアル](https://docs.github.com/ja/copilot/reference/cli-command-reference#slash-commands-in-the-interactive-interface)

- 基本機能
  - `/init`：プロジェクトの初期化
  - `/yolo`：すべて許可
  - `/cd [directory]`：現在のディレクトリを表示・移動
  - `/resume [sessionId]`：セッションを再開
  - `/usage`：使用状況を表示
  - `/terminal-setup`：IDE 向けに改行をサポート
  - `/update`：CLI を更新
- 計画機能
  - `/plan [prompt]`：タスクの計画（Shift+Tab でもいい）
  - `/research <topic>`：Deep Research (GitHub and web)
- 実装機能
  - `/fleet [prompt]`：並列作業の指示（後述）
  - `/delegate [prompt]`：GitHub Copilot Agent に移行
  - `/agent`: エージェントの作成・管理
- レビュー機能
  - `/diff`：差分をレビュー
  - `/review [prompt]`：コードレビュー

## Fleet の使い方

新機能のテストケース作成など、並列作業の指示に使う。
[Autopilot で使う例](https://docs.github.com/ja/enterprise-cloud@latest/copilot/concepts/agents/copilot-cli/fleet)：

1. PLAN モードで実装計画を立てる (Shift+Tab)
2. `/fleet` の並列作業に向いているかチェック
3. `Accept plan and build on autopilot + /fleet` で実行
