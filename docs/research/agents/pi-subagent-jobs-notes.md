# pi の子エージェント job の結果の保持と通知の仕様メモ

> `docs/spec/guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo` から移した記録。移設時点で再測定していない。

## 記録 — 観測日は各文に記載（移設 2026-10-26）

- **対象バージョン**: 各文に記載（pi 1.3.0 前後）
- **環境**: 各文に記載

### 問い

完了した job の結果の保持（`FINISHED_TTL_MS`）・通知・保存ファイル・`audit.ts` の確認は、実装上どう動くか。

### 根拠

`home/dot_config/pi/harness/`（`children.ts`・`audit.ts`）、`test/agents/` の試験名は元の文のとおり。

### 結果（元の文）

- **結果の保持と通知の見出し**: 完了した往復の結果（redact 済みの全文）は、30 分・最大 20 件（`FINISHED_TTL_MS`・`MAX_FINISHED`）だけ親のプロセス内に残し、`{jobId, status: true}` で引ける（`keep` なしで自動で消えた子も対象。引くときの切り詰めは 2 万字で、切ったことを示す）。`close` した job の分は消える。
  バックグラウンドの完了通知（`child-finished`）の見出しには `(#通番 起動 HH:MM:SS / 完了 HH:MM:SS)` を足す（通番は pi セッション内で 1 から）。結果の全文は cwd 基準の `.tmp/subagents/<通番>-<job id>.md` にも書き、通知の末尾に `結果の全文: <パス>` を 1 行で示す。
  保存先の `.tmp/subagents` がシンボリックリンクなら書かず、ファイルは排他的に作る（既存なら書かずに警告）。保存のたびに、`.tmp/subagents` の `*.md` を新しい順に 50 件だけ残し、更新時刻が 7 日より古いものを消す（失敗は警告しない）。`close` した job の結果は、往復の完了が遅れて届いても再び登録しない。生きた job が無いときの `close` は、保持結果の cwd と役割が同じときだけ消し、違うときは「存在しない」と同じ応答にする。batch の見出しに載せる依頼文の先頭は伏字化してから切り、保存ファイルは各子の全文を 2 万字まで書く。警告文に入れる例外の message も伏字化する。
   完了した往復の結果には、答えがあるとき、job 行の前に `- calls: <ツール名×件数>` の 1 行（事実。`guarded_` を除き、多い順）を足す。ツール名だけを数え、引数と出力は残さない（上限 500 件）。答えに標準形の見出し（結論・根拠・未確認・次の候補）が欠けていれば、tool errors の警告の後に `format check (...)` と `- missing: ...` を足す。見出しは行頭の記号を無視した前方一致で見る。警告にとどめ、結果の本文は変えず、拒否もしない。「通った」などの主張語の検出は、実例のほとんどが否定・引用・仮定で誤検出が多いため入れない（`audit.ts`）。
  既知の限界: セッションをまたいだ参照の境界は cwd と役割までで、セッション識別子は無い。
  保存・通知の配信・ToDo 反映の失敗は握りつぶさず、UI があれば `ctx.ui.notify`、無ければ stderr に警告する（通知は止めない）。試験は `test_finished_result_can_be_read_with_status_until_the_job_is_closed` / `test_background_notification_has_sequence_and_times_and_the_result_is_saved`

### 解釈・次の候補

現行の仕様（何が保持され、いつ消え、何が通知されるか）は [pi-subagents.md](../../spec/guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) に要点だけ残してある。
