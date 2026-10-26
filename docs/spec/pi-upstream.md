# pi の公式仕様と、実測で頼っている挙動の棚卸し

pi（earendil-works/pi）の挙動のうち、このリポジトリが頼っているものを、**公式の仕様に明示があるか**で分ける。
仕様の本文は pi の更新で変わるので、**明示があるものはここへ写さず、リンクだけを置いて都度読む**。
**明示が無いものは、実測したことをここに書き、試験で固定する**（公式を読んでも分からないため）。

- 対象のバージョン: 入れているのは **pi 1.4.0**（`pi --version`）。表 B の「確認した版」は項目ごとに実測した版（1.1.0〜1.3.0）で、1.4.0 では全項目を再測定していない
- 見出し: [A. 公式に明示がある（リンクだけ）](#a-公式に明示があるリンクだけ) / [B. 明示が無い（ここに書く）](#b-明示が無いここに書く) / [確認先](#確認先と更新時の手順) / [codemode の扱い](#codemode-の扱い)

## 確認先と更新時の手順

| 確認先 | 場所 |
| --- | --- |
| インストール済みの文書 | pi の npm パッケージの `docs/` ディレクトリ（Windows の npm global は `%APPDATA%\npm\node_modules\@earendil-works\pi-coding-agent\docs\`）。目次は `docs.json`、更新の記録は同じ階層の `CHANGELOG.md`。**入れている版に合う文書は、これ** |
| ソースと文書（上流） | <https://github.com/earendil-works/pi>（`packages/coding-agent/docs/`） |
| 利用者向けの文書 | <https://pi.dev/docs/latest/文書名>（例: `codemode`・`mcp`・`extensions`・`cli`・`windows`。2026-10-12 に取得できることを確認）、更新の記録は <https://pi.dev/changelog>。`https://pi.dev/docs/windows`（版なし）は 404 |
| 版 | `pi --version`、`~/.pi/agent/install/releases/<版>/`（公式インストーラー） |

pi を更新したときの手順:

1. `CHANGELOG.md` の該当の節を読み、下の表の項目に触れる変更が無いかを見る
2. 表 A の文書の該当箇所を読み直す（リンク先の記述が変わっていないか）
3. **表 B の試験を回す**（Unix で `test/agents/test_pi_harness.py` と `test_pi_harness_extensions.py`。Windows でも一部は回る。[実測 E5](../research/agents/pi-extension-under-harness.md)）。落ちたら、挙動が変わった印なので、表 B と実測の記録を直す
4. 直したら、表の「確認した版」を更新する

## A. 公式に明示がある（リンクだけ）

仕様は pi の文書が正本。ここには、**何に頼っているか**と**どこを読むか**だけを書く（文書名は、pi の npm パッケージの `docs/` 配下のファイル）。

| 項目 | 公式の文書 | このリポジトリが頼っているところ |
| --- | --- | --- |
| `-ne` は発見・設定・組み込みの拡張を無効にし、明示した `-e` は読む | `cli.md`（`-e`、`-ne`） | `pis` の起動（`-nbt -ne -e builtin:mcp -e <フルガード>`）、Orca の拡張を足す形、[外部の拡張の方針](guard/pi-guard.md#拡張の方針) |
| 組み込みの拡張の名前（`builtin:mcp`・`builtin:llama.cpp`・`builtin:codemode`・`builtin:tool-search`） | `settings.md`（Built-in extensions） | `-e builtin:mcp` だけを戻す。`codemode` を足すときは `-e builtin:codemode` |
| ツールの選択（`-nbt`・`--tools`・`-xt`・`-nt`、`defaultTools`） | `cli.md`、`settings.md` | 組み込みのツールを外し、フルガードの `guarded_*` だけにする |
| `codemode`（スクリプトの API・結果の形・オプション・`store`・`models`・上限） | `codemode.md`、`cli.md`（Enable codemode）、`settings.md`（`codemode.mode`・`codemode.inlineBudget`） | 検索の入口の比較（[入口の選び方](guard/pi-guard.md#入口の選び方)）。今は使っていない |
| MCP の設定・`exposure`（`codemode` / `deferred` / `direct` / `hidden`）・ツール名 `mcp__<server>__<tool>`・`pi mcp add`・project trust | `mcp.md` | `[[mcp]]` の `exposure`（[仕様](agent-config-generation.md#mcp-サーバ)）、`mcp.json` を `pis` が拒む理由 |
| 拡張の API: `registerTool`、`registerMcpServer` | `extensions.md` | フルガードのツールと MCP の登録 |
| `tool_call` は入力を書き換える・実行を止められる、`tool_result` は合成される、`tool_call` の失敗は fail-safe で止まる、`ctx.executeTool` の入れ子も `tool_call` / `tool_result` を通る | `extensions.md`（Events、Nested tool calls、Error handling） | 判定の方式（`tool_call` と `execute()` の二重の判定）、`codemode` の中の呼び出しが判定を通ること |
| 初期のプロンプトとツール集合を記録し、変更は次の要求の前に追記する | `extensions.md`（Prompt cache の節） | キャッシュ安定性の見込み（ツール定義を増やすと先頭側が変わる） |
| `ctx.hasUI`・`ctx.mode` | `extensions.md` | UI の無い起動での確認の扱い（フルガード側の判断は表 B の 8） |
| `skills` の設定 | `settings.md`（`skills`）、`skills.md` | `[pi.settings] skills = ["~/.claude/skills"]` |
| project trust: `--approve` / `--no-approve` が保存済みの決定（`trust.json`）より先に効く。`AGENTS.md` は trust と無関係に読まれる。`.pi/` と、作業先から祖先の `.agents/skills` が保護対象 | `security.md`（Understand project trust）、`configuration.md` | `pis` は `--no-approve` を固定し、作業先のスキルだけ `--skill` で足す（[起動](guard/pi-guard.md#起動)） |
| `--print`・`--mode json` / `rpc` とイベント | `cli.md`、`json.md`、`rpc.md` | 試験（偽のモデル）、Zed・Orca の RPC |

## B. 明示が無い（ここに書く）

公式の文書では確かめられない挙動。**実測した版と根拠（記録・試験）**を付け、更新時に試験で確かめる。

| # | 挙動（実測） | 公式の記述 | 確認した版 | 根拠・固定する試験 | 対応 |
| --- | --- | --- | --- | --- | --- |
| 1 | 組み込みと**同じ名前**のツールを登録しても、`/reload` でフルガードが抜けると組み込みのツールが同じ名前で戻り、判定なしで動く。`-nbt` でも防げない | 無し | 1.1.0 | [E1](../research/agents/pi-harness-spike.md)、`test_reload_without_harness_leaves_no_tools` | ツールを組み込みに無い名前（`guarded_*`）で登録 |
| 2 | **`-nbt -ne -e builtin:mcp` では `codemode` と `tool_search` が宣言されない。** `exposure` が `codemode` / `deferred` の MCP のツールは `Tool … not found` で呼べない | **食い違う**: `cli.md` は「MCP の拡張が、サーバが要るときに有効にする」とするが、`-ne` では起きない | 1.1.0 | [E6](../research/agents/pi-extension-under-harness.md#記録-e6--2026-10-11)、`test_mcp_tool_without_exposure_is_unreachable_under_the_harness` | `[[mcp]]` の `exposure` を省略すると `direct`（+37 トークン）。`codemode` は `-e builtin:codemode`（+680） |
| 3 | 別の拡張が、フルガードと**同じ名前のツール**を登録すると、読み込みの失敗（`Tool "x" conflicts with <パス>`）で**起動が止まる**（許可側へは倒れない） | 無し | 1.1.0 | [E5](../research/agents/pi-extension-under-harness.md)、`test_extension_cannot_replace_a_guarded_tool` | 差し替えはできない前提で、拡張を足す |
| 4 | `bash` のツールの結果の `details.truncation.content` に**生の出力**が入る（モデルへは送られないが、セッション・JSON・画面に残る） | `message-types.md` は `BashExecutionMessage`（`!` の直接実行）だけで、ツールの結果の `details` は無し | 1.1.0 | [E3](../research/agents/pi-harness-spike.md)、`test_bash_output_is_redacted_everywhere` | 伏字化を `execute()` の中で `details` まで掛ける |
| 5 | `codemode` の中で `Promise.all` などで並べた呼び出しでは、確認が重なり、先の確認が決着せず（TUI が `Working` のまま）止まる | 無し | 1.1.0 | E3 | フルガードが確認を 1 件ずつ順に出す |
| 6 | 既定の圧縮は、別名のツールで読み書きしたファイルを拾わない（`readFiles` / `modifiedFiles` が空） | `compaction.md` は `fileOps` とフックを説明するが、別名のツールの扱いは無し | 1.1.0 | [E2](../research/agents/pi-harness-spike.md) | `session_before_compact` で `fileOps` へ足す |
| 7 | 設定と認証を**読むだけ**でも、隣に `.lock` を `mkdir` する。agent の置き場を読み取り専用にすると、設定は無視され、認証は失敗する | 無し | 1.1.0 | [E4](../research/agents/pi-harness-spike.md) | 境界用の agent の置き場を起動ごとに作る |
| 8 | UI の無い起動（`-p`）では、フルガードの確認（ask）は拒否になる | `ctx.hasUI` は明示（表 A）。**拒否にする判断はフルガードの実装** | 1.1.0 | `test_decisions_reach_the_tools` | フルガードの設計（公式の挙動ではない） |
| 9 | ツール定義の常駐トークン: 最小の MCP ツール 1 つで約 +37、`codemode` で約 +680（偽のモデルの見積もり） | 無し（`codemode.inlineBudget` の既定は宣言の説明に 3,000 トークンまで） | 1.1.0 | E6 | 入口の選択の目安 |
| 10 | 試験が使う `pi-ai/dist/providers/faux.js` の位置は、インストール方法で変わる（mise・公式インストーラーは兄弟、Windows の npm global は入れ子） | 内部のパスで、公開 API ではない | 1.1.0 | `test/agents/pi/faux.ts` が両方に対応 | パスが変わったら試験が落ちる |
| 11 | Windows の npm global の `pi` は `pi.CMD` で、子の pi を `spawn("pi")` する処理（子エージェント）と、その試験が動かない | 無し | 1.1.0 | Windows で `test_pi_harness.py` の 9 件が失敗 | Windows には `pis` を配らず、設定でフルガードを載せ、子は読み取り専用の `task` だけ（`guarded_task` は使わない。[Windows](guard/pi-guard.md#windows)） |
| 12 | `fd`・`rg` は、`<agent 置き場>/bin` → PATH の順に探し、どちらにも無ければダウンロードして `<agent 置き場>/bin` へ置く（`tools-manager.js` の `getToolPath`、`config.js` の `getBinDir`）。起動ごとに新しい agent 置き場では、毎回ダウンロードされる | 未確認（実装を読んだ。公式の文書は探していない） | 1.1.0 | [記録 S1](../research/agents/pis-sandbox-field-test.md)、`test_agent_dir_carries_the_instructions_keybindings_and_prompts` | サンドボックスの agent 置き場の `bin/` を、本物の `~/.pi/agent/bin` へのリンクにする |
| 13 | セッションの置き場は `sessions/--<作業ディレクトリ>--`（先頭の区切りを外し、`/` `\` `:` を `-` にする。`getDefaultSessionDirPath`）。`--session-dir` は渡した場所へそのまま置く | 未確認（`pi.py` の記述による。今回は再確認していない） | 1.1.0 | `test_pi_boundary.py` の `sessions_dir` の試験 | サンドボックスの起動が同じ命名を再実装している（変わると外の `pi -c` で再開できない。pi の更新時に再開を確かめる） |
| 14 | 明示した `--skill` は `--no-approve` でも読まれ、**同名のスキルはグローバル（`settings.json` の `skills`）が勝つ**。`--approve` の自動発見ではプロジェクトが勝つ（乗っ取れる） | `cli.md` に `--skill` の説明はあるが、競合の優先は無い（`skills.md` は「最初に見つけたものが残る」） | 1.3.0 | `test_explicit_skill_loads_under_no_approve_and_global_wins_on_a_name_clash` | `pis` は作業先の `.agents/skills` を `--skill` で足す（[起動](guard/pi-guard.md#起動)） |
| 15 | `/reload` は `--skill` で明示したディレクトリを再走査し、起動後に足したスキルが `[Skills]` と `/skill:` の補完に出る | `skills.md` は「編集後は `/reload`」とあるが、`--skill` のパスは明示が無い | 1.3.0 | tmux の TUI で実測（2026-10。試験は無し） | 起動後に足したスキルは `/reload` で読める |
| 16 | pi は、宣言されたツールに `read` か `bash` があるときだけ、スキルの一覧をシステムプロンプトへ入れる（`dist/core/system-prompt.js`）。**フルガード（`guarded_*`）の下では pi 自身は一覧を入れない** | 無し（`extensions.md` は `before_agent_start` の `systemPromptOptions` を書き換えられると書く） | 1.3.0 | `core/system-prompt.js` と実測。フルガードが `before_agent_start` で同じ形の一覧を `sections.skills` に足す（`disable-model-invocation` のスキルは除く）。`test_the_harness_adds_the_skill_list_to_the_system_prompt` と `test_the_child_also_gets_the_skill_list` | 対応済み（`index.ts`）。pi の版で `systemPromptOptions` の形が変わったら、この 2 件が落ちる |
| 17 | RPC の子への `steer`（作業中の追加指示）は、今のターンのツール呼び出しが終わったあとに届き、子はもう 1 回答える。`abort` は今の往復だけを止め、`agent_settled` で終わる。子は残る | `rpc-commands.md` にコマンドの説明はあるが、子の応答の形と順序は明示が無い | 1.3.0 | `test_steer_reaches_a_running_child`、`test_abort_stops_only_the_round_and_keeps_the_child` | `guarded_task` の steer / abort。版で応答の形が変わったらこの 2 件が落ちる |
| 18 | `agent_before_settle` は、応答を終える直前に、`outcome: "completed"` で発火する。この時点で `context.canContinue` は `false`（最後が assistant のメッセージのため）だが、`custom_message` を足して `continue: true` を返すと、次のモデルの呼び出しが 1 回起きる。`canContinue` で続行を断ってはいけない | `extensions.md` は「エントリを足して `continue: true` で 1 回続行できる。無条件の続行はループする」とだけ書く（`canContinue` の意味は無い） | 1.3.0 | `test_todo_reminds_once_when_the_answer_ends_with_work_in_progress`、`test_todo_does_not_remind_when_nothing_is_in_progress` | `todo` のリマインド。利用者の発言ごとに 1 回だけ出すことでループを避ける |
| 19 | 拡張が `compact()` を直接呼ぶとき、**思考レベルを渡さないと、要約の依頼は「thinking: disabled」で送られる**。Copilot の `claude-sonnet-5.5` はこれを 400（`To turn thinking off on this model, send "thinking": {"type": "between_tools"} instead of {"type": "disabled"}`）で拒む。pi 本体の経路は、セッションの思考レベル（`pi.getThinkingLevel()`）・再試行の方針（既定 3 回）を渡す（`core/agent-session.js` の `compact` 呼び出し）。思考レベルが `off` のときは、pi 既定の圧縮も同じ 400 で失敗する | 無し（`compaction.md`・`extensions.md` に、`compact()` の引数の扱いは書かれていない） | 1.3.0 | 2026-10-20 に実際のモデル（`github-copilot/claude-sonnet-5.5`）で再現し、思考レベルを渡して解消。`low`・`medium`・`high`、`claude-haiku-5.5`・`gemini-3.8-flash`・`grok-4.7`、2 回続けて圧縮、のどれでも成功。`test_compaction_sends_the_session_thinking_level`、`test_compaction_retries_with_minimal_thinking_when_disabled_is_rejected`（直しを外すと落ちることを確認） | 対応済み（`index.ts`）。`off` のときは `minimal` で 1 回やり直す。思考レベルの指定を受け付けない別のモデルが見つかったら、この表へ足す |

## codemode の扱い

- **スクリプトの API・結果の形・上限・有効化の方法は、公式に明示がある**ので、**ここには写さず、リンクだけ**にする（表 A）。読む先は
  `codemode.md`（スクリプト・グローバル・結果）、`cli.md`（有効化）、`mcp.md`（`exposure` との関係）、`settings.md`（`codemode.mode`・`codemode.inlineBudget`）
- **このリポジトリの条件での挙動は、公式に無いので、表 B に書いた**（2: `pis` では既定で使えない、9: 常駐の +680 トークン、5: 並列の確認が止まる）
- 今は使っていない（検索は skill + CLI、MCP は `direct`）。使うなら、まず表 B の 2・5・9 を読み、入口の選び方（[比較表](guard/pi-guard.md#入口の選び方)）で他の入口と比べる

## 運用

- 新しく pi の挙動に頼るときは、**まず公式の文書を探す**。明示があれば表 A に 1 行（リンクと頼っている所）。無ければ、実測して表 B に書き、**試験で固定する**
- 表 B の項目が、公式の文書で明示されるようになったら、表 A へ移して、ここのノウハウは消す（リンクだけにする）
- 実測の経緯は [research/agents/](../research/index.md)（E1〜E6）、判定の設計は [pi のガード](guard/pi-guard.md)
