# pi の子エージェント

子エージェント（`guarded_task`）の仕様: 起動と役割、`review` への依頼の書き方、子を保持して追加依頼する job、子の操作、worktree 隔離。Windows の素の pi の読み取り専用の `task` と、二つの task を別物にしている理由も含む。起動・設定は [pi のガード](pi-guard.md)。

## Windows の子エージェント

Windows では `guarded_task` を使えないので、**読み取り専用の子エージェント `task`** を `subagents` 拡張で出す。shell・編集を持つ役割は出さない。

- 拡張 `index.ts`（`task` ツール）と `agents.json`（`[pi.agents]` から生成。`generate.py --target pi-subagents`）を Windows にだけ配る（Unix は `.chezmoiignore` で除外）。settings の `+extensions/subagents/index.ts` で明示ロードする
- 出すのは `read` `grep` `find` `ls` だけの役割（今は `explore` と `review`）。子は `<実行中の pi>（node 版は node + cli.js、バイナリ版は pi.exe） --mode json -p --no-session -ne --tools read,grep,find,ls` に、フルガードを読むフラグを足して起動する（`pi.cmd` のシェルを通さない）
- **子もフルガード付きで起動する**（役割 `reader`）。置き場 `~/.config/pi/harness` が読めなければ、子を起動せず理由つきで失敗する。親に印 `globalThis.__PI_FULL_GUARD__` が無ければ `task` を実行しない。したがって、子にも判定器と読み取り拒否・伏字化が効く。実機は未検証
- 境界（Fence）は無いので、サンドボックスとしての隔離は無い
- 子のモデルは `second_opinion` が `github-copilot/gpt-6.1-sol`（2026-10-27 に、Terra から Sol へ揃えた）。`deep` は pi の Copilot だけ `claude-sonnet-5.5#xhigh`。OpenCode の階層の `gpt-6-astra` は pi の Copilot 経由で使えない（`model_not_supported`）ので、`[pi.model.tier.github-copilot]` で上書きする（Unix のフルガードにも効く）。`gpt-6.1-terra` は pi のモデル一覧（`pi --list-models`）の Copilot には無く、「custom model id」の警告つきで動く（2026-10-27 に確認）。カタログには残し、明示の指示のときだけ使う。`worker` は上書きしない（Sonnet 5.5 `#medium`。`review` と系統を分けるため）。**Bedrock の pi は、`second_opinion` が `us.openai.gpt-6.1-sol`**（`[pi.model.tier.amazon-bedrock]`）。**未確認**: pi から Bedrock の GPT-6.1 へのツール呼び出しと、推論の強さの指定（Bedrock は `additionalModelRequestFields.reasoning.effort`）。会社の機で確かめる。動かなければ、この表を消すと従来の `us.openai.gpt-6-sol` に戻る

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
子の system（`--append-system-prompt`）の先頭には、全役割共通の前置き（`index.ts` の `CHILD_PREAMBLE`）を足す。AGENTS.md・個人用の指示のうち親の責務（委譲・取り込み・全件検査・コミットと承認・`ask`）は子に適用せず、依頼文を優先させる。子は既定で AGENTS.md を全文で受ける。`[pi.child] context = "extract"` にすると役割ごとの抜粋になる（[子の文脈の抜粋](#子の文脈-agentsmd-の抜粋-chg-0059)）。試験は `test_pi_harness.py::test_child_system_prompt_starts_with_the_preamble_then_the_role`。

| キー | 意味 |
| --- | --- |
| `profile` | 子の役割（`[pi.profiles]` の名前）。`task` を持つ役割は使えない（入れ子にしない） |
| `tier` | モデルの階層。今は `[opencode.model.tier.<プロバイダ>]` から引き、`#variant` を pi の思考の強さ（`:medium` など）に読み替える。無ければ親と同じモデル |
| `inherit_bypass` | 真なら、親が bypass のとき子も bypass で動く。ask に `git commit` などが残る役割には付けない |
| `timeout_minutes` | 1 往復の上限（分。1〜120 の整数。省略は 15）。「まとめに入れ」の steer は、この上限の 80% で送る。深く考える `plan` だけ 30 |
| `check_conditions` | 真なら、依頼の守る条件の番号（行頭の `C1: …`）が、返答の「守る条件の突き合わせ」の節に全部あるかを検査し、欠けていれば結果に警告を出す（`plan` だけ。下の「`plan`（計画役）」） |
| `description` / `system` | 親のツールの説明に出す説明と、子のシステムプロンプトに足す指示（`--append-system-prompt`） |

今の宣言（`common.toml.tmpl`）:

| 名前 | 役割 | 階層 | bypass を継ぐ | 今の OpenCode での相当 |
| --- | --- | --- | --- | --- |
| `explore` | `explorer`（`reader` + `wc` と読み取り専用の git） | 親と同じ | 継ぐ | `explore` |
| `review` | `explorer`（`explore` と同じ） | `second_opinion` | 継ぐ | `review` |
| `plan` | `reader`（bash なし） | `deep` | 継がない | なし（OpenCode の `plan` は別物） |
| `commit` | `committer` | `routine` | 継がない | `commit` |
| `worker` | `worker` | `worker` | 継ぐ | `fleet-worker` / `bypass-fleet-worker` |

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。最右列「今の OpenCode での相当」が対象。pi の仕様は表の左の列と [判定 API](pi-decide.md)。

**`plan`（計画役。[CHG-0044](../../change/0044-plan-agent.md)）**: 大きく複雑な変更・曖昧な要件・移行の、実装の計画を、読み取り専用（`read`・`grep`・`find`・`ls`）で調べて作る。
`reader` にするのは、`explorer` の bash では共通の `skill_scripts` の許可が通り、読み取り専用を指示だけでは強制できないため。Git の差分や履歴は見られないので、要るなら親が依頼文に載せる（返答には、確かめていない範囲を書かせる）。
階層は `deep`（Copilot は Sonnet 5.5 の `xhigh`、Bedrock は Opus 5.5 の `high`）で、`bypass` は継がない。`effort` は、ユーザが指示したときだけ変える（`max` は 17〜18 分かかるので、`plan` だけ 1 往復の上限を 30 分にしている）。
依頼文は自己完結で、**目的・前提・守る条件（`C1: …` と番号つき）・対象のパス・必要な Git の情報・返答の形式**を書く。返答は、結論・手順・変更するファイルの一覧・守る条件の突き合わせ・根拠・リスク・検証の方法・利用者に確認すべき点・未確認・次の候補の順。
**番号の検査（警告だけ）**: `check_conditions` の役割の結果で、依頼の番号が、見出しに「守る条件」を含む節（次の見出しまで）に全部あるかを見る。節が無い・番号が欠けていれば、`conditions check (…)` を結果に足す。**番号の一致は、条件を満たす証明ではない**（内容は親が確かめる）。`C1` と `C10` は取り違えない。依頼に番号が無ければ検査しない。
測定は [CHG-0044](../../change/0044-plan-agent.md)（`medium` は存在しない関数名などの誤りが多く、`xhigh` 以上で質が上がる。独立した採点で 15.0 対 20.5〜21.5 点）。

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
  枠は spawn の前に同期で確保する。1 往復の待機は役割の上限（`timeout_minutes`。省略は 15 分）まで（超えたら `limit` で止める）
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
- **計画モード（`/plan`）の間**: 書き込みの権限を持つ役割（`worker`・`commit`）の子は、起動（単発・並列）も、既存の子への続きの依頼・steer もできない（`plan` 拡張が立てる `globalThis.__piPlanMode` を、`guarded_task` が見る）。読み取り専用の役割（`reader`・`explorer`）は動く。状態・一覧・abort・close は通す。並列は、1 つでも書き込みの役割があれば全体を拒否する。計画の前から動いている書き込みの子は止めない
- **時間の上限**: 1 往復は、役割の `timeout_minutes`（省略は 15 分。`plan` は 30 分）。上限の 80% で、子へ steer で「まとめに入れ」を送る（途中の結果を残すため。送ったかの直接の試験は無い）
- **利用者コマンド**: `/agents`（一覧）、`/agent <名前> <依頼>`（子を直接起動。完了はチャットに表示するだけで、モデルのターンは起こさない）。モデルは呼べない
- **フッター**: `activity` が、動いている子が 3 件以下なら `🤖 explore 12s, review 40s`、それより多ければ件数
- **やらないこと**: プロジェクト内の定義ファイルからの役割（`--no-approve` と衝突）、子から子（入れ子）
- **worktree 隔離**: `guarded_task` の `isolation: "worktree"`（opt-in。単独の新規 `worker` のみ）。仕様は [CHG-0029](../../change/0029-worktree-isolation.md)。

### 子の文脈 (AGENTS.md) の抜粋 (CHG-0059)

子に渡す AGENTS.md（グローバルと作業先・祖先）を、全文ではなく**役割ごとの抜粋**にできる。**既定は従来どおりの全文（`inherit`）**。設計と経緯は [CHG-0059](../../change/closed/0059-child-context.md)、実測は [記録](../../research/agents/child-context-probe.md)。

| 項目 | 内容 |
| --- | --- |
| 設定 | `[pi.child] context = "inherit" \| "extract"`（`common.toml.tmpl`） |
| 環境変数 | `PI_HARNESS_CHILD_CONTEXT`（親。設定より優先）。未知の値では子を起動しない |
| 起動契約 | 親が子へ `PI_HARNESS_CHILD_AGENT`（役割名）と `PI_HARNESS_CHILD_CONTEXT` を渡す。`commit` 役など 4 役以外は常に `inherit` |
| 子側 | `PI_HARNESS_CHILD=1` かつ契約が `extract` のときだけ、`before_agent_start` で**毎メッセージ** `contextFiles` の `AGENTS.md` / `CLAUDE.md` を役割ごとの抜粋に変える |
| 役割 | `explore` / `review` / `plan` / `worker`。`explore` と `review` は profile が同じだが、役割名で別の抜粋になる |

**動作表**（子の役割が 4 役のとき。`extract` の列は子が受けるもの）:

| ファイルの状態 | `inherit` | `extract` |
| --- | --- | --- |
| 導入前（有効な識別子も有効な印も無い。普通の HTML コメント・印に似た行も無視） | 全文 | 全文（他のリポジトリの規約を守る） |
| 導入済み・正常 | 全文 | その役割のブロックだけ |
| 導入済み・破損・未分類・未知の役割・未知の版 | 全文 | **子は終了**（`exit 78`。原因つき） |

- 導入済み = いずれかの有効な識別子・有効な印・識別子の書き損じがある。**`child-context` で始まる有効でない行は、導入前でも破損**
- 印に似た行 = `<!--` の直後の語が `child` / `parent` の行。導入前では無視、導入済みでは破損
- 詳細の表（コードブロック・識別子の欠落・役割のブロックが 0 件など）は [CHG-0059 §4.1](../../change/closed/0059-child-context.md#41-記法と契約)

**失敗のしかたと除外する経路**:

| 項目 | 内容 |
| --- | --- |
| 失敗 | stderr に原因を出して `exit 78`。親は子の結果を失敗とし、原因を返す。黙って全文にも抜粋にもしない |
| 入力の形が契約違反 | `contextFiles` が配列でない・要素がオブジェクトでない・`path` / `content` が文字列でない。同じく終了 |
| 除外する経路 | `PI_HARNESS_CHILD=1` だけの子・契約が無い子・`inherit`・4 役以外・**`PI_SUBAGENT_CHILD=1`（Windows の別の `subagents` 拡張の子。契約変数が親から残っていても対象にしない）** |
| メッセージごと | `contextFiles` はメッセージごとに元の内容で渡されるので、毎回変換する（[実測](../../research/agents/child-context-probe.md)） |
| `{systemPrompt}` を返す拡張 | 返り値が全体を決め、文脈の書き換えは効かない。今の拡張に `before_agent_start` で返すものは無いが、新しい拡張を足すときは注意する（検出は無い） |

**観測**:

- 結果の見出しに `- 文脈: inherit` または `- 文脈: extract` の 1 行
- `PI_HARNESS_CHILD_CONTEXT_REPORT=<パス>`（試験用）: 決定ごとの JSON 1 行（`path`・`kind`・`why`・`blocks`・`before`・`after`。本文は入れない）

**戻し方**（C6）:

1. `[pi.child] context` を `inherit` に戻す（または `PI_HARNESS_CHILD_CONTEXT=inherit`）
2. **起動済みの子を終了する**（子の契約は起動時に決まり、起動後は変わらない）
3. **親を再起動する**（環境変数を変えるには、起動済みの親へは届かないので、この場合は再起動が必須。`/reload` だけでは、親の環境変数は変わらない）

**正本の記法と、新しい行の足し方**（正本: `home/.chezmoitemplates/agent-instructions.md`・各リポジトリの `AGENTS.md`）:

| 記法 | 意味 |
| --- | --- |
| `<!-- child-context: v1 -->` | 導入済みの識別子。ファイルの最初の空でない行 |
| `<!-- child:<役割> -->` 〜 `<!-- /child -->` | 子向け。役割は `explore` / `review` / `plan` / `worker` / `all`（カンマ区切り） |
| `<!-- parent -->` 〜 `<!-- /parent -->` | 親だけ |

- **見出し以外の行は、子向けか親だけのブロックの中に置く**。ブロックの外に置くと、導入済みのファイルでは「未分類」で子の起動が失敗する（見出しの行だけが外にあってよい。抜粋には入らない）
- 印は行全体がその 1 つのコメントのときだけ。入れ子・閉じ忘れ・未知の役割は破損
- 文章の途中に印を書くときは、行頭を `<!--` にしない（正本の「印を無視して全文に従う」という注記は、行頭が普通の文）
- 試験と検査: `test/agents/test_child_context_sources.py`（正本 2 つが `lint` を通ること・各規則が役割ごとの期待どおり抽粋に入ること）。**新しい規則を足したら、同じ試験の `RULES` に役割別の期待を足す**（子向けのブロックを足したときは必須。抽粋に入らないところでは任意だが、分類を残すので足すことを勧める）

**既知の制限**（[CHG-0059 §8](../../change/closed/0059-child-context.md#8-未解決未確認)）:

| 項目 | 状態 |
| --- | --- |
| 導入前を全文継承した理由 | 通常の経路では出ない（観測の記録のみ） |
| 非隔離の子の `exit 78` 後のプロセス後始末・MCP 子孫の残留 | **未確認** |
| 祖先の `AGENTS.md` の二重化 | 保持（S5 で評価） |
| Windows の `process.exit`・`writeSync(2)` | **未確認** |
| 他の CLI（Codex・Copilot・OpenCode）の HTML コメントの扱い | **未確認**（公式資料を先に検索） |
| 実モデルが抜粋で規約を守るか | **未確認**（S5） |

### worktree 隔離の場所と承認

- **場所**: `<リポジトリ根>/.tmp/worktrees/pi-agent-<job id>`。`.tmp/` が `.gitignore` で除外されていなければ起動を拒否する。回収は `refs/pi-agent/<job id>` と `.tmp/subagents/<job id>.patch`、記録は `.tmp/subagents/worktrees/`。掃除・回収のやり直しは利用者専用の `/worktrees`（モデルは呼べない）
- **隔離の worktree の作成と回収は、ハーネスが内部で `git` を実行する**（判定器を通らない）。子の書込範囲は Landlock で、その worktree・共有 `.git` の `worktrees/pi-agent-<id>`・`objects` などに狭める
- **親（`pi` 本体）が worktree のファイルを編集するときの承認**は、通常の書き込みと同じ。そこが作業ツリーの中（`cwd` の実体パスの下。`decide.py` の `_inside`。`.tmp/worktrees/…` を含む）なら allow、外（`~/worktrees/…` など）なら ask（境界つきでは、開けていない場所は deny）
- **親が `git worktree` を `bash` で直接実行したとき**: `add` / `list` / `prune` は規則に当たらず ask（`source: default`。`pis` で境界が証明されたセッションでは、[手順 4'](pi-decide.md) の緩和で allow）。`remove` は `[bash] deny`（作業内容を失うため）

### 並列実装の運用（隔離なしの worktree）

複数の独立した実装を、**子（`worker`）を並べて**進める手順。素の `pi` では、子の強制の囲い（`isolation: "worktree"`）が使えない（認証のロックの書き込みが拒否される。[CHG-0029](../../change/0029-worktree-isolation.md) の E6。保留）ので、
**隔離なし**で、feature ごとの worktree（`.tmp/worktrees/<名前>/`。作業ツリーの中なので書き込みは allow）に作業場所を分け、**指示と取り込み前の検査**で混線を防ぐ。囲いではない（下の「限界」）。

**前提**: 子が止まらずに動くには、**親の bypass の継承**か、`pis` の境界が要る（無いと、日常の shell の ask で止まる）。bypass でも、`mustConfirm`・deny（`git add`/`commit`/`checkout`/`reset`/`stash`、元に戻せない git 操作）は残る。**子の `git status`/`git diff` は、通常は ask（`[pi.shell] allow` に無い）で、bypass か境界で通る**（子に許可を足す案は、引用で `--output` の検査を回避できる穴と、`cd` で別リポジトリへ行く形の信頼の範囲が指摘され、保留）。

**手順**（親が行う。チェックリストと踏みやすい落とし穴は、スキル `feature-orchestration`）:

1. 作業を、**ファイルの範囲が重ならない**単位に分ける（同じファイルを 2 つの単位が触ると、`finish` で衝突する）。単位ごとに、変更してよいパス（`--owned` に渡す glob）を決める。
2. 単位ごとの feature と worktree（`name` は小文字・数字・`.`・`_`・`-`）は、**親が** `git flow feature start <name> --worktree --no-fetch` で起票する（起票は機械では止めない。[CHG-0050](../../change/0050-slim-guarded-action.md)）。
3. 単位ごとに `guarded_task`（`agent: "worker"`、`background: true`。同時に 4 本まで）で子を起動する。依頼文は下の雛形。`isolation` は付けない。
4. 子の完了の通知ごとに、**取り込み前の検査**: `python3 scripts/parallel_check.py --owned <名前>=<glob>,… …`（本体の変更・範囲の外・重複を見る。終了コード 1 なら、原因を確かめるまでコミットしない）。あわせて、その worktree の差分を確かめる（親が `cd <wt> && git diff --stat`・`git diff`）。
5. 検査を通った単位だけ、親が `git add` する（**整形 hook の直後は数秒待ち**、`git diff --cached --numstat` で空のファイルや行数の急減がないか見る）。続けて `git_commit`（`dir` に worktree。`message` は 1200 字以下。feature の linked worktree は確認なし。[CHG-0053](../../change/0053-worktree-integration-gate.md)）。子は `git add`/`commit` できない（deny）。新しい試験ファイルは `scripts/verify.py` の `_PI_TESTS` へ、`index.ts` から import される新しい `.ts` は試験用のコピー一覧へ、親が登録する（登録漏れは全件検査の後で落ちる。`test/test_verify.py` が 2 秒で先に見つける）。
6. 全件検査（`mise run verify:all`）は親が 1 回（`bg_run`。同時に 1 本。同じリポジトリの全 worktree・全会話で、排他ロックが機械的に保証する。[検証の方針](../development.md#全件検査の排他)）。通ったら、単位ごとに順番に `git flow feature finish <name> --squash …` で取り込む（**cd を付けず本体のルートで実行する。先頭が `git flow feature finish` でないと、確認画面に squash メッセージと衝突の事前検査が出ない**。**`bypass` でも必須確認**。承認画面が出る。承認が時間切れなら、再試行せず利用者の指示を待つ）。先に `finish` した単位の後で残りが衝突するなら、解決して `git add` し、`git flow feature finish --continue <ブランチ名>`（名前なしでは失敗する）。
7. 失敗した単位は、`git flow feature delete <name>`（必須確認）で捨てる。

**取り込み前の関門 `scripts/feature_gate.py`**: `python3 scripts/feature_gate.py check <feature> --owned <glob,glob>` は読み取り専用の関門で、scope（担当外の変更）・numstat_drop（行数の急減）・register_tests（試験の登録漏れ）・register_harness_copy（試験用コピー一覧の登録漏れ）を見る。実 index・ref・作業ツリーは変えない（git のオブジェクトは書く）。

**子への依頼文の雛形**（`<…>` を埋める。子は会話を見られない）:

```text
## 目的
<この単位で達成すること。1〜3 行>

## 作業場所（厳守）
- 作業は <リポジトリのルート>/.tmp/worktrees/<名前>/ の中だけ。ファイルの読み書きは、このディレクトリの絶対パスで行う。
- 変更してよいのは次のパスだけ: <glob の一覧>。これ以外（ほかの worktree・本体のファイル）は、読むだけで変更しない。
- コマンドは、cd <worktree> && <コマンド> の形で実行する（git -C は使わない）。git add・commit・checkout・reset・stash はできない（親がコミットする）。
- 共通の約束（ツールの制約・報告形式・時間制限）は、`.agents/skills/feature-orchestration/references/worker-common.md` を読む。

## 守る条件
C1: <変えてはいけないもの>
C2: …

## 完了条件・確かめ方
- <実行する試験のコマンド（cd <worktree> && …）と、通る条件>

## 返答
- 変更したファイルの一覧、試験の結果（コマンドと出力の要点）、確かめられなかったこと、判断に迷った点。
```

**限界**: 子が、ほかの worktree や本体を書き換えても、**強制では止まらない**（bypass 中は、作業ツリーの外の書き込みの ask も allow になる）。`scripts/parallel_check.py` が、取り込み前に、**Git が報告する変更**（追跡ファイルの変更と未追跡ファイル。リネームは旧パスも数える）の範囲で見つける。ignore されたファイル・worktree の外（例: `~`）への書き込み・symlink の先は見えない。子へのコミットの許可（`guarded_action` を子へ）は、親の手数が許容できないと分かるまで、作らない（親が diff を確かめてからコミットする方が安全）。

### 積み重ね（依存する feature）

feature B が、まだ `develop` に入っていない feature A の変更を要るときの運用。A の承認（保留）を待たずに B を進められる。手順のチェックリストは、スキル `feature-orchestration`。

- **許可の状況**: feature の worktree の中の `git merge feature/<A>`、A の先頭からの起票（`git flow feature start <B> feature/<A>`・`git switch -c`）は、保護ブランチを動かさないので、統合の必須確認にはならない。判定器の結果は、通常モードで確認（`ask`）、bypass で許可。`git rebase` は共通の deny のまま（履歴を書き換えない）。保護ブランチへの統合は、今までどおり必須確認（または保留の承認）。
- **依存は宣言しない**: git の祖先関係から導く。B の先頭が、他のローカルの feature ブランチ G の先頭を祖先に持ち、G が `develop` に統合されていないとき、G は B の依存。G を足しても `develop` の内容が変わらないもの（squash で統合済みで、ブランチだけ残っている）は除く。宣言ファイルは古くなるので作らない。
- **関門**: `parallel_check.py`・`feature_gate.py` は、依存 G の `develop...G` の変更パスを、B の変更から引く（担当外・重複の誤検知を防ぐ）。出力に `depends on:`。B の未コミットの変更は引かない。限界: B が G のファイルを**コミットで**さらに編集しても検知されない。先頭が同じ 2 つのブランチは、互いを依存に数えない。
- **承認画面**: `git_integrate`（計画の `stacked`）は、統合元が未統合の他の feature/bugfix を含むとき、「含む他の feature (未統合): <名前, …> — この統合に含まれる。先に個別に統合すると、この統合が衝突することがある」を 1 行出す。その feature を統合する保留が未承認のときは、名前の後ろに「 (保留 …<末尾 4 桁> が未承認)」を付け、複数行で出す（状態が pending のものだけ。読めないときは保留の記述なし）。表示だけで、保留の記録・再検査・承認の判断には使わない。
- **順序**: **積み重ねは先頭の B だけを保存・承認する**。コミットは分けてよいが、統合の保存は先頭の 1 件。B は A のコミットを含むので、A の変更も一緒に統合される。
  - 理由: A を先に squash で統合すると、develop には A の内容が入るが、A の元のコミットとは繋がらない。B が A のファイルをさらに直していると、あとの B の統合は 3 方向 merge で衝突する（`conflict`）。承認のたびに再発するので、下から 1 件ずつ承認する運用は成立しない。実例: 2026-11-03 の PR ビューアの積み重ね 6 本（[CHG-0060](../../change/0060-local-pr-viewer.md)）。最初の 3 本は通ったが、4 本目から衝突して止まった。
  - 下の A の保留は承認せず破棄してよい（`/pending drop`）。
  - **強制はしない**（A を捨てて B だけ入れたいとき・A が古くなったとき・循環で詰まるため）。B を先に入れると、あとの A は `no_change`（統合しても内容が変わらない）で断られる。
  - 復旧（A を先に統合し、B が `conflict` で断られるとき）: B の枝へ develop を「枝の側を優先」で取り込む。
    1. `git merge-tree --write-tree -X theirs --name-only develop feature/<B>` で tree を作る（`ours` は第 1 引数 = develop の側。枝の側は `theirs`）。
    2. 検証: 「B の先頭 → その tree」の差が develop だけにある変更だけであること（`git diff --stat feature/<B> <tree>`）。`scripts/verify.py` など共有ファイルに無関係な変更が無いこと。
    3. `git commit-tree <tree> -p feature/<B> -p develop -m "merge: develop を取り込む"` で merge commit を作り、B の worktree で `git merge --ff-only <commit>`。
    4. `git merge-tree --write-tree --name-only develop feature/<B>` が衝突しないことを確かめ、B を新しい保留として保存し、古い保留を `/pending drop` で破棄する。
- **規則**: マージは親だけ（子は git を書けない）。衝突は止めて報告する（LLM に直させない）。
- **見送り**: 依存の宣言ファイル・汎用 DAG。配車（[CHG-0056](../../change/0056-orchestrator.md)）の `needs` は「統合済みを待つ」計画上の前提で、積み重ね（コミット済みの先頭から始める）とは別のもの。
- **試験**: `test_parallel_check.py`・`test_feature_gate.py`（関門）、`test_pi_integrate_plan.py`・`test_pi_integrate_action.py`（`stacked`・`no_change`）。

### 複数の会話を並行して使う運用

1 つのリポジトリで、pi の会話（セッション。Orca・Zed など別の入口のスレッドも同じ）を**同時に複数**動かすときの規則。
長い作業を話題ごとに分ける（会話の文脈を軽くする）ときや、利用者が複数の画面から指示するときに使う。

**前提**: 会話どうしは、**共有の `.git`（ref・オブジェクト）を共有し、作業ツリー（worktree）だけが別**になる。feature の worktree は `.tmp/worktrees/<名前>/` で、本体の作業ツリーは 1 つしかない。
`git flow feature finish` や `git merge` は**本体の `develop` を進め、本体の作業ツリーを書き換える**ので、同時に 2 つの会話から行うと、衝突の解決と確認の承認が混線する。

**規則**（強制ではなく運用。機械が守るのは 4 だけ）:

1. **取り込みの窓口を 1 つの会話に決める**。保護ブランチを進める操作（`git flow feature finish`・`git merge`・将来の `/pending approve`）は、**窓口の会話だけ**が行う。ほかの会話は、feature の**コミットまで**で止め、取り込みの依頼を窓口へ渡す（利用者が窓口の会話で「取り込んで」と言う）。`finish` は必須確認なので、承認の画面も窓口の会話だけに出る。
2. **1 つの worktree は、同時に 1 つの会話（または 1 つの worker）だけが編集する**。ほかの会話の worktree や本体を、編集しない。
3. **同じファイルを触る話題は、同時に進めない**。共有されやすいファイル（`common.toml.tmpl`・golden・docs の索引・`index.ts`・`actions.ts`・`scripts/verify.py`・試験用のコピー一覧）は、1 つの話題だけが持つ。衝突は、窓口が `finish` で解決する。
4. **全件検査（`mise run verify:all`）は、排他ロックで自動的に 1 本ずつ**になる（[検証の方針](../development.md#全件検査の排他)）。ほかの会話の検査を待つ間は、`bg_run` で待つか、ほかの作業をする。
5. **引き継ぎのファイルは、会話ごとに別**（`.tmp/keep/checkpoint/<話題>-….md`）。同じファイルを 2 つの会話が書かない。
6. **会話の切り替え・再起動・終了は、動いている子と `bg_run` のジョブが無いときに行う**。pi が終われば、その pi の子とジョブも止まる前提で運用する（止まった検査は、最初からやり直す）。
7. **新しい会話の始め方**: 最初に、その話題の案件の docs（`docs/change/`）と引き継ぎのファイルを読ませ、「取り込みはしない。コミットまでで窓口に渡す」と伝える。設計・決定は、会話の中ではなく docs に残す（会話は圧縮で細部が落ちる）。

**限界**: 規則 1〜3・5〜7 は指示で守る（機械では止めない。[CHG-0050](../../change/0050-slim-guarded-action.md) と同じ方針）。窓口の会話が不在でも、ほかの会話は取り込めてしまう（`finish` の承認は利用者が見る 1 回だけが砦）。

### 親の絞り込み（orchestrate）

親を「計画・判断・委譲・承認」に絞り、作業（実装・コマンドの実行）を子へ寄せる仕組み。**命令（プロンプト）ではなく、ツールと判定で強制する**（[CHG-0045](../../change/0045-orchestrator-parent.md) 段 6。設計の経緯は [調査記録](../../research/agents/orchestrator-role-plan.md)）。
**今の範囲は、役割と切り替えまで**（段 1〜2）。親専用の検査操作（`check_*`）と、親の読み取りの制限は、まだ無い。

- **役割 `orchestrator`**（`[pi.profiles.orchestrator]`）: `tools = ["read", "grep", "find", "ls", "task", "todo", "ask", "action"]`、`default = "deny"`（許可リスト）。`bash`・`edit`・`write`・`bg_*`・MCP を持たない。
  生成器（`pi_orchestrate`）が、許可リストであること・`task` を含むこと・作業のツールを含まないこと・実装役（`[pi] default_role`）のツールの部分集合であることを検査し、満たさなければ生成を止める
- **切り替え**（`[pi.orchestrate] default = "off"`）: 起動時の状態は `PI_HARNESS_ORCHESTRATE`（`1` / `0`）か `default`。実行中は、**利用者専用の `/orchestrate on|off|status`**（`/bypass` と同じ形で、モデルが呼べるツールは作らない。OFF は確認なし）
- **二重の防御**: (1) ON の間は、`before_agent_start` で毎ターン `setActiveTools` を、役割の許可リストに絞る（`/plan` など他の拡張が一覧を戻しても、次のターンで絞り直す）。切り戻しのために、絞る前の一覧を持つ。
- **切り替えと確認待ちの競合**: `/bypass` と `/orchestrate` は権限の世代番号を進める。確認待ちの間に世代が変わったら、その承認は無効（`block`）にし、実行前の判定でも、世代が違う判定は使わず現在の役割で判定し直す。**`/reload` を跨いで利用者の選択を保つ**（切り替えのたびに `PI_HARNESS_ORCHESTRATE` を更新する。モジュールの変数は `/reload` で消えるため）
  (2) 判定器の `role` を、呼び出しごとに評価する（`orchestrate ? "orchestrator" : 起動時の役割`。`judge/call.ts`）。役割に無いツールは deny（bypass でも）。拒否の理由に、「作業は `worker` に任せる。通常の親に戻すのは利用者」を添える
- **使えない起動**: 子（`PI_HARNESS_CHILD=1`）・Windows（子を作れない）・設定が無い・`task` を持たない役割では、何もしない（`/orchestrate` は理由を表示して終わる）。子の挙動は変わらない
- **親が失う操作の代替**: 作業・検証は `worker`、調査・git の状態は `explore`、コミットなどは `guarded_action`（`git_commit`）。素の `pi` では、`worker` の shell は通常は ask で止まるので、**親の `/bypass on` が前提**になる（親が作業のツールを持たないので、bypass の危険は小さい）
- **まだ無いもの**: ON の永続（`/reload` で起動時の状態に戻る。`[pi.orchestrate] default = "on"` か環境変数で固定する）、`check_*`（`mise run verify` などの固定引数の親専用の操作。承認ポリシーに触れるので、実装の前に `review`）、親の読み取りの制限、フッター以外の計測（`delegate-stats` への印）
