# 作業台帳 (work ledger) の核

追記専用のイベントログと、その畳み込み (reducer) で、ゴール・task・run の状態を導く純関数の群。pi の API にも fs にも依存しない。
配線（store・digest・sched・journal・index.ts）は別の feature。実装は `home/dot_config/pi/harness/work/`、試験は `test/agents/test_work_core.py`。

## 構成

| ファイル | 役割 |
| --- | --- |
| `types.ts` | 契約の型（`Node`・`LedgerEvent`・`Money`）。変えるときは依存する feature を同時に直す |
| `events.ts` | イベントのペイロード・検証・`makeEvent`（利用者専用イベントの出所を検査） |
| `transitions.ts` | 遷移表（goal・task・run の状態 × イベント × 変種）。未定義は `TransitionError` |
| `reduce.ts` | `reduce` / `fold` / `serialize`。入力を変更しない。前提を満たさないイベントは例外（拒否）で、状態を進めない |
| `invariants.ts` | `check(state, prev?)` が I1〜I10 の違反を返す |
| `project.ts` | 投影: `ready`・`waitingUser`・`nextDecision`・`budgetStatus`・`criticalPaths` |
| `globs.ts` | 書き込み集合の重なり判定（保守的。偽陰性 0） |

## 遷移の要約

- goal: draft → planned（`plan.proposed`）→ active（利用者の `plan.approved`）⇄ paused → done（verdict done が先）| cancelled
- task（check・integrate も同じ）: proposed → ready → running ⇄ waiting → checking → done。failed は retry で ready、block で blocked
- run: reserved → started → done | blocked | failed | limit | aborted | lost。task は run の終了状態で checking・blocked・failed へ
- 取り消し・skip・retry・block は `verdict` イベントの `verdict` 値で表す。取り消された task へ遅れて届く `run.ended` は許す

## 不変条件

| # | 内容 |
| --- | --- |
| I1 | `after` は非循環（任意の長さ・自己依存を含む）で、依存先が存在する |
| I2 | running には生きた run か開いた待ち、waiting には開いた待ち |
| I3 | 各階層で spent ≤ reserved ≤ budget、親 ≥ Σ 子、使用量は減らない |
| I4 | running・waiting・checking の task と integrate の `writes` は互いに素 |
| I5 | user 待ちは利用者だけが解く。他の待ちは同種の事実か利用者 |
| I6 | done の task には check の証拠。goal の done には verdict done と全 task の決着 |
| I7 | 注釈は追記のみ（300 字以内） |
| I8 | lease は goal だけが持ち、保持者でない追記は拒否 |
| I9 | seq に欠番も重複もない（受け入れて anomalies に残す） |
| I10 | 利用者専用（`plan.approved`・`budget.adjusted`・`goal.resumed`）は出所が user のときだけ |

## 設計上の判断

- `edge.added` の `{from, to}` は「from が to に依存する」。循環なら適用せず `rejections` に残す（`resolveEdge` で追記前に `edge.rejected` へ変換できる）
- `skipped` は依存を満たしたものとして扱う（`cancelled` は満たさない）
- 予算: `reserved` は「使用済み＋未使用の予約」。run の終了で未使用分を階層から戻す。予算を超える予約は reducer が拒否する。見積りを超えた使用は予約も同額増やし、超過は I3 が検出する
- 出所は `data.source`、lease の保持者は任意の `data.holder`（`types.ts` に専用欄が無いため）
- `run.ended` の二重配送は例外で拒否する。証拠の id（`check:<seq>`）に seq が入るので、合流性は seq を除いて成り立つ
- `globsMayOverlap` は「ディレクトリへの書き込みは配下に及ぶ」と「スラッシュ無しはどの階層にも合致」を保守側に取る（`*.ts` と `*.md` も重なる扱い）
- `ready` の順序: 臨界路の長さ（降順）→ bundle → 費用の昇順 → id。実行中の `writes` と重なる task は出さない
