# pi の長い sleep の誘導の由来と実モデルでの確認

`docs/spec/guard/pi-decide.md#誘導` から移した記録。移設時点で再測定していない。

## 記録 E1 — 2026-10-20

- **対象バージョン**: pi（`sonnet-5.5`・`gpt-6-sol`）
- **環境**: 基準は spec 側の記述（`long-sleep-in-foreground` の導入時）

### 問い

`sleep` で会話を止めない誘導（`long-sleep-in-foreground`）は、実モデルで `bg_run` への誘導として働くか。

### 事前の予想

元の文には書かれていない。

### 方法・条件

利用者の提案（2026-10-20）から入れた規則。実モデルで「30 秒待ってから実行」を依頼した。

### 結果

元の文: 「この規則は、利用者の、「sleep で会話を止めない」という提案（2026-10-20）から。実モデルで「30 秒待ってから実行」を依頼し、`sonnet-5.5`・`gpt-6-sol` とも、`bg_run` で待ち、完了通知で報告した。」

### 考察

2 モデルとも期待どおりの行動だった（標本は 2 モデル・1 依頼）。

### 次の問い

現行の仕様は [pi-decide.md の誘導](../../spec/guard/pi-decide.md#誘導)。バックグラウンド実行の誘導の実験は [pi-bg-experiments.md](pi-bg-experiments.md)。

### 参照

- [pi-decide.md の誘導](../../spec/guard/pi-decide.md#誘導)
