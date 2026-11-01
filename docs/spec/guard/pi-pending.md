# 保留（非同期承認）の仕様

確認が時間切れ・不在・UI なしで取れないとき、操作を**実行せず**、構造化した記録として保留する。利用者だけが、あとで `/pending approve` で実行する。
案件と経緯は [CHG-0055](../../change/0055-async-approval.md)、決定は [ADR-0023](../../adr/0023-pending-approval.md)。実装は `home/dot_config/pi/harness/pending-*.ts`・`integrate-*.ts`・`exclusive-lock.ts`・`native-action.ts`。

## 状態

- 実装済み・**本番では無効**（`[pi.pending] enabled = false`・`[pi.integrate] enabled = false`）。有効にするのは、実機の確認（CHG-0055 の P9 の出口条件）の後の、別の変更。
- 対応する操作は `git_integrate`（保護ブランチへの統合）だけ。`git_commit` は従来の退避（[pi の拡張](pi-extensions.md#guarded_action承認つきの外部操作)）のまま、gh は確認が取れなければ拒否のまま。
- 実機（TUI・Orca・Zed）・Windows は**未確認**。実際の pi の試験（RPC）では、TUI 専用の経路（承認の画面・時間切れの案内）を回せない。

## キルスイッチ

`[pi.pending] enabled` と `[pi.integrate] enabled` の**両方が true**のときだけ、`git_integrate` が見え、使える。どちらかが false の間は、ツールの説明・システムプロンプト・拒否の理由・承認の対応表に何も足さず、従来と同一（試験: `test_pi_integrate_index.py`）。
`[pi.pending] modes`（既定 `["tui"]`）に含まれない実行モードでは保存しない。

## 流れ

1. **要求**: モデルが `guarded_action` の `git_integrate`（`source`・`message`・任意の `cleanup`）を呼ぶ。**保存専用**: 確認画面を出さず、実行もしない。前提（統合元・統合先の OID、結果の tree、マージベース、メッセージの digest）を取り、`refs/pi/pending/<id>` に保存し、必ず `not approved:` で始まる結果を返す。検査の順は、子 → 無効 → 実行モード → 未対応 → 中断 → 前提の取得 → 保存。同じ要求は重複して保存しない。
2. **承認**: 利用者が、**統合先の worktree（本体）で起動した pi の TUI で** `/pending approve` を実行する。feature 側の pi は保存だけで、承認も実行もしない。モデルの実行中（`ctx.isIdle()` が偽）は断る。
3. 記録を読む → **`authorize`**（いまの役割・操作の定義で再判定。子・action ツールの無い役割・未登録の操作・不正な引数は断る。保留の記録は信頼しない入力）→ アダプターが、現在の設定・実行先で**実行計画**を作る → 画面に表示（期限なし）→ 承認（保留 ref の CAS）→ 再検査 → 開始を記録 → 実行 → 結果を記録 → 通知。
4. **通知**: BEL・フッター・モデルへの固定テンプレートのメッセージ。記録の自由な文を指示として流さない。通知は正本ではなく、失っても `/pending list` で確認できる。

## コマンド（利用者専用。モデルは呼べない）

`/pending [list | show [<id>] | approve [<id>] | resolve [<id>] [<結果>] | drop [<id>] | unlock | log]`

| サブコマンド | 内容 |
| --- | --- |
| `list` | 保留・実行中・結果の一覧（新しい順）。ロックを持っていれば 1 行で出す |
| `show` | 詳細（旧形式の退避も） |
| `approve` | 承認して実行（TUI のみ） |
| `resolve` | 実行者が生きているかもしれない試行の決着（`success`・`failed`・`retry`・`pending`・`abandon`）。排他の操作の started は、停止を確かめたかを聞く |
| `drop` | 保留の破棄（確認つき。1 件でも確認する） |
| `unlock` | 孤児になったロックを外す（確認つき・TUI のみ） |
| `log` | 結果の履歴 |

**ID を打たせない**（スマホの端末でも使えるように）:

- `<id>` を省くと、その種類の候補から**選ぶ**。候補が 1 件なら `approve`・`show` は選びを飛ばす（`drop`・`resolve` は 1 件でも確認する）。
- 一覧の 1 行は、ID を出さず `操作名 経過 要約`（44 セル以内）。同じ表示が並ぶときだけ、末尾 4 桁を添える。
- **末尾一致**: 数字だけで 15 桁未満・3 桁以上（例 `approve 4708`）は、その種類の候補の ID の末尾に一致するものを探す。複数なら選ぶ（TUI でなければ断る）、無ければ「見つからない」。15 桁の ID と `refs/` の指定は従来どおり。
- Tab 補完は、サブコマンドと ID。選ぶのは ID を決めるだけで、承認・破棄・決着の検査は、同じ経路を通る。

## 状態と ref

| ref | 意味 |
| --- | --- |
| `refs/pi/pending/<id>` | 保留の記録（要求） |
| `refs/pi/running/<id>` | 実行中の試行（`reserved` → `started`。実行者の owner を持つ） |
| `refs/pi/done/<id>` | 結果。`not_executed`・`success`・`failed_confirmed`・`unknown` |
| `refs/pi/lock/<key>` | 排他ロック（common-dir 単位で 1 本。`<key>` は common-dir の sha256） |

保持の既定は、保留 30 日・結果 90 日。上限（件数・読む量・時間）を超えたら、保存せず断る。期限切れの掃除と復旧は、無効でも `session_start` で動く。

## 実行の安全

- **排他ロック**は、実行の間だけ持つ。取得できなければ（別の実行・孤児・読めない）、保留へ戻す。自動で回復するのは、検証できた同一の試行が `reserved` で、owner が `gone` のときだけ。`started` は自動で回復しない（`/pending resolve` で、停止を確かめたと答える）。
- 実行器は、hook が動く git を専用のプロセスグループで起動し、中断・時間切れでは**停止を確認してから**結果の確認と rollback を行う。停止を確認できないとき（排他の操作の例外・不正な結果・旧形式の `unknown` も同じ）は、**結果を書かず、running とロックを残し**、モデルには「再実行しない」の固定文だけを返す。自動で `reset` しない。
- 統合は、統合先の worktree の中でだけ実行する。`runsHere` は `git rev-parse` の common-dir・git-dir・show-toplevel の一致で判定し、観測できなければ「中ではない」。統合の前に、統合先・統合元の OID と結果の tree が、承認した計画と一致することを再検査する。
- 結果の facts（`source_oid`・`target_oid_before`・`result_commit`・`result_tree`・`cleanup` など）を記録する。結果コミットは、commit の成立を確かめた後だけ。
- 統合の成功は、commit の親が計画どおりであることに加えて、**統合先 ref（`plan.target.ref`）が結果コミットを指している**ことを確かめてから記録する。一致しない・読めないときは `unknown`（cleanup に進まず、自動で `reset` もしない）。feature ブランチの削除は `update-ref --no-deref -d`（実行の途中で別ブランチへの symbolic ref に差し替わっても、参照先を消さない）。
- **外部のコードを、承認の前に動かさない**: hook・fsmonitor・外部 diff を止め、外部 merge driver と、`filter.<名前>.clean|smudge|process` が設定されたリポジトリは、算出と実行の前に断る（初版の対象外。Git LFS などを使うリポジトリは保留に保存できない）。実測で、filter は `merge.renormalize` の有無にかかわらず、算出の途中で起動していた。
- **停止確認の要否は、アダプター表が空でも失われない**: 排他かどうかは、アダプターが見つからない（キルスイッチを切って再起動した後など）ときも、排他として扱う（`--confirm-stopped` を求める側へ倒す）。承認の画面の後、実行の前に、`authorize` をもう一度呼ぶ（画面は期限なしで、眺める間に役割・設定が変わりうる）。

## モデルから見える面

- `guarded_action` の操作一覧に `git_integrate`（有効なときだけ）。bash の説明に、「統合は `git_integrate` を優先する。bash の `git flow feature finish` は即時の承認が要り、時間切れになりうる」の 1 文（有効なときだけ）。
- 統合の必須確認が**時間切れ**で拒否されたとき、TUI で、子でなく、action ツールがある役割のときだけ、「再試行せず `git_integrate` で保存できる」の案内を足す。判定・確認・拒否は変えない。
- 保存の結果は「元の操作は未実行。保留 `<id>` に保存した。再試行しない。…利用者が統合先の worktree で `/pending approve` を実行し、一覧から選ぶと実行される」。

## 保証の範囲

ガードは境界ではなく「うっかり防止」。保証するのは、**ガードが識別する直接経路**（`guarded_action` と bash の `git flow`・`git merge` など）だけ。Python・node の内部、alias、利用者のシェルは対象外。`refs/pi/` を書く git コマンドは必須確認（P6）。

## 試験

| 対象 | 試験 |
| --- | --- |
| 保存層・状態遷移 | `test_pi_pending_ops.py` |
| 承認・実行・排他・復旧 | `test_pi_pending_approve.py`、`test_pi_approve_core.py`、`test_pi_exclusive_lock.py` |
| `/pending` の選択・補完 | `test_pi_pending_command.py`、`test_pi_pending_pick.py` |
| 統合の計画・実行器・アダプター | `test_pi_integrate_plan.py`、`test_pi_integrate_exec.py`、`test_pi_integrate_action.py` |
| 保存専用の操作 | `test_pi_pending_request.py`、`test_pi_native_action.py` |
| 配線・キルスイッチ（実際の pi） | `test_pi_integrate_wiring.py`、`test_pi_integrate_index.py` |
| 時間切れの案内・bash の説明 | `test_pi_integration_gate.py`、`test_pi_tools_ext.py` |
