# アーキテクチャ決定記録（ADR）

設計判断とその根拠を記録する。

[ドキュメント一覧へ戻る](../index.md)

## 目的

「なぜその形なのか」は時間が経つと失われる。判断の背景・却下した選択肢・
トレードオフをここに残す。

## 運用

- ファイル名は `NNNN-kebab-case-title.md`（4 桁ゼロ埋め、連番）
- 新規作成時はこの索引にも 1 行追加する
- ステータスは `Proposed` / `Accepted` / `Deprecated` / `Superseded by ADR-NNNN`
- 決定を覆す場合は既存 ADR を書き換えず、新しい ADR を起こして古い方を `Superseded by` にする
- 決定の一部だけを改める場合（部分改定）は、新しい ADR を起こし、旧 ADR は本文を残したまま
  冒頭に改定の案内（日付・改めた範囲・後継へのリンク・残りは有効であること）を置く
- 決定の受諾（`Accepted`）と実装の完了は別物。実装の進捗は [案件](../change/index.md) が持つ
- テンプレートは `~/.claude/skills/sdd-docs/references/adr-template.md`

## 一覧

| ADR | 内容 | ステータス |
| --- | --- | --- |
