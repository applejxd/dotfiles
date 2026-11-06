# 継続の調停 (settle arbiter)

`agent_before_settle` の継続判断を 1 か所 (`work/arbiter.ts`。純関数) にまとめる。提案者はハンドラも副作用も持たず、
事実 (`Facts`) から `Proposal` を返すだけ。`arbitrate(facts, proposals)` が表で 1 つに決める。
背景と決定の経緯: [ADR-0026](../../adr/0026-work-ledger-integrated-architecture.md)。配線 (`index.ts`・`wake()` の実呼び出し) は別の feature。

## 優先順位表 (上から最初に当たる行が勝つ)

| 行 | 条件 | 結果 |
| --- | --- | --- |
| 0 | 子・print・json | なし |
| 1 | 中断 (Esc) | なし。保存中なら `checkpoint cancel`、goal 実行中なら `goal.paused` |
| 2 | 圧縮中・phase が compacting / plan | なし。phase が saving のまま圧縮中として見送るときは `checkpoint cancel` (古い保存周期を持ち越さない) |
| 3 | 利用者の入力・エラー応答・連続継続の上限 | なし。利用者の入力で保存中なら `checkpoint cancel`。エラーは `run.failed` を通知 (保存中なら続けて compact) |
| 4 | 保存 (文脈 ≥ 閾値・cooldown 外) | LLM の指示つきで継続 (単独)。機械だけなら継続せず直接 compact。保存中の settle も compact |
| 5 | 予算超過かつ完了の申告 | 先に評価 (継続)。申告が無ければ継続せず `budget.paused` |
| 6 | 失敗の判断 (子の失敗・承認の連続失敗) | 継続 (triage) |
| 7 | LLM の仕事が ready (todo・goal の継続・親の手順) | 継続 |
| 8 | 完了の申告・停滞 | 評価して継続 |
| 9 | 待ちだけ | turn を起こさない。新しい user 待ちは alert だけ |

行 5〜8 に当たる提案は `entries` を 1 件にまとめる (≤600 字。勝者の `customType`)。置換で互いを上書きしない。

## 守る条件

- `arbitrate` は純関数 (入力を変えない・決定的)。`entries` は常に 0 または 1 件。
- `wake` は `effects` の中だけ。提案者は作れず (渡しても捨てる)、`trigger:"resume"` (圧縮の完了後) で行 5〜8 に当たるときだけ `arbitrate` が出す。
- 通知は `notices.ts` の `select` を必ず通す (表に無い組は例外 → 閉じる)。
- 迷ったら継続しない。不正な事実・例外・不明な通知は継続なしで返す。compact の効果があれば継続しない。

## 現状 3 者との対応

| 現状 | 提案者 |
| --- | --- |
| `autocheckpoint.ts` の idle / saving | `proposeCheckpoint` (行 4。再開の `RESUME_PROMPT` は `wake` に置換) |
| `todo/index.ts` の before_settle | `proposeTodo` (行 7。`nudged` は `append_event` で記録) |
| `goal-core.ts` の `decideSettle` 5〜9 | `proposeGoal` (行 5〜8) |
| 子の完了 | `proposeChildren` (行 6・7・9) |

## 限界

- 文面は最小の仮 (配線時に現状の本文へ差し替える)。計画の「エラーは triage」は、継続せず通知にした (安全側)。
- 計画中・goal の phase は事実として受け取るだけで、台帳の投影からの導出は配線の側。
- 試験: `test_work_arbiter.py`（事実の直積約 12 万通りを独立した仕様と照合・性質試験・現状 3 者の回帰）。
