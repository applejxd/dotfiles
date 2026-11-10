# 作業台帳の実行時 (runtime)

1 つの会話が台帳を開いて持ち続ける接着層（`harness/work/runtime.ts`）。pi の API には依存しない（登録は別の feature）。
部品は [store](store.md)（永続・lease）・[ledger](ledger.md)（reduce・不変条件）。

## モード

| mode | 意味 |
| --- | --- |
| `driver` | lease を持ち、書ける。heartbeat を 30 秒ごと（`timers` を注入可） |
| `readonly` | lease が取れない・引き継がれた・台帳の再生や不変条件に失敗。読むだけ（`readonlyReason`） |
| `degraded` | 書き込み失敗（ENOSPC など）・台帳の破損。書かない。`onAlert` |
| `off` | `PI_WORK=0`・子（`PI_HARNESS_CHILD`）・旗 `enabled:false`。fs に一切触れない |

## 順序

- `start`: 置き場の解決（`resolveStoreRoot`）→ `createStore` → **lease を先に取り、その後に `load`**（torn tail の切り詰めや隔離は書き手だけが行う）→ `fold` → 不変条件 `check`。違反は読み取り専用に降格して lease を返す。
- 取れたら、生きた goal ごとに `lease.acquired`（出所 system）を最初に追記する。前の保持者がいれば `lease.expired` を先に出す。goal の作成（`goal.created`）の直後にも自動で足す。store は lease.acquired を自動では書かず、holder 付きの追記は I8 で拒否されるため。
- `submit`: 全イベントを先に `reduce` と `check`（純関数。1 件でも失敗なら 1 件も追記しない）→ `store.append` → 成功した分だけ状態へ反映 → `onChange`。直列化する。

## 守る条件

- 状態は常に永続済みのイベントの fold。追記が途中で失敗しても、成功した分までしか進めない（`applied` に返る）。
- 不変条件違反を永続しない。読み取り専用・degraded・off では `ok:false` で拒否する。
- 同じ root の 2 つ目は `readonly`。heartbeat や追記で `NO_LEASE` を見たら降格する。
- `state()` は深く凍結した複製（Map の書き換えも例外）。

## 限界

- スナップショットは使わず、毎回全ログを畳む。
- 再 open の同一 holder・pid は store が許す（拡張の再読み込み）。
- 表示（panel・アラート）と `index.ts` への登録は別の feature。
