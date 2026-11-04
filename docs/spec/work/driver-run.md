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
6. **起動前の判定（`canSpawn`）**: index.ts が `guarded_task` の `execute` と同じ条件（`decide("task")` が deny なら起動しない、ask なら**起動せず保留**＝自動承認しない、`/plan` が有効なら書き込みのある役割を拒否）で渡す。保留の task は ready のまま残り（予約を作らず失敗にも数えない）、次の tick で再評価する。保留があると、その回の tick 全体を見送る。
7. **役割・隔離は信頼した対応表で決める**（`planSpawn`。モデルの `attrs.role`・strategy の隔離は使わない。fail-closed）。
8. **セッション世代**: `session_start`・`session_shutdown` で世代を進め、`submit` の待ちの後・spawn の直前に停止・世代・runtime の一致を再確認する。外れていれば子を起動せず、予約を `aborted` の `run.ended` で取り消す。
9. scheduler 所有の子は一往復専用。終了時に必ず `close()` して枠を返す（隔離の job は `finalized` を待ってから）。
10. 起動するのは、利用者が承認した時点の task だけ（`Node.approved`）。承認の後にモデルが `work add` で足した task は起動しない（[台帳](ledger.md#設計上の判断)）。

### 起動制約

| task の種類 | 役割 | 隔離 | 備考 |
| --- | --- | --- | --- |
| 読み取り（`ro`・`writes` が空） | `explore`（読み取り専用） | なし | `writes` があれば属性の不整合で拒否 |
| 編集（`edit`・`writes` あり） | `worker` | **常に worktree**（strategy が none・shared でも引き上げ） | 隔離を作れなければ起動せず失敗（フォールバックしない）。`writes` が空なら拒否 |
| 検査（`check`） | 起動しない | - | 検査は harness が実行する別経路。理由つきで失敗 |
| 未知の `kind`・未知の隔離・台帳に無い task | 起動しない | - | 拒否 |

## Spawner の対応

| 操作 | 実体 |
| --- | --- |
| `spawn` | `canSpawn` → `spawnChild(planSpawn の役割, ctx, owner, undefined, planSpawn の隔離)` → `job.run(prompt)` |
| `steer` | `job.steer` |
| `abort` | `job.close(true)`（`session_shutdown` でも全ての子へ） |

ループ: 2 秒のタイマー・子の完了で `tick`。予約イベントが台帳に通らなければ子を起動しない。子の時間切れは 429 でなく失敗として返す。

## runtime の共有

`register.ts` が公開する `globalThis.__piWorkRuntime()`（runtime）と `__piWorkHolder()`（holder）を `registryRuntime` が読む（旧の登録簿 `__piWork = {runtime, holder}` も読む）。
台帳の runtime は `register.ts` が持つので、**スケジューラを使うには `PI_WORK_TOOL=1` も要る**（無ければ runtime が取れず何も起動しない）。

## 限界

- 完了後の検査は `check` オプション（省略時は checking のまま。別の経路が `check.result` を入れる）。
- 実 pi・実際の子での確認は未実施。
- 承認時の task の snapshot（承認後に `work add` された task の起動）と台帳の保護パスは別の feature。

戻し方: 旗を外す。

試験: `test/agents/test_work_driver_run.py`。

[仕様の索引へ戻る](../index.md)
