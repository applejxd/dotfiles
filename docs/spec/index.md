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
- dotfiles では「source state 更新済み」と「各 OS へ配備・確認済み」を分ける
- 実装を変えたら同じコミットでここも直す

## 一覧

| 文書 | 内容 |
| --- | --- |
| [プロジェクト構造](structure.md) | ディレクトリ構成、chezmoiスクリプトの順序、対応OS、gh / Herdr / AI CLIのmise管理、個人用カスタム指示の共有 |
| [開発ガイド](development.md) | mise / uv / pre-commitを使った開発と検証 |
| [セキュリティ](security.md) | Bitwarden、sops、ageの役割と要件 |
| [Secret管理セットアップ](sops-age.md) | sops + ageの導入、日常操作、復旧 |
| [エージェント権限仕様](agent-permissions.md) | Claude Code / Copilot CLI中心のpermissionと、各CLIへのhook・MCP生成 |
| [OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md) | `ocs` の構成、起動順序、境界の組み立て規則、状態の置き場、起動前の退避 |
| [文脈の引き継ぎ](checkpoint.md) | 圧縮を跨いで作業文脈を保つ checkpoint の保存先・記録の形・hook |
| [トラブルシューティング](troubleshooting.md) | よくある障害の原因と対処 |

[ドキュメント一覧へ戻る](../index.md)
