# 調査記録

特定時点の実測、比較、アップストリーム調査を保存します。
現在の運用ルールは [仕様・運用](../spec/index.md)、採用した設計判断は
[ADR](../adr/index.md) を参照してください。

## 運用

- ファイル名は `kebab-case-topic.md`（連番なし）
- **1 記録 = 1 回の調査・試行。** 観測日と一次情報の URL を必ず書く
- 実測は**実行したコマンドと出力**を載せる。推測を書くときは「推測」と明示する
- **過去の記録を書き換えない。** 新しいパスは新しい記録として追加する。
  訂正は元の観測と区別して残す
- 陳腐化しても削除しない。「いつ時点か」が分かれば古い観測にも価値がある
- **現在の総合判断は [探索・変更案件](../change/index.md) の候補比較表が正本。**
  ここを全部読まないと現状が分からない状態にしない
- 大きくなったらディレクトリへ分割し、`YYYY-MM-DD-<pass>.md` を並べる
- テンプレートは `~/.claude/skills/checkpoint/references/research-template.md`

## 一覧

| 文書 | 内容 |
| --- | --- |
| [エージェントハーネス比較](agent-harness-comparison.md) | Claude Code / Copilot CLI / Codex CLIの機能・強制層・設定差分、OpenCodeへの乗り換え評価 |
| [compaction 関連の hook 仕様](compaction-hooks.md) | 圧縮の直前・直後に割り込める hook、Copilot の入力契約の実測 |
| [sandbox機能の包括調査](sandbox-capabilities.md) | Claude Code / Copilot CLIのsandbox全機能、採用状況、落とし穴 |
| [zenoとzsh-autosuggestionsの連携](zeno-autosuggestions-integration.md) | widget競合の原因、ロード順、回避策 |

[ドキュメント一覧へ戻る](../index.md)
