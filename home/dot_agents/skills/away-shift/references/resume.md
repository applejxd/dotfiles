# 再開・停止・期限の手段（pi の stock）

away-shift は離席時間いっぱい動くため、開始前に次ができると確かめる。1 つでも確かめられなければ、**開始せずに理由を利用者へ報告する**。

| 必要なこと | 手段 | 確認の方法 |
| --- | --- | --- |
| 子を起動する | `subagent`（`async: true`、`cwd` = worktree） | ツールが使える |
| 再開 | **子の完了通知**（親は自動で再開する） | 標準の動作（下の実測） |
| 停止 | `subagent({ action: "stop", id })` と `audit --kill` | 標準の動作（下の実測） |
| 復帰 | 利用者のメッセージが届いた時点で、サイクルを打ち切る | 手順 4（`SKILL.md`） |

## 再開: 子の完了通知（既定）

親は、子を `async: true` で起動して応答を終える。子が終わる（完了・失敗・停止・タイムアウト）と、拡張が通知を親に送り、**アイドルの親が自動で再開する**。
`sleep` も `bg_run` も要らない。通知には、子の最終報告の要約と、`Parent action`（結果を読んで再開するか、完了を報告する）が載る。

- 再開時に、親の文脈は残っている（同じ会話）。それでも、run_id と枝・worktree は `todo` に残す（圧縮に備える）。
- 起動できる子は同時に 4 つまで（`maxActiveAsyncRunsPerSession`）。away-shift は **worktree への書き手を 1 つにする**ので、1 つずつ起動する。
- 実測（2026-11-10、リハーサル）: 5 サイクルで、起動から完了通知まで 30〜45 秒。毎回、通知で親が再開した。

## 停止: `subagent stop` と `audit --kill`

```text
subagent({ action: "stop", id: "<子の id>" })
python3 ~/.agents/skills/away-shift/scripts/away_guard.py audit <run_id> --kill --write
```

- **`stop` は子を止めるが、子が実行中のサブプロセスは止めない**（実測）。`timeout 5m sleep 240` を実行中の子に `stop` を打つと、
  子は数秒で `stopped` になったが、`sleep` は残った（親が `init` に付け替わった孤児になる）。
  → **子のコマンドには `timeout` を付けさせる**（`brief-common.md` に書いてある）。止め損ねても `timeout` で終わる。
- `audit --kill` は、cwd が worktree の中にあるプロセスを止める（SIGTERM、2 秒待って SIGKILL）。ただし次は**止めない**（一覧に `[止めない: …]` で出す）。
  - **端末つきのプロセス**（利用者が worktree で動かしているシェル・コマンド）。子エージェントの配下には端末が無い（実測: 子の `sleep` は端末なし、pi の画面は `pts/0`）。
  - **run より前に起動したプロセス**。
- Linux 以外（`/proc` が無い環境）では、プロセスの確認を飛ばす。

## 期限: `checkpointBeforeDeadlineMs`

子の起動に `timeoutMs`（期限までの上限）と `checkpointBeforeDeadlineMs` を付けると、実行器が**期限の少し前に子へ割り込む**。
「チェックポイントして止まれ」という指示（steer）が、子の**次のツール境界**で届く。子は新しい作業を始めず、状況を書いて終わる。
値は `check` が出す（`CHILD_TIMEOUT_MS` は `min(30 分, 残り − 予備 15 分)`、`CHILD_CHECKPOINT_MS` は `min(3 分, その 1/3)`）。

- 割り込みは、実行中のツール呼び出しの中には届かない。**`CHILD_CHECKPOINT_MS` は、子の最長のコマンドより長く**する（`brief-common.md` は、コマンドに `timeout` を付けさせる）。
- 実測（2026-11-10）: `timeoutMs` 90 秒・`checkpointBeforeDeadlineMs` 45 秒で、15 秒のコマンドを繰り返す子を動かした。
  開始から 44 秒で割り込みが要求され、57 秒（13 秒後。実行中のコマンドが終わった境界）で子に届き、子は `checkpoint.md` を書いて 70 秒で**正常終了**（`complete`）した。ハードキル（90 秒）の前に終わった。
- 子が止まらなければ、`timeoutMs` で強制終了される（その場合も、子のサブプロセスは残る。`audit --kill` で掃除する）。

## 復帰

利用者のメッセージが届いたら、親は今のサイクルを打ち切る。実行中の子を `subagent stop` し、`audit --kill --write` を実行して、レポートを提示する。

## 手段 B: `/goal` の `goal_wait`（採らない。2026-11-10 に評価）

入れ済みの `pi-goal`（`/goal`）には、予約・再開の標準の仕組みがある。`goal_wait({ goal_id, reason, resume_after_ms })` は、
外部の待機を用意したあと、指定の時間で 1 回だけ自分を起こす。**採らない**。理由は次のとおり。

- **開始は利用者**。`/goal` はスラッシュコマンドで、エージェントからは起動できない。
- **「戻ったので止める」を表せない。** `goal_complete`・`goal_blocked` は、この用途に合わない。実測では、待機中の利用者のメッセージで待機が起き、`/goal` の続きを自動で始めた。
- **予算の数え方が読みにくい。** `--tokens 150k` は、数ターンの試験で尽きた（`158.4k/150k`）。
- 時間指定の自動の再開は未確認。

## 手段 C: `bg_run` の `sleep`（子を使わないときの待機。既定にしない）

`away_guard.py sleep <秒> --note "…"` を `bg_run` で起動すると、完了の通知で親が再開する（実測: 3〜120 秒、確認なし）。
子の完了通知が使える今は不要。子が長い処理（学習など）を投入して、結果が出るまで待つだけのサイクルを作りたいときの、待機の部品として残す。

## 子の確認（ask）

子の確認は、親の画面へ転送される（実測: 約 11 秒で承認され、続行した）。離席中は誰も答えず、5 分で拒否される（承認にならない）。
子の自己申告は当てにしない。拒否されたかどうかは、審査ログ（`~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl`）が正。

## 未確認

- 数時間規模の運転（子の完了通知による再開の連鎖）。
- 子 1 回あたりのトークン・費用と、親の文脈の伸び。
- Windows・macOS（`audit --kill` は Linux のみ）。
