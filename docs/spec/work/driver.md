# 並列実行基盤のドライバ

> **凍結した自作基盤の文書**（[ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md)。保存のみ・開発しない）。ここに出てくるコマンド・ツール（`guarded_task`・`/bypass`・`/pending`・`/orchestrate` など）は、stock の pi には**存在しない**。いまの stock の pi のコマンドは [早見](../pi-commands.md)。

スケジューラの `next()`（[仕様](scheduler.md)）は「何をするか」を返すだけ。ドライバ（`home/dot_config/pi/harness/work/driver.ts`）はそれを台帳のイベントと子の起動・停止の**効果**に変換し、子の完了・失敗・429 を台帳へ戻す。純関数（pi・fs・時計・乱数なし。時刻と乱数は引数）。入力は変更しない・決定的。配線は別の feature（旗 `PI_WORK_SCHEDULER=1`、既定は無効）。

## 入出力

| 関数 | 役割 |
| --- | --- |
| `tick(state, {now, res, aimd, memo, spawner, budget, holder})` | `schedStateOf` → `next()` → `{events, effects, memo, rejected, actions}`。start は `run.reserved` を台帳の門（`reduce`）に当て、通ったものだけ出す。通らないものは `rejected` |
| `onSpawned(state, runId, pid)` | `run.started` |
| `onUsage(state, runId, usage)` | `run.usage`。子と評価役の使用量を run → task → goal へ合算（予算に効く） |
| `onFinished(state, runId, result, ctx)` | `note`（結論か「失敗: 理由」）→ `run.ended` → 検査。`{events, state, aimd, rateLimited, error, digestInput}` |
| `onChecked(state, taskId, check)` | `check.result`（checking の task のみ） |
| `reconcile(state, {live})` | spawner が知らない started の run を `lost` で、起動されないまま残った reserved の run を `aborted` で閉じる（[詳細](#reconcile)） |

効果: `spawn`（`workTool:false` 固定・`runId`・`prompt`・`worktree?`）・`steer`・`abort`・`pause_provider`・`resume_provider`・`wake`。実行は注入する `Spawner {spawn, steer, abort}` が行う（型だけ定義）。

### reconcile

`live`（spawner が知っている run）に無い、目的の goal 配下の生きた run を閉じる。

- `started`: プロセスが消えたとみなし、note「失敗: プロセスが消えた (lost)」と `run.ended lost`。
- `reserved`: 予約だけで起動されなかった run（shutdown で取消の書き込みが通らなかった等）。note と `run.ended aborted` で予約を解放する。task が `failed` になれば `verdict retry` で ready へ戻す（失敗に数えない）。

呼び出し側（`driver-run.ts`）は、runtime・世代ごとに 1 回呼ぶ（新しい世代・新しい runtime で再度）。

## 429 と予算

- 429（`status:"limit"`、または失敗の文言が `is429`）は run を `limit` で閉じ、`resource.429`（aux）を残し、AIMD を半減、task を `verdict retry` で ready に戻す。失敗に数えない。連続成功で `aimd` が +1。5 連続で `goal.paused` と `wake`（`provider_exhausted`）を 1 回だけ出す。
- 失敗の理由は必ず非 null（無ければ「原因不明 (status=…)」）。run の note に残り、Digest の本文になる。
- 起動時の見積りを `run.attrs.est` に残す（台帳の `reserved` は超過分だけ増え、比が 1 を超えないため）。`adapt` がこれを `SchedRun.reserve` に使い、steer は 1.5 倍で 1 回、abort は 2 倍で 1 回（`memo` で重複を防ぐ）。
- 無出力の見張り: 子の出力を受けたら `onOutput(state, runId, now, memo)` が aux の `notice` と、`memo.outputAt` の更新を返す（台帳の attrs を書く既存イベントが無いため記憶で持つ）。`adapt` は run の `attrs.lastOutputAt`・`attrs.steeredAt` も読む。stall の steer は 5 分で 1 回、abort は 10 分。
- `Effect.spawn.workTool` は常に `false`。子に work ツールを渡さず、台帳へ書かせない。

## 限界

- stall の見張りは、配線が子の出力のたびに `onOutput` を呼ぶことが前提（未配線）。見込み（speculative）と競争（race）の 2 つ目の run は、台帳の門が task running の 2 つ目の予約を拒否する可能性があり、`rejected` に出る。
- `memo`（steer・abort・通知の重複防止）は呼び出し側が持ち回る（永続しない）。

## 配線の手順

1. `spawnChild` と `Jobs` を `Spawner` に包む。`spawn` は `SpawnSpec` から子を起動し `{runId, pid}` を返す。
2. 旗が立っているときだけ、完了通知ごと（と定期）に `tick` → `events` を `submit` → `effects` を実行 → `onSpawned`。子の終了で `onFinished` → `submit`。
3. 起動時に `reconcile` を 1 回呼ぶ。

試験: `test/agents/test_work_driver.py`（流れ・429・予算・writes・workTool・不変・性質試験 200 本）。

[仕様の索引へ戻る](../index.md)
