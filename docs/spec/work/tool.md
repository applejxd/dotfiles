# モデル向けツール `work` の純関数 (work-tool-core)

既存ツール `todo` の置換。実装は `home/dot_config/pi/harness/work/tool.ts`（純関数。pi の API・fs・`index.ts` への登録は含まない。登録は別 feature・旗 `work_tool` 既定偽）。
`handleWork(state, args, {now, holder}) → {ok, events, text, details}`。入力の state は変えず、events は reducer を通った有効なものだけ（操作は全部成功か全部なし）。試験は `test/agents/test_work_tool.py`。

## op

| op | 引数 | 台帳のイベント |
| --- | --- | --- |
| add | `title, kind?, parent?, writes?, deps?, wait?` | `node.added`（goal が無ければ `goal.created` も）。`wait` は手動の run を開始して `wait.opened` |
| set | `id, status?, deps?`（どちらか必須） | status: `pending`=retry・`in_progress`=手動 run の開始・`blocked`/`done`=run 終了（done は `check.result` pass）・`cancelled`=cancel。deps=`edge.added` |
| note | `id, text`（300 字以内＝台帳の上限） | `note.appended`（by=llm。追記のみ） |
| list | `filter?` | なし。ready・running・waiting・done の件数と各最大 10 件 |
| plan | `goal, tasks[{title,kind?,writes?,deps?:番号}]` | `goal.created`・`node.added`・`plan.proposed`（提案だけ） |
| cancel | `id, reason` | 走る run を中止して `verdict` cancel（goal は取り消せない） |

## 守る条件

- `spawn`・承認・予算変更・resume の op は無い（未知の op は拒否。出所は常に `model`。I10）。
- 遷移・依存の循環（自己・任意の長さ）・未承認の計画の開始は reducer が拒否し、`ok:false` と理由を返す。
- 引数は厳格に検査する（余計なキー・型違い・title 200 字・id の形式・制御文字）。
- `text` は 1,500 字まで（超過は「…（全文は /work）」）。title・状態・id だけで、note の本文は `text` にも `details` にも出さない。

## todo との対応

| todo | work |
| --- | --- |
| add | add |
| set status（pending / in_progress / done） | set |
| list | list |
| clear | cancel（task ごと） |

## 限界

- 承認前の計画（proposed）の task は開始できない。`add` は生きた goal（active を優先）へ入り、無ければ draft の goal を作る（承認は利用者）。
- `holder` は、台帳の lease の保持者と一致するときだけイベントへ記す（それ以外は store が付ける）。
- 配線（`index.ts`・役割ごとのツール一覧・判定器・golden）は未実装。
