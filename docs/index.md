# ドキュメント

このリポジトリの詳細資料は、目的別に3カテゴリへ整理しています。
基本的な導入手順はリポジトリ直下の [README](../README.md) を参照してください。

| カテゴリ | 内容 |
| --- | --- |
| [仕様・運用](spec/index.md) | 構成、開発、セキュリティ、セットアップ、トラブル対応 |
| [ADR](adr/index.md) | 採用した設計判断、却下した選択肢、トレードオフ |
| [調査記録](research/index.md) | 比較調査、原因分析、アップストリーム情報 |

## 目的から探す

| 目的 | 文書 |
| --- | --- |
| リポジトリ全体の構成を知る | [プロジェクト構造](spec/structure.md) |
| 開発環境を準備して検証する | [開発ガイド](spec/development.md) |
| Bitwarden / sops の仕組みを知る | [セキュリティ](spec/security.md) |
| sops + age を導入・復旧する | [Secret管理セットアップ](spec/sops-age.md) |
| AI CLI のpermission / hookを変更する | [エージェント権限仕様](spec/agent-permissions.md) |
| エラーを切り分ける | [トラブルシューティング](spec/troubleshooting.md) |
| 設計理由を確認する | [ADR一覧](adr/index.md) |
| 技術調査の結果を確認する | [調査記録一覧](research/index.md) |

## 配置ルール

- 運用手順・現在の仕様は `spec/`
- 長期的な設計判断は `adr/`
- 時点依存の比較・検証記録は `research/`
- 新しい文書を追加したら、対応するカテゴリの `index.md` も更新する
