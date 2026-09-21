# 現在地とドキュメント

目的: Windows / Ubuntu / WSL / macOS の dotfiles を chezmoi で管理し、
AI CLI の権限・hook・スキルを単一ソースから生成する。

- **最終レビュー**: 2026-09-19
- **対象範囲**: source state は全 OS ぶん。**配備・確認済みは Linux / WSL のみ**

導入手順はリポジトリ直下の [README](../README.md) を参照。

## 現在有効な状態

- **利用できるもの**: chezmoi による配備、`common.toml` からの権限 / hook / MCP 生成、
  sops + age による秘密管理、`checkpoint` スキル（手動起動）と圧縮前後の hook
- **既知の制限・未検証範囲**:
  - **実機での圧縮試験は未実施**（配備は済んだ。新しいセッションが要る）
  - Windows 実機での検証は未実施（source state は更新済み）
  - Copilot の圧縮直後の注入は Claude より 1 ツール分遅い（同じターン内には届く）
  - Copilot では文脈使用率を推定できないため、閾値監視は見送り
  - OpenCode は hook / sandbox を持たないため、防御が permission リスト 1 層だけ
    （[OpenCode V2 の扱い](spec/agent-permissions.md#opencode-v2-の扱い)）
- **現行仕様**: [仕様・運用](spec/index.md)

## 活動中

| 案件 | 状態 | 現在の見立て・最大の未解決点 | 次の確認 |
| --- | --- | --- | --- |
| [CHG-0001](change/0001-compaction-context-handover.md) | In progress | 段 1〜6 完了。両 CLI に復帰注入を実装し、実機での圧縮試験だけが残る | P0-3（新しいセッションで圧縮を起こす） |

## 判断待ち・障害

- なし

## 最近の重要な変更

- 2026-09-20 — Copilot でも圧縮直後に checkpoint を自動注入（`PreCompact` の印 +
  `postToolUse`）。「原理的にできない」という誤った前提を訂正
  — [記録 E7](research/compaction-hooks.md)
- 2026-09-19 — `adr` スキルを `checkpoint` へ統合（役割の重複を解消）
  — [CHG-0001](change/0001-compaction-context-handover.md)
- 2026-09-19 — docs を「情報の役割」で分け、案件を中心に置く運用へ
  — [ADR-0010](adr/0010-exploratory-spec-driven-docs.md)
- 2026-09-19 — `checkpoint` スキルを追加（compaction を跨ぐ復帰記録）
  — [ADR-0009](adr/0009-save-before-documenting.md)
- 2026-09-14 — Copilot の開発ツール自動許可を切り、必要な範囲を明示
  — [ADR-0008](adr/0008-explicit-dev-tool-grants.md)

## 段階と置き場所

| 段階 | カテゴリ | 答える問い | 寿命 |
| --- | --- | --- | --- |
| 探索・計画 | [探索・変更案件](change/index.md) | この目的をどう達成するか | 永続（終了後も状態を付けて残す） |
| 観測 | [調査記録](research/index.md) | 何を観測したか | 永続（追加のみ） |
| 決定 | [ADR](adr/index.md) | なぜその選択をしたか | 永続（覆すときは新規 ADR） |
| 仕様 | [仕様・運用](spec/index.md) | 今どうなっているか | 永続（置換） |

## 目的から探す

| 目的 | 文書 |
| --- | --- |
| リポジトリ全体の構成を知る | [プロジェクト構造](spec/structure.md) |
| Herdr を mise で導入・更新する | [Herdr の管理](spec/structure.md#herdr-の管理) |
| GitHub CLI を mise で導入・更新する | [mise による CLI 管理](spec/structure.md#mise-による-cli-管理) |
| Claude Code / Copilot CLI / OpenCode を導入・更新する | [AI CLI の導入](spec/structure.md#ai-cli-の導入) |
| 開発環境を準備して検証する | [開発ガイド](spec/development.md) |
| Windows 資産を実機で検証する | [Windows 実機での検証](spec/development.md#windows-実機での検証) |
| Bitwarden / sops の仕組みを知る | [セキュリティ](spec/security.md) |
| sops + age を導入・復旧する | [Secret管理セットアップ](spec/sops-age.md) |
| AI CLI の permission / hook を変更する | [エージェント権限仕様](spec/agent-permissions.md) |
| OpenCode の権限がなぜ他と違うか知る | [OpenCode V2 の扱い](spec/agent-permissions.md#opencode-v2-の扱い) |
| OpenCode のプラグインを検討する | [プラグイン生態系の棚卸し](research/opencode-plugins.md) |
| 圧縮を跨いで作業文脈を保つ仕組みを知る | [文脈の引き継ぎ](spec/checkpoint.md) |
| MCP サーバを追加・変更する | [MCP サーバ](spec/agent-permissions.md#mcp-サーバ) |
| sandbox で何ができるか調べる | [sandbox機能の包括調査](research/sandbox-capabilities.md) |
| エラーを切り分ける | [トラブルシューティング](spec/troubleshooting.md) |
| いま何を探索しているか知る | [探索・変更案件](change/index.md) |
| 設計理由を確認する | [ADR一覧](adr/index.md) |
| 技術調査の結果を確認する | [調査記録一覧](research/index.md) |

## 配置ルール

- 複数候補があり、まだ決着していない → `change/` の案件
- 実際に観測・実測した → `research/` に日付つきの記録を追加
- 後で理由を失うと困る重要な選択をした → `adr/`
- 今の動き方・使い方が変わった → `spec/`
- **このセッション限りの実行状態** → docs に書かない。
  `checkpoint` スキルが解決するセッション別ファイルへ（固定パスを書かない）
- 文書を増減したら、対応するカテゴリの `index.md` も更新する
- **全ての作業が 4 種類を生産するわけではない。** 誤字修正や単純な設定変更に
  案件や比較表を要求しない
