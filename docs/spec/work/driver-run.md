# ドライバの接着層（driver-run）

ドライバの純関数（[driver.md](driver.md)）を、pi の実際の子の起動に繋ぐ薄い層（`home/dot_config/pi/harness/work/driver-run.ts`）。

## 旗

`PI_WORK_SCHEDULER=1` のときだけ有効。既定は何も登録せず、何も起動しない。`PI_WORK=0` で一括無効。子（`PI_HARNESS_CHILD`）では動かさない。台帳の runtime が取れない間・driver モードでない runtime（読み取り専用・off・degraded）でも何もしない。

## 安全条件

1. 子の起動は注入された `spawnChild`（index.ts）の 1 本。argv・env・役割・書き込み範囲は既存のまま。新しい権限の経路は作らない。
2. 子に `work` ツールを渡さない。子では `registerWork` が登録されず（`child` で無効）、この層も `registerTool` を持たない。依頼文にも使えないと書く。
3. 判定器の確認・拒否は子の中で従来どおり効く（この層は判定の経路を変えない）。
4. 同時数は `min(aimd の上限, jobs.max - 他の子の数)`。
5. 予算: 使用量の増分を台帳へ入れ、見積りの 1.5 倍で steer、2 倍で abort（driver.ts）。

## Spawner の対応

| 操作 | 実体 |
| --- | --- |
| `spawn` | `spawnChild(role, ctx, owner, undefined, isolation==="worktree")` → `job.run(prompt)` |
| `steer` | `job.steer` |
| `abort` | `job.close(true)`（`session_shutdown` でも全ての子へ） |

ループ: 2 秒のタイマー・子の完了で `tick`。予約イベントが台帳に通らなければ子を起動しない。子の時間切れは 429 でなく失敗として返す。

## runtime の共有

`globalThis.__piWork = {runtime, holder}` を `registryRuntime` が読む。`register.ts` は未対応のため、置かれるまで何も起動しない。

## 限界

- 完了後の検査は `check` オプション（省略時は checking のまま。別の経路が `check.result` を入れる）。
- 実 pi・実際の子での確認は未実施。

戻し方: 旗を外す。

試験: `test/agents/test_work_driver_run.py`。

[仕様の索引へ戻る](../index.md)
