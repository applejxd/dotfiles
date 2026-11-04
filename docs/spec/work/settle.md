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

## 既存の 3 者の移し方 (配線済み・旗つき: feature `work-settle-wire`)

旗 `PI_WORK_ARBITER=1` のときだけ移る。**旗が無効 (既定) なら従来どおり** (autocheckpoint と todo が自分で登録し、調停は登録しない)。

1. `index.ts`: `registerAutoCheckpoint` の直後 (`registerJournal` より前) で `registerSettle(pi, makeSettleDeps({...}), ...)` を 1 回呼ぶ。
   旗が有効なら autocheckpoint・todo は `agent_before_settle` を登録しないので、登録順 (pi は登録順の連鎖) は問題にならない。
2. autocheckpoint: `checkpointSnapshot()` (`phase`・`percent`・`cooldown`) と `checkpointExec` (`compact`・`cancel`・`markSaving`・`notify`・`wake`) を公開。
   ctx は `session_start`・`before_agent_start`・`turn_end` で控える。保存の指示が勝ったことは journal の tap (`work/settle-snapshot.ts` の `tapJournal`) が `markSaving` で受ける。
3. todo: `globalThis.__piTodoSnapshot()` (`open`・`doing`・`blocked`・`queued`・`nudged*`・`markNudged`)。リマインドが勝ったことは同じ tap が `markNudged` で受ける。
4. snapshot の組み立ては `work/settle-snapshot.ts` の `buildSnapshot` (欠け・壊れは継続しない側へ)。`streak` は数えない (0 固定)。
5. 圧縮完了後の自動再開 (`trigger: resume`) は**従来の経路のまま** (実機で確かめてから調停へ移す)。goal の配線は別 feature。

## 限界

- `exec.checkpoint(action)` の引数・`snapshot` の鮮度 (turn 中の更新) は配線側の責務。この層は写された値を信じる。
- `notify` の `show` は調停が `select` で決めた値。ここでは表に在る事象かの検査だけを重ねる。
- `resume` (圧縮後の起床) は `handleSettle` の対象外 (settle トリガのみ)。
