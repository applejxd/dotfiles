# Copilot CLI リファレンス

- カスタムスラッシュコマンドは claude のものを読み取れる
- [config.json 仕様](https://docs.github.com/ja/enterprise-cloud@latest/copilot/reference/cli-command-reference#configuration-file-settings)


## デフォルトのスラッシュコマンド

[マニュアル](https://docs.github.com/ja/copilot/reference/cli-command-reference#slash-commands-in-the-interactive-interface)

- 基本機能
  - `/init`：プロジェクトの初期化
  - `/yolo`：すべて許可
  - `/cd [directory]`：現在のディレクトリを表示・移動
  - `/usage`：使用状況を表示
  - `/terminal-setup`：IDE 向けに改行をサポート
  - `/update`：CLI を更新
- 計画機能
  - `/plan [prompt]`：タスクの計画（Shift+Tab でもいい）
  - `/research <topic>`：Deep Research (GitHub and web)
- 実装機能
  - `/fleet [prompt]`：並列作業の指示（後述）
  - `/delegate [prompt]`：GitHub Copilot Agent に移行
- レビュー機能  
  - `/diff`：差分をレビュー
  - `/review [prompt]`：コードレビュー

## Fleet の使い方

新機能のテストケース作成など、並列作業の指示に使う。
[Autopilot で使う例](https://docs.github.com/ja/enterprise-cloud@latest/copilot/concepts/agents/copilot-cli/fleet)：

1. PLAN モードで実装計画を立てる (Shift+Tab)
2. `/fleet` の並列作業に向いているかチェック
3. `Accept plan and build on autopilot + /fleet` で実行