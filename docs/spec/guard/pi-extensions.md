# pi の拡張と補助機能

pi のフルガードが持つ拡張と補助機能の仕様: 拡張の入れ方の方針（入口の選び方・外部の拡張・自作の拡張）、`guarded_action`、ツールの拡張、圧縮、`git commit` の確認、整形、`/fleet`、stepback、キーバインド、Orca・Zed。起動・設定・MCP は [pi のガード](pi-guard.md)、子エージェントは [pi の子エージェント](pi-subagents.md)、サンドボックスは [pis のサンドボックス](pi-sandbox.md)。

## 拡張の方針

**拡張は自作を基本とする**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)）。外部の拡張は、**どうしても必要で、自前実装が困難で、振る舞いを十分に確認したもの**だけを、
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
| `todo` | `todo` ツールと `/todos`。**リストは 1 つで、勝手には消さない**（同じ目標のための別目標は同じリストへ足していく）。ツールの操作は `list`（`all` で完了・中止も）/ `add`（`text` か `texts` で複数）/ `set`（`id` と `status`: `pending`・`in_progress`・`blocked`・`done`・`cancelled`。何度呼んでも同じ結果で、旧 `toggle` の取り違えが起きない）/ `update`（`text` か `note`）/ `remove` / `clear` / **`batch`**（`ops` に操作の配列。順に適用し、1 件でも失敗したら全体を適用せず、失敗した `ops[i]` を返す）/ **`replace`**（`items` でリスト全体を置き換える。`id` を付けた項目は引き継ぎ、載せない既存の項目は消える。Claude Code の `TodoWrite` 相当）。項目には**メモ `note`**（完了の根拠・引き継ぎ。80 字まで表示）を付けられる。変更の結果としてモデルへ返すのは、**変更の要約と、未完了の先頭 3 件・件数だけ**（全件は `list`）。`list` が返す一覧は未完了だけで、完了・中止は件数にたたむ。`in_progress` は同時に 1 件までが指示で、超えると結果に注意を出すが止めない。**`blocked`（`[~]`）は、ジョブ・子・利用者の返答など外部の完了待ち**で、未完了には数えるが、`in_progress` の同時 1 件の数と終了時のリマインドの対象には入れない。note なしで `blocked` にすると、待ち先を書く旨の注意を返す（拒否はしない）。**`in_progress` が残ったまま応答を終えようとしたとき、`agent_before_settle` で確認を促すメッセージ（`custom_message`）を足して続行を 1 回だけ要求する**（利用者の発言ごとに 1 回。中断・エラーで終わったときは出さない。切るには環境変数 `PI_TODO_NO_REMINDER=1`）。子の完了は `guarded_task` の `todo` で項目へ反映できる。`/todos` は全件を表示し、`/todos tidy`（完了・中止を片付ける）・`/todos clear` は**利用者専用**（モデルは呼べない）。状態はツール結果の `details` と、利用者の操作の custom エントリ（`todo-state`）に持つので、分岐・再開・圧縮のあとも、その時点に戻る（旧形式 `{ id, text, done }` も読む）。フッターに `📋 完了/全体 ▶ 作業中の項目`（全部完了なら `✅`）を出す |
| `plan` | `/plan` で切り替え。計画中は **`edit` / `write` / `bash` / MCP などのツールを外し**、`read` / `grep` / `find` / `ls` / `todo` / `task` だけを残す（`guarded_` 付きも同じ）。計画の指示を毎ターン注入し、番号付きの手順で終わったら「実行する / 続ける / 直す」を尋ねる。「実行する」でツールを戻し、実行を依頼する。**計画の間は、`guarded_task` が読み取り専用の役割（`reader`・`explorer`）の子しか起動・続行させない**（`globalThis.__piPlanMode` の印。単発・並列・続きの依頼・steer を拒否し、状態・abort・close は通す。計画の前から動いている書き込みの子は止めず、利用者へ知らせる。[CHG-0044](../../change/0044-plan-agent.md)） |
| `btw` | `/btw [--plain] <質問>`。いまの会話（user / assistant の本文とツール呼び出しの要約）を文脈に答える。**既定は、読み取り専用の子（`explore`）が、必要ならファイルを読んで確かめてから答える**（会話は新しい側 2 万文字まで。子の起動は、フルガードか Windows の `subagents` 拡張が `globalThis.__piAskReadChild` に置く入口を使い、上限は 3 分）。`--plain` は、ツールなしで**現在のモデル**が 1 回だけ答える（速い。会話は新しい側 6 万文字まで、上限 2 分）。**子が失敗したときは、理由を表示して終わる**（調べていない推測を答えとして出さない。ファイルを見ずに答えさせるなら `--plain`）。子の入口が無いときだけ `--plain` と同じ動きになる。答えは、端末の高さに合わせて**本文の窓だけを描くスクロールできる表示**に出し（↑↓ / j k で 1 行、Space / b で 1 ページ、g / G で先頭・末尾、Enter / Esc / q で閉じる。位置と閉じる案内は最下行）、会話履歴にもモデルの文脈にも残さない。返信はどの経路でも **2 万文字**で切り、「省略あり」を末尾に書く。子と `--plain` の指示は「画面 1 枚（約 20 行）に収める」。エージェントの応答中でも使える |
| `ask` | `ask` ツール。利用者へ選択肢つきの質問を**最大 4 問まとめて**尋ねる（`questions`: `question`・`header`・`options` 2む4 個（`label` と `description`）・`multi`）。画面は、**TUI では自前のパネル**（`ctx.ui.custom()`。問が複数のときは問ごとのタブと最後の「確認」タブ（Tab / Shift+Tab で移動。回答は保持して戻って直せる。確認タブで未回答を警告し、Enter で送信。Esc は全体の中止）。問が 1 つだけならタブも確認も無く、答えたらすぐ送る。選択肢と説明を縦に並べ、カーソルは ❯。複数選択は Space でカーソルを動かさずに切り替え、Enter で確定（チェックしたまま Tab で離れても回答として扱う）。`Type something.` はその行の下でその場で書き、Enter で確定（複数選択でもこの Enter で、チェックと自由記述をまとめて確定する）・Esc で一覧へ戻る。数字キーで行へ移動。IME のためフォーカスをエディタへ渡す）、**RPC（Orca・Zed）では 1 問ずつの `select` / `input`**（選択行は「1. ラベル」の 1 行だけで、説明は質問文の下に番号つきの一覧として出す。表示幅 64 カラムで自前に折り返して字下げし、選択肢の間に空行を入れる。RPC の複数選択は、チェックを切り替えるたびにカーソルが 1 個目に戻る）。長い行の折り返しで境界とカーソルが分からなくなったため）（TUI と RPC で共通。Orca と Zed でも動く）。全問に自由記述の行 `Type something.` を自動で足す（空の入力は記録せず選択肢へ戻る）。`Other` / `Type something.` / `Next` は選択肢のラベルに使えない（`reserved_label`。ほかに `no_questions`・`too_many_questions`・`duplicate_question`・`empty_options`・`duplicate_option_label`・`no_ui`）。**推奨の検査**: 各質問は推奨の選択肢をちょうど 1 つ（multi は 1 つ以上）持ち、先頭に置く。印は label の末尾の `(推奨)` か `(recommended)`（直前に空白を置く。全角括弧・大文字小文字可。label に残り、答えもそのまま返す）。違反は `missing_recommended`・`multiple_recommended`（multi 以外で 2 つ以上）・`recommended_not_first` で、違反した質問を全部 1 つのエラーにまとめ、直し方を添えて返す（形の検査の後。label は 60 字までなので短くする）。試験は `test_pi_harness.py`。戻りは `answers`・`unanswered`（0 始まりの番号）・`cancelled`。中断や時間切れのところから先は未回答として返る。**1 回の画面の待ち上限は 5 分**（試験用に `PI_ASK_TIMEOUT_MS`）。**UI が無い実行（print・子エージェント）では、`before_agent_start` でツールを外す**。`plan` 中も残る。設計は公開拡張（`rpiv-ask-user-question`・`pi-ask-user`）の README を参考にした（[調査 P3・P4](../../research/agents/pi-public-extensions-survey.md)）。タブ画面・プレビュー・メモは作らない（`ctx.ui.custom()` が必要で、RPC では出せない） |
| `notify` | **利用者の入力を待つとき、端末へ BEL（`\x07`）を 1 回送る**。送るのは、作業が完全に終わったとき（`agent_settled`。`agent_end` ではない）、フルガードの確認（`confirmInOrder`）を出す直前、`ask` の質問を出す直前。Zed の Terminal Threads は、フォーカス外の端末の BEL を通知にする（[Terminal Threads](https://zed.dev/docs/ai/terminal-threads)）。**TUI（`ctx.mode === "tui"`）のときだけ書く**。RPC では stdout が JSON 行の通信なので汚さない。試験は `test_the_bell_is_written_only_in_the_tui_not_in_print_mode`（鳴らさないことだけ。鳴ること自体は未確認）。ACP 経由の Zed（pi-acp）には効かない（[Z1・Z2](../../research/agents/zed-orca-pis-integration.md)） |
| `activity` | 動いている子エージェント（`task` / `guarded_task`）とバックグラウンドジョブの数を、入力欄の下の専用の 1 行（ウィジェット。起動モード・ToDo のステータス行とは別の行）に `🤖 2 subagents / ⚙️ 1 jobs` の形で常時出す（0 件の側は出さず、どちらも 0 なら消す）。1 秒ごとに数え直し、表示が変わったときだけ `setStatus` する。子は起動する側（`subagents` とフルガード）が `globalThis.__piChildren` に登録し、ジョブは `bg_run` が `globalThis.__piJobs` に登録する。ツールは `bg_run`（コマンドを切り離して起動し、ID を返す（ログのパスは見せない。`read_deny_globs` で読めないので、教えるとモデルが行き止まる。[実験 B1 の F4](../../research/agents/pi-bg-experiments.md)））・`bg_log`（状態とログの末尾と総行数。ID なしで一覧）・`bg_kill`（プロセスの木ごと止める）。pi の終了時には動いているジョブも止める。**ジョブが終わると `pi.sendMessage`（`triggerTurn: true`、`deliverAs: "followUp"`）で LLM へ終了を知らせる**（ID・exit・コマンド・ログ末尾 20 行）。 **2.5 秒の間に終わった分は 1 通にまとめる**（2 件以上は各ログの末尾 5 行。同時に終わる 12 件で 12 ターンになっていた。[B1 の F3](../../research/agents/pi-bg-experiments.md)）。 **終了後に `bg_log` で読んだジョブは通知から外し、全部が読み済みならターンを起こさない**（画面の通知だけ。B1 の F2）。 親が作業中は届けず、「まとめる窓が閉じた」と「`agent_settled`（`agent_end` ではない。再試行・圧縮・続行がその後に続くことがある）」の両方を満たしてから、読み済みを除いて届ける。アイドルなら、窓が閉じたときにすぐターンを起こす。 試験は `test_jobs_that_finish_together_wake_the_agent_once` / `test_a_job_read_with_bg_log_after_it_finished_does_not_wake_the_agent` / `test_a_job_not_read_still_wakes_the_agent_after_the_turn`（外すと落ちることを確認）。 ないとジョブ待ちで止まったターンが再開しない。`bg_kill` で止めたときと終了時の停止では送らない。一覧のコマンドは作らない（数だけ）。**待ち方の案内はツール側に置く（AGENTS.md には書かない）**: `bg_run` の `description` / `promptGuidelines` / 戻り値と、実行中のジョブの `bg_log` の戻り値に、「終了すると自動で通知が届く。`sleep` や `bg_log` の連打で待たず、他の作業を進めるか応答を終える」を入れた。試験は `test_bg_run_and_a_running_bg_log_tell_the_model_not_to_wait_by_sleeping_or_polling`。旧 `/agents` はこれに置き換えた |
| `delegate-nudge` | 親が委譲を忘れない契機の第一歩として、**通知なしで統計だけを取る**試作（N1a）。利用者の発言ごとに、読み取り系ツール（`guarded_read` / `guarded_grep` / `guarded_find` / `guarded_ls`、素の pi の `read` / `grep` / `find` / `ls`）の呼び出し回数・結果の行数と文字数・エラー数・ツール名ごとの回数、`guarded_task` の新規の子の起動数（agent ごと。status・steer・追加依頼は数えない）、それ以外のツール呼び出しの数を、`appendEntry("delegate-stats", …)` でセッションに 1 件残す（モデルの文脈には入らない）。**読んだ内容・パス・引数は入れない**。通知もツール結果の変更もしない（ハンドラは常に `undefined` を返し、例外は黙って無視する）。**子（`PI_HARNESS_CHILD=1`）では動かず**、`PI_DELEGATE_NUDGE=0` で止められる。`/delegate-stats` で直近 10 発言の要約と合計を出す。案件は [CHG-0031](../../change/0031-delegate-nudge.md)。**`own_extensions` に登録済み**（`common.toml.tmpl`）。試験は `test_pi_harness_extensions.py` の `test_delegate_nudge_*`（5 件） |

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

### guarded_action（承認つきの外部操作）

`git commit`・`gh issue comment`・`gh issue edit`（本文とタイトル）を、**1 回の承認で、ハーネスが組み立てた argv を、シェルを通さずに実行する**ツール（[CHG-0038 段 G11](../../change/0038-guard-reclassification.md)）。通常の ask（コマンドを見せて判断）と違い、内容を見せて承認を取り、承認した内容がそのまま使われる。
ガードは境界ではなく「うっかり防止」なので、**誤った経路（bash の直接実行）へ行かないよう寄せる**仕組みであって、経路の強制ではない（Python や curl 経由は迂回できる。強制が要る GitHub 操作は、トークンの権限側で行う）。

- **操作の表**: `common.toml` の `[[pi.actions]]`（`id`・`label`・`argv`・`fields`・`replaces`・`preview`）。生成器が検証して `rules.json` の `judge.common.pi.actions` へ出す。操作の追加は、表に項目を足すだけ（ツールは増えない）。今は `gh_issue_comment`（`repo`・`number`・`body`）、`gh_issue_edit_body`（`repo`・`number`・`body`）、`gh_issue_edit_title`（`repo`・`number`・`title`）、`git_commit`（`message`、任意の `dir`）。feature の起票・クローズ（`git flow`）と規約の強制は、この表から外した（[CHG-0050](../../change/0050-slim-guarded-action.md)、[ADR-0021](../../adr/0021-conventions-as-instructions-slim-guarded-action.md)。下の「撤去した操作と gate」）。フィールドの型は `repo`・`int`・`line`（1 行の短い文字列。`title` など。`argv` の 1 要素として直接渡す）・`text`（`file = true` の本文）。`line` は改行・制御文字を含められない（確認画面と `argv` の見え方がずれないように）。`gh` にタイトルのファイル渡しが無いので `line` を足した。issue の編集は、本文とタイトルを別の操作にしてある（片方だけ直すときに、もう片方を渡し直さなくてよい）。ラベル・担当者・状態の変更は対象外
- **ツール**: `guarded_action`（引数 `action` と `params`）。登録されるのは、役割の `tools` に `action` がある親の役割（`implementer`）だけ。子エージェント・読み取り役・探索役には無く、実行時にも拒否する。判定器は `action` を役割の許可だけで通し、**汎用の ask・確認は出さない**（確認は `execute()` が 1 回だけ行う）。
- **確認**: `select` で「承認して実行 / 編集して承認 / 拒否」。内容（`content` のフィールド）の全文、プレビュー、**実行する argv** を表示する（表示と実行は同じ配列）。**RPC（Orca・Zed など TUI 以外）では、詳細をチャットに出し、承認ダイアログは要点だけにする**: RPC の `select` は `title` と選択肢しか持たず、全部を詰めると chat UI（特にスマホ）ではみ出して承認の選択肢に届かないため。確認の前に、今までの詳細（全文・プレビュー・統計・argv）を**ツールの途中経過**（`execute` の `onUpdate`。RPC では `tool_execution_update`）として出し、ダイアログの `title` は「上記の内容で実行しますか」の 1 文だけにする（要点を繰り返さない。利用者の決定）。詳細には、対象のリポジトリ（作業ツリーの実体パス）・ブランチ・HEAD・本文の全文・ステージ済みの統計・argv と、退避の注意書き（`git_commit`）を出す。途中経過のイベントは pi が非同期に流し、ダイアログの要求より後に出ることがあるので、詳細を出した後に 300 ms 待ってからダイアログを出す（待たないと「上記」が見えない順になる。実測）。全文は「編集して承認」のエディタでも見られる。`argv` の中で `content` の値を含む要素は `<名前>` に置き換える（本文が 2 回出るのを避ける。実際に実行する配列は変えない）。**途中経過を出せないときは、詳細を見せずに承認させないよう、スマホ向けに縮めた詳細（本文は先頭 10 行・800 字、統計は先頭 8 件、空行なし、1 行 100 字）をダイアログに出す。** TUI はこれまでどおりダイアログに全部出す。**Orca が途中経過をチャットに表示するか、スマホで見やすいかは、実際の Orca では未検証**（公開の情報では確認できなかった）。子は拒否（`not approved:`）。**`git_commit` の無反応（`[pi.confirm] timeout_seconds`）・UI 無し・不在は、拒否ではなく退避して続行**（下の「退避」）。取消・中断・拒否と、`git_commit` 以外の操作の無反応・UI 無しは、拒否のまま。bypass でも省略できない。「編集して承認」は `editor`（timeout が無いので、選んだ後にだけ開く）、「拒否」は `input` で理由を任意に取る。
- **退避（`git_commit` の無反応・UI 無し・不在。CHG-0046）**: 承認が取れないときは、実行せず、**表示した内容**を `refs/pi/pending/<時刻>` に退避して、`not approved:` で始まる結果（`isError`）で返す。文言は「元の操作は未実行。内容は `<ref>` に退避した。再試行しない。この操作に依存しない作業を続け、最後に『保留したコミット』として報告する」（保存に失敗したときは、成功した ref を返さず、退避できなかったと返す）。
  - **表示の前に tree を確定**する（`snapshotStaged`。一時のインデックスで作り、実のインデックスへ書き戻さない）。表示する HEAD・ブランチ・インデックスの識別子は、この snapshot と一致していなければ、表示せずにやり直しを返す。時間切れのあとは、実のインデックスを読み直さず、確定した tree を保存する（待つ間に別の操作がステージを変えても、退避は表示した内容）。取れない（空・確定中に変化）ときは退避不能とし、確認画面にそう出して、時間切れは拒否になる
  - **時間切れ**は、自前のタイマー（`timeout_seconds`）が発火したときだけ。TUI の組み込みの期限は 3 秒遅らせた保険。利用者の取消（Esc）・呼び出し元の中断・例外・「拒否」は、退避しない
  - **不在**: 時間切れのあと、利用者の入力（`input` の `source` が `extension` 以外。`/pending` も含む）が無い間は、待ち列の中で、次の確認を出さずに退避する。入力の世代で、待機中の入力のあとの時間切れが不在を立てないようにする。`session_start` で初期化
  - 退避は**独立**した commit（親は表示時点の HEAD。ほかの退避を親にしない。コミットが無いリポジトリでは親なし）。出自は末尾の trailer（`Pi-Pending-Request`・`-Branch`・`-Head`）。保存・破棄の内部の git は、**hook を無効**（`core.hooksPath=/dev/null`）にして実行する
  - 確認画面には「N 分応答が無ければ、実行せず内容を退避して作業を続けます。編集・拒否理由の入力中は対象外」と出す。**編集して承認の `editor`・拒否の理由の `input` には期限が無い**（対象外）
  - **`/pending`**（利用者専用。モデルは呼べない）: `list`（新しい順）・`show <ref>`（差分の本文まで）・`drop <ref>`（到達用の ref を外す。オブジェクトは `git gc` まで残る。名前空間の外・symbolic ref は拒否。`--no-deref`）。取り込みは未実装（CHG-0046 の段 4）。**片付けは、ハーネスが自動で行う**（`reconcilePending`。モデルは消せない）: 同じ tree のコミットが `HEAD` の履歴（新しい側の 500 件）にある（取り込み済み）・同じ tree と起点の退避がより新しくある（重複）・30 日より古い、のどれかを、`git_commit` の成功の直後と `session_start` で消す。内容が変わった途中の状態は、期限まで残る
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

`session_before_compact` で、圧縮の要約の依頼に**引き継ぎの指示**（Next Steps は手順と合格条件まで書く・
略語を展開する・未作成の文書は「未作成」と書く・制約と却下済みの方針を残す）を足す。pi の要約はセッションに
残り、`pi -c` で再開しても消えないので、外部ファイル・skill・注入の印は作らない。

- `compact()` を `ctx.modelRegistry.streamSimple` 経由で呼ぶ。認証の解決結果の `baseUrl` をモデルへ反映する

- 失敗したら標準エラーと通知（端末の幅で切れないよう全文）へ理由を出して、pi の既定の圧縮に任せる（指示は補助で、圧縮は止めない）
- **`compact()` に、セッションの思考レベル（`pi.getThinkingLevel()`）と、一時的な失敗の再試行方針（pi の既定値に固定。利用者の `retry` 設定は拡張から読めないため）を渡す**。渡さないと、思考の無効を受け付けないモデルが 400 を返して既定の圧縮に落ちる（[表 B の 19](../pi-upstream.md#b-明示が無いここに書く)）。思考レベルが `off` で同じ 400 になったときは、思考を `minimal` にして 1 回だけやり直す
- `/compact <焦点>` の引数（`event.customInstructions`）は、引き継ぎの指示に【利用者の指定】として合わせる（自作の圧縮が成功すると既定の圧縮には進まないので、合わせないと捨てられる）
- 要約が出力の上限（`reserveTokens` の 0.8 倍）で切れたとき（`Summarization failed: generation hit the token cap …`。切れた要約は pi が保存しない）だけ、
  `reserveTokens` を倍にして **1 回だけ**やり直す
- 指示は履歴の要約にだけ入る。分割されたターンの前半の要約（`Turn Context`）には入らない（pi の仕様）
- 別名のツールで触ったファイルは、これまでどおり要約のファイルの一覧に足す

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
- モデルには「コミットは実行していない。内容は `refs/pi/pending/…` に退避した。**再試行しない**。コミットが要らない
  作業を続け、最後に『保留したコミット』として ref・件名・対象を報告する」と返す
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

`~/.pi/agent/AGENTS.md` は、Claude Code・Codex・Copilot と同じ共通の指示（`agent-instructions.md`）。

### Orca・Zed

- **Orca**: Orca は pi を起動するとき、ステータス表示の拡張を `~/.pi/agent/extensions/orca-agent-status.ts` に
  置く。`pis` は `-ne` で拡張を読まないので、Orca から起動したとき（`ORCA_AGENT_HOOK_PORT` がある）に限り、
  Orca の印（`@orca-managed-pi-extension`）がある拡張だけを `-e` で足す。サンドボックスの内側は `~/.pi/agent` を読めない
  ので使えない（状態表示は出ない）。Orca が `pi` と `pis` のどちらを起動するかは Orca 側の設定による
- **Zed など RPC で起動するクライアント**: 確認は `extension_ui_request` として届き、応えないと永久に待つので、
  TUI 以外では確認に 5 分の期限を付け、期限が来たら拒否する。クライアントが確認の要求（`confirm`）に
  対応していなければ、ask になる操作は拒否される
