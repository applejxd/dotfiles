# 子エージェント（guarded_task）の仕様に添えていた経緯・日付・試験結果

> `docs/spec/guard/pi-subagents.md#子エージェント` から移した記録。移設時点で再測定していない。

## 記録 — 観測日は各文に記載（移設 2026-10-26）

- **対象バージョン**: 各文に記載（pi 1.3.0 前後）
- **環境**: 各文に記載

### 問い

子エージェントの階層・`review` の役・結果の保持について、どの時点で何を確かめて決めたか。

### 根拠

[CHG-0029](../../change/0029-worktree-isolation.md)・[pi-bg-experiments](pi-bg-experiments.md)。元の文のとおり。

### 結果（元の文）

- `explore` に `tier` を付けていないのは、**確認した上での現状**（2026-10-09）。`tier` が無いと生成される `model` が
`null` になり、フルガードは親の現在のモデル（`ctx.model`）で子を起動する（`index.ts` の `agent.model ??`）。
親が `default` のままなら Copilot は `claude-sonnet-5.5`、Bedrock は `us.anthropic.claude-sonnet-5-5` で、
`/model` で親を変えると `explore` も追従する。

- `routine` にする案: 読むだけの探索なので軽くてよいが、今の Copilot は `routine` も `default` も
  `claude-sonnet-5.5` で差が出ない。差が出るのは Bedrock の `#low` だけ。**今は変えない**
- 未確認: 子へ `settings.json` の `defaultThinkingLevel`（今は `medium`）が実際に効いているか

- review の節の bullet: 「`review` を `explorer` 役にしたのは、差分を親が貼らずに済ませるため（2026-10-21、利用者の判断）。以前は `reader` で `git` を使えず、差分を依頼文へ入れる必要があった」
- 結果の保持と通知の見出しの bullet: 「試験は `test_finished_result_can_be_read_with_status_until_the_job_is_closed` / `test_background_notification_has_sequence_and_times_and_the_result_is_saved`（親が実行して通った。2026-10-22）」
- ToDo の行: 「試験は `test_task_requires_todo_*` ほか（未実行）」（移設時点の spec の表現。実行結果は未確認）
- **worktree 隔離は実装済み**: `guarded_task` の `isolation: "worktree"`（opt-in。単独の新規 `worker` のみ）。仕様は [CHG-0029](../../change/0029-worktree-isolation.md)。S5（実機の通し確認）の後に、この文書へ移す
- Windows の子エージェントの bullet: 「…`gpt-6-astra` は pi の Copilot 経由で `model_not_supported`（2026-10 実測）なので、`[pi.model.tier.github-copilot]` で上書きする」

### 考察

現在の仕様は ../../spec/guard/pi-guard.md の該当節。ここの数値・日付は観測時点のもので、再測定していない。
