# 調停の接着層 (settle)

`work/settle.ts`。調停 ([arbiter](arbiter.md) の `settle(facts)`) を `agent_before_settle` に登録する薄い層。判断は持たない。
autocheckpoint・todo・goal がそれぞれ登録して `entries` の置換や継続を取り合うのを、1 つのハンドラにまとめるための入口。

## 登録条件

`registerSettle(pi, deps, {enabled, child}) → {registered}`。`enabled` (旗 `PI_WORK_ARBITER=1`) が偽、または `child` が真なら何も登録しない
(既定は無効)。登録は `pi` ごとに 1 回で、2 回呼んでもハンドラは 1 つ (べき等。2 回目は `registered: true`)。

## ハンドラの流れ

1. `deps.snapshot()` (台帳の投影・フェーズ・各提案者の入力) と、イベント (`outcome`・`entries`)・ctx (`mode`・`hasPendingMessages`・`isCompacting`) から `Facts` を組む。
2. `settle(facts)` → `Decision`。
3. 返り値: 継続のときだけ `{ entries: [...event.entries, ...新しい entries], continue: true }`。それ以外は `{}` (前のハンドラの entries を消さず、`continue` も返さない)。
4. `effects` を実行する。`wake` は `exec.wake` だけ (高々 1 回。settle では出ず resume のときだけ)、`notify` は `notices.ts` の `select` を通して `exec.notify`
   (表に無い事象は出さない)、`append_event` は `runtime.submit` (観測用 aux)、`checkpoint` は `exec.checkpoint`。各効果の失敗は他を止めない。
5. `journal.emit("settle", {source: "arbiter", outcome, continue, by, row, why})` を 1 件。

snapshot の取得などで例外が出たら `{}` (継続しない)。ハンドラは `pi.sendUserMessage` / `triggerTurn` を呼ばない。

## 既存の 3 者の移し方 (配線の手順。別の feature)

1. `index.ts` で旗が有効なとき、3 者の `agent_before_settle` 登録を外し、`registerSettle` を 1 回呼ぶ (`deps` を 3 者の状態から作る)。
2. autocheckpoint: `phase`・`percent`・`cooldown` を snapshot に写し、`exec.checkpoint("compact")` に `ctx.compact` を、再開は `exec.wake` に結ぶ。
3. todo: `doing` / `blocked` / `queued` と `nudged*` を snapshot に写す (`nudged` の更新は `append_event` の効果で受ける)。
4. goal: `goal-core` の事実 (`active`・`claim`・`stall`・予算) を snapshot に写す。
5. 旗が無効なら従来どおり (旗の ON/OFF で二重に登録しない)。

## 限界

- `exec.checkpoint(action)` の引数・`snapshot` の鮮度 (turn 中の更新) は配線側の責務。この層は写された値を信じる。
- `notify` の `show` は調停が `select` で決めた値。ここでは表に在る事象かの検査だけを重ねる。
- `resume` (圧縮後の起床) は `handleSettle` の対象外 (settle トリガのみ)。
