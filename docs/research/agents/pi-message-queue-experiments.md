# pi 1.4.0 のメッセージ・キューの挙動の実験（CHG-0061 S0）

- **日付**: 2026-11-03
- **対象**: pi 1.4.0。[CHG-0061](../../change/closed/0061-pr-inbox.md)（受信箱）の設計が頼る API の挙動
- **方法**: 実際の pi を RPC モードで起動し、偽のモデル（`test/agents/pi/faux.ts` の `faux/spike`）で動かした。実験用の拡張を `-e` で足し、すべてのイベントを時刻つきで記録した（拡張・生ログは非公開の作業領域。使い捨て）。`--no-session`・オフライン
- **限界**: **偽のモデルと RPC だけ**。TUI（`/new`・`/reload` の対話経路、中断で編集欄に戻る挙動）・Fence・Windows・実モデルの LLM 呼び出しの最中は**未確認**。1 条件につき 1 回の実行（確信度: E1・E2 は高、E3・E5・E6〜E8 は中）

## 結果

事実は観察したこと。含意は、そこからの設計上の判断。

### E1 アイドルのとき（`sendMessage` / `sendUserMessage` の違い）

| 送り方 | run が始まるか | 文脈に入る時 | メモ |
| --- | --- | --- | --- |
| `sendMessage(…, {triggerTurn:false})` | 始まらない | 次の利用者入力の run | custom は user の**前** |
| `deliverAs:"followUp"`（`triggerTurn` なし） | 始まらない | 同上 | アイドルでは `triggerTurn:false` と同じ |
| `deliverAs:"nextTurn"` | 始まらない | 次の run | custom は user の**後** |
| `triggerTurn:true` | **始まる** | すぐ | `before_agent_start` の `messageType` は `"custom"`。送信の直後に `isIdle()` は偽 |
| `sendUserMessage()` | 始まる | すぐ | `messageType` は `"user"`。`input` イベントが出る（`source: "extension"`） |

- 含意: `auto`（アイドルの自動起動）は `triggerTurn:true` で実現できる。既存の注入（`messageType === "user"` のときだけ）は、自動起動の run（`"custom"`）では動かない。

### E2 実行中のとき

| 送り方 | 届く位置 |
| --- | --- |
| `followUp` | 今の run の**最後の応答の後**、同じ run の中。`before_agent_start`・`agent_start` は増えない |
| `steer` | 今の turn のツール実行の後、次の LLM 呼び出しの前 |
| `nextTurn` | 実行中は届かない（次の run で入る） |

- 利用者の入力が積まれているとき: steer の列が先に FIFO で 1 turn ずつ出て、その後に followUp の列が出る。custom と利用者の入力は同じ列を共有する。
- 含意: **`followUp` には `before_agent_start` が来ない**。注入の hook に頼れず、**送る時点で内容を確定**させる。

### E3 中断（RPC の `abort`）

- custom の `followUp` は、`pendingMessageCount` にも RPC の `queue_update` にも**出ない**（利用者の `followUp` は出る）。
- 中断しても**捨てられない**。キューに残り、**次の run の末尾**で届く（custom の `steer` は、その turn の終わりに文脈へ入る）。
- 含意: 「受領を先に記録したので、中断で捨てられると失う」は、RPC では当てはまらない。**逆に、中断後に古い文が次の作業へ混ざり、利用者から見えない**（TUI の表示で補う必要）。TUI で編集欄に戻るかは未確認。プロセスが終了すれば、キューの文は失われる（手動の再送で救う）。

### E5 圧縮中

- 圧縮中の `isIdle()` は**偽**（既知の挙動の確認）。
- 圧縮中の `triggerTurn:true`: **新しい run が圧縮と並行して始まり、完了した**。この実験では `Compaction cancelled` は**再現しなかった**（圧縮は成功。偽のモデルの要約は一瞬で終わるため、圧縮の LLM 呼び出しの最中に重ねる形は作れていない）。`triggerTurn:false`・`followUp` は run を始めず、圧縮も成功した。
- ソースの読解（確信度は低〜中）: `compact()` は冒頭で `abort()` を呼ぶ。`prompt()` は圧縮中なら例外。`sendCustomMessage` には圧縮の検査が無い。
- 含意: 実機の圧縮の失敗（完了通知で中断。[圧縮の失敗の調査](pi-compaction-failure-survey.md)）は、偽のモデルでは再現できない。**`compact-defer` は維持する**（受信箱の送信も、同じ口を通す）。

### E6 タイマーの寿命

| 場合 | `session_shutdown` の理由 | その後の `session_start` | 観察 |
| --- | --- | --- | --- |
| `/reload` | `reload` | `reload` が 1 回 | 古いタイマーの tick は、shutdown の後に残らない |
| 新しいセッション（RPC の `new_session`） | `new` | **`new` が 2 回**（同じ時刻） | 素朴な実装（`session_start` ごとにタイマーを始め、`session_shutdown` で最後の 1 つだけ閉じる）では、**タイマーが二重になり**（tick が 2 倍）、先の 1 つが残る |
| 終了 | `quit` | — | 閉じて終わる |

- 含意: **タイマーの開始は冪等にする**（すでに動いていれば、先に閉じてから始める。`session_start` が複数回来ても 1 つだけ）。RPC の `new_session` での観察。TUI の `/new` で 1 回だけかは未確認なので、冪等であることを前提にする。

### E7 `agent_settled` と順序

- `agent_settled` の時点で `isIdle()` は真。
- `agent_settled` の中で `sendMessage(…, {triggerTurn:true})` を呼ぶと、**新しい run がすぐ始まる**（`messageType: "custom"`）。毎回呼ぶようにすると、**run が無限に連鎖する**（実験で確認）。
- `agent_settled` の中の `deliverAs:"followUp"` は、アイドルなので run を始めない（E1 と同じ）。
- 実行中の `followUp` の配送順は E2 のとおり（最後の応答の後、同じ run の中）。
- 含意: `agent_settled` から起こす処理には、**回数の上限と、同じ batch を二度送らない仕組み**（受領を前提条件つきで先に記録）が必須。

### E8 古い `ctx` の扱い

- `/reload`・新しいセッションの後に、前に保持した `ctx`・`pi` を使うと、**すべて例外**になる（`ctx.cwd`・`ctx.isIdle`・`pi.sendMessage`・`pi.getActiveTools`。「This extension ctx is stale after session replacement or reload」）。
- `new_session` の前後で `cwd` は変わらなかった。
- 含意: タイマーの callback は、**その `session_start` で受けた `ctx`・`pi` だけ**を使い、世代の印で古い callback を無効にする。例外は握って静かに止める。

## 予想と違った点

1. `followUp` は run の途中に入り、`before_agent_start` が来ない。
2. custom のキューは、`pendingMessageCount`・`queue_update` に見えない。中断しても残る。
3. `new_session` で `session_start` が 2 回来る。
4. `agent_settled` からの `triggerTurn:true` は、連鎖して止まらない。
5. 圧縮中の `triggerTurn` で `Compaction cancelled` は再現しなかった（偽のモデルの限界）。

## 採否の基準（CHG-0061 の段へ）

| 機能 | 進めてよい条件 |
| --- | --- |
| 受信箱のタイマー（S2） | 開始が冪等（`session_start` を 2 回続けて呼んでも 1 つ）。`session_shutdown` で閉じ、その後に tick が無い。callback は現在の `ctx`・`pi` だけを使い、古いものは例外を握って止まる |
| `queue`（S3） | busy のときだけ `followUp`。内容は送る時点で確定。キューの文が見えない点を、**TUI の表示（件数のバッジ）で補う**。プロセス終了で失われる点は手動の再送で救う。TUI で中断したときの挙動を実機で確認してから |
| `auto`（S4） | `triggerTurn:true` を、回数の上限・`isIdle()` の再確認・確認画面中と圧縮中の抑止つきで。**`agent_settled` から無条件に呼ばない**。同じ batch を二度送らない（受領が先） |
| 圧縮との併用 | `compact-defer` を通す。実機（実モデル）で、完了通知が圧縮を中断した既知の事実を踏まえて再確認する |

## 未実施（実機で確かめること）

| # | 内容 |
| --- | --- |
| E4 | 承認の確認画面（`/pending approve`）の最中の `isIdle()` と、その間の `triggerTurn` の効果（TUI が要る） |
| E3（TUI） | 中断したとき、積んだ文が編集欄に戻るか |
| E5（実モデル） | 圧縮の LLM 呼び出しの最中に `triggerTurn:true` を送ったとき |
| E9 | Fence の内側（`pis`）から `refs/pi/review/*` の読み書きと `for-each-ref` が通るか |
| E11 | 同じ worktree の 2 セッションで、一方が取り込んだときのバッジ |
| E12 | Windows で `for-each-ref` を 5 秒ごとに起動したときの CPU・遅延 |
