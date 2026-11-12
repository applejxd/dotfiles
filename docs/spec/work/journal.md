# 作業の観測ログ（journal）

> **凍結した自作基盤の文書**（[ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md)。保存のみ・開発しない）。ここに出てくるコマンド・ツール（`guarded_task`・`/bypass`・`/pending`・`/orchestrate` など）は、stock の pi には**存在しない**。いまの stock の pi のコマンドは [早見](../pi-commands.md)。

作業台帳（`home/dot_config/pi/harness/work/types.ts`）のイベント形式 `LedgerEvent` の `aux: true`（観測用）の最初の実装。**観測だけで、振る舞いは変えない。**
並列度の律速を実測するための基準値を取る。

## 置き場と形式

- `<作業ツリー>/.tmp/work/journal/<session>.jsonl`（git 管理外）。1 行 1 JSON（`ts`・`seq`・`type`・`data`・`aux:true`）
- 追記のみ。fsync しない（観測用）。書けなくても例外を出さず、`lastError` に残す
- 秘密・本文は残さない。120 字を超える文字列は `<N chars>` に置き換える。ツールの入力・出力の本文は持たず、文字数だけ残す
- `PI_JOURNAL=0` で無効。子（`PI_HARNESS_CHILD`）では記録しない

## 事象

journal 自身が pi のイベントを購読する（`registerJournal`。`index.ts` の呼び出しは 1 行で、`activity`・`todo` など既存の拡張は変えない）。

| type | 元のイベント | 主な項目 |
| --- | --- | --- |
| `session.start` | `session_start` | reason |
| `tool.call` | `tool_execution_end` | tool・ms・isError・chars |
| `run.started` | `guarded_task` の起動 | role・background |
| `run.ended` | `child-finished` の通知 | id・role・state・ms・usd |
| `wait.opened/resolved` | `ui_prompt_*`（user）・ジョブ完了（job） | on・ref・ms |
| `settle` | `agent_before_settle` | outcome・continue・by |
| `notice` | 自動の通知（custom メッセージ・自動の再開） | kind・shown・folded・lines_shown・chars_shown・chars_to_model |
| `resource.429` | `after_provider_response` | status |
| `strategy` | （予約。記録器の `emit` から出す） | |

## 指標（`scripts/work_stats.py`）

M1 親の接触（`tool.call` ＋ 完了通知の起床）と run あたりの回数、M2 子の同時数（平均・最大）、M4 完了から次の起動までの遅延（p50・p90）、
利用者待ちの件数と時間、M5 見える自動メッセージの行数/日、M6 モデルの文脈に入った通知の文字数（p90）。

## 限界

- `settle` は先に走った handler の `entries`・`continue` だけ見える。`todo` が後に走ると `by` が空になる（`notice` の `todo-reminder` が正）
- `wait.opened(job/merge)` は未記録。`run.started` は起動の数と役割だけ（子の id は完了時にだけ分かる）
- 同時数は起動数と完了数の差。子の id で突き合わせていないので、完了通知の取りこぼしで多めに出る
