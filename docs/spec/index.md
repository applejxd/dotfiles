# 仕様・運用

現在有効な構成、セットアップ、運用手順をまとめています。

## 運用

- ファイル名は `kebab-case-topic.md`（連番なし）
- **現在の姿を書く。** 歴史的な意思決定の長い説明は
  [ADR](../adr/index.md) と [案件](../change/index.md) へリンクする。
  ただし**現在の運用に必要な判断基準・理由はここに書いてよい**
- 古くなった記述は残さず**置換**する（履歴は git が持つ）
- **意図した契約と実装の不一致は、不一致として記録する。**
  観測されたバグや未検証の挙動を、そのまま仕様として追認しない
- dotfiles では「source state を更新した」「対象の機械へ適用した」「実機で確かめた」を
  分けて書く（[用語集](glossary.md#適用と検証の段階)）
- 実装を変えたら同じコミットでここも直す

## 一覧

| 文書 | 内容 |
| --- | --- |
| [プロジェクト構造](structure.md) | ディレクトリ構成、chezmoiスクリプトの順序、対応OS、chezmoi 本体の導入、gh / Herdrのmise管理、AI CLIの公式インストーラーでの導入、oh-my-pi の設定、個人用カスタム指示の共有 |
| [開発ガイド](development.md) | 環境の準備、変更の種類ごとの検証、Windows 実機での検証、スクリプトの追加 |
| [テストと検証の仕組み](testing.md) | Docker ハーネスのモード・環境変数・判定の契約、GitHub Actions で見ている範囲、既知の未達 |
| [セキュリティ](security.md) | 秘密情報の保護対象・脅威と、Bitwarden / sops の方式の理由 |
| [秘密情報の管理セットアップ（sops + age）](sops-age.md) | age 鍵の作成・バックアップ、プロジェクト設定、鍵の復旧手順 |
| [エージェント権限仕様](agent-permissions.md) | AI CLI の permission / hook / sandbox の入口。CLI ごとの適用範囲、3 層の概要、OpenCode の保存した承認の確認とリセット（`oc-utils`）、動作確認・導入・トラブルシュート |
| [設定の生成と所有権](agent-config-generation.md) | `common.toml` の構成と編集ルール、生成先と所有権、MCP、OpenCode の設定、hook の単一ソース化 |
| [コマンド・ファイルの判定](agent-command-policy.md) | 照合規則、allow / ask / deny の使い分けと例外、bash 検査ルールの足し方、CLI 差 |
| [sandbox (Claude Code / Copilot CLI)](agent-sandbox.md) | sandbox 層・ネットワーク層・seccomp、マシン固有の許可 (`local.toml`) |
| [OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md) | `ocs` の構成、起動順序、Fence の境界の組み立て規則、DB の共有、起動前の退避、境界チェック（`ocs --check`） |
| [文脈の引き継ぎ](checkpoint.md) | 圧縮を跨いで作業文脈を保つ checkpoint の保存先・記録の形・plugin・失敗時の動作 |
| [トラブルシューティング](troubleshooting.md) | 症状 → 対象 OS・CLI → 対応先の索引 |
| [トラブルシューティング: 導入と適用](troubleshooting-bootstrap.md) | スクリプトの再実行、Python・Bitwarden・mise・APT・AI CLI の導入で起きる障害 |
| [トラブルシューティング: AI CLI の実行時](troubleshooting-agents.md) | sandbox の依存（Copilot / Claude 別）、Windows の hook、skills の読み込み失敗、`.copilot/skills` の junction |
| [用語集](glossary.md) | 境界・隔離起動・通常起動、出力内容と配置先、許可の種類、秘密情報と資格情報、適用と検証の段階、A1 / A2 / B |

[ドキュメント一覧へ戻る](../index.md)
