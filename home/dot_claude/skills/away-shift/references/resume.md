# 再開・停止・復帰の手段

away-shift は離席時間いっぱい動くため、開始前に次の 3 つができると確認する。
1 つでも確認できなければ、**開始せずに理由をユーザへ報告する**。

| 必要なこと | 内容 |
| --- | --- |
| 再開 | サイクルの終わりに、`NEXT_WAKE_SECONDS` 後に自分を起こす予約をできる |
| 停止 | 停止条件に当たったとき、予約を取り消せる |
| 復帰 | ユーザのメッセージが届いた時点で、サイクルを打ち切れる |

## CLI ごとの手段

| CLI | 再開・停止の手段 | 状態 |
| --- | --- | --- |
| Copilot CLI | `manage_schedule`（`wakeup` / `create` / `stop`） | 未確認（このリポジトリで実測していない） |
| OpenCode v2 | 不明 | 未確認 |
| Claude Code | 不明 | 未確認 |

どの CLI で使えるかは実測が無いので断定しない。ツール一覧に予約・取り消しに
相当するものが見つからなければ「手段なし」として開始しない。
実測したら、この表を更新する。

## `manage_schedule` を使える場合

`check` が出した `NEXT_WAKE_SECONDS` を `delaySeconds` に渡す。

```text
manage_schedule(action="wakeup", id=<自己ペースループの id>,
                delaySeconds=<NEXT_WAKE_SECONDS>,
                reason="away-shift <run-id> cycle <N+1>")
```

自己ペースループとして起動されていない場合は、最初のサイクルで
`manage_schedule(action="create", interval="<NEXT_WAKE_SECONDS>s", prompt=...)`
を作る。prompt には **run_id と「SKILL の手順 3 から再開する」旨**を書く。

停止・復帰では `manage_schedule(action="stop", id=...)` を呼ぶ。

## サブエージェント

サブエージェントを起動する道具の名前も CLI ごとに違う。この skill の本文は
特定のツール名を前提にしない。使えるものを確認し、無ければ使わない。
