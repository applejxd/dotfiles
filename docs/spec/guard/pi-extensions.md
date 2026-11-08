# pi の拡張と補助機能

pi のフルガードが持つ拡張と補助機能の仕様: 拡張の入れ方の方針（入口の選び方・外部の拡張・自作の拡張）、`guarded_action`、ツールの拡張、圧縮、`git commit` の確認、整形、`/fleet`、stepback、キーバインド、Orca・Zed。起動・設定・MCP は [pi のガード](pi-guard.md)、子エージェントは [pi の子エージェント](pi-subagents.md)、サンドボックスは [pis のサンドボックス](pi-sandbox.md)。

## 拡張の方針

> **2026-11-09 の注記**: 自作基盤は凍結し、方針は [ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md)（既存の拡張・設定の評価を先にし、自作は最後の手段）に置き換えた。以下は、凍結した自作ハーネス（custom プロファイル）のときの記録。

**拡張は自作を基本とする**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)。Superseded）。外部の拡張は、**どうしても必要で、自前実装が困難で、振る舞いを十分に確認したもの**だけを、
例外として導入する。手順は ADR-0016 の「例外の手順」（審査・版の固定・偽のモデルでの試験・配備・記録）。

- `pis` は `-ne` を維持し、足す拡張は必ず `-e <パス>` で明示する（自動発見はしない）
- 足した拡張のツールも判定と伏字化を通る。拡張の読み込み時の処理は囲えないので、審査と版の固定で下げる
- 素の `pi`（Orca・Zed など）は拡張を自動で読むが、この方針は**このリポジトリが配る拡張**に適用する

### 入口の選び方

機能の入口は、**必要な能力を満たす最小のもの**を選ぶ。中核を CLI にして、上に MCP や拡張を薄く被せる形も取れる。

| 観点 | skill + CLI | MCP | 拡張（自前） |
| --- | --- | --- | --- |
| 常駐するコンテキスト | skill の名前と説明だけ。本文は必要時に読む | `codemode`（既定）はツール定義を宣言せず、サーバ名の 1 行。`direct` ならツール定義が常駐 | ツール定義が常駐（動的な有効化もできるが、ツール集合が変わる） |
| キャッシュへの影響（見込み。実測は未） | ツール集合が変わらないので小さい | `codemode` は小さい。接続後に概要が追記されることがある | ツールを足すと先頭側の固定部分が変わる（最小のスキーマで入力 +36 トークン、偽のモデルの見積もり） |
| 使える CLI | `bash` と skill を持つものすべて（pi、Claude Code、OpenCode、Copilot） | MCP を持つもの（登録の経路は CLI ごとに違う） | **pi 専用**（TypeScript、pi の API に依存） |
| フルガードとの整合 | `guarded_bash` の判定と伏字化を通る。許可の規則をサブコマンドで絞る | `mcp__*` として判定（既定は確認）、結果は `tool_result` で伏字化。`mcp.json` は `pis` と共存できない | 判定と伏字化は通る（[E5](../../research/agents/pi-extension-under-harness.md)）。読み込み時のコードは囲えない |
| 機能の深さ | 呼び出しと標準出力まで。UI・イベント・状態は持てない | 型付きのツール、構造化された結果、**常駐サーバでの状態保持** | **pi の内部に介入できる**（イベントのフック、スラッシュコマンド、UI、システムプロンプト、子エージェントの起動、圧縮、独自のプロバイダ） |
| 試験のしやすさ | 手で実行でき、単体テストも簡単 | 中（プロトコルの層が増える） | 偽のモデルが要る（フルガードの試験の仕組みはある） |
| 開発・保守のコスト | 最小 | 中（サーバ・登録・配布） | 中〜大（pi の版に追従する） |
| 1 回の使用の手間 | skill を読む往復が 1 回増える。以後は `bash` を呼ぶだけ | 型付きで呼べる。`codemode` だと間接が増える | 直接呼べる |

- **単純な要求と応答**（検索・取得）→ skill + CLI。コンテキストと保守が最小で、どの CLI でも同じ
- **構造化した結果・常駐した状態・複数の CLI で共有する標準の入口**（ブラウザの操作、認証つきの長いセッション、DB への接続など）→ MCP
- **pi の内部への介入**（`task` の子エージェント、フルガード、Orca の状態表示）→ 拡張。他の 2 つでは代えられない
- 検索は拡張でしかできないこと（フック・UI・プロンプトの書き換え）を要さず、拡張は pi 専用・読み込み時のコードを囲えない・pi の版に結びつく。拡張は「不利」ではなく、検索には過剰

### 外部の拡張

導入済みの外部の拡張の記録。ここに無い外部の拡張は、導入していない。

| 名前 | 版 | ハッシュ | 必要な理由 | 自作が困難な理由 | 審査日 |
| --- | --- | --- | --- | --- | --- |
| （無し） | | | | | |

### 自作の拡張: todo / plan / btw

`~/.pi/agent/extensions/{todo,plan,btw,activity,ask,notify}/index.ts`（実体は `home/dot_pi/agent/extensions/`）。pi 同梱の例（`examples/extensions/todo.ts`・`plan-mode`）を参考に、必要な部分だけ自作した。全 OS に配る。

| 拡張 | 中身 |
| --- | --- |
| `todo` | `todo` ツールと `/todos`。**リストは 1 つで、勝手には消さない**（同じ目標のための別目標は同じリストへ足していく）。ツールの操作は `list`（`all` で完了・中止も）/ `add`（`text` か `texts` で複数）/ `set`（`id` と `status`: `pending`・`in_progress`・`blocked`・`done`・`cancelled`。何度呼んでも同じ結果で、旧 `toggle` の取り違えが起きない）/ `update`（`text` か `note`）/ `remove` / `clear` / **`batch`**（`ops` に操作の配列。順に適用し、1 件でも失敗したら全体を適用せず、失敗した `ops[i]` を返す）/ **`replace`**（`items` でリスト全体を置き換える。`id` を付けた項目は引き継ぎ、載せない既存の項目は消える。Claude Code の `TodoWrite` 相当）。項目には**メモ `note`**（完了の根拠・引き継ぎ。80 字まで表示）を付けられる。変更の結果としてモデルへ返すのは、**変更の要約と、未完了の先頭 3 件・件数だけ**（全件は `list`）。`list` が返す一覧は未完了だけで、完了・中止は件数にたたむ。`in_progress` は同時に 1 件までが指示で、超えると結果に注意を出すが止めない。**`blocked`（`[~]`）は、ジョブ・子・利用者の返答など外部の完了待ち**で、未完了には数えるが、`in_progress` の同時 1 件の数と終了時の `in_progress` のリマインドの対象には入れない（代わりに、`in_progress` が無く `blocked` があり、着手できる `pending`（「【将来」を含まないもの）も残るときは、利用者の発言ごとに 1 回だけ、依存しない作業を続けるよう促す。`pending` は「契約が確定して着手できる」項目だけで、利用者の判断が未回答の設計・確認されていない計画は `blocked` にする（共通指示の「計画と契約」の「着手の条件は確認済みの契約」）。止まってよいのは、契約の範囲に進められる作業が無く、利用者の決定が要るときだけ。承認・実機や操作の確認の待ちは理由にしない）。note なしで `blocked` にすると、待ち先を書く旨の注意を返す（拒否はしない）。**`in_progress` が残ったまま応答を終えようとしたとき、`agent_before_settle` で確認を促すメッセージ（`custom_message`）を足して続行を 1 回だけ要求する**（利用者の発言ごとに 1 回。中断・エラーで終わったときは出さない。切るには環境変数 `PI_TODO_NO_REMINDER=1`）。子の完了は `guarded_task` の `todo` で項目へ反映できる。`/todos` は全件を表示し、`/todos tidy`（完了・中止を片付ける）・`/todos clear` は**利用者専用**（モデルは呼べない）。状態はツール結果の `details` と、利用者の操作の custom エントリ（`todo-state`）に持つので、分岐・再開・圧縮のあとも、その時点に戻る（旧形式 `{ id, text, done }` も読む）。フッターに `📌 完了/全体 ▶ 作業中の項目`（全部完了なら `✅`）を出す |
| `plan` | `/plan` で切り替え。計画中は **`edit` / `write` / `bash` / MCP などのツールを外し**、`read` / `grep` / `find` / `ls` / `todo` / `task` だけを残す（`guarded_` 付きも同じ）。計画の指示を毎ターン注入し、**計画が詰まったと判断した応答（見出し「## 実行計画」と番号付きの手順の両方があるもの）だけ**「実行する / 続ける / 直す」を尋ねる（番号付きの行だけでは尋ねない。相談の途中の応答で毎回聞かれないようにする。判定は `isPlanReady`、試験は `test/agents/test_pi_plan_ready.py`）。「実行する」でツールを戻し、実行を依頼する。**計画の間は、`guarded_task` が読み取り専用の役割（`reader`・`explorer`）の子しか起動・続行させない**（`globalThis.__piPlanMode` の印。単発・並列・続きの依頼・steer を拒否し、状態・abort・close は通す。計画の前から動いている書き込みの子は止めず、利用者へ知らせる。[CHG-0044](../../change/0044-plan-agent.md)） |
| `btw` | `/btw [--plain] <質問>`。いまの会話（user / assistant の本文とツール呼び出しの要約）を文脈に答える。**既定は、読み取り専用の子（`explore`）が、必要ならファイルを読んで確かめてから答える**（会話は新しい側 2 万文字まで。子の起動は、フルガードか Windows の `subagents` 拡張が `globalThis.__piAskReadChild` に置く入口を使い、上限は 3 分）。`--plain` は、ツールなしで**現在のモデル**が 1 回だけ答える（速い。会話は新しい側 6 万文字まで、上限 2 分）。**子が失敗したときは、理由を表示して終わる**（調べていない推測を答えとして出さない。ファイルを見ずに答えさせるなら `--plain`）。子の入口が無いときだけ `--plain` と同じ動きになる。答えは、端末の高さに合わせて**本文の窓だけを描くスクロールできる表示**に出し（↑↓ / j k で 1 行、Space / b で 1 ページ、g / G で先頭・末尾、Enter / Esc / q で閉じる。位置と閉じる案内は最下行）、会話履歴にもモデルの文脈にも残さない。返信はどの経路でも **2 万文字**で切り、「省略あり」を末尾に書く。子と `--plain` の指示は「画面 1 枚（約 20 行）に収める」。エージェントの応答中でも使える |
| `ask` | `ask` ツール。利用者へ選択肢つきの質問を**最大 4 問まとめて**尋ねる（`questions`: `question`・`header`・`options` 2む4 個（`label` と `description`）・`multi`）。画面は、**TUI では自前のパネル**（`ctx.ui.custom()`。問が複数のときは問ごとのタブと最後の「確認」タブ（Tab / Shift+Tab で移動。回答は保持して戻って直せる。確認タブで未回答を警告し、Enter で送信。Esc は全体の中止）。問が 1 つだけならタブも確認も無く、答えたらすぐ送る。選択肢と説明を縦に並べ、カーソルは ❯。複数選択は Space でカーソルを動かさずに切り替え、Enter で確定（チェックしたまま Tab で離れても回答として扱う）。`Type something.` はその行の下でその場で書き、Enter で確定（複数選択でもこの Enter で、チェックと自由記述をまとめて確定する）・Esc で一覧へ戻る。数字キーで行へ移動。IME のためフォーカスをエディタへ渡す）、**RPC（Orca・Zed）では 1 問ずつの `select` / `input`**（選択行は「1. ラベル」の 1 行だけで、説明は質問文の下に番号つきの一覧として出す。表示幅 64 カラムで自前に折り返して字下げし、選択肢の間に空行を入れる。RPC の複数選択は、チェックを切り替えるたびにカーソルが 1 個目に戻る）。長い行の折り返しで境界とカーソルが分からなくなったため）（TUI と RPC で共通。Orca と Zed でも動く）。全問に自由記述の行 `Type something.` を自動で足す（空の入力は記録せず選択肢へ戻る）。`Other` / `Type something.` / `Next` は選択肢のラベルに使えない（`reserved_label`。ほかに `no_questions`・`too_many_questions`・`duplicate_question`・`empty_options`・`duplicate_option_label`・`no_ui`）。**推奨の検査**: 各質問は推奨の選択肢をちょうど 1 つ（multi は 1 つ以上）持ち、先頭に置く。印は label の末尾の `(推奨)` か `(recommended)`（直前に空白を置く。全角括弧・大文字小文字可。label に残り、答えもそのまま返す）。違反は `missing_recommended`・`multiple_recommended`（multi 以外で 2 つ以上）・`recommended_not_first` で、違反した質問を全部 1 つのエラーにまとめ、直し方を添えて返す（形の検査の後。label は 60 字までなので短くする）。試験は `test_pi_harness.py`。戻りは `answers`・`unanswered`（0 始まりの番号）・`cancelled`。中断や時間切れのところから先は未回答として返る。**1 回の画面の待ち上限は 5 分**（試験用に `PI_ASK_TIMEOUT_MS`）。**UI が無い実行（print・子エージェント）では、`before_agent_start` でツールを外す**。`plan` 中も残る。設計は公開拡張（`rpiv-ask-user-question`・`pi-ask-user`）の README を参考にした（[調査 P3・P4](../../research/agents/pi-public-extensions-survey.md)）。タブ画面・プレビュー・メモは作らない（`ctx.ui.custom()` が必要で、RPC では出せない） |
| `notify` | **利用者の入力を待つとき、端末へ BEL（`\x07`）を 1 回送る**。送るのは、作業が完全に終わったとき（`agent_settled`。`agent_end` ではない）、フルガードの確認（`confirmInOrder`）を出す直前、`ask` の質問を出す直前。Zed の Terminal Threads は、フォーカス外の端末の BEL を通知にする（[Terminal Threads](https://zed.dev/docs/ai/terminal-threads)）。**TUI（`ctx.mode === "tui"`）のときだけ書く**。RPC では stdout が JSON 行の通信なので汚さない。試験は `test_the_bell_is_written_only_in_the_tui_not_in_print_mode`（鳴らさないことだけ。鳴ること自体は未確認）。ACP 経由の Zed（pi-acp）には効かない（[Z1・Z2](../../research/agents/zed-orca-pis-integration.md)）。**pi 1.4.0 は、これとは別に OSC 7501 を内蔵している**（`working` / `blocked` / `done` / `error` / `idle`。端末が問い合わせに答えたときだけ送る。`PI_PROGRAM_STATUS=1` で強制、`0` で停止。tmux と screen は通さない）。拡張の `select` / `input` / `editor` は `blocked`（`kind=question`）、`confirm` は `kind=permission` になるが、**`ctx.ui.custom()` は対象外**で、自作の `ask` の質問パネルと確認の全文ビューアは `blocked` にならない（コードの読み。実機の送信は未検証。[調査 HO1](../../research/agents/host-integration-survey.md)） |
| `activity` | 動いている子エージェント（`task` / `guarded_task`）とバックグラウンドジョブの数を、入力欄の下の専用の 1 行（ウィジェット。起動モード・ToDo のステータス行とは別の行）に `🤖 2 subagents / ⚙️ 1 jobs` の形で常時出す（0 件の側は出さず、どちらも 0 なら消す）。1 秒ごとに数え直し、表示が変わったときだけ `setStatus` する。子は起動する側（`subagents` とフルガード）が `globalThis.__piChildren` に登録し、ジョブは `bg_run` が `globalThis.__piJobs` に登録する。ツールは `bg_run`（コマンドを切り離して起動し、ID を返す（ログのパスは見せない。`read_deny_globs` で読めないので、教えるとモデルが行き止まる。[実験 B1 の F4](../../research/agents/pi-bg-experiments.md)））・`bg_log`（状態とログの末尾と総行数。ID なしで一覧）・`bg_kill`（プロセスの木ごと止める）。pi の終了時には動いているジョブも止める。**ジョブが終わると `pi.sendMessage`（`triggerTurn: true`、`deliverAs: "followUp"`）で LLM へ終了を知らせる**（ID・exit・コマンド・ログ末尾 20 行）。 **2.5 秒の間に終わった分は 1 通にまとめる**（2 件以上は各ログの末尾 5 行。同時に終わる 12 件で 12 ターンになっていた。[B1 の F3](../../research/agents/pi-bg-experiments.md)）。 **終了後に `bg_log` で読んだジョブは通知から外し、全部が読み済みならターンを起こさない**（画面の通知だけ。B1 の F2）。 親が作業中は届けず、「まとめる窓が閉じた」と「`agent_settled`（`agent_end` ではない。再試行・圧縮・続行がその後に続くことがある）」の両方を満たしてから、読み済みを除いて届ける。アイドルなら、窓が閉じたときにすぐターンを起こす。 試験は `test_jobs_that_finish_together_wake_the_agent_once` / `test_a_job_read_with_bg_log_after_it_finished_does_not_wake_the_agent` / `test_a_job_not_read_still_wakes_the_agent_after_the_turn`（外すと落ちることを確認）。 ないとジョブ待ちで止まったターンが再開しない。`bg_kill` で止めたときと終了時の停止では送らない。一覧のコマンドは作らない（数だけ）。**待ち方の案内はツール側に置く（AGENTS.md には書かない）**: `bg_run` の `description` / `promptGuidelines` / 戻り値と、実行中のジョブの `bg_log` の戻り値に、「終了すると自動で通知が届く。`sleep` や `bg_log` の連打で待たず、他の作業を進めるか応答を終える」を入れた。試験は `test_bg_run_and_a_running_bg_log_tell_the_model_not_to_wait_by_sleeping_or_polling`。旧 `/agents` はこれに置き換えた |
| `delegate-nudge` | 親が委譲を忘れない契機の第一歩として、**通知なしで統計だけを取る**試作（N1a）。利用者の発言ごとに、読み取り系ツール（`guarded_read` / `guarded_grep` / `guarded_find` / `guarded_ls`、素の pi の `read` / `grep` / `find` / `ls`）の呼び出し回数・結果の行数と文字数・エラー数・ツール名ごとの回数、`guarded_task` の新規の子の起動数（agent ごと。status・steer・追加依頼は数えない）、それ以外のツール呼び出しの数を、`appendEntry("delegate-stats", …)` でセッションに 1 件残す（モデルの文脈には入らない）。**読んだ内容・パス・引数は入れない**。通知もツール結果の変更もしない（ハンドラは常に `undefined` を返し、例外は黙って無視する）。**子（`PI_HARNESS_CHILD=1`）では動かず**、`PI_DELEGATE_NUDGE=0` で止められる。`/delegate-stats` で直近 10 発言の要約と合計を出す。案件は [CHG-0031](../../change/0031-delegate-nudge.md)。**`own_extensions` に登録済み**（`common.toml.tmpl`）。試験は `test_pi_harness_extensions.py` の `test_delegate_nudge_*`（5 件） |

- **`speed`**（同じ表の拡張。`own_extensions` に登録済み）: 直近 1 回のモデル呼び出し（1 つの assistant メッセージ。ツール実行の時間は含めない）の速度を、ステータス行 `speed` に `📝58t/s 1.2s`（decode と TTFT）で出す。記録・コマンド・ツール・通信は無い。時刻は、`before_provider_request` を t0、最初の `message_update` の `*_delta`（thinking・text・toolcall のどれでもよい）を t_first、assistant の `message_end` を t_end とする。**`provider_stream_event` は使わない**（`data` は提供元ごとの生の値で、最初の 1 件が内容か接続開始かを型から区別できない）。TTFT = t_first − t0、decode = `usage.output` ÷ (t_end − t_first)。**`—` は、取れない値**（t0 か t_first が無い、出力 30 トークン未満、decode 区間 0.3 秒未満）。**取れなかった項目は、直近の有効な値を表示し続ける**（短い応答で decode だけが取れないときも、`—` に戻らず、前の decode を残して TTFT だけ今回の値にする。`~` も直近の値のものを残す。`—` を出すのは、セッションを開いてから一度も取れていない間だけ）。**`~` は、確定値でないしるし**（`usage.reasoning` が 0 より大きいのに thinking のデルタを 1 件も見ていない = reasoning がストリームに出ない経路で、decode が過小になりうる）。エラー・中断の応答は更新せず、`session_start`（切り替えを含む）で消し（直近の値も捨てる）、UI が無いモード・子（`PI_HARNESS_CHILD=1`）では何もしない。prefill 速度は出さない。faux のプロバイダは `before_provider_request` を呼ばないので、統合試験では TTFT を測れない（純関数と、時計を差し替えたイベント列の試験で補う）。未確認: 実際のストリームの時刻の精度、TUI・Orca での見え方、Copilot 経由の reasoning。比較の根拠は [記録 P8](../../research/agents/pi-public-extensions-survey.md#記録-p8--2026-10-31-tok-s-の拡張speed-の測り方の比較)。試験は `test_pi_speed.py`
- **モデルに存在を知らせる**: `todo` / `bg_run` / `bg_log` / `bg_kill` にも `promptSnippet`（と `todo` / `bg_run` の `promptGuidelines`）を付けた。無いと「Available tools」に載らず、モデルが使い忘れる（[子エージェント](pi-subagents.md#子エージェント)と同じ対処）。試験は `test_todo_and_activity_tools_are_listed_in_the_system_prompt`
- `pis` は `-ne` なので、`-e` で明示して足す。素の `pi` は自動発見で読む
- **自作の拡張の一覧は `common.toml` の `[pi] own_extensions` の 1 か所**。生成器が `rules.json` の `extensions` へ出し、`pis` と `ocs` の `pi.py`（サンドボックス）が同じ一覧を読む。`[pi.sandbox] read` の拡張の分もこの一覧から生成する。拡張を足すときは一覧へ名前を足すだけ。`rules.json` に一覧が無い（配り直していない）と、`pis` は起動しない
- フルガードの役割は、`implementer` の `tools` に `todo` を足してある（判定器は `todo` を allow）。`plan` はツールを登録しないので判定に関わらない
- 計画中は shell が無いので、`git log` などの調査もできない。必要なら `/plan` を終えて調べる
- `pis --boundary` も同じ一覧を `-e` で足す。読み取りは拡張ごとに開ける（`~/.pi/agent/extensions/<名前>`。一覧に無い `orca-agent-status` などは開けない）。実機で `todo`・`plan`・`btw` の認識を確認した
- 実測と未確認の項目は [自作の拡張の実測](../../research/agents/pi-own-extensions-measurements.md)（`activity`・`btw`・`todo`・`plan`）
- **フルガード（`pis`）の下では、`bg_run` のコマンドを bash と同じ判定（`decide`）に通す**。deny は止め（bypass でも外れない）、ask は確認画面を出し（画面に「バックグラウンドで実行」と出る）、役割の `shell_deny` / `shell_allow` と誘導も効く。役割が `bash` を持たなければ `bg_run` も使えない。`bg_log` / `bg_kill` はジョブの確認と停止だけなので、`bash` を持つ役割には allow。素の `pi` でも、フルガードが同じ判定を掛ける（Windows も設定でフルガードが載る。ただし `bg_run` は cmd で動き、実機は未確認。フルガードの印が無い起動では実行しない）
- `btw` は、`--plain` では `ctx.modelRegistry.complete()` を 1 回呼び、既定では `explore` の子を 1 つ起動する。どちらもトークンを消費する（セッションの合計には入らない）
- **子の入口 `__piAskReadChild`**: 利用者のコマンドが起こす操作なので、`/agent` と同じく判定器は通さない。そのかわり、起動できる役割を**読み取り専用（`reader` / `explorer`）に限る**（`worker` / `commit` は拒否）。答えには伏字化を掛ける（Windows の `subagents` 拡張の入口は、子がフルガード付きで起動するので判定と伏字化が効く想定。実機は未確認。子の出力の貯め込みは 8 MB で止める）。試験は `test_ask_read_child_entry_runs_only_read_only_agents`・`test_btw_asks_an_explore_child_by_default_and_plain_does_not`、表示の部品（上限・窓・スクロールのキー）は `test_btw_view.py`。（実測は上の記録）

### todo の別表示

チャットの履歴が todo の一覧で流れないよう、表示をチャットから分けた（`extensions/todo/view.ts` の純関数 + `index.ts` の配線。試験は `test_pi_todo_view.py`）。

- **チャット**: `renderCall` / `renderResult` は既定で 1 行に畳む（例: `📌 todo update #101 → blocked`、結果は「未完了 18 件・完了 83 件」）。展開（pi の expanded）すると、モデルへ返す本文を行頭の印で色づけして出す。**モデルへ返す `content` の text・`details` は変えない**
- **`/todos`（引数なし）**: overlay で全件を見る。状態ごとの見出し（進行中・待ち・未着手・完了・中止。件数つき）で区切り、各項目は 1 行目「アイコン `#id` 題名」（進行中は accent の太字、待ちは warning、未着手は通常、完了は success、中止は dim の取り消し線）、2 行目以降に note を dim で 2 行まで（超えたら `…`）
- **操作**: ↑↓ / j k で 1 行、PgUp / PgDn でページ、g / G で先頭・末尾、`a` で完了・中止の表示を切り替え（既定は未完了だけ）、Esc / q で閉じる
- **大きさ**: 高さは「内容」と「端末の行数 − 4」の小さい方（描画のたびに `tui.terminal.rows` を読むのでサイズ変更に追従）。桁は表示幅（全角 2）で切る・折り返す。pi-tui に依存しない自前の幅関数を使う（node の試験で単体に動かすため）
- **TUI 以外**（`ctx.hasUI` が false、または `ctx.mode` が tui 以外）: 従来どおり `ctx.ui.notify` のテキスト。`/todos tidy`・`/todos clear`・ステータス行は変えない
- **未確認**: 実機の TUI での見た目（色・overlay の位置と大きさ・端末のリサイズ）と Windows。反映には `chezmoi apply` と pi の再起動が要る

### guarded_action（承認つきの外部操作）

`git commit`・`gh issue comment`・`gh issue edit`（本文とタイトル）を、**1 回の承認で、ハーネスが組み立てた argv を、シェルを通さずに実行する**ツール（[CHG-0038 段 G11](../../change/0038-guard-reclassification.md)）。通常の ask（コマンドを見せて判断）と違い、内容を見せて承認を取り、承認した内容がそのまま使われる。
ガードは境界ではなく「うっかり防止」なので、**誤った経路（bash の直接実行）へ行かないよう寄せる**仕組みであって、経路の強制ではない（Python や curl 経由は迂回できる。強制が要る GitHub 操作は、トークンの権限側で行う）。

- **操作の表**: `common.toml` の `[[pi.actions]]`（`id`・`label`・`argv`・`fields`・`replaces`・`preview`）。生成器が検証して `rules.json` の `judge.common.pi.actions` へ出す。操作の追加は、表に項目を足すだけ（ツールは増えない）。今は `gh_issue_comment`（`repo`・`number`・`body`）、`gh_issue_edit_body`（`repo`・`number`・`body`）、`gh_issue_edit_title`（`repo`・`number`・`title`）、`git_commit`（`message`、任意の `dir`）。feature の起票・クローズ（`git flow`）と規約の強制は、この表から外した（[CHG-0050](../../change/0050-slim-guarded-action.md)、[ADR-0021](../../adr/0021-conventions-as-instructions-slim-guarded-action.md)。下の「撤去した操作と gate」）。フィールドの型は `repo`・`int`・`line`（1 行の短い文字列。`title` など。`argv` の 1 要素として直接渡す）・`text`（`file = true` の本文）。`line` は改行・制御文字を含められない（確認画面と `argv` の見え方がずれないように）。`gh` にタイトルのファイル渡しが無いので `line` を足した。issue の編集は、本文とタイトルを別の操作にしてある（片方だけ直すときに、もう片方を渡し直さなくてよい）。ラベル・担当者・状態の変更は対象外
- **ツール**: `guarded_action`（引数 `action` と `params`）。登録されるのは、役割の `tools` に `action` がある親の役割（`implementer`）だけ。子エージェント・読み取り役・探索役には無く、実行時にも拒否する。判定器は `action` を役割の許可だけで通し、**汎用の ask・確認は出さない**（確認は `execute()` が 1 回だけ行う）。
- **確認**: `select` で「承認して実行 / 編集して承認 / 拒否」。内容（`content` のフィールド）の全文、プレビュー、**実行する argv** を表示する（表示と実行は同じ配列）。**RPC（Orca・Zed など TUI 以外）では、詳細をチャットに出し、承認ダイアログは要点だけにする**: RPC の `select` は `title` と選択肢しか持たず、全部を詰めると chat UI（特にスマホ）ではみ出して承認の選択肢に届かないため。確認の前に、今までの詳細（全文・プレビュー・統計・argv）を**ツールの途中経過**（`execute` の `onUpdate`。RPC では `tool_execution_update`）として出し、ダイアログの `title` は「上記の内容で実行しますか」の 1 文だけにする（要点を繰り返さない。利用者の決定）。詳細には、対象のリポジトリ（作業ツリーの実体パス）・ブランチ・HEAD・本文の全文・ステージ済みの統計・argv と、退避の注意書き（`git_commit`）を出す。途中経過のイベントは pi が非同期に流し、ダイアログの要求より後に出ることがあるので、詳細を出した後に 300 ms 待ってからダイアログを出す（待たないと「上記」が見えない順になる。実測）。全文は「編集して承認」のエディタでも見られる。`argv` の中で `content` の値を含む要素は `<名前>` に置き換える（本文が 2 回出るのを避ける。実際に実行する配列は変えない）。**途中経過を出せないときは、詳細を見せずに承認させないよう、スマホ向けに縮めた詳細（本文は先頭 10 行・800 字、統計は先頭 8 件、空行なし、1 行 100 字）をダイアログに出す。** TUI はこれまでどおりダイアログに全部出す。**Orca が途中経過をチャットに表示するか、スマホで見やすいかは、実際の Orca では未検証**（公開の情報では確認できなかった）。子は拒否（`not approved:`）。**`git_commit` の無反応（`[pi.confirm] timeout_seconds`）・UI 無し・不在は、拒否ではなく退避して続行**（下の「退避」）。取消・中断・拒否と、`git_commit` 以外の操作の無反応・UI 無しは、拒否のまま。bypass でも省略できない。「編集して承認」は `editor`（timeout が無いので、選んだ後にだけ開く）、「拒否」は `input` で理由を任意に取る。
- **TUI の `git_commit` の確認は、要約が既定（CHG-0050 の後続）**: TUI では常に、小さい変更も含めて、確認の title はラベル付きの箇条書きの要約（**リポジトリ名・ブランチ（短縮 HEAD つき）・件名（本文の 1 行目。**切らずに字下げして折り返す**。最大 5 行）の順**、本文の大きさの行は出さない（本文の全文はチャットと「全文を見る」で見る）、変更（合計の行を見出しにし、上位 5 ファイルを字下げで。同名が無いファイルは最後の要素だけ。変更行の合計。棒グラフは出さない）と残りの件数。リポジトリ名は**本体のリポジトリ名**（git の共通ディレクトリの親。worktree の名前はブランチ名と重複するので出さない。git が使えないときは `dir` の指定の最後の要素、無ければ作業ツリーの最後の要素）。約 12 行。絶対パスは出さない）にし、行は端末の幅（`process.stdout.columns`。全角を 2 桁と数える）で切る。注意書きも 1 行に縮める。Orca のスマホ（約 46 桁）で旧版の全文が画面を埋め、選択肢が画面の外に出た実測による。詳細（本文全文・argv など）はツールの途中経過としてチャットにも出す（Orca のスマホの TUI で、途中経過が描かれ、`ctrl+o` で展開できることを実機で確認。ダイアログの要約は残す）。選択肢は「承認して実行 / 全文を見る / 編集して承認 / 拒否」の 4 つにする。「全文を見る」は、**先頭から読める自前のビューア**（`harness/text-viewer.ts`。`ctx.ui.custom`。本文・プレビュー・argv・退避の注意を読むだけ。↑↓/j/k・Space/b・g/G でスクロールし、q / Enter / Esc で閉じる。位置を案内の行の先頭に出す）で開き、閉じると同じ確認に戻る（期限は select ごとに仕切り直し。ビューアは期限の対象外）。pi の `ctx.ui.editor` は開いたときにカーソルを末尾に置く（`pi-tui` の `setText`。開始位置の指定が無い）ので末尾から見え、使わない。`custom` が無い画面では editor に戻す。`gh_issue_*`・RPC は、従来どおり全文を出す。表示だけを変え、同一性の照合・実行の argv・時間切れ・退避は変えない。見えない範囲は、本文の 2 行目以降と下位のファイルで、承認前に AI がチャットへ書く全文が補う。**成功結果は、編集したときだけ「実際に使った最終の内容」を返す**（編集しないときは「承認した内容のとおり」）。Zed など `editor` が使えない画面では「全文を見る」が機能しないが、RPC は要約しない。試験: `test_pi_action_view.py`。実機の Orca スマホ TUI で、要約が 1 画面に収まり、選択肢の 4 つまで見えることを確認（2026-10-31、箇条書きにする前の並び。長い行は「…」で切れる）。未確認: 箇条書きの並び・全文ビューア（先頭からの表示とキー操作）の実機での見え方、Zed での「全文を見る」
- **確認の省略（自由区。[CHG-0053](../../change/0053-worktree-integration-gate.md)）**: `[pi.integrate] skip_confirm_in_free_zone`（**同梱の設定は true**。生成器の既定は false）が真のときだけ、`git_commit` の cwd（`dir` を解決した対象）が**自由区**（リンクされた worktree で、HEAD が保護でない `refs/heads/feature/*`。`freezone.ts`。接頭辞は [`pi.json`](#プロジェクトごとの設定pijson) で変えられる）なら、確認（select）を出さずに実行する。UI が無い実行でも進む（退避しない）。子は従来どおり拒否。**実行直前に、自由区かをもう一度判定し**、なくなっていれば未実行で返す。結果は「承認した内容のとおり」ではなく、「確認なしで実行した (自由区: ブランチ。実行後の HEAD: …)」を返し、`details.freeZone` に判定と省略したかを入れる。**設定が偽の間は判定を「自由区の判定 (観測中。確認は省略していない)」として、真で自由区でないときは「自由区の判定: not free (理由)。確認を省略せず、承認を取って実行した」を結果に添える**（誤判定を見る）。自由区の外・判定できないとき・設定が無い／不正なときは、従来どおり確認する（deny にしない）。試験: `test_pi_free_zone_commit.py`
- **退避（`git_commit` の無反応・UI 無し・不在。CHG-0046）**: 承認が取れないときは、実行せず、**表示した内容**を `refs/pi/pending/<時刻>` に退避して、`not approved:` で始まる結果（`isError`）で返す。文言は「元の操作は未実行。内容は `<ref>` に退避した。再試行しない。続きの作業を子（worker など）に背景で任せられるなら任せ、親は応答を終えて idle になる（退避は `/pending` で確認・破棄するだけで、承認して実行する経路は無い）。任せられる作業が無ければ、『保留したコミット』として報告して終える」（保存に失敗したときは、成功した ref を返さず、退避できなかったと返す）。
  - **表示の前に tree を確定**する（`snapshotStaged`。一時のインデックスで作り、実のインデックスへ書き戻さない）。表示する HEAD・ブランチ・インデックスの識別子は、この snapshot と一致していなければ、表示せずにやり直しを返す。時間切れのあとは、実のインデックスを読み直さず、確定した tree を保存する（待つ間に別の操作がステージを変えても、退避は表示した内容）。取れない（空・確定中に変化）ときは退避不能とし、確認画面にそう出して、時間切れは拒否になる
  - **時間切れ**は、自前のタイマー（`timeout_seconds`）が発火したときだけ。TUI の組み込みの期限は 3 秒遅らせた保険。利用者の取消（Esc）・呼び出し元の中断・例外・「拒否」は、退避しない
  - **不在**: 時間切れのあと、利用者の入力（`input` の `source` が `extension` 以外。`/pending` も含む）が無い間は、待ち列の中で、次の確認を出さずに退避する。入力の世代で、待機中の入力のあとの時間切れが不在を立てないようにする。`session_start` で初期化
  - 退避は**独立**した commit（親は表示時点の HEAD。ほかの退避を親にしない。コミットが無いリポジトリでは親なし）。出自は末尾の trailer（`Pi-Pending-Request`・`-Branch`・`-Head`）。保存・破棄の内部の git は、**hook を無効**（`core.hooksPath=/dev/null`）にして実行する
  - 確認画面には「N 分応答が無ければ、実行せず内容を退避して作業を続けます。編集・拒否理由の入力中は対象外」と出す。**編集して承認の `editor`・拒否の理由の `input` には期限が無い**（対象外）
  - **`/pending`**（利用者専用。モデルは呼べない）: `list`（新しい順）・`show <ref>`（差分の本文まで）・`drop <ref>`（到達用の ref を外す。オブジェクトは `git gc` まで残る。名前空間の外・symbolic ref は拒否。`--no-deref`）。取り込みは未実装（CHG-0046 の段 4）。新形式の保留（`git_integrate`・`/pending approve` など）は撤去済み（[履歴](pi-pending.md)）。**片付けは、ハーネスが自動で行う**（`reconcilePending`。モデルは消せない）: 同じ tree のコミットが `HEAD` の履歴（新しい側の 500 件）にある（取り込み済み）・同じ tree と起点の退避がより新しくある（重複）・30 日より古い、のどれかを、`git_commit` の成功の直後と `session_start` で消す。内容が変わった途中の状態は、期限まで残る
- **撤去した操作と gate（CHG-0050）**: 次は 2026-10-31 に撤去した（経緯は [CHG-0047](../../change/0047-gitflow.md)・[CHG-0049](../../change/0049-gitflow-convention-guard.md) と [CHG-0050](../../change/0050-slim-guarded-action.md)、理由は [ADR-0021](../../adr/0021-conventions-as-instructions-slim-guarded-action.md)）。
  - `gitflow_feature_start` / `commit` / `finish` / `discard` の 4 操作と、その確認なしの許可リスト、実効設定の安全プロファイル、`git flow` の bash 拒否（`shell_deny`・`replaces`）
  - feature の worktree の中の `git_commit` の確認なし（WIP の省略）。`git_commit` は、どこから呼んでも**常に確認する**
  - develop / main の直接の編集・コミットを拒否する gate（`edit` / `write` / `git_commit`）と `/gitflow-allow`
  - 今は、feature の起票・クローズは利用者が自分のシェルで `git flow feature start` / `finish` を実行し、AI は feature の worktree で起動した `pi` から `git_commit` する。develop / main への直接の編集・コミットは、機械では止めず、`AGENTS.md` と `commit` スキルの指示で運用する（[開発](../development.md)の gitflow-lite の節）
- **`dir`（入れ子・仮想 monorepo。任意の引数）**: `git_commit` は既定でセッションの cwd のリポジトリで動く。cwd の中に独立した git リポジトリ（子）があるときは、`dir`（cwd からの相対パス）でその子を指す。型 `dir` は `argv` に現れず（実行する場所を選ぶ）、`optional = true` なら省略できる。構文を見るのは `validateCall`（絶対パス・`~`・`..`・制御文字・バックスラッシュを拒否。`""` と `.` は省略と同じ）、実体を見るのは `resolveRepoDir`（シンボリックリンクを解決したあと cwd の外を拒否、かつ `git rev-parse --show-toplevel` がそのパス自身（リポジトリの最上位）でないと拒否）。解決後のリポジトリで、スナップショット・プレビュー・同一性の照合・実行・退避（`refs/pi/pending/` はそのリポジトリへ保存）を行う。確認画面の詳細の「対象」に `dir: <パス>` と、実体の「リポジトリ」を出す。**判定と実行は同じ解決済みの対象を見る**: 実行直前にもう一度 `resolveRepoDir` して、承認の間に指す先が変わっていれば拒否する（うっかり・承認中の差し替えの範囲。最後の syscall 直前の差し替えを原子的に防ぐものではない）。`dir` を指すときを含め、プレビュー・スナップショット・実行の git はすべて、対象のリポジトリを選ぶ継承環境変数（`GIT_DIR`・`GIT_WORK_TREE`・`GIT_COMMON_DIR`・`GIT_INDEX_FILE`・`GIT_OBJECT_DIRECTORY`・`GIT_ALTERNATE_OBJECT_DIRECTORIES`・`GIT_NAMESPACE`）を**落とした同じ環境**（`repoTargetEnv`）で動かす（拒否はしない。見る側と実行する側で対象がずれないように、環境を 1 つに固める）。`GIT_CONFIG_*` は残す（AI CLI のハーネスが常に注入する防御的な設定で、`core.worktree` を注入しても対象は変わらない。実測）。`--show-toplevel` は `GIT_DIR` の乗っ取りを検出できないので、観測ではなく変数を外すことが守りの本体。`dir` つきのコミットも**常に確認する**。退避の結果には対象のリポジトリを添える。`git -C 子 commit` は `git commit` に正規化されて同じ deny に当たるので、deny の理由に「任意の引数: dir」の説明を添える（呼び出し例には入れない）。制限: 退避されたコミットの自動の片付け（`reconcilePending`）は、そのリポジトリへの次の `dir` つきの `git_commit` の成功後にだけ動く（`session_start` と `/pending` は cwd のリポジトリだけ）。注意: 子のリポジトリの設定（hook など）は、cwd のリポジトリと同じようにコミットで動く。
- **同一性**: `git_commit` は、プレビューで HEAD・ブランチ・index の識別子（`git ls-files -s -z` の sha256。書き込みを伴わない）を取り、**実行の直前に再取得して照合**する。不一致なら実行せず、もう一度呼ぶよう返す。ステージ済みが空ならエラー。プレビューのコマンドは、設定ではなくコードの許可リスト（`git_staged`・`none`）に限る。hook（pre-commit）による実行中の変更までは保証しない。**メッセージは 1200 文字まで**（`message` の `max_chars`）。超えると確認の前に拒否し、モデルが箇条書きに縮めて呼び直す（本文の肥大化の抑制。2026-10-28 に、直近 40 コミットの本文が 1 件あたり約 120〜410 語まで膨らんでいたため。書き方は `commit` スキルの「スタイル規範」）。
- **実行**: `execFile`（シェル無し）、cwd は `ctx.cwd`、環境変数は継承（ブローカー経由の `gh` のため）、120 秒。本文は 0700 のディレクトリへ 0600・排他的作成で書き、承認後に再読みせず、`finally` で消す。値は型（`repo` の正規表現・`int`・`text` の長さと NUL）で検証し、`-` 始まりは通らない。終了コードが 0 でなければ、出力を返してエラーにする。
- **誤った経路を寄せる**: `replaces`（`git commit`・`gh issue comment`・`gh issue edit`）に当たる bash は、`action` を持つ役割では **deny**（ask にしない）。評価の位置は `[[pi.guide]]` の直後、`shell_deny` の前（bypass でも外れない）。理由に、`guarded_action` の呼び出し例（`-R` と番号が分かれば候補として入れる）を入れる。同じコマンドに当たる操作が複数あるとき（`gh issue edit` は本文とタイトル）は、表の順に全部の例を「または」でつなぐ。`action` を持たない役割・他の CLI は従来どおり（`git commit` は ask）。ツールの説明、`guarded_bash` の説明、`ask` の説明にも同じ境界を書く。
- **指示**: グローバル指示と `commit` スキルは、`guarded_action` が使えるときは事前に `ask` で承認を取らず、bash で実行しない、と書く（ツールが無い環境は従来どおり）。
- **計測**: `.agents/skills/friction-review/scripts/measure_routing.py`（導入前の基準: 71 セッションで投稿・コミットの bash の直接実行 275 回、うち直前に `ask` で承認を取ったもの 60 回）。導入後に同じスクリプトで、bash の直接実行の割合と `guarded_action` の呼び出し数を比べる。
- **試験**: `test_pi_actions.py`（生成器・判定器・TS/Python の同一性）、`test_pi_actions_harness.py`（確認が 1 回・実行・拒否・時間切れ・UI 無し・子・引数の検証・同一性・本文ファイル・編集）。
- **確認済み（2026-10-27）**: `gh_issue_edit_title`・`gh_issue_edit_body` の実行（個人のリポジトリのテスト用 issue。本文は複数行・日本語・バッククォートを含み、壊れずに反映された。承認は 1 操作につき 1 回）。
- **未確認**: 実際の TUI での確認画面の表示（3 択、長い本文、editor の操作）。サンドボックス内でのブローカー経由の `gh` の実機。`git commit` の hook が失敗したときの再試行の運用。**段階 3**（表の一般化と、`gh pr create`・`gh issue create`・`gh pr comment` などの追加）は、実測の後。

### プロジェクトごとの設定（`pi.json`）

各リポジトリの `.agents/config/pi.json` で、統合まわりの **3 つの値だけ**を、そのプロジェクト用に変える（[CHG-0057](../../change/0057-per-project-integrate.md)）。
**保護ブランチは変えられない**（全体設定 `[pi.integrate] protected_refs` のまま）。リポジトリ内のファイルはエージェントが書き換えられるので、保護を弱める手段を置かない。
利用者向けの書き方は [pi-manual.md の 7.6](../pi-manual.md#76-プロジェクトごとの設定pijson)。

- 実装の状況: 解析・検査・ローダー、自由区・`/board`・プレビューへの配線、`risk_paths`、分類器の穴 2 件はすべて取り込み済み（2026-11-02）。**実機確認（架空の一時リポジトリ）は未実施**。確認省略を実際の `pi.json` で配備するのは、その後（どのリポジトリにも実際の `pi.json` はまだ無い）

#### 形

```json
{
  "integrate": {
    "target": "production",
    "source_prefixes": ["task/"],
    "free_zone_prefixes": ["task/"]
  }
}
```

| キー | 意味 | 省略したときの既定 |
| --- | --- | --- |
| `target` | 統合先（`/board` の比較先・`git flow finish` のプレビュー） | `[pi.integrate] target` |
| `source_prefixes` | 統合元として許す接頭辞 | `["feature/", "bugfix/"]` |
| `free_zone_prefixes` | 自由区（確認の省略）の接頭辞 | `["feature/"]` |

- 全て省略できる。ファイルが無い・キーが無いときは、全体の既定
- 接頭辞の既定は、TS の定数（`DEFAULT_SOURCE_PREFIXES`・`DEFAULT_FREE_ZONE_PREFIXES`）
- 上限: ファイル 4096 バイト・配列は 8 要素・文字列は 64 字（`target` は 128 字）・ネストは 2 段（トップ → `integrate`）

#### 読み方

- **HEAD にコミットされた blob だけ**を読む（`git --no-replace-objects ls-tree -l --full-tree HEAD` → `cat-file blob`）。**作業ツリーの編集は、コミットするまで反映されない**
- `--no-replace-objects`: `git replace` で HEAD のコミットの中身を差し替えられても読まない
- ファイルが無いときは「設定なし」（全体の既定・診断なし）
- **読めないときは `LoadedProfile.readFailed`**（設定は全体の既定で返すが、呼ぶ側が fail closed に使う）:
  - `ls-tree`・`cat-file` が失敗した（HEAD が無い場合もここに入る。コード上の読解）
  - `ls-tree -l` の出力を解釈できない（`ls_tree_unparsed`）。blob が欠けるとサイズ欄が `BAD` になるだけで終了コードは 0 なので、これもここ
  - 設定が無い・内容が無効（診断つき）のときは `readFailed` ではない（従来どおり既定へ戻す）
- symlink・サブモジュール・BOM つきのファイルの扱い:
  - モードが `100644` / `100755` 以外（symlink・サブモジュール）か、blob でない: 無効（`not_regular_file`）
  - 4096 バイト超: 無効（`too_large`）
  - BOM は取り除いて読む
- 空のファイル（空白だけを含む）は「設定なし」と同じ（全体の既定・診断なし）
- 結果のキャッシュは blob の ID（と全体の既定の値）が鍵。HEAD が変われば blob の ID も変わるので、古さの問題が無い
- `pi.json` を持たないリポジトリで増える git の起動は、`ls-tree` の 1 回だけ。判定の結果は変わらない（自由区の例外は下の「自由区の fail closed」）

#### 検査と無効

- **未知のキー（どの階層でも）・型違い・サイズ超過・検査に落ちた値が 1 つでもあれば、設定全体が無効**。全体の既定のまま動き、診断を出す（綴り違いが黙って効かないのを防ぐ）
- `protected_refs`・`extra_protected_refs` は未知のキーではなく `protected_refs_not_allowed`（保護は全体設定で指定する）
- 検査の内容:
  - `target`: 空でない・ワイルドカード（`*` `?` `[`）を含まない・全体の保護の**完全一致の要素**
  - 接頭辞: 末尾が `/`・禁止文字（`*` `?` `[` `\` `~` `^` `:`・空白・制御文字・`..`・`//`・`@{`）を含まない・先頭が `/` でない・`refs/` で始まらない
  - **保護と交差しない**（大文字小文字を区別しない。`isProtectedRef` と同じ比較）
- 交差の判定（接頭辞 `P`・保護 `Q`）:

| 保護 `Q` の形 | 拒否する条件 | 例 |
| --- | --- | --- |
| 完全一致（ワイルドカードなし） | `Q` が `P` で始まる | `P = feature/`・`Q = feature/base` |
| `B/*`（末尾 `/*`） | `B/` が `P` で始まる、または `P` が `B/` で始まる | `P = release/`・`Q = release/*` |

- 重複する要素は 1 つにまとめる（エラーにしない）
- 診断は**固定のコードとキー名だけ**。入力の本文・値・パースの例外文は出さない

| 診断コード | 意味 |
| --- | --- |
| `invalid_json` | JSON として読めない |
| `not_object` | トップが object でない |
| `unknown_key` | 未知のキー |
| `protected_refs_not_allowed` | 保護の指定（全体設定でだけ指定する） |
| `bad_type` | 型が違う |
| `too_large` | ファイル・文字列が上限超過 |
| `too_many` | 配列が 8 要素超 |
| `bad_target` | `target` が保護の完全一致の要素でない |
| `bad_prefix` | 接頭辞の形が不正 |
| `prefix_overlaps_protected` | 接頭辞が保護と交差する |
| `not_regular_file` | 通常のファイルでない（symlink・サブモジュールなど） |
| `read_failed` | blob を読めなかった |
| `ls_tree_unparsed` | `git ls-tree` の出力を解釈できなかった |

#### 使う場所

| 場所 | 使う値 | 読む HEAD | 読めないとき |
| --- | --- | --- | --- |
| 自由区の判定（`freezone.ts`） | `free_zone_prefixes` | **主 worktree（git の common dir）** | **自由区にしない** |
| raw `git flow … finish` のプレビュー | `target`・`source_prefixes` | **cwd と主 worktree の両方** | **「確認できない」** |
| `/board` | `source_prefixes`・比較先の `target` | cwd | 全体の既定 |
| execute 直前の統合ゲート（S7） | `free_zone_prefixes`（自由区の判定をやり直す） | 主 worktree | 自由区にしない |

- **自由区は、feature 自身の HEAD の `pi.json` を読まない**。エージェントが自分で書いた設定で、自分の自由区を広げられないようにするため。設定の変更は、承認された統合で主ブランチに入るまで自由区に効かない。保護ブランチの拒否は残る
- raw `git flow … finish` の確認画面（`confirm-view.ts`）: squash（`--squash --squash-message "$(cat <path>)"`）は「(squash)」、**merge commit の finish（`-M` / `--merge-message`。`--squash-message` と同じ読み方）は「(merge commit)」**の見出しで、行き先・メッセージ・衝突の有無を先に出す（表示だけ。判定は変えない）。
  - チャット経由の統合の標準は `git flow feature finish <名前> --no-ff --no-squash -M "$(cat <メッセージ>)" --keepremote --no-fetch --no-push --notag`（bundle は squash すると取り込み元の枝が祖先にならず、`wt_clean.py` の判定が壊れるため merge commit）。`--squash` と `-M` の両方は squash 表示に警告を足す
- raw `git flow … finish` のプレビュー: cwd の HEAD と主 worktree の HEAD の**両方**を読み、どちらかが `target` か `source_prefixes` を既定から変えている・読めない・common dir を得られないときは、「統合の内容は確認できない」と出す（別のブランチの差分を見せない）。`free_zone_prefixes` だけの変更では止めない
- `/board`: 実効の `source_prefixes` で feature を拾う。**比較先は実効の `target`**（設定を読んだときは、設定が無い・無効でも、全体の既定か `pi.json` の値）。設定が有効で既定と違うとき・無効のときだけ、1 行を足す（`pi.json: 有効 (統合元 …)`・`pi.json: 無効 (コード)`）
- **execute 直前の再判定（S7）**: tool_call で決めた判定を再利用するときも、execute 直前に `tightenIntegration` をかけ直す（`index.ts`）。tool_call の後に主設定が変わって自由区でなくなっても、古い許可で実行しない。拒否・必須確認はそのまま、許可だけを再判定する。RPC の回帰試験がある（`test_s7_the_integration_gate_is_rechecked_just_before_execute`）
- **保護・分類器・統合ゲート（`judge/*`・`integration-gate.ts`）は変えない**。保護は全体のまま
- `.agents/config/pi.json` の変更は、`[pi.integrate] risk_paths` に入れると、PR ビューアの統合画面で「リスクのあるパス」として見える（[pi-decide.md](pi-decide.md)）

#### 自由区の fail closed

自由区は確認を省く側なので、設定の出所が信頼できない・読めないときは自由区にしない（`freezone.ts` の `classifyFreeZone`）。確認が増える側に倒れる。

| 条件 | 理由 |
| --- | --- |
| **common dir の HEAD が、保護ブランチ上の symbolic ref でなければ自由区にしない**（detached・判定不能・非保護ブランチ）。**設定の有無にかかわらず** | feature の worktree から `git update-ref --no-deref main-worktree/HEAD <OID>` で主 HEAD を広い設定のコミットへ向けられる。主 HEAD を設定の無いブランチへ切り替えて、狭めた設定を消せる（いずれも実 git で再現） |
| 設定を読めない（`readFailed`） | 狭めている設定を見落とすかもしれない。設定が無い・内容が無効のときは従来どおり既定へ戻す |
| 読み取りは `--no-replace-objects` | `git replace` で HEAD のコミットの中身を差し替えられないようにする |
| linked worktree の管理ディレクトリが `<common dir>/worktrees/` の下 | `.git` ファイルの書き換えによる偽の worktree を自由区にしない |

- **C2 の例外**: `pi.json` が無いリポジトリでも、主 worktree が detached・非保護ブランチ上だと、自由区は効かず確認が増える
- 保護ブランチの拒否（全体設定）は残る。観測の添え書き（`details.freeZone.profile`）は診断コードだけ（入力の本文・キー名は出さない）
- git の起動（linked worktree の自由区の判定）: `rev-parse` + `symbolic-ref`（feature）+ `symbolic-ref`（主 HEAD）+ `pi.json` の `ls-tree`（計 4 回。blob があれば `cat-file` がさらに 1 回）

#### 土台: 分類器が保護ブランチへの書き込みを網羅していること

- 自由区の設定の出所は「保護ブランチの先端は承認を経た」という前提に立つ。この前提は、分類器が保護ブランチへの直接の書き込みを確認なしで通さないことが基礎
- 別の feature で閉じた穴（[pi-decide.md](pi-decide.md) に記載）: 他の worktree の ref の別名（`main-worktree/…`・`worktrees/<id>/…`）への `update-ref`・`symbolic-ref`、`git replace`、`git fetch --refmap`・`-c remote.<名>.fetch=`
- **網羅は保証しない**。保証範囲は「ガードが識別する直接経路」。`git config remote.*.fetch` を先に書く 2 段の手順などは範囲外

#### pi の project trust との関係

- **連動しない**。project trust は `.pi` の設定・拡張の読み込みを決めるだけで、`pi.json` は別の仕組み
- 連動は後から足せる（未解決。[CHG-0057](../../change/0057-per-project-integrate.md)）

#### 既知の制限・未確認

- 主 worktree の HEAD が存在しないブランチを指す bare リポジトリでは、自由区が効かない（確認が増える側。コードの読解。実機は未確認）
- 主 worktree が detached・非保護ブランチ上のとき、自由区が効かない（C2 の例外）
- 独立 review は 4 回で止めた。残りは既知の制限として扱う

- 任意の外部プロセスによる HEAD の更新との競合を、完全に原子的に防ぐ保証ではない（既存の契約と同じ）
- **未確認**: Windows。実機（`pis`・実 TUI）での見え方
- 試験: `test_pi_integrate_profile.py`（純関数）・`test_pi_integrate_profile_load.py`（実 git の一時リポジトリ）・`test_pi_freezone_profile.py`（自由区・プレビュー・`/board`・S7。実 git と RPC）

### ツール引数の JSON を壊さない設定

モデルが出すツール引数の JSON が壊れる問題（`Invalid arguments for tool … in JSON`）への対処。pi 本体が引数の JSON を解析できないと、ツール側では救えない（`toolCall.argumentsError`）。

- **設定**: `models.json` の `providers.github-copilot.compat.supportsEagerToolInputStreaming: false`（Anthropic の細粒度ツールストリーミングを送らない。プロバイダー単位で、モデルの一覧を持たない）。配るファイルは `home/dot_pi/agent/models.json`。戻すときは、設定を外す。副作用は、ツール引数が完成するまで画面に出ないこと。
- **`pis` の内側**: agent ディレクトリは本物の `models.json` を写さず、**`providers.*.compat` だけ**を写す（`ocs/pi.py` の `_copy_provider_compat`。`apiKey`・`baseUrl`・`headers`・`models` は写さない許可リスト）。ブローカーの `baseUrl` とは合成される。
- **`strict`（厳密な JSON スキーマ）は採用していない**。Bedrock 経由の環境ではこの設定は効かず、同じ対処は要らない。原因の候補・実測・採らなかった理由・調べた範囲は [記録](../../research/agents/tool-arg-json-breakage.md)。

### ツールの拡張（`guarded_read` / `guarded_write` / `guarded_bash` の使いやすさ）

誘導の deny（[誘導](pi-decide.md#誘導)）が多発する原因は、代替が同等でないことと、ツール定義の説明が弱いこと
（[CHG-0038](../../change/0038-guard-reclassification.md) 段 G8。他の製品の調査は
[記録](../../research/agents/tool-design-survey.md)）。ハーネスは、pi の組み込みの定義を `...def` で展開して
`guarded_*` として登録し、`tools-ext.ts` で次を足す（pi 本体を import しない純関数。node で単体試験できる）。

- **説明の上書き**: `guarded_bash` は「実行（ビルド・テスト・git・`grep`/`find`/`ls`）に使い、ファイルの内容を読む・作る・変える用途に
  使わない」と、具体的な言い換え（`cat`/`head`/`tail`/`sed -n` → `guarded_read`、`echo >`・`cat > f <<EOF` → `guarded_write`、
  `sed`/`awk` → `guarded_edit`）、複数ファイルは並列の `guarded_read`、長い待ちは `bg_run` を書く。組み込みの snippet にあった、
  ファイル操作の `ls, grep, find` を勧める文は外した。`guarded_read`・`guarded_write`・`guarded_edit` にも、使い分けとトークン効率を書く
- **`guarded_read` の `tail`**: 末尾から N 行（`offset` と同時に指定するとエラー、`limit` は無視、32 MiB 超は不可）。総行数を数えて
  `offset`・`limit` に直し、組み込みの `read` を呼ぶ。判定は `path` に従来どおり掛かる
- **`guarded_write` の `append`**: 既存の末尾へ、`content` をそのまま連結（改行は自動で足さない）。組み込みの write の mutation queue・
  親ディレクトリの作成・整形・判定（`edit` の deny・ask・bypass）はそのまま
- **読みの失敗のヒント**: offset が範囲外のとき有効な範囲、存在しないとき同じディレクトリの似た名前（最大 3 件。`read_deny_globs` に
  当たるもの・`decide` が allow でないものは出さない）
- **拒否メッセージの言い換え**: 誘導の deny（読み取り・書き込みの 4 規則）の理由の末尾に、該当の断片と具体的な言い換え
  （`sed -n 'A,Bp' f` → `guarded_read {path, offset, limit}`、`tail -n N f` → `{tail: N}`、`cat >> f <<EOF` → `guarded_write {..., append: true}` など）
  を機械的に足す。パイプ・リダイレクト・`$`・グロブ・引用の閉じ忘れを含む断片、パースできない形には付けない。**deny の判定は変えない**
  （再試行のコストを下げる変更）
- **`guarded_edit` の失敗のヒント**: 失敗した結果の末尾に、次の一手を追記する（元のメッセージは消さない。`tool_result` で扱う。引数の不正は `execute` に届く前に起きるため）。見つからない → 最も近い箇所（行番号と、違う行の期待と実際。空白・タブ・改行コードの違いの可能性）。結果が同一 → newText がすでにあれば「適用済みの可能性（行 N）」。複数一致 → 一致した行番号と直前の行。引数の不正 → 編集を小さく分ける、全体の書き換えは `guarded_write`。重なり → 1 つにまとめる。ファイルが読めない・512 KiB 超・バイナリ・読み取り拒否のときは、ヒントを省く（本文は最大 3 行の抜粋）。純関数は `tools-ext.ts`、試験は `test_pi_tools_ext.py`。
- **`ask` の引数の正規化**: `prepareArguments`（スキーマ検証の前に呼ばれる）の純関数 `normalizeAskArgs`（`extensions/ask/normalize.ts`）で、よくある形の間違い（`question`・`options` がトップレベル、`question` が要素の外、`question` が無く `header` がある、`options` が文字列、`questions` が JSON 文字列、`multi` が文字列、`description` が無い）を直す。**意味を変える補完（推奨の自動付与など）はしない**。壊れた JSON は pi 本体が解析できず、ツール側では救えないので、説明に正しい例と「文字列に半角の `"` を入れない」を足して発生率を下げる。自前のエラー文にも正しい例を添える。`constrainedSampling`（プロバイダー側の厳密なスキーマ）は使わない（経緯は [記録](../../research/agents/tool-extension-measurements.md)）。
- **しないこと**: 複数ファイルの一括読み（並列の呼び出しで足りる）、`stdin` の引数（pi の bash は `command` と `timeout` しか受けない）、
  透過実行、`executable`

## ガード以外の機能

OpenCode のガードにあった機能のうち、pi へ移したもの。仕分けと経緯は
[CHG-0020](../../change/0020-pi-migration.md#段-5-の仕分け2026-10-09)。

### 圧縮（旧 checkpoint）

`session_before_compact` で、圧縮の要約の依頼に**引き継ぎの指示**（長さの上限 1 万 5 千字・前回の要約は丸ごと引き継がず作り直す・
表を使わない・Next Steps は手順と合格条件まで書く（詳しく書くのは最優先の 3〜5 件）・
略語を展開する・未作成の文書は「未作成」と書く・制約と却下済みの方針を残す）を足す。pi の要約はセッションに
残り、`pi -c` で再開しても消えないので、外部ファイル・skill・注入の印は作らない。

- `compact()` を `ctx.modelRegistry.streamSimple` 経由で呼ぶ。認証の解決結果の `baseUrl` をモデルへ反映する

- 失敗したら標準エラーと通知（端末の幅で切れないよう全文）へ理由を出して、pi の既定の圧縮に任せる（指示は補助で、圧縮は止めない）
- **`compact()` に、セッションの思考レベル（`pi.getThinkingLevel()`）と、一時的な失敗の再試行方針（pi の既定値に固定。利用者の `retry` 設定は拡張から読めないため）を渡す**。渡さないと、思考の無効を受け付けないモデルが 400 を返して既定の圧縮に落ちる（[表 B の 19](../pi-upstream.md#b-明示が無いここに書く)）。思考レベルが `off` で同じ 400 になったときは、思考を `minimal` にして 1 回だけやり直す
- **要約の思考レベルには上限 `low` を掛ける**（`capCompactThinking`。`off`・`minimal`・`low` はそのまま、より深いものは `low`）。要約の時間は出力の長さが支配的で、深い思考は要らないため（実測は [記録](../../research/agents/pi-compaction-failure-survey.md#要約の長さと所要時間2026-11-03-の実測)）。`off` には落とさない（無効を受け付けないモデルがあるため）
- `/compact <焦点>` の引数（`event.customInstructions`）は、引き継ぎの指示に【利用者の指定】として合わせる（自作の圧縮が成功すると既定の圧縮には進まないので、合わせないと捨てられる）
- 要約が出力の上限（`reserveTokens` の 0.8 倍）で切れたとき（`Summarization failed: generation hit the token cap …`。切れた要約は pi が保存しない）だけ、
  `reserveTokens` を倍にして **1 回だけ**やり直す
- 指示は履歴の要約にだけ入る。分割されたターンの前半の要約（`Turn Context`）には入らない（pi の仕様）
- **失敗の理由をセッションに残す**: 自作の圧縮が既定へ落ちたとき（`harness-compact-fallback`）と、本体の経路が失敗・中断したとき（`session_compact_failed` → `harness-compact-failed`）、理由の全文（4000 字まで。超えた分は `…(以下 N 字は省略)`）を `pi.appendEntry` で `custom` のエントリとして残す（モデルの文脈には入らない）。記録の失敗は標準エラーに 1 行出すだけで、圧縮は止めない。見方: セッションの `*.jsonl` で `"customType":"harness-compact-failed"`（または `-fallback`）を探す。成功した圧縮は記録しない
- `reserveTokens` を倍にする再試行は、pi 1.4.0 以降は効かない（本体が要約の出力上限を撤廃した。出典: pi の CHANGELOG 1.4.0）。1.3.0 以前向けに残してあり、撤去は別判断
- 別名のツールで触ったファイルは、これまでどおり要約のファイルの一覧に足す

#### 圧縮中の完了通知の保留

| 項目 | 内容 |
| --- | --- |
| 問題 | 圧縮（`/compact`。約 5 分）の最中に、背景ジョブ・子の完了通知（`triggerTurn: true` の `pi.sendMessage`）が届くと、通知が新しい発言を始め、圧縮が `Compaction cancelled` で中断される。利用者の入力には「圧縮中は送れない」確認があるが、`sendMessage` の経路には無い（pi 1.4.0 の `sendCustomMessage`） |
| 仕組み | 状態 `compacting` を、`session_before_compact` で true、`session_compact` / `session_compact_failed` で false にする。true の間の配信は保留し、false になったときに**登録順**に実行する（1 件が例外でも残りを実行）。圧縮していないときは即時で、挙動は変わらない。成功の `session_compact` は、pi が圧縮の状態を解く**前**に届く（失敗は解いた後）ので、成功のときだけ 1 tick 遅らせて解除する |
| 対象（harness） | `child-finished`（子 1 件・並列のまとめ）。`index.ts` の `createCompactDefer`。配信の失敗の扱い（`warnUser`）は保留した関数の中にあるので変わらない |
| 対象（activity） | バックグラウンドジョブの `flush`。作業中（`busy`）と同じく `compacting` でも溜め、終わりに `pending` が残り、まとめる窓のタイマーが無ければ 1 回だけまとめて配信する |
| 安全弁 | 終わりのイベントが来ない異常でも通知が永遠に出ないことを防ぐため、開始から 20 分（`COMPACT_DEFER_MAX_MS`）で自動的に false にして保留を流す。タイマーは `unref`。圧縮が続けて始まったらタイマーを張り直し、保留は残す。`session_shutdown` でタイマーを止め、保留は捨てる |
| 既知の制限 | ① 開始イベントより前の数ミリ秒の窓では保留できない ② `ctx.isIdle()` は圧縮中も false なので、`isIdle` での判定はできない ③ 通知を保留しても、別経路の中断（利用者が圧縮中に Esc を押す、など）は防げない |
| 試験 | `test/agents/test_pi_compact_defer.py`（harness は `index.ts` の `region compact-defer` の区画を node で実行。activity は偽の `pi`。配線は文字列で確認） |

#### 文脈の使用率による自動の保存と圧縮

旗 `PI_WORK_ARBITER=1` (既定は無効) のときは、この拡張と todo は `agent_before_settle` を登録せず、事実 (`checkpointSnapshot()`) と効果 (`checkpointExec`) を調停へ渡す。
圧縮完了後の自動再開は旗に関わらず従来の経路。旗と配線は [settle](work/settle.md#既存の-3-者の移し方-配線済み・旗つき-feature-work-settle-wire)。

文脈の使用率が閾値以上になったら、エージェント自身に保存させてから圧縮を起動する（`harness/autocheckpoint.ts`。親のセッションだけ）。

| 項目 | 内容 |
| --- | --- |
| 流れ | `agent_before_settle` で、使用率（`ctx.getContextUsage().percent`）が閾値（既定 80%）以上なら、保存の指示を `custom_message`（利用者にも表示）で積み `continue: true` で 1 回だけ継続する。次の settle で `ctx.compact({ customInstructions })`（上の引き継ぎの指示）を起動する。圧縮の完了・失敗のどちらでも 10 分の冷却に入る |
| 保存の指示 | sdd-docs で docs へ未反映の決定を反映し、`.tmp/keep/checkpoint/NEXT.md`（私用）を書き直し、todo を更新する。コミットしない・公開リポジトリの規約を守る・本体（develop）の docs は編集しない・サブエージェントを起動しない |
| ループ防止 | 保存の継続は 1 サイクルに 1 回。圧縮が済むまで、冷却が明けるまで、再び積まない |
| entries の合成 | pi は同じ settle の複数の拡張の `entries` を**後勝ちで置き換える**（`runner.js` の `emitBoundary`）。前の結果は `event.entries` に入るので、`agent_before_settle` を返す拡張は `entries: [...(event.entries ?? []), 自分の entry]` で引き継ぐ（autocheckpoint → todo の順で、保存の指示が todo のリマインドに消されていた）。両方残して 1 ターンに入れる |
| 何もしない場合 | 子・print / json モード・`PI_AUTOCHECKPOINT=0`・`percent` が null（圧縮直後など）・直前の実行が中断 / エラー |
| 中断・失敗 | 保存の実行が中断（Esc）されたら、その周期の圧縮は起動しない。保存の実行がエラーで終わっても圧縮は進める。`compact` が例外でも状態は戻る |
| 調整 | 環境変数 `PI_AUTOCHECKPOINT_PERCENT`（0 超 100 以下。不正値は 80）。無効化は `PI_AUTOCHECKPOINT=0`。設定ファイルには出していない |
| 再開 | 圧縮が**成功**（`onComplete`）したら、200ms 待ってから `pi.sendUserMessage(RESUME_PROMPT, { deliverAs: "followUp" })` で短い再開の指示を 1 回だけ送る（アイドルなら新しいターンが始まり、streaming 中なら followUp で待つ）。200ms は、pi が圧縮の状態を解く前に完了通知が届くため（`index.ts` の `session_compact` と同じ扱い）。待つ間に別の周期が始まった・無効化された場合は送らない。失敗・中断では送らない。1 周期に 1 回で、冷却（10 分）の間は新しい周期が始まらないので、再開で使用率が閾値を超えてもループしない。指示は `NEXT.md` の先頭と todo を読んで続け、判断待ちだけなら「待機」と答えて止まる。`PI_AUTOCHECKPOINT_RESUME=0` で再開だけを無効にする（全体は `PI_AUTOCHECKPOINT=0`） |
| 限界 | 保存の質は**エージェント次第**で保証しない（指示を守らない・docs の反映が不完全なことがある）。組み込みの自動圧縮（窓 − `reserveTokens` 付近）は**予備として残る**ので、保存より先にそちらが走ることもある。使用率は settle の時点でしか見ないので、1 回の長い実行の途中では働かない。再開の指示は、判断待ち・完了待ちだけのときも 1 ターン走る（「待機」と答えるだけ） |
| 試験 | `test/agents/test_pi_autocheckpoint.py`（`test/agents/pi/autocheckpoint_driver.mjs` が偽のイベントとコンテキストを handler へ渡す）。実機の確認は未実施 |

### 思考とツール出力の既定の折り畳み

- 思考のブロックは `[pi.settings] hideThinkingBlock = true` で、ツール出力は `quiet-notices.ts` が `session_start` で `ctx.ui.setToolsExpanded(false)` を呼んで、既定で畳む（スマホで読みやすくするため。表示だけ）。
- 展開は `ctrl+t`（思考）・`ctrl+o`（ツール出力）。戻し方: `hideThinkingBlock = false`、環境変数 `PI_FOLD_TOOLS=0`。UI なし・API なし・例外のときは何もしない。

### 自動の通知を畳む表示

方針: チャットには**会話と判断の要求だけ**が目に入るようにし、自動で出る通知は既定で 1 行に畳む。**表示だけ**で、モデルに渡す本文（`content`）は変えない（`harness/quiet-notices.ts` の純関数。`registerMessageRenderer`・`registerMarkdownTransformer`・ツールの `renderResult` で表示だけを差し替える）。

| 通知 | 出所 | 畳んだ表示（展開で全文） |
| --- | --- | --- |
| 子の完了（`child-finished`） | `index.ts`（`sendMessage`） | `✓ worker goal-eval 3:31 $0.58 · 完了 j7`（記号・役割・題名・所要・費用・状態・job id。幅 46 桁に収める。全角は 2 桁） |
| 背景ジョブの完了（`bg-job-finished`） | `activity/index.ts` | `✓ job make test · 完了 bg-3` / `✗ job … · 失敗 exit 2` |
| todo のリマインド（`todo-reminder`） | `todo/index.ts` | `📌 続き: 未完了 N 件` |
| 自動の保存（`autocheckpoint`） | `autocheckpoint.ts` | `💾 保存を指示（使用率 82%）` |
| 自動の再開（user メッセージ） | `autocheckpoint.ts`（`sendUserMessage`） | `▶ 再開を指示（自動）`（Markdown の変換。展開は不可） |
| `guarded_action` の結果 | `actions.ts`（ツール結果） | 成功は `✓ <repo> <branch> <ID> <件名>`・`pre-commit: 全 N 項目 Passed`・確認省略の注記。hook は**失敗したものだけ**全文 |

- **畳まない**: 失敗（`✗` 失敗・時間切れ・中断）・承認待ち（`⚠`）・警告（ツールエラー・形式検査・条件検査・本体の dirty）は、畳んでも 1 行に必ず出す（`⚠N件`）。確認画面・`ask`・`/btw`・エラー通知・`guarded_action` の失敗（`details` が無い結果）・`guarded_pr_summary` は今までどおり。
- **kill スイッチ**: `PI_QUIET_NOTICES=0` で従来の全文表示（renderer を登録しない）。既定は畳む。
- **モデルへの本文は不変**: `content`・`sendMessage` / `sendUserMessage` の引数は変えない（`details` に `id`・`title`・`percent`・`open`・`repo` を足しただけ。`details` はモデルへ渡らない）。試験は `test/agents/test_pi_quiet_notices.py`（失敗・警告が畳まれない・46 桁・全角・展開と kill スイッチで全文・配線）。
- 実 TUI・スマホ・Orca/Zed での見え方は未確認。

### セッションごとの一時置き場（`.tmp/s/<ID>/`）

[CHG-0042](../../change/0042-tmp-lifecycle.md)。作業ツリーの `.tmp/` に残骸が溜まる（実測で 31 GB）のを防ぐため、
フルガード（`harness/session-tmp.ts`）が、セッションごとの置き場を作り、`quit` で消す。

- **作る**: `session_start` で `<cwd>/.tmp/s/<セッション ID の末尾 8 文字>/`（権限 0700）を排他的に作り、`.owner`
  （JSON: `pid`・`start`（`/proc/<pid>/stat` の起動時刻）・`pidns`・`host`。権限 0600）を書き、`process.env.TMPDIR` をそこへ向ける。
  bash ツール・`bg_run`・子は `process.env` を基に環境を作るので、受け取る（実機で確認）。
  **セッション ID は UUIDv7 で、先頭 8 文字は時刻（約 65 秒は同じ）なので、ランダムな末尾を使う**。同じ名前の別のセッションの置き場が
  あれば、末尾を伸ばす（12・16・24 文字）。パスが 80 文字を超えるとき（ソケットのパス長の上限）は作らない
- **何もしない**: 子エージェント（`PI_HARNESS_CHILD=1`。親の `TMPDIR` を継承する。隔離子は従来どおり `/tmp`）・`pis` の内側
  （`PI_HARNESS_BOUNDARY=1`。`TMPDIR=/tmp` の tmpfs で、セッションごとに消える）・Windows・`<cwd>/.tmp` が無い/
  シンボリックリンク（`.tmp` を勝手に作らない）・`.tmp/s` がリンク
- **消す**: `session_shutdown` の `reason` が **`quit` のときだけ**、この実行（プロセス）が作った置き場を**すべて**消す。
  `new`・`resume`・`fork` では消さない（会話が旧置き場のパスを参照し続ける。pi が切り詰めた出力の全文のパスなど）。
  `reload` は同じセッションが続くので消さず、再読み込み後も同じ置き場を使う。**消す前に、その置き場を `TMPDIR` にしたまま
  生きているプロセス**（`/proc/*/environ`）がいれば、最大 3 秒待ち、まだいれば**消さない**（次の起動の回収が消す）
- **回収**: 起動時（`session_start` の `reason` が `startup`）に、`tmp_clean.py` を背景で呼ぶ。**持ち主の死亡を確証できた
  `s/<名前>/` だけ**を消す（SIGKILL・クラッシュ・RPC モードの SIGINT で残ったもの。実機で、`session_shutdown` が呼ばれないことを確認）。
  1 日に 1 回（`.tmp/.clean-stamp`）は、再生成できる名前（テスト・導入の一時）の掃除も行う。**未知の名前は消さない**
- **死亡の確証**: 同じホスト・同じ PID namespace で、`.owner` の pid が無い、または起動時刻が違う（pid の再利用）。
  別の namespace・`.owner` が無い/壊れている/書きかけ・`/proc` が無いときは残す。**年齢だけでは `s/` を消さない**
- 取り込み待ちは `.tmp/keep/<話題>/`（自動では消さない）。運用の置き場（`research`・`review-loop`・`away-shift`・`subagents`・
  `worktrees`・`checkpoint-*`）も消さない。`activity` の `bg_log` は、終わったジョブの実際のログのパスを保持する
  （`TMPDIR` がセッションで変わるため）
- 試験: `test_pi_session_tmp.py`（表試験。`session_tmp_driver.mjs`）。掃除のスクリプトは `test_tmp_clean.py`

### `git commit` の確認

`git commit -m …` の確認の本文に、件名・本文・追加するパスを出す。フルガードの置き場の純関数
（`~/.config/pi/harness/commit-message.js`）を取り込み、表示の幅と行数は
`[opencode.ask_description.commit]` を使う。読み込めなくても出さないだけでフルガードは止めない。

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は上の本文（[`git commit` の確認](#git-commit-の確認)）。

OpenCode の guide plugin には同じ内容の写しがあり（`test_pi_commit_confirm.py` が一致を確かめる）、
OpenCode の撤去（CHG-0020 の段 6）で写しごと消す。フルガードは OpenCode の置き場を読まない（CHG-0023 の段 3g の前半）。

### commit の確認 (素の pi)

フルガードを読まない `pi`（フルガードの読み込みに失敗した起動など）では、bash の git は素通りになる。その補助として、
小さな拡張 `~/.config/pi/commit-confirm` を用意している。**今は `settings.json` の `extensions` に入れていない**（Unix・Windows とも、フルガードに `git commit` の確認があるため。拡張本体の配備は残るが、Windows の settings は読まない）。必要なときは `-e` で明示して読ませる。
**保護ではなく補助**で、別名・スクリプト越しの git は検出しない。`!git commit`（利用者が手で打つ）も対象外。
`pis` は `-ne` で外れるので、フルガード自身の確認と二重にならない。

| コマンド | 扱い |
| --- | --- |
| `git push`（`-C dir`・`sh -c '…'`・`commit && push` も） | **確認せずに拒否**する。push は完全手動。連結した commit も実行しない |
| `git commit` | 構造にして見せて確認する（下） |
| それ以外 | 何もしない |

検出は、引用符の外のコマンドの先頭だけを見る小さな字句解析（`parse.ts`）。引用符の中の文字列
（`echo "git commit"`）や `git commit-tree`・`git stash push` は拾わない。

表示の例・一時 index の作り方・退避 ref の鎖の実装・実際のモデルでの確認は
[commit の確認の仕様メモ](../../research/agents/commit-confirm-spec-notes.md)。

#### 確認の表示

事実は git から取り、メッセージだけコマンドから読む（`describe.ts`）。生のコマンドは出さない。
出す項目は、リポジトリ（origin の URL。認証情報は出さない）、ブランチと上流との差、対象（ファイル数と行数）、メッセージ、注意。

- 対象は、**実行したらコミットされる内容**を一時のインデックスに再現して数える（通常・`-a`・`add … &&`・`git commit <パス>`・`--amend` の違いを吸収する）。
  HEAD・本物のインデックス・作業ツリーは変えない
- メッセージは `-m`（複数も）、`-F file`、`-F - <<'EOF'`、**`-m "$(cat <<'EOF' … EOF)"`**（エージェントの定番）を読む。
  本文は 72 桁・8 行まで、件名は切らない
- `--no-verify`・`--amend`・`-S`・`--allow-empty` は「注意」に出す。コミットする変更が無いときも書く
- **読めない形は「読めない」と言う**。`VAR=値 git commit`・`sudo git commit`・連結（`&&` 以外・`add`/`cd` 以外が付く）・
  パイプ・リダイレクト・`$VAR`・`$(…)`・`-e`（エディタ）・メッセージ無しは、
  「解釈できない形のコマンドです。次がそのまま実行されます:」と生のコマンドを（12 行まで）見せる。
  構造化の表示が、後ろに付いた操作を隠さないための規則
- **並んだ commit の限界**: pi は同じ応答の全呼び出しの `tool_call` を終えてから実行を始めるので、2 件目の表示は 1 件目のコミットがまだ入っていない状態で組む（2 件目は 1 件目の対象も含めて見せる）。実行の終わりを待つ案は、全呼び出しの確認が終わるまで実行が始まらないため、安全弁の時間まで止まって採れなかった
- 確認で実行する `git add` は一時のインデックスに対してだけ動くが、`.gitattributes` の clean filter は走る
  （`git commit` を承認すれば同じものが走る）。`core.fsmonitor` は切り、diff は `--no-ext-diff`

#### 時間切れと退避

確認が取れなかったとき（時間切れ・不在・画面なし）は、**コミットせず、内容を退避して作業を続けさせる**。

ここは素の pi の補助（`commit-confirm`）の節。フルガードの `guarded_action` の `git_commit` は、同じ方針を別の実装（表示前に確定した tree の保存）で行う（上の「退避」）。

- 期限は TUI が **15 分**（画面に残り秒が出る）、RPC など（Zed）が **5 分**。時間切れは拒否と同じ `false` で返るので、
  経過時間で見分ける。利用者が拒否したときは退避しない（「拒否した。続け方を確認する」と返す）
- 退避は、コミットの**オブジェクトだけ**を作り、`refs/pi/pending/<時刻>` に置く。
  ブランチ・HEAD・インデックス・作業ツリーは動かず、hook も呼ばれない。直前の保留を親にした**鎖**にする
- モデルには「コミットは実行していない。内容は `refs/pi/pending/…` に退避した。**再試行しない**。続きの作業を子（worker など）に
  背景で任せられるなら任せ、親は応答を終えて idle になる（退避は `/pending` で確認・破棄するだけで、承認して実行する経路は無い）。任せられる作業が無ければ、『保留したコミット』として
  ref・件名・対象を報告して終える」と返す
- **不在**: 時間切れの後は、利用者の入力（`input` イベント。拡張が起こしたものを除く）があるまで、次の確認で待たずに
  退避する。1 回の応答に並んだ commit も、先の確認が時間切れなら後ろを待たない
- **連結したコマンド**（`git commit … && 別の操作`）はコマンド全体を止める。退避は最初の `git commit` から**近似**する
  （今ステージされている内容と、そのメッセージ）。理由に「連結していた他の操作も実行していないので、commit と分けて実行し直す」と書く。
  最初の commit も読めないものは退避できない（その旨を返す）
- `--amend` は退避できない

後から見る・取り込む:

```sh
git log --oneline refs/pi/pending/<名前>          # 保留したコミット (鎖の全体)
git reset --soft refs/pi/pending/<最後の名前>     # HEAD だけ進める。作業ツリーは変わらない
git for-each-ref --format='%(refname)' refs/pi/pending/ | xargs -n1 git update-ref -d   # 全部捨てる
```

試験の期限は `PI_COMMIT_CONFIRM_TIMEOUT_MS` で縮める（本番では使わない）。

- Windows にも配る。`.chezmoiignore` は `.config/pi/` を戻し、除外するのは `landlock_exec.py` だけ。Windows 実機は未検証
- 試験: `test_pi_commit_parse.py`（解釈・表示・退避。node で直接）、`test_pi_commit_confirm.py`
  （pi + 偽のモデル。RPC・非対話・TMUX の TUI）

### 確認画面の手順の一覧

bash の確認（ask・必須確認）に、1 行のコマンドを**手順に解きほぐした一覧**を添える。**表示だけで、判定（`judge/`）には使わない**（案件 [CHG-0062](../../change/0062-pr-hub-simplify.md)・バックログ #98）。

```text
コマンド (全文):
cd /abs && git log --oneline | head -3 > /tmp/o

手順:
  1. 作業場所を `/abs` に変更
  2. `git log --oneline`（履歴を表示） を実行し、出力を次へ渡す
  3. `head -3`（先頭を表示） を実行し、標準出力を `/tmp/o` に書き込む（上書き） [副作用の候補: ファイルを書き込む]
```

- **作り方**: 同梱の `mvdan-sh`（mvdan/sh の GopherJS 版。`home/dot_config/pi/harness/vendor/mvdan-sh/`）の構文木から作る（`explain.ts`）。
  説明の語（git のサブコマンドなど）・副作用の印・ヒアドキュメントの本文のキーワードは固定の表で、モデルには作らせない
- **実測**: 実際の bash 呼び出し 8514 件のうち 8513 件を解析できた。1 件あたり約 0.2 ms、読み込みは約 72 ms（初回の 1 回だけ。遅延読み込み）
- **構造化する形**: `&&` `||` `;` パイプ・リダイレクト・`$(…)`・バッククォート・サブシェル・`{ }`・for / while / if・
  ヒアドキュメント（本文は命令と分け、Python・Node・シェルの本文は危ない語に印を付ける）・`xargs`・`find -exec`・`bash -c`・
  `env` / `time` / `nohup` / `sudo` の前置き。上限は手順 16・1 手順 200 字・入れ子 3 階層
- **原文に倒す形**: プロセス置換・関数定義・`case` / `select`・`eval`・`((`・構文エラー・入れ子の上限超え・mvdan-sh を読み込めないとき。
  その手順は「解析できない部分: <原文>」と出し、末尾に注意の 1 行を足す
- **配備**: `chezmoi apply` で `~/.config/pi/harness/vendor/` に入る。反映には pi の再起動が要る
- **折りたたみ**: 手順が 6 つ（`FOLD_OVER`）を超え、確認の理由に当たった手順があるときだけ、
  当たった手順・その前後 1 手順・副作用の候補つきの手順・「ほか N 手順」を残し、ほかを「… N 手順を省略 (原文で確認)」の 1 行にまとめる。
  手順の番号は元のまま。当たりが無く 6 手順以下のときは全部出す。原文（全文）は常に画面にある。
  **`hit` が無い長い一覧は、自明な読み取り・整形の手順（`echo`・`tail`・`git log` など。副作用の印・書き込みのリダイレクトが無いもの）だけを省略する**
  （`cd`・不明なコマンド・`rm`・`curl`・`git push` などは残す。残りが 0 なら全部出す）。**統合の確認は、統合の動詞（`git merge` など）を `hit` にする**。
  **当たりの位置情報を判定から渡すのは別の変更（フルガードの再設計）**。
  「当たった」は、規則のパターンを表示の側で照合した近似で、判定器が実際に当てた箇所と一致しないことがある
  （位置情報つきの判定は、判定の構文木化〔バックログ #100〕のあと）
- **保証の言い過ぎを避ける**: 一覧は**理解を助ける補助**で、判定ではない。解析が不完全なことがある。**常に原文（全文）を確認する**。
  mvdan-sh は 2021 年版で、新しい bash の構文に追随していない可能性がある（その場合は構文エラーとして原文に倒れる）。
  手順の切り出しは Offset（UTF-8 のバイト位置）に依存するので、日本語を含む原文の試験を持つ
- **更新**: 版を固定して取り込み、`vendor/mvdan-sh/README.md` の版・バイト数・sha256 と、`judge/syntax.ts` の期待値（`MVDAN_SHA256`・`MVDAN_BYTES`）を書き換える（試験が三者の一致を確かめる）。
  `index.js` は minified なので、pre-commit の整形（`end-of-file-fixer`・`trailing-whitespace`）と git の改行変換（`.gitattributes` の `vendor/** -text`）の対象から外す（書き換わると sha256 が変わる）
- **読み込み（`judge/syntax.ts`。判定にはまだ接続しない）**: 構文木の読み込みと小さな道具（`arr`・`typeOf`・`pos`・`end`・`cut`）を `explain.ts` から `judge/syntax.ts` へ移した。
  `index.js` のバイト列を読んで **sha256 を期待値と照合し、照合したのと同じバイトを `new Function` で評価する**（読み直さない。`createRequire` はパスから読み直すので使わない。
  `node:vm` でなく `new Function` なのは node・bun〔JavaScriptCore〕で同じに動くため）。GopherJS の初期化が書く `global.require`・`Error.stackTraceLimit` は評価の後で戻す。
  失敗（欠損・sha 不一致・評価の失敗・解析の失敗）は例外にせず `{ ok: false, why }`。判定に接続するときは、これらをすべて deny にする（決定済み）。
  vendor のディレクトリは引数で注入する（試験用の `PI_EXPLAIN_VENDOR` 環境変数は廃止。差し替えは `setDefaultVendorDir`）
- **自己診断**: `selfDiagnose()` が既知の 3 コマンド（`git push origin main`・`cd /x && git log | head -3`・`echo "確認"`）の文の数・語の位置（UTF-8 のバイト位置）を確かめる。
  `node judge/doctor.mjs`（型除去に対応した node か bun で実行）が、実行環境・sha・自己診断・読み込みと解析の時間・メモリの増分を出し、OK / NG を終了コード 0 / 1 で返す。
  NG の理由には「対処: `pis` の外のシェルで `chezmoi apply`」を添える
- 試験: `test/agents/test_pi_explain.py`（`explain_driver.mjs`。反例・日本語・読み込み失敗・代表 30 件の原文倒れ 3 件以下）、
  `test/agents/test_pi_syntax_runtime.py`（`syntax_driver.mjs`・`syntax_probe.ts`。vendor を壊したときの失敗・doctor・bun・**実際の pi の中での読み込み**。pi・bun が無い環境では skip＝未実測）

### 整形

`guarded_edit` / `guarded_write` の後に、`[[hooks]]` の `post_edit`（`markdownlint.sh`・`format-file.sh`）を宣言順に呼ぶ。ファイルの書き込みの順番待ち（`withFileMutationQueue`）の
中で行う。整形は黙って済ませ、markdownlint が残した違反（hook が exit 2 で返す警告）と、**整形で本文が変わったこと**（「[整形] … 先に read し直す」）だけを
結果の末尾に足してモデルへ返す。失敗しても編集は成功のまま。

- **同じ応答に同じファイルへの編集が並んだとき、整形は最後の 1 件の後に 1 回だけ行う。** 編集の間に整形が入ると、後ろの編集の `oldText`（整形前の本文を見て作ったもの）が整形後の本文と合わず、`The old text must match exactly` で失敗する（遅いマシンや承認待ちで、編集の開始がずれると起きやすい）。`message_end` で、その応答の `guarded_edit` / `guarded_write` の数をファイルごとに数え、`tool_result` で残りが 0 になった件が整形する（応答が別なら、それぞれの最後の後）
- 整形の hook は**非同期**で実行する（同期で待つと、整形の間、同じ応答の他の tool call の処理も止まる）
- 同じ応答の同じファイルへの編集が照合に失敗したとき、結果に「前の編集が先に適用されている。read し直し、変更を 1 回の `edits[]` にまとめる」を足す
- 並べずに 1 回の `edits[]` にまとめるのが本来の使い方（すべて元の本文に対して照合される）。ツールの説明にも「同じファイルへの `guarded_edit` を 1 つの応答に並べない」を足した
- 試験: `test_parallel_edits_to_one_file_are_formatted_once_after_the_last` ほか（`test_pi_harness.py`。整形の hook を呼ぶたびにログへ書く hook に差し替えて、回数を数える）

### fleet

`/fleet <依頼>`（`~/.pi/agent/prompts/fleet.md`）が、依頼を並列に動かせる作業に分け、`guarded_task`（`worker`）を
1 回の応答に並べて起動させる。指示文は `[pi.commands.fleet]` から作る。pi は 1 つの返答に並んだ tool call を
並列に実行する。`-ne` でもプロンプトテンプレートは読まれる（試験済み）。

### stepback

`/stepback [質問]`（`~/.pi/agent/prompts/stepback.md`）が、質問から具体的な固有名・数値・状況を取り除いた**ステップバック質問**（背景にある原理・概念・上位の問い。1〜3 個）を作って利用者へ示し、先にそれへ答えてから、その答えを根拠に元の質問へ答えさせる
（ステップバック・プロンプティング）。指示文は `[pi.commands.stepback]` から作る。

- **引数を省略した `/stepback`**: 会話の直前の利用者の質問と、それへの直近の回答を対象にし、「この回答をもっと俯瞰して見直す」依頼として扱う。
  直前の回答がどの粒度・前提で答えたかを踏まえてステップバック質問を作り、答え直しでは「直前の回答と何が変わるか」を示す。
  対象の決め方は、`$ARGUMENTS` が空かどうかをモデルが文面で判断するだけで、拡張のコードは無い。直前のやり取りが無いときは、対象を利用者に尋ねて止まる

- 利用者が打ったときだけ展開されるプロンプトテンプレートで、モデルが呼べるツールは作らない。ツールを増やさないので、ガードの判定・伏字化は変わらない
- 確かめるときは読み取りだけにし（状態を変えない）、確かめていないことは「未確認」「推測」と書かせる。元の質問が変更・実行の依頼でも、答え（方針）を出すところまでで止め、作業に進むかは利用者に確かめさせる
- ツール名に依らない文面なので、役割（`reader` など）を問わず使える。配る範囲は `/fleet` と同じ（Unix のフルガード側。Windows は `.chezmoiignore` で `prompts/` ごと除外）
- 試験: `test_pi_harness.py` の `test_stepback_prompt_template_*`（偽のモデルで、引数が `質問:` に入り本文が届くことまで。モデルが実際にどう答えるかは未確認）

### キーバインド

`~/.pi/agent/keybindings.json` は `[pi.keybinds]` の中身そのもの（ファイルごと生成器の持ち物）。今は
`app.interrupt` に Ctrl+C を足し、`app.clear` を外し、Ctrl+D で終了する（今の OpenCode の設定と同じ操作）。

### 共通の指示

`~/.pi/agent/AGENTS.md` は、Claude Code・Codex・Copilot と同じ共通の指示（`agent-instructions.md`。平らな 25 行。進め方の詳細はスキル `agent-workflow`）。

### Orca・Zed

- **Orca**: Orca は pi を起動するとき、ステータス表示の拡張を `~/.pi/agent/extensions/orca-agent-status.ts` に
  置く。`pis` は `-ne` で拡張を読まないので、Orca から起動したとき（`ORCA_AGENT_HOOK_PORT` がある）に限り、
  Orca の印（`@orca-managed-pi-extension`）がある拡張だけを `-e` で足す。サンドボックスの内側は `~/.pi/agent` を読めない
  ので使えない（状態表示は出ない）。Orca が `pi` と `pis` のどちらを起動するかは Orca 側の設定による
- **Zed など RPC で起動するクライアント**: 確認は `extension_ui_request` として届き、応えないと永久に待つので、
  TUI 以外では確認に 5 分の期限を付け、期限が来たら拒否する。クライアントが確認の要求（`confirm`）に
  対応していなければ、ask になる操作は拒否される
