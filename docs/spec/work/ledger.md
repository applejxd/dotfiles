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

- goal: draft → planned（`plan.proposed`）→ active（利用者の `plan.approved`）⇄ paused → done（verdict done が先）| cancelled。active・paused の `plan.approved` は状態を変えない再承認（下記）
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
- 出所と lease の保持者は `LedgerEvent` の専用欄 `source`・`holder`（任意）。`makeEvent` が引数から設定し、`data` の中の `source`・`holder` は捨てる（lease.* のペイロードの `holder` は除く）。`source` 欄が無いイベントは system 扱い（利用者専用は拒否）。I8 は `holder` 欄で検査する
- `run.ended` の二重配送は例外で拒否する。証拠の id（`check:<seq>`）に seq が入るので、合流性は seq を除いて成り立つ
- `globsMayOverlap` は「ディレクトリへの書き込みは配下に及ぶ」と「スラッシュ無しはどの階層にも合致」を保守側に取る（`*.ts` と `*.md` も重なる扱い）
- `ready` の順序: 臨界路の長さ（降順）→ bundle → 費用の昇順 → id。実行中の `writes` と重なる task は出さない
- I10 の拡張: 対象が goal ノードの `verdict` cancel（`/goal clear`）は、出所が user でなければ reducer が拒否する（対象の種類を知るのは reducer）。task の cancel はモデルでも通る
- `goal.paused` の `reason` は goal ノードの `pauseReason` に保存し、`goal.resumed` で消す（`goalStateOf` の停止理由はここから導く）
- `Money` に任意の `rounds`（goal の予算の往復数）を足した。reducer は budget を丸ごと写し、予約・使用量の合算（`MONEY_KEYS`）には使わない。負の値は拒否
- 承認の時点の task だけが自動起動の対象: `Node.approved`（任意）を `plan.approved`（利用者専用）の reducer が、その goal 配下の非終端の task へ立てる。承認の後に `work add` で足した task は持たない（遷移表の初期状態は従来どおり ready）
- `approved` の有無を見るのはスケジューラの選別（`adapt.ts` の `schedStateOf`・`readyOf`）だけ。表示用の `project.ready` と、モデルが `work set` で自分で進める操作は変えない
- 再承認: active・paused の goal も利用者の `plan.approved` を受ける（goal の状態は変わらない自己遷移）。reducer が、その時点の非終端の task すべてに `approved` を立てる。承認の対象（`approved` の無い非終端の task）が 0 件なら拒否する（空の承認を作らない）。モデル出所は従来どおり拒否（I10）
- 経路は `/goal approve`（利用者の確認画面が、承認の対象の title〔最大 10 件〕と総件数を出す）。承認の前なら計画へ入れるか、モデル自身が `set` で進めるのも従来どおり
- 再承認の hash は goal の `planHash`（承認の時点の計画）を使う。`plan.proposed` は active では受けないまま

## 接続と統合試験

- 台帳 → スケジューラ・digest の接続は `work/adapt.ts`（`schedStateOf`・`digestInputOf`。純関数）。台帳の `ready` と同じく active な goal の task・run だけを渡す
- 端から端の試験は `test_work_e2e.py`（store で永続 → 読み直して fold → メモリの fold と一致、kill -9 後の再生、sched・digest への接続、利用者専用イベントの偽装）
- `globsMayOverlap` の実装は `globs.ts` に一本化した。`overlap.ts` も `globs.ts` の既定（保守的・gitignore 流）で呼ぶ（`strict` は撤去）
- 食い違い 2 件は解消した（`xfail` を外した）: ①スラッシュ無しの glob（`*.py`）は sched も台帳の門と同じ判定で「重なる」とし、台帳が拒否するものを start しない ②`ready` は任意の `estimateMs` 見積りを受け、`adapt.readyOf` が sched と同じ見積り（`attrs.estimateMs`、無ければ役割×大きさの p50）を渡す。順序の一致は `test_work_e2e.py` が固定する
- `adapt` は run の `attrs.est`（起動時の見積り）を `SchedRun.reserve` に使い、`attrs.lastOutputAt`・`attrs.steeredAt` も読む（超過後も 1.5 倍の steer・2 倍の abort が出る）。`wake_parent` の理由は `all_done`（失敗なしの全終端）・`failed`（失敗を含む全終端）・`awaiting_approval`（未承認の task が残る）・`stuck` に分けた。arbiter など理由を読む側は無い（`proposeChildren` は理由を見ない）。
