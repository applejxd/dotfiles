# `/goal` と作業台帳

`/goal` の状態の唯一の出所は台帳の `goal.*` イベントの fold。`goal-core.ts` の `GoalState` はそこから**導出**する（写しを 2 つにしない）。
実装は `home/dot_config/pi/harness/work/goal.ts`（純関数。pi の API・fs・index.ts なし。配線は別の feature）。試験は `test/agents/test_work_goal.py`。
関連: [台帳](ledger.md)・[調停](arbiter.md)。

## コマンド → イベント（出所は常に `user`）

| コマンド | イベント | 備考 |
| --- | --- | --- |
| `<目標>` | `goal.created` → `plan.proposed` → `plan.approved` | 予算は必須で有限（既定 20 回・90 分）。目標があれば拒否 |
| `pause` | `goal.paused` | 停止中は何もしない |
| `resume` | `goal.resumed` | 実行中は何もしない |
| `budget` | `budget.adjusted` | 指定した軸だけ上書き。範囲検査は `goal-core.ts` の `setBudget` |
| `clear` | `verdict`（cancel） | 目標なしは何もしない |
| `status` / `draft` / error | なし | `text`・`draft`・`parseGoalArgs` の error をそのまま返す |

## 導出（`goalStateOf`）

- 最後の goal が `active`・`paused`・`done` のときだけ `GoalState` を返す。目標なし・draft・planned・cancelled は null。
- 予算は node の `budget`（Money に `rounds` を足す。`ms` = 分 × 60000。トークン無制限は `UNLIMITED` = 有限の大きな値で表す）。
- `lifetime.resumes` は `attrs.resumes`。`used`・`counters`・停止の理由などは台帳に無いので、`GoalRuntime` を重ねて渡す（省略は 0・`user`）。

## 守る条件

- モデル・system 出所は `plan.approved`・`budget.adjusted`・`goal.resumed` を作れず、reducer も拒否する。モデルだけでは目標を active にできない。
- `goalCommandToEvents` は `{kind: "approve"}` も受ける（`/goal` の引数解析には載せず、配線が直接渡す）。計画の承認前は従来どおり `plan.approved`。active・paused は、承認後に足した未承認の task（`pendingApproval`）があるときだけ再承認の `plan.approved` と、承認の対象（title 最大 10 件と総件数）を `approval` で返す。対象が無ければ失敗。
- 予算は常に有限（範囲外・0・無限は拒否）。変換は入力を変更せず決定的。
- 差分試験: 乱数のコマンド列で、`goal-core.ts` 直接と、変換 → `reduce` → 導出の `GoalState` が一致する（`updatedAt` を除く）。

## 限界と解消した食い違い

- `updatedAt` は台帳に無い（`createdAt` か `rt.updatedAt`）。
- 解消: 停止の理由は `goal.paused` の `reason` を goal ノードの `pauseReason` に保存し、`goalStateOf` が読む（`rt.pause` があればそれが優先）。
- 解消: `clear` の `verdict` cancel は、reducer が出所 user でなければ拒否する（I10 の拡張。task の cancel はモデルでも通る）。
- 解消: 予算の `rounds` は `Money` の任意の項目になった（`budget` の往復で落ちない）。
- 目標の id は時刻由来。同じ時刻の目標は重複で拒否する。
