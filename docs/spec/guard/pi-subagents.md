# pi の子エージェント

子エージェント（`guarded_task`）の仕様: 起動と役割、`review` への依頼の書き方、子を保持して追加依頼する job、子の操作、worktree 隔離。Windows の素の pi の読み取り専用の `task` と、二つの task を別物にしている理由も含む。起動・設定は [pi のガード](pi-guard.md)。

## Windows の子エージェント

Windows では `guarded_task` を使えないので、**読み取り専用の子エージェント `task`** を `subagents` 拡張で出す。shell・編集を持つ役割は出さない。

- 拡張 `index.ts`（`task` ツール）と `agents.json`（`[pi.agents]` から生成。`generate.py --target pi-subagents`）を Windows にだけ配る（Unix は `.chezmoiignore` で除外）。settings の `+extensions/subagents/index.ts` で明示ロードする
- 出すのは `read` `grep` `find` `ls` だけの役割（今は `explore` と `review`）。子は `<実行中の pi>（node 版は node + cli.js、バイナリ版は pi.exe） --mode json -p --no-session -ne --tools read,grep,find,ls` に、フルガードを読むフラグを足して起動する（`pi.cmd` のシェルを通さない）
- **子もフルガード付きで起動する**（役割 `reader`）。置き場 `~/.config/pi/harness` が読めなければ、子を起動せず理由つきで失敗する。親に印 `globalThis.__PI_FULL_GUARD__` が無ければ `task` を実行しない。したがって、子にも判定器と読み取り拒否・伏字化が効く。実機は未検証
- 境界（Fence）は無いので、サンドボックスとしての隔離は無い
- 子のモデルは `second_opinion` が `github-copilot/gpt-6.1-terra`。OpenCode の階層の `gpt-6-astra` は pi の Copilot 経由で使えない（`model_not_supported`）ので、`[pi.model.tier.github-copilot]` で上書きする（Unix のフルガードにも効く）。`gpt-6.1-terra` は pi のモデル一覧（`pi --list-models`）の Copilot には無く、「custom model id」の警告つきで動く（2026-10-27 に、短い応答とツール呼び出しで確認。一覧に載るのは `openai` の `gpt-6.1-terra` と、Copilot の `gpt-6.1-sol`）。以前は `gpt-6-sol`。`worker` は上書きしない（Sonnet 5.5 `#medium`。`review` と系統を分けるため）。**Bedrock の pi は、`second_opinion` が `us.openai.gpt-6.1-terra`**（`[pi.model.tier.amazon-bedrock]`）。**未確認**: pi から Bedrock の GPT-6.1 へのツール呼び出しと、推論の強さの指定（Bedrock は `additionalModelRequestFields.reasoning.effort`）。会社の機で確かめる。動かなければ、この表を消すと従来の `us.openai.gpt-6-sol` に戻る

## 二つの task を別物にしている理由

Windows の `task`（`subagents` 拡張）とフルガードの `guarded_task`（`registerTask` と `children.ts`）は、**統合せず別物のまま**にしている。

- **子の実行方式が違う**: `subagents` は 1 回だけ実行する `--mode json -p`、`guarded_task` は常駐できる `--mode rpc`（`Job`。並列・背景・`keep`・`steer`・`abort`）。後者の子はハーネスを `-e` で読み、`PI_HARNESS_*` を前提にする
- **`Job` は Windows で使えない**ので、`subagents` は読み取り役に限る
- **ずれは試験で止める**: 宣言は同じ `[pi.agents]` から出る。名前・モデル・読み取り専用の役割の説明と指示が食い違わないことを `test_pi_subagents.py::test_declarations_stay_in_step_with_the_full_guard_agents` が確かめる（`plain_description` を宣言した役割だけ、意図して違う）
- 重なる量・共通モジュールにしない理由は [記録](../../research/agents/two-task-tools-rationale.md)

## 子エージェント

`[pi.agents.<名前>]` に宣言し、親の `guarded_task` ツールで起動する。子は同じフルガードを付けた別の pi プロセスで、
**RPC モード**（`--mode rpc --no-session --no-approve -nbt -ne -e builtin:mcp -e <フルガード>`。`pis` と同じ保護条件）で
動かし、親の拡張が job として保持する（`children.ts`）。判定は子のフルガードが子の役割で行う。

| キー | 意味 |
| --- | --- |
| `profile` | 子の役割（`[pi.profiles]` の名前）。`task` を持つ役割は使えない（入れ子にしない） |
| `tier` | モデルの階層。今は `[opencode.model.tier.<プロバイダ>]` から引き、`#variant` を pi の思考の強さ（`:medium` など）に読み替える。無ければ親と同じモデル |
| `inherit_bypass` | 真なら、親が bypass のとき子も bypass で動く。ask に `git commit` などが残る役割には付けない |
| `description` / `system` | 親のツールの説明に出す説明と、子のシステムプロンプトに足す指示（`--append-system-prompt`） |

今の宣言（`common.toml.tmpl`）:

| 名前 | 役割 | 階層 | bypass を継ぐ | 今の OpenCode での相当 |
| --- | --- | --- | --- | --- |
| `explore` | `explorer`（`reader` + `wc` と読み取り専用の git） | 親と同じ | 継ぐ | `explore` |
| `review` | `explorer`（`explore` と同じ） | `second_opinion` | 継ぐ | `review` |
| `commit` | `committer` | `routine` | 継がない | `commit` |
| `worker` | `worker` | `worker` | 継ぐ | `fleet-worker` / `bypass-fleet-worker` |

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。最右列「今の OpenCode での相当」が対象。pi の仕様は表の左の列と [判定 API](pi-decide.md)。

`explore` に `tier` は付けない。`tier` が無いと生成される `model` が `null` になり、フルガードは親の現在のモデル（`ctx.model`）で子を起動する（`index.ts` の `agent.model ??`）。`/model` で親を変えると `explore` も追従する。

- 子は会話を見られない。**転写や差分の全文を渡すのではなく、意図と問いを渡す**（[review への依頼の書き方](#review-への依頼の書き方)）
- **モデルに存在を知らせる**: 自作ツールは `promptSnippet` が無いと system prompt の「Available tools」に載らず、
  モデルは関数定義の一覧に埋もれた `guarded_task` に気付きにくい（実際に「子が無い」と誤認した）。
  `registerTask` は `promptSnippet` と、`review` を使う場面の `promptGuidelines` を付ける。
  Windows の `subagents` 拡張の `task` も同じ（`todo` / `activity` も同様に対処済み）。試験は `test_task_tool_is_listed_in_the_system_prompt`
- **子の結果**: 子の RPC のイベントから、承認されなかった呼び出し（理由が `not approved:` で始まる。
  フルガードが付ける）・ほかのツールのエラー・最後の返答を拾う。承認されなかった呼び出しがあれば
  `blocked`（承認待ちで未完了）として、親のツールの結果をエラーにする。RPC の子は UI があるものとして確認要求
  （`extension_ui_request` の `confirm` / `select` / `input` / `editor`）を出すので、親は**即座に `cancelled`
  を返す**（親モデルは承認できない）。ask は bypass を継がない限り `blocked` になる
- 親を中断すると、子をプロセスグループごと止める
- 子の返答の本文にも伏字化を掛け、その後に 20000 文字で切り詰める
- 起動の前に、親の判定器で `task` を判定する（`tool_call` と `execute()` の両方）

### review への依頼の書き方

`review` は、親とは別系統のモデルに、親の判断を step back して検証させる役。**親が全部書く方式だと、親の解釈と取捨選択が混ざる**
（不利な事実が落ちる・前提ごと引き継ぐ）ので、親は意図と問いを書き、客観的な事実は子が自分で取りに行く。

| 親が書く | 子が自分で取る |
| --- | --- |
| 目的と制約 / 確かめたことと未確認のこと / 退けた案と理由 / 暫定の結論（最後に「疑う対象」と明記）/ 聞きたいこと | 差分（`git diff`・`git log`・`git show`）・対象のファイル・関連する `docs/` |

- `review` を `explorer` 役にしたのは、差分を親が貼らずに済ませるため。
- 子の指示（`[pi.agents.review] system`）は、先に目的だけから自分の案を考え、そのあと親の結論と比べる順にして、anchoring を避ける。親の「確認済み」は検証対象で、依頼文に無い関連箇所と不利な事実も探させる。材料が足りなければ推測で埋めず、何があれば判断できるかを返させる
- **指摘には改善案を付けさせる**（2026-10-27 から）: 子の指示（`[pi.agents.review] system` と `plain_system`、OpenCode の `[opencode.agents.review]`）と、`review-loop` の依頼の雛形（`references/review-prompt.md`）の出力の節で、**BLOCKER と MAJOR には必ず改善案**（具体的な直し方・採る場合の代償・確かめ方。複数案なら推奨を 1 つ）、**MINOR には 1 行の直し方**を付けさせ、NIT は任意にした。以前は「代替案は、採る場合の代償と一緒に示す」だけ（条件つき）で、`review-loop` の雛形も「提案（任意）」だったため、指摘だけで終わりえた。MINOR にも付けるのは、1 行で済み、直す側が往復せずに済むため
- 親への指示は、フルガードの `promptGuidelines`（`harness/index.ts`）と `AGENTS.md` の「別モデルへの相談」に書いた。Windows の素の `pi` は `git` が無いので、差分は依頼文へ貼る（`plain_system`）
- **既知の限界**: `git <サブコマンド> -- <パス>`（`git diff -- <パス>`・`git show <rev> -- <パス>`・`git log -- <パス>`）は通る。正規化後の先頭語が `git` のときだけ、`--` の後ろを別コマンドとして抽出しないため（`judge/normalize.ts`・`command_policy.py`。抽出を抑えるだけで、deny / ask / allow の判定は従来どおりコマンド全体に掛かる）。それ以外のコマンドの `--` の後ろ（`mise exec -- CMD`・`kubectl exec p -- git push` など）は従来どおり別コマンドとして評価される。試験は `test_double_dash_decisions`（`test_decide.py`）
- **未確認**: 実際のモデルで、依頼文の型が守られ、`review` の指摘の質が変わるか（試験は設定の整合と、子が `wc` と読み取り専用の git を使えることまで）

### 子を保持して追加依頼する（job）

`guarded_task` は 1 つのツールで 3 形式を持つ。形の排他は、スキーマではなく **`execute()` が確かめる**
（tool の最上位に `anyOf` を置くと拒む提供元がある。判定器は名前と役割だけを見る）。
**`false` / `""` / `[]` / `0` / `null` は「指定なし」として扱う**。厳格なスキーマのモデル（`gpt-6-sol`）は、使わない省略可能な引数もこれらで埋めて送る。
`agent` はスキーマがエージェント名の列挙なので、`""` も列挙に加えている（無いと `execute()` に届く前に pi の検証で拒まれる）。
この扱いが無いと `` `list` must be true `` で 5 回連続で拒まれた（[実験 B1 の F5](../../research/agents/pi-bg-experiments.md)。試験は `test_task_input_ignores_unused_arguments_filled_with_empty_values` と
`test_task_input_forms_accept_empty_fillers_but_still_reject_real_conflicts`）。

| 形式 | 入力 | 動き |
| --- | --- | --- |
| 新規 | `{agent, task, keep?}` | 子を起動して 1 往復を待つ。`keep` が無ければ完了で子を止める（従来と同じ）。`keep=true` なら idle で残し、`jobId` を返す |
| 追加依頼 | `{jobId, task}` | 残した子へ、履歴を保ったまま次の依頼を送る。`agent` `keep` `close` は付けられない |
| 停止 | `{jobId, close:true}` | 子を止める（冪等。無ければ「既に無い」を成功で返す） |

- **往復の終わり**は `agent_settled`（自動リトライ・圧縮の回復まで終えた境界）。`prompt` の応答の `disposition` が
  `started` でなければ失敗にする（前回の答えを返さない）。終了コードは使わない
- **最終状態**の優先順: 親の停止・中断・時間切れ（`closed` / `limit`）→ `not approved:` があれば `blocked` →
  最後の assistant の `stopReason`（`stop` / `toolUse` は `done`、`length` `error` `aborted` と未知の値・
  assistant 無しは `failed`）。途中のツールエラーはモデルが回復して `done` なら失敗にせず、件数だけ返す
- `done` 以外になった job は、その場で止めて**再利用しない**（未実行の操作を完了済みとみなした履歴から続けないため）
- 同じ job への依頼は 1 つずつ。`running` 中の追加依頼は待たせず `busy` で断る。`running` 中の `close` は即停止し、
  待っていた呼び出しには `closed` を返す。`jobId → 所有確認 → running` は await の前に同期で確定する
  （並列のツール呼び出しで競合しないため。`guarded_task` を逐次実行にしないこと）
- 生かしておく子の上限は 4（`running` も含む）。上限では追い出さず、新しい起動を断って jobId の一覧を返す。
  枠は spawn の前に同期で確保する。1 往復の待機は 15 分まで（超えたら `limit` で止める）
- job は起動時の cwd と役割を持ち、別の cwd・役割からの追加依頼は断る。`jobId` は乱数だが認証手段ではなく、
  所有の確認が本体
- **止まる契機**: `close`・`keep` 無しの完了・`done` 以外・セッションの終了と切り替えと `/reload`（`session_shutdown`）・
  `/bypass` の切り替え（起動時の bypass を持ち越させない）・親プロセスの終了。TTL は無い
  （忘れた job は上限のエラーの一覧で気付く）。止め方は stdin を閉じ、3 秒で終わらなければプロセスグループを SIGKILL
- モデルへは `promptGuidelines` で「後続が見込まれるときだけ `keep`」「追加依頼は返った `jobId` にだけ」
  「終わったら `close`」「消えたら要約を添えて新規にやり直す」を伝える
- 子が質問して止まり、回答で再開する形は**未対応**。子から親への通信は無い（結果の返却と、バックグラウンドの完了通知だけ）

### 子の操作: バックグラウンド・状態・steer・並列・モデル・ToDo

`guarded_task` に、引き続き 1 つのツールで次の形を足した（排他は `execute()` で確かめる。[調査 P2](../../research/agents/pi-public-extensions-survey.md)）。
見た目はフッター 1 行とテキストだけ。ウィジェットは作らない。

| 形 | 入力 | 動き |
| --- | --- | --- |
| バックグラウンド | `{agent, task, background: true}`（追加依頼も同じ） | ID をすぐ返す。完了は `pi.sendMessage`（`triggerTurn`・`followUp`）で親へ知らせ、ターンが再開する（`activity` の `bg_run` と同じ方式）。親の中断には縛られない。`keep` なしなら完了で子を止める |
| 状態 | `{jobId, status: true}` / `{list: true}` | 状態・経過時間・最後のツール・呼び出し数・トークン（子の assistant メッセージの `usage` の合計） |
| steer | `{jobId, steer: "..."}` | RPC の `steer`。子の今のターンのツール呼び出しが終わったあと、次の LLM 呼び出しの前に届く |
| abort | `{jobId, abort: true}` | RPC の `abort`。**今の往復だけ**止め、子は残す（状態 `aborted`。履歴は途中までで、`keep` なら追加依頼で続けられる）。`done` 以外で job を止める原則の例外（親が明示した中断だから） |
| 並列 | `{tasks: [{agent, task, model?, effort?}, ...]}`（最大 12） | 上限 4 は維持し、超えた分は断らず空きを待つ。結果は順に連結。上限は「生かしておく子」を数えるので、空きが 0 なら断る |
| モデルと effort | `model`・`effort`（単発と、並列の各項目） | [カタログ](../agent-model-assignment.md#子エージェントのモデルのカタログ)・親の完全な `provider/id`・宣言済みの役割の既定のモデルから選ぶ。`effort` は `minimal`〜`max` の 6 段（`off` は拒否）。**ユーザが指示したときだけ指定する**（省略すると役割の既定）。結果と状態に、使ったモデル・effort・既定か指定か・未確認・高コストの印を必ず出す。追加依頼では変えられない |
| ToDo | `{agent, task, todo: <id>}` | 子が `done` で終わればその項目を `done` にし、結果を `note` へ。それ以外はメモだけ（`todo` 拡張が `globalThis.__piTodoUpdate` を置く）。**`todo` ツールが有効な実行では、新しい子を起動する単発の形（`explore` / `review` / `worker`）に `todo` が必須**で、無いと `todo is required for <agent>: add a todo item for this work and pass its id as \`todo\`` を `error`で返し、子は起動しない（`commit`は任意。追加依頼・状態・steer・abort・close と、`tasks`の並列は対象外。項目の存在は確かめず、`todo`は整数かだけをスキーマで見る）。`todo` ツールが無い実行（todo 拡張を読み込まない試験など）では要求しない。試験は `test_task_requires_todo_*` ほか |

- **モデルと effort の選択**（`harness/model-choice.ts`。[CHG-0043](../../change/0043-model-catalog.md)）: 許可の集合は「カタログ（設定のプロバイダのもの）∪ 親の完全な `provider/id` ∪ 役割の既定」。
  `model` は `id` か `provider/id`（設定と違うプロバイダは、親の完全な `provider/id` と役割の既定に一致するときだけ）。優先順位は
  **明示の `effort` ＞ `model` の接尾辞（`id:level`）＞（同じモデルのとき）役割の既定の effort ＞ pi の既定**。起動には `--model provider/id[:effort]` を渡す
  （対応しない段は pi が丸める。`claude-sonnet-5.5:off` は 400 なので、`off` は選ばせない。実測）。`""`・`null` は「指定なし」。
  **親（LLM）が、ユーザの指示なしに高価なモデルを選ぶ危険は、確認画面なしで受容している**（利用者の決定。補い: 説明で「指示があったときだけ」と書く、結果に必ず表示する）
- **結果の形**: 見出し行（`child <役割>: <状態> [時間, 呼び出し数, トークン, 費用]`）→ **使ったモデルと effort の行** → 承認待ち → 警告（子のツールエラー。同じものは 1 つにし、5 件まで）→ job → `answer:` の順。
  エラーを答えに混ぜない
- **結果の保持と通知**: 完了した往復の結果（redact 済みの全文）は、30 分・最大 20 件（`FINISHED_TTL_MS`・`MAX_FINISHED`）だけ親のプロセス内に残し、`{jobId, status: true}` で引ける（`keep` なしで自動で消えた子も対象。引くときの切り詰めは 2 万字）。`close` した job の分は消える。
  バックグラウンドの完了通知（`child-finished`）の見出しには通番と起動・完了の時刻を付け、結果の全文を cwd 基準の `.tmp/subagents/<通番>-<job id>.md` にも書いて、通知の末尾にそのパスを示す（新しい順に 50 件、7 日を超えたものは消す）。
  完了した往復の結果には、答えがあるとき `- calls: <ツール名×件数>` の 1 行を足す。答えに標準形の見出し（結論・根拠・未確認・次の候補）が欠けていれば `format check (...)` の警告を足す。警告にとどめ、結果の本文は変えず、拒否もしない（`audit.ts`）。
  保存・通知・ToDo 反映の失敗は握りつぶさず、UI があれば `ctx.ui.notify`、無ければ stderr に警告する。セッションをまたいだ参照の境界は cwd と役割まで。
  実装の細部と試験は [job の結果の保持の仕様メモ](../../research/agents/pi-subagent-jobs-notes.md)。
- **時間の上限**: 1 往復は 15 分。上限の 80% で、子へ steer で「まとめに入れ」を送る（途中の結果を残すため。送ったかの直接の試験は無い）
- **利用者コマンド**: `/agents`（一覧）、`/agent <名前> <依頼>`（子を直接起動。完了はチャットに表示するだけで、モデルのターンは起こさない）。モデルは呼べない
- **フッター**: `activity` が、動いている子が 3 件以下なら `🤖 explore 12s, review 40s`、それより多ければ件数
- **やらないこと**: プロジェクト内の定義ファイルからの役割（`--no-approve` と衝突）、子から子（入れ子）
- **worktree 隔離**: `guarded_task` の `isolation: "worktree"`（opt-in。単独の新規 `worker` のみ）。仕様は [CHG-0029](../../change/0029-worktree-isolation.md)。

### worktree 隔離の場所と承認

- **場所**: `<リポジトリ根>/.tmp/worktrees/pi-agent-<job id>`。`.tmp/` が `.gitignore` で除外されていなければ起動を拒否する。回収は `refs/pi-agent/<job id>` と `.tmp/subagents/<通番>-<job id>.patch`、記録は `.tmp/subagents/worktrees/`。掃除・回収のやり直しは利用者専用の `/worktrees`（モデルは呼べない）
- **隔離の worktree の作成と回収は、ハーネスが内部で `git` を実行する**（判定器を通らない）。子の書込範囲は Landlock で、その worktree・共有 `.git` の `worktrees/pi-agent-<id>`・`objects` などに狭める
- **親（`pi` 本体）が worktree のファイルを編集するときの承認**は、通常の書き込みと同じ。そこが作業ツリーの中（`cwd` の実体パスの下。`decide.py` の `_inside`。`.tmp/worktrees/…` を含む）なら allow、外（`~/worktrees/…` など）なら ask（境界つきでは、開けていない場所は deny）
- **親が `git worktree` を `bash` で直接実行したとき**: `add` / `list` / `prune` は規則に当たらず ask（`source: default`。`pis` で境界が証明されたセッションでは、[手順 4'](pi-decide.md) の緩和で allow）。`remove` は `[bash] deny`（作業内容を失うため）
