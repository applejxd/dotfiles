# ガードツール（guarded_edit / ask）の失敗の集計と見送った案

> `docs/spec/guard/pi-guard.md#ツールの拡張guarded_read--guarded_write--guarded_bash-の使いやすさ` から移した記録。移設時点で再測定していない。

## 記録 — 観測日は各文に記載（移設 2026-10-26）

- **対象バージョン**: 各文に記載（pi 1.3.0 前後）
- **環境**: 各文に記載

### 問い

`guarded_edit` と `ask` の失敗はどれだけあり、どう直したか。何を見送ったか。

### 根拠

`friction-review` の集計（`.agents/skills/friction-review/`）。元の文のとおり。

### 結果（元の文）

- `guarded_edit` の失敗のヒントの節から: （`friction-review` の集計: 呼び出し 940 件のうち 118 件（約 12.5%）が失敗。内訳は、oldText が見つからない 50、結果が同一 36、引数の不正 16、複数一致 9、重なり 3）
- 同じ bullet から: 実機で確認（oldText の空白を間違えた呼び出しで、行 2 の違いが返る）。
- `ask` の引数の正規化の bullet から: （失敗 11 件: 壊れた JSON 6、`question` が要素の外 5）
- 同じ bullet から: （効果は未測定）（壊れた JSON の発生率を下げる説明の効果）
- 同じ bullet から: `constrainedSampling`（プロバイダー側の厳密なスキーマ）は、`guarded_edit` で JSON の不正が出ていることから、今の経路では効かない可能性が高いと見て見送った。

### 考察

現在の仕様は ../../spec/guard/pi-guard.md の該当節。ここの数値・日付は観測時点のもので、再測定していない。
