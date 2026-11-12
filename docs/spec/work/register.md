# 作業台帳の pi への登録 (register)

> **凍結した自作基盤の文書**（[ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md)。保存のみ・開発しない）。ここに出てくるコマンド・ツール（`guarded_task`・`/bypass`・`/pending`・`/orchestrate` など）は、stock の pi には**存在しない**。いまの stock の pi のコマンドは [早見](../pi-commands.md)。

`work/register.ts` の `registerWork(pi, opts)` が、台帳のツール `work`・コマンド `/work`・パネルを pi に登録する最小の配線。
`index.ts` は `registerJournal` の次で 1 回呼ぶだけ。判定の経路・権限・他の登録には触れない。

## 旗

- **既定は無効**（何も登録しない）。`PI_WORK_TOOL=1` のときだけ有効。
- `PI_WORK=0` で一括無効。子（`PI_HARNESS_CHILD`）では登録しない（子は台帳に書かない）。
- 戻し方: `PI_WORK_TOOL` を外す（登録コードは残るが何も起きない）。

## 登録するもの

- `session_start`: runtime を開く（`createRuntime` → `start`）。holder は `<pid>:<sessionId>`。
- ツール `work`: 引数は `WORK_TOOL_SCHEMA`。`handleWork` → `ok` なら `submit`。`submit` が失敗したときは、永続済みのイベント数 (`applied`) で分ける。
  0 件なら「拒否: 状態は変わっていない」。1 件以上なら「失敗: 一部は記録済み。`list` で現在の状態を確認」を返し、
  `details` に `partial: true` と `applied` (件数と種別だけ。本文・秘密は入れない)。runtime はイベントを1件ずつ永続し、成功分を反映してから失敗を返すため。
- `/work`: 台帳の一覧（`list` 相当）を通知で表示する。読み取り専用なら注記を付ける。
- パネル: 変化のたびに `renderPanel`（5 行以内）をウィジェット `work` へ。UI が無い ctx では出さない。
- 通知: runtime の警告は `notices.select("run.warning")` を通し、silent なら出さない。
- `session_shutdown`: `close()`（lease を解放）とパネルの消去。
- 観測: `<cwd>/.tmp/work/journal/<session>-work.jsonl` に `tool.call`（op と ok だけ。本文なし）と `session.start`。

## べき等・読み取り専用

- new / fork / resume で `session_start` が複数回来ても、同じ cwd と session の runtime は 1 つだけ（`opening` を共有）。session が変われば閉じて開き直す。
- 読み取り専用・縮退・off では台帳のイベントを追記せず、理由（別の会話が駆動中など）を text で返す。`list` は読み取れる。
  観測ログ（journal）は別で、読み取り専用でも `.tmp/work/journal/` に追記する。

## 限界

- 権限の表（役割のツール一覧・判定器の許可）は別の feature。この feature では `work` を許可しない。
- goal の `/goal` コマンド・arbiter・sched の配線は含まない。`todo` 拡張とは独立（併用できる）。
- 実 pi での登録・実 TUI の表示は未確認（偽の pi と実の runtime で試験済み）。
- 引数の検査は `handleWork` が持つ（spawn・承認・予算変更は拒否される）。

試験: `test/agents/test_work_register.py`。
