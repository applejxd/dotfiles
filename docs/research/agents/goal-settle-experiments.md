# pi の継続（settle）・永続・書き込み境界の実験（`/goal`・作業台帳の仮定の確定）

作業台帳（`/goal`）の設計の仮定を、pi 1.5.0 の拡張 API の実挙動で確かめた記録。
実験は 2026-11-05。faux モデルのみ（実モデルは呼んでいない）。実験の道具は `.tmp/exp/`（使い捨て。セッション終了で消える）。

## 要旨

- E-a: `agent_before_settle` で `continue:true` を 5 回返すと `agent_start`・`agent_end` は 6 回、`agent_settled` は 1 回。継続中の abort では `before_settle` は呼ばれず `aborted:true`。
- E-c: `agent_before_settle` のハンドラは登録順の連鎖で、前の `entries`・`continue` を見る。返した `entries` は丸ごと置換。
- 置換の結果、`todo` 拡張が `event.entries` を引き継がず、先の harness autocheckpoint の entries を消す（要修正）。
- E-i: `<git-common-dir>` への mkdir・排他 mkdir・write・append・fsync・rename・readdir・rmdir・unlink は `pis` で通る。
- `.git/hooks`・`.git/config` は読み取り専用。子（`PI_HARNESS_WRITE_ROOT` あり）の `guarded_write` は判定器が拒否する。
- E-h: assistant メッセージが 1 つも無い新規セッションでは `appendEntry` がファイルに残らない。1 往復後は `kill -9` でも残る。
- E-h: RPC ではスラッシュコマンドを `prompt` で送れ、`setStatus`・`setWidget`・`notify` は `extension_ui_request` に出る。
- 未実測: E-f・E-g・E-h の print/json。E-d・E-e は下の表を参照。

## 実測の表

凡例: **事実** = この実験で観測した。**文書** = pi の docs に書いてある。**推測** = 観測も文書も無い。
版はすべて pi 1.5.0。

| 項目 | 操作（日時） | 事実 | 文書・推測 |
| --- | --- | --- | --- |
| E-a 連続継続 | `agent_before_settle` で N=5 回 `continue:true`（11-05 02:57〜） | `agent_start` 6・`agent_end` 6・`agent_settled` 1。`before_agent_start`・`input` は継続で再発火しない。継続メッセージは `message_end` を出さず、`get_messages` に `role:custom`+`customType` で現れる。2 回目以降の `event.entries` は `[]`。`event` のキーは `type, outcome, entries, continue, context` | — |
| E-a abort | 継続中の run を abort | `agent_end` の後に `before_settle` は呼ばれず、`agent_settled{aborted:true}` | — |
| E-a error | faux で `stopReason:error` | `before_settle` は `outcome:"error"` で呼ばれ、`continue` で続行できた。非一時的なエラーで retry イベントは出ない | — |
| E-b branch の形 | harness あり、承認拒否・deny を含む | 先頭に `model_change`・`thinking_level_change`・空の `message/system`。assistant の `usage` は `input:0`（大半は `cacheWrite`/`cacheRead`。faux の値）。toolResult は `message.{toolCallId,toolName,content,details,isError,timestamp}`。拒否は `not approved:` 始まり、deny は `` `git push` は deny パターンに…`` 始まりで両方 `isError:true`。`guarded_task` の review は `todo:<id>` が無いと `isError`。失敗した review の呼び出しも branch に残る。todo の状態は `custom/todo-state` | 実モデルの `usage` は未確認。承認が通った非 0 終了の `isError` は未確認 |
| E-c 連鎖 | harness autocheckpoint → todo → 仮の goal の 3 者が同じ settle で返す（`.tmp/exp/e_c.mjs`） | 各ハンドラは前の `entries`・`continue` を見る（登録順の連鎖）。返した `entries` はそのフィールドを丸ごと置換。`continue` は返したときだけ置換。後のハンドラが `continue:false` を返すと先の `true` は取り消され、`entries` は確定し、続きの run は起きない（`agent_start` 1 回）。継続要求時は `agent_start` 2・`agent_settled` 1。2 回目の settle は `entries:[]`・`continue:false` に戻る | — |
| E-c 置換の実害 | 同上 | autocheckpoint の後に todo が走ると `custom_message:autocheckpoint` が消え、確定した custom は `todo-reminder` のみ。autocheckpoint の phase は saving のまま残り、次の settle の圧縮が「Nothing to compact」で失敗した。goal が `[...event.entries, 自分]` を返すと両方残る | 原因は `dot_pi/agent/extensions/todo/index.ts` の `agent_before_settle` が自分の分だけ返すこと（コードを読んで確認。修正は別件） |
| E-i git-common-dir | `pis` の内側で `.tmp/exp/e_i_pis.mjs` と `guarded_write`・`touch`（11-05） | mkdir・排他 mkdir（2 回目 EEXIST）・writeFile・appendFile・read・fsync（ファイル・ディレクトリ）・rename（上書き含む）・readdir・rmdir・unlink が通る。`.git/hooks`・`.git/config` は読み取り専用（`touch` が失敗）。子の `guarded_write` は判定器が「担当の worktree の外へ書けない」と拒否 | `boundary.py:248` は `git-common-dir` を `allowWrite`、`hooks`・`config` を `denyWrite` にしており、実測と一致（コードを読んだ） |
| E-d session_start | RPC で新規→1 往復→`new_session`→1 往復→`/reload`（prompt）→`fork`、別プロセスで `-c`、`switch_session`（`.tmp/exp/e_d.mjs`、11-05） | 新規起動は `reason:startup` 1 回。`new_session` は `session_before_switch`→`session_shutdown:new`→`session_start:new` **2 回**。`fork` は `session_before_fork`→`shutdown:fork`→`start:fork` **2 回**。`switch_session`（/resume 相当）は `shutdown:resume`→`start:resume` **2 回**。`-c` は `reason:startup` 1 回（`resume` ではない）。`session_tree` はどの操作でも出ない。RPC で `/reload` を `prompt` に送ると組み込みの再読み込みではなく `disposition:started`（モデルへのプロンプト扱い）で `session_start` は増えない | 2 回来るのは [message-queue 実験](pi-message-queue-experiments.md) の既知の挙動と一致（原因は未切り分け）。TUI の `/resume`・`/tree`・`/reload` は未実測 |
| E-e 圧縮との同居 | RPC（faux）で 150KB 程度の発言を繰り返して自動圧縮を起こし、拡張コマンドから `ctx.compact()`、RPC `compact`＋`abort`（`.tmp/exp/e_e.mjs`、`lab.ts`、11-05） | 自動圧縮（`threshold`）: `agent_end`→`session_before_compact`→`session_compact`→`agent_before_settle`→`agent_settled{aborted:false}`。圧縮は settle 前に終わり、`before_settle` は呼ばれる。アイドルでの `ctx.compact()` は `agent_settled` を発火せず、`onComplete` のみ（`aborted` の値は得られない）。圧縮が原因で `aborted:true` になることは観測しなかった（全 settle が `false`）。小さいセッションでの `compact` は "Nothing to compact (session too small)" で失敗し `session_compact_failed`。圧縮中の RPC `abort` は "Compaction cancelled" で失敗として終わり `session_compact_failed`（`abort_compaction` は未知コマンド）。対象はアイドル時で、 settle 中の圧縮は観測していない | 「保存中に Esc で `before_settle` が呼ばれないか」は未実測（圧縮がアイドルで起こったため）。継続（`continue`）と自動圧縮が同じ run で重なるケースも未実測（実験では継続は先頭の 1 回のみ）。TUI の Esc は未実測 |
| E-h 永続 | RPC で `/ap`（`appendEntry`）の後に `kill -9`（`.tmp/exp/e_h.mjs`） | assistant 無しの新規セッション: セッションファイル自体が作られず残らない（H1）。1 往復後: `/ap` 応答直後・500ms 後の `kill -9` でも残る（H2・H3）。継続の `custom_message` も settle 後の `kill -9` で残る（H4） | — |
| E-h RPC | RPC で `/ui` など | スラッシュコマンドは `prompt` で送れ、応答は `data.disposition:"handled"`。`setStatus`・`setWidget`・`notify` は `extension_ui_request` の `method` に出る。`get_commands` に拡張のコマンドが載る | — |
| E-h print/json | `/ui` を print/json で実行 | 200 秒でタイムアウトし結果が取れず（原因未調査） | 固まる可能性はあるが推測 |

## 仮定の訂正表（`goal-core.ts`・台帳計画）

| 仮定（旧） | 実測（新） |
| --- | --- |
| 自分の `entries` を返せば足される | 返した `entries` は丸ごと置換。`[...event.entries, 自分]` で足す。足さない拡張（todo）が先の分を消す |
| `continue` は各ハンドラの OR | 返したときだけ置換。後のハンドラの `false` が先の `true` を取り消す。goal は登録順の最後に置くか、`event.continue` を見て決める |
| 2 回目以降の settle も前の提案が残る | 2 回目は `entries:[]`・`continue:false` に戻る（前回の分は commit 済み） |
| `unapproved` は `not approved:` 始まりで数える | deny は `` `…` は deny パターンに…`` 始まりで数え落とす（`summarizeRun`・`detectReview` の直し要） |
| review の呼び出しは成功のものを数える | 失敗（`todo` 欠落で `isError`）も branch に残る。`isError` を見て数える |
| `usage.input` でトークンを数える | faux では `input:0`。`cacheRead`+`cacheWrite`+`output` か `totalTokens` を使う（実モデルは S4 で確認） |
| 台帳は `appendEntry` で永続できる | 最初の assistant メッセージより前は残らない。1 往復後は `kill -9` でも残る |
| 台帳をどこにファイルで置けるか | `<git-common-dir>` 配下は親の `pis` から fs で書ける（`hooks`・`config` を除く）。子は書けない（親の harness だけが書く設計と整合） |
| 継続メッセージは `message_end` で見える | `message_end` は出ない。`get_messages` の `role:custom` で見る |
| RPC・print で UI が同じ | RPC は `extension_ui_request` に出る。print/json は未確認（固まる疑い） |

## 未実測

実測した項目は上の表へ追記する。以下は E-d・E-e の結果を除き未実測。

- E-d の TUI 操作（`/resume`・`/tree`・`/reload`。RPC の相当操作は実測済み）。
- E-e の残り: settle 中の圧縮と Esc、継続と自動圧縮が重なるケース。
- E-f: settle 中の長い await・Esc・`hasPendingMessages`。
- E-g: `custom_message` の TUI での見え方（TUI は faux でも自動化が重い）。
- E-h の print/json。
- 実モデル・Orca/Zed・Windows の項目。
