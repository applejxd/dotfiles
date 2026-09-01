# アーキテクチャ決定記録（ADR）

このリポジトリの設計判断とその根拠を記録する。

## 目的

dotfiles は「なぜその形なのか」が失われやすい。
特に外部ツールとの相互作用や、一見遠回りに見える実装の理由は、
時間が経つと再発見にコストがかかる。
判断の背景・却下した選択肢・トレードオフをここに残す。

## 運用

- ファイル名は `NNNN-kebab-case-title.md`（4 桁ゼロ埋め、連番）
- 新規作成時はこの索引にも 1 行追加する
- ステータスは `Proposed` / `Accepted` / `Deprecated` / `Superseded by ADR-NNNN`
- 決定を覆す場合は既存 ADR を書き換えず、新しい ADR を起こして
  古い方を `Superseded by` にする
- テンプレートは `home/dot_claude/skills/adr/references/adr-template.md`

## 一覧

| # | タイトル | ステータス | 日付 |
| --- | --- | --- | --- |
| [0001](0001-external-tool-config-coexistence.md) | 外部ツールが書き込む設定領域と chezmoi の共存 | Accepted | 2026-08-30 |
| [0002](0002-loopback-http-approval-scope.md) | ループバック宛 HTTP リクエストの承認緩和範囲 | Accepted | 2026-09-01 |
| [0003](0003-require-python-311-for-agent-configuration.md) | agent 設定生成に Python 3.11 以上を要求する | Accepted | 2026-09-01 |
| [0004](0004-hook-check-semantic-axis.md) | hook の判定軸を表層構文から副作用の性質へ移す | Accepted | 2026-09-01 |
