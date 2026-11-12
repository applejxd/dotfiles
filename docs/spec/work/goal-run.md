# `/goal` の pi への配線 (goal-run)

> **凍結した自作基盤の文書**（[ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md)。保存のみ・開発しない）。ここに出てくるコマンド・ツール（`guarded_task`・`/bypass`・`/pending`・`/orchestrate` など）は、stock の pi には**存在しない**。いまの stock の pi のコマンドは [早見](../pi-commands.md)。

`work/goal-run.ts` の `registerGoal(pi, opts)` が、台帳の上の `/goal`（[goal.md](goal.md)）を pi に登録する接着層。
変換・導出は `goal.ts`、引数の解析と予算の検査は `goal-core.ts` の純関数に任せ、ここは pi の API へ繋ぐだけ。`index.ts` は `registerWork` の次で 1 回呼ぶ。

## 旗

- **既定は無効**（何も登録しない）。`PI_WORK_GOAL=1` のときだけ有効。`PI_WORK=0` で一括無効。子（`PI_HARNESS_CHILD`）では登録しない。
- 戻し方: `PI_WORK_GOAL` を外す（コードは残るが何も起きない）。

## 登録するもの

- コマンド `/goal <引数>`: `parseGoalArgs` → `goalCommandToEvents` → `runtime.submit`（出所は常に user）。status・draft は通知で表示。エラー・読み取り専用は理由つきで拒否。
  目標があるときの新しい `/goal <目標>` は拒否（goal.md の `set` と同じ）。予算は既定 20 回・90 分の有限値で、0・無限・範囲外は解析で拒否。
- `/goal approve`: 計画（モデルのツール `work` の `plan` が提案したもの）を利用者が承認する。UI があれば確認画面（`ctx.ui.confirm`）を出し、承認したときだけ `plan.approved` を user 出所で出す。承認前は task が走らない。モデルは提案だけで承認・再開・予算変更・目標の破棄はできない（I10）。
- `/goal approve`（active・paused の goal）: 承認後にモデルが `work add` で足した task（`approved` なし）が 1 件以上あるときだけ通り、再承認の `plan.approved` を出す（goal の状態は変えない）。確認画面（題「task の再承認」）に、未承認の task の title（最大 10 件・幅を切る）と総件数を出す。対象が 0 件なら「承認待ちの計画はありません」で拒否する。**確認画面の対象と承認の集合は結び付ける**: 承認イベントに確認画面へ出した未承認 task の ID 集合（`approvalIds`）を含め、reducer が適用時点の集合と照合して、増減していれば拒否する（確認の間に `work add` された task は承認されず、「確認後に対象が変わりました。もう一度 `/goal approve` してください」と通知する）。画面の題は 伏字化（`registerGoal` の `redact`。既定は最小の形、index.ts が `redactText` を渡す）→ `sanitizeUntrusted` → 一行化 → 幅の切り詰めで安全にし、task の ID を併記する。`work` の `add` の注記が案内する経路はこれ。変換は純関数 `goalCommandToEvents({kind:"approve"})`（[goal.md](goal.md)）。
- `input` イベント: 拡張以外の通常入力（`/goal` 自体を除く）で、実行中の目標を system 出所の `goal.paused` で一時停止する（理由は `input`。`goal-core` の `PauseReason` に合わせた）。
- `globalThis.__piGoalSnapshot()`: settle への goal の事実（`settleFactsOfGoal`）。台帳が使えない・目標が無い・計画の承認前・形が不完全なときは `undefined`（提案しない）。

## runtime の共有

`PI_WORK_TOOL=1` のとき、`register.ts` が `globalThis.__piWorkRuntime`（現在の runtime を返す関数）を公開し、goal-run はそれを使う（同じ台帳・同じ lease）。無効なときは goal-run が自分で runtime を開閉する。

## 限界

- 評価役 `goal-eval.ts` は呼ばない（注入点 `evalFn` を持つだけ。別 feature）。claim・counters・使用量は台帳に無いので、事実は claim=false・停滞なしで返す。
- `settle-snapshot.ts` の `buildSnapshot` はまだ `__piGoalSnapshot` を読まない（goal は常に inactive）。取り込みは別 feature。
- 実 pi での確認は未実施（偽の pi・偽の ctx と実の runtime の試験のみ）。
