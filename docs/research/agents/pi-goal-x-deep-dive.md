# pi-goal-x の深掘り（ソース・issue/PR と、自作で上回れるかの判断）

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

- **観測日**: 2026-11-05
- **対象**: `pi-goal-x` v0.34.1（npm 公開 2026-10-27、コミット `b0fc15e`。GitHub `tmonk/pi-goal-x`、MIT）
- **実施の範囲**: **読んだだけ**（clone したソース・`gh` で取った issue/PR・npm のメタ情報）。**コードは 1 度も実行していない**。
  動作・障害は、コードを読んだ上での推測と、公開リポジトリの試験の題名からの推定。推測は「推測」と書く
- **原文の保存先**: `.tmp/research/pi-goal-x/`（`sources/SOURCES.md` に一覧。clone は `repo/`）。コードの引用は MIT で、1 か所 15〜40 行まで
- **先行調査**: 約 20 件の比較は `goal-command-survey.md`（別 feature の worktree にあり、まだ develop に無い）。案件は
  [CHG-0025](../../change/closed/0025-goal-autonomous-loop.md)。方針は [ADR-0016](../../adr/0016-pi-extensions-own-first.md)（公開拡張は導入せず自作）

## 結論

1. **規模は大きい**。配布される `extensions/` は TS 19,526 行・51 ファイル（うち保存 `storage/` 973 行）。試験は 87 ファイル・約 27,000 行。
   実行時の依存は **0**（peer は pi-ai・pi-coding-agent・pi-tui・typebox のみ）。ネットワーク・外部コマンドの呼び出しは **0**、fs の呼び出しは約 87 か所
2. **強み**: ① 継続の許可を永続の状態機械にした（所有者・世代・dispatch の請求。再送しない）② 完了を別セッションの監査役が見て、
   最後の行の印だけを判定にする（失敗は不承認）③ 保存は temp＋rename、行ごとの revision による楽観的な競合検知、per-goal ロック、
   ledger の torn 行の許容、復旧コマンドまで持つ。保守者の応答も速い（closed の issue の多くが数日以内に修正）
3. **弱点（根拠つき）**: ① 既定で**無制限に自走**し、idle のループで 1 時間 25〜45M トークンの報告がある（issue #55・#100。`maxAutonomousRuns` と
   idle backoff は既定オフ）。**予算の穴**もある（tokenBudget は親の input＋output だけで、監査役・Oracle の分は数えない）
   ② **ターン内の変更をメモリに溜め、ターン終わりに 1 回だけ書く**（`goal-service.ts:202`）。kill で最大 1 ターン分の進捗・タスクの完了・使用量が消え、
   他プロセスが先に書いていたら溜めた分を**捨てる**（`:224`）。目標ファイルに fsync が無い ③ 監査役の `bash` は拡張を読まない入れ子の
   セッションで動く（`goal-auditor.ts:350`）ので、**フルガードの判定の外**。「書き換えない」は prompt の約束だけ
4. **自作で上回れるか**: **条件つきで可能**。上回れるのは「予算を必須にする・フルガード下で迂回しない・保存を fsync 付き追記にする・
   評価役の独立と費用の可視化・faux モデルでの再現可能な試験」。**上回れない・薄い**のは、対話の起案（questionnaire 1,073 行）・ダッシュボード・
   複数目標・Windows の rename 再試行・27,000 行の試験の厚み。最小の自作（約 1.5〜2.5 千行・推測）で、安全面は上回り、機能の幅は下回る
5. **保存の信頼性の結論**: 「跨会話の保存が当てにならない」は、**破損ではなく設計に由来する消え方**が 4 つ見つかった（下の C 節）。
   ① ターン内バッファの kill／競合での消失 ② 新しい会話は既定で目標に**フォーカスしない**（`autoSelectSingleGoal` は既定 false）
   ③ 保存先が cwd 基準（`.pi/goals`。別の worktree・別の cwd からは見えない。issue #73）④ 壊れた目標ファイルは**黙って除外**される。
   **データ破損の実報告は issue に 0 件**（推測の域を出ない）。vendor するなら、①④ をパッチする前提

## A 規模と体制

| 項目 | 値（出典） |
| --- | --- |
| 版・公開 | v0.34.1。npm の `time.modified = 2026-10-27T16:36:54Z`、`dist.unpackedSize = 1,066,675`、79 ファイル（`npm view`） |
| ライセンス | MIT（`repo/LICENSE`。npm メタも MIT） |
| 主要言語・実行 | TypeScript。Node ≥22.19（型除去で実行。ビルド無し）。`pi.extensions = ["extensions/goal.ts"]`（`package.json`） |
| ファイル数・行数（`extensions/`） | 51 ファイル・19,526 行（`wc -l`）。`storage/` 4 ファイル 973 行 |
| 大きいファイル | `goal-settings.ts` 1,370／`goal-state.ts` 1,099／`goal-questionnaire.ts` 1,073／`goal-ledger.ts` 1,007／`goal-commands.ts` 866／`goal-service.ts` 843／`widgets/goal-widget.ts` 723／`storage/goal-files.ts` 695／`goal-events.ts` 676／`widgets/goal-dashboard-renderer.ts` 674 |
| 試験 | `tests/` 87 ファイル（`*.test.ts`）約 26,965 行。ほかに SDK worker・e2e・shell・fault-injection・実機の PTY・ベンチ（`experiments/`） |
| 実行時の依存 | **0**（`dependencies` 無し）。peer: `@earendil-works/pi-ai`・`pi-coding-agent`・`pi-tui` ≥1.4.0 <2.0.0、`typebox` ^1.3.11。devDependencies は eslint・typescript・`@xterm/headless` など。install 系の script（postinstall・prepare）は**無い**（`package.json`） |
| 配布物 | `files`: `extensions`・復旧スクリプト 1 本・README・LICENSE・docs 一部・badge。bin は `pi-goal-x-recover` のみ |
| commit | 492（初回 2026-05-07）。直近 90 日（2026-08-07〜）316、直近 30 日（2026-10-06〜）52。タグ 95（v0.34.0 と v0.33.0 は同日 2026-10-24、v0.34.1 は 2026-10-27） |
| 貢献者 | 上位 10 名のみ確認: Thomas Monk 378（**77%**）・Gaoge Zhang 38・Zhang 17・bot 12・JOHN SAM 8・ほか 1〜6 件。直近 90 日は Thomas Monk 250／316（**79%**） |
| バス係数 | **実質 1**（commit の約 8 割が 1 人。外部の PR は 85 件中 tmonk 38・その他は 1〜4 件ずつ。マージ 58・closed 24・open 3） |
| 公開状況 | ★125・fork 60（`gh api`）。open の issue 5・open の PR 3（2026-11-05） |
| 最後の commit から今日まで | 9 日間 commit なし（HEAD 2026-10-27）。その間に issue #119〜#126 が増えた（#125・#126 は未対応） |
| fork | `fan92rus/pi-goal-x`・`expoli/pi-goal-x` は GitHub 上の fork で、★0・最終 push 2026-10-27（本家と同日）。**本家からの差は確認していない**（未確認）。npm の同名 scope 版は中身を見ていない |
| CI | `ci.yml`: 差分に応じて型検査・eslint・「runtime, installed package and cache regressions」・`npm audit --omit=dev`・**ベンチの回帰ゲート**。`publish.yml` は npm の trusted publishing（`specs/2026-09-08-npm-trusted-publishing`） |

## B アーキテクチャ

### 入口と pi の API の使い方

入口は `extensions/goal.ts`（42 行）。`registerGoalCommands`・`registerGoalTools`・`registerGoalEvents` と、`createGoalCore`（`goal-state.ts`）に分かれる。
子セッション（`isDelegatedGoalSession()`）では目標の所有権を持たず、文脈の絞り込みだけを登録して戻る（`goal.ts`）。

| pi の API | 使い方（ファイル） |
| --- | --- |
| `registerCommand` | `goal`・`sisyphus`・`goal-direct`・`sisyphus-direct`・`goal-tweak`・`goal-pause`・`goal-resume`・`goal-clear`・`goal-list`・`goal-status`・`goal-refresh`・`goal-recovery`・`goal-focus`・`goal-unfocus`・`goal-settings`・`goal-cancel`（`goal-controls.ts` の `GOAL_COMMANDS`の 16 種。名前は設定で別名にできる。`goal-commands.ts:737-860`） |
| `registerTool` | `create_goal`・`get_goal`・`update_goal`（核の 3 つ）、`set_goal_tasks`・`update_goal_task`（タスク）、`goal_question`・`goal_questionnaire`・`propose_goal_draft`（起案の間だけ）（`goal-tool-names.ts`） |
| `on(...)` | `context`（`registerGoalContext`）・`before_provider_request`・`agent_start`・`message_start`・`turn_start`・`tool_call`・`tool_execution_end`・`turn_end`・`message_end`・`session_start`・`session_before_compact`・`session_compact`・`session_compact_failed`・`session_tree`・`before_agent_start`・`agent_end`・`agent_settled`・`session_shutdown`（`goal-events.ts` の 17 か所） |
| 状態の書き込み | `pi.appendEntry`（フォーカス情報だけ。`goal-state.ts:437`）、`pi.sendMessage`（チェックポイント・監査の表示）、`pi.events.on("pi-goal:wake")`（他拡張から待ちを解く。`goal-scheduler.ts`） |
| UI | `ctx.ui.setWidget`（目標の widget）・`setStatus`・`onTerminalInput`（Esc などの割り込み）・`notify`・`select/confirm/custom` |
| 入れ子のセッション | `createAgentSession`（`goal-auditor.ts:324`・`goal-oracle.ts:244`）。監査役・Oracle |

使っている拡張 API の幅は広い。`agent_settled`（pi ≥1.4）に依存し、peer の範囲が狭い（`>=1.4.0 <2.0.0`）。pi 側の変更で壊れた履歴が多い
（issue #77 peer 範囲、#78・#90・#113 の stale な ExtensionContext、#45・#47・#52 の RPC で `ui.custom` が無いホスト）。

### 状態のデータ型（原文）

`goal-record.ts` の `GoalRecord`（抜粋）:

```ts
export interface GoalRecord {
 id: string;
 objective: string;
 status: GoalStatus;   // "active" | "paused" | "blocked" | "budget_limited" | "complete"
 autoContinue: boolean;
 usage: GoalUsage;     // { tokensUsed, activeSeconds }
 sisyphus: boolean;
 createdAt: string;
 updatedAt: string;
 activePath?: string;
 archivedPath?: string;
 stopReason?: StopReason;
 pauseReason?: string;
 skipAuditor?: boolean;
 revision?: number;    // 永続の単調増加カウンタ。別プロセスの書き込みの検知に使う
 tokenBudget?: number; // 任意。既定は無し
 scheduler?: GoalSchedulerState;
 currentTaskId?: string;
 taskList?: GoalTaskList;
 verificationContract?: string;
}
```

タスクは `GoalTask { id, title, status: "pending"|"complete"|"skipped", evidence?, skipReason?, verificationContract?, subtasks? }` の木。
証拠（`evidence`）は**自由な文字列**で、機械的な検査は無い（`normalizeTaskItem`）。

継続の許可は `goal-scheduler-state.ts` の `GoalSchedulerState { version, owner, generation, used, phase: idle|ready|waiting|claimed|running|interrupted,
decision, wait?, dispatch?, repairUsed, idle? }`。壊れた値は「`interrupted`・`used = MAX_SAFE_INTEGER`」へ倒す（使用済みの許可を黙って戻さない）。

### 設定のスキーマ

`goal-settings.ts`（1,370 行）。階層は「環境変数 > project（`.pi/pi-goal-x-settings.json`）> global > 既定」で、keys は 40 前後。主なもの:

| キー | 既定 | 意味 |
| --- | --- | --- |
| `maxAutonomousRuns` | **未設定＝無制限**（`goal-settings.ts:855-858`） | 自動継続の回数の上限。`0` で自動継続を無効化 |
| `strictExecutionContract` | false | 各実行の終わりに `update_goal` の宣言（ready／wait）を必須にする |
| `idleContinuationBackoff` | **false** | 何もしない継続を 0→30→60→120→240→300 秒に間引く |
| `stallTimeoutMinutes` | **0（無効）** | 無活動の検知（通知とプロンプトだけ。止めない） |
| `networkRecovery.maxAttempts` / `maxDelayMs` | 0（**無制限**）／80,000 | 一時的な通信障害の再試行 |
| `autoSelectSingleGoal` | **false** | 新しい会話で、開いた目標が 1 つのときに自動でフォーカス |
| `disabled`・`model`・`provider`・`thinkingLevel` | 監査役 on・親と同じモデル | 完了の監査役 |
| `auditorProjectResources` | false | 監査役にプロジェクトの skills・拡張を渡す |
| `goalsRoot`／`PI_GOAL_ROOT` | `<cwd>/.pi/goals` | 保存先の上書き（絶対パスか `~/`。シンボリックリンクは拒否） |
| `oracle.*` | **無効** | 「ブロック」時に強いモデルへ 1 回相談する（read-only） |

### UI

`widgets/` 3,300 行強（`goal-widget.ts` 723・`goal-dashboard-renderer.ts` 674・`goal-controls-dialog.ts` 329・`task-list-overlay.ts` 409 ほか）と
`goal-widget.ts`（455）。コンパクトなウィジェット・展開できるダッシュボード（タスク木・証拠・経過・トークン・監査の進捗）・タスク一覧のオーバーレイ・
ショートカット（Esc＝割り込み、Ctrl+Shift+T＝展開、Ctrl+Shift+A＝監査役の切替。すべて変更できる）。ここだけで `src` の約 2 割。

## C アルゴリズム

### 継続の起こし方

1. `agent_end` が「この run で継続してよいか」の意図だけを記録する（`continuationAfterSettleFor`。`goal-events.ts:611` 付近）。
   通信障害・abort・エラーのときは継続せず、通信障害は別のタイマー（`networkErrorRecoveryAfterSettleFor`）へ
2. `agent_settled`（pi が再試行・圧縮・キューの片付けを終えた時点）で `scheduler.settled()` → 非 strict なら `implicitReady()` を書き、`schedule()` で
   `runtime.queueContinuation()` を呼ぶ（`goal-scheduler.ts` の `settled`・`schedule`）
3. 実際に配送する直前に `claim()`。永続の状態へ `phase = "claimed"`・`used++`・`dispatch = {id, kind}` を書く。チェックポイント（`pi-goal-event`、
   version 3）に `generation`・`dispatchId` を載せ、`message()` で一致するときだけ `running` にする。**一致しない古いチェックポイントは
   `rejectCheckpoint()` で turn ごと abort**（`goal-scheduler.ts` の `message`・`goal-events.ts` の `before_agent_start`）
4. 再起動・再開時、`claimed`／`running` のままなら**再送せず pause**（「Previous autonomous execution was interrupted... its dispatch will not be replayed.」。`restore`）。
   所有者（`ctx.sessionManager.getSessionId()`）が違えば `/goal-resume` まで動かない

→ **kill のあとで二重に走らない**設計。一方で、`maxAutonomousRuns` 未設定では `claim()` が `available()` を常に真にする（`limit === undefined`）。

### 完了判定と監査役のフロー

`goal-completion.ts` の `runGoalCompletionFlow`。

1. `update_goal({status:"complete"})` → 変更を `flushForAudit`（書けなければ監査しない）→ 検証（`validateGoalCompletion`）→ タスクの関門
   （`blockCompletion` かつ未完了があれば拒否）
2. `completion_requested` → `audit_started` を **ledger に即時追記**してから監査役を起動
3. 監査役: `createAgentSession`（`goal-auditor.ts:324-351`）。空の ResourceLoader（拡張・skills・AGENTS なし）、`SessionManager.inMemory`、
   **道具は `["read","grep","find","ls","bash"]`**、モデルは設定（既定は親と同じ）。実行は同一プロセス内
4. 監査役の prompt（`buildGoalAuditorPrompt`。要点）: 「独立した完了監査役。実際の成果物を read/grep/find/ls/bash で調べる。
   ファイルを**変更しない**・`.pi` の目標やサブエージェントのメタデータを片付けない。**書類・件数・ビルド成功だけは証拠にならない**。
   足場・テンプレート・浅い草稿・代理の節目は不承認。**最後の行に `<approved/>` か `<disapproved/>` だけを書く**」。
   目標・実行役の完了の主張（**UNTRUSTED** と明記）・タスク木・検証契約・warm context（ledger の末尾 8 件と前回の不承認の理由）を XML 風のタグで渡す。
   タグの区切りは `&`・`<`・`>` を実体参照にして破られないようにする（`escapePromptPayload`）
5. 判定: 出力の**最後の非空行**が `<approved/>` のときだけ承認（`parseAuditorDecision`、`goal-auditor.ts:64`）。エラー・中断・印なしは**承認しない**
6. 承認 → `commitCompletion`。**revision が監査中に変わっていたら完了しない**（「the goal changed during the audit」）。不承認 → 理由を差し戻し、
   次の prompt に「[AUDITOR REJECTION] ...」（理由の先頭 300 字）を入れる。監査役が Esc で中断されたら、利用者に「監査なしで完了」か「続ける」を尋ねる
7. **監査を飛ばせる経路**: 目標ごとの `skipAuditor`、設定の `disabled`、Esc の「監査なしで完了」。いずれも `audit_skipped` を ledger に残す

引用（`goal-auditor.ts` 340-351。MIT）:

```ts
const { session } = await createSession({
 cwd: args.ctx.cwd,
 model,
 thinkingLevel,
 ...resolveAuditorSessionModelOptions(args.ctx),
 // E3: default = the empty isolated loader (deliberate isolation);
 // when auditorProjectResources is on, let the runtime build its own
 // loader so the project's skills/extensions reach the auditor.
 ...(projectResources
  ? { resourceLoaderOptions: { noExtensions: false, noSkills: false, noPromptTemplates: false, noThemes: false, noContextFiles: false } }
  : { resourceLoader: makeAuditorResourceLoader() }),
 sessionManager: SessionManager.inMemory(args.ctx.cwd),
 settingsManager: SettingsManager.inMemory({ compaction: { enabled: false } }),
 tools: ["read", "grep", "find", "ls", "bash"],
} as Parameters<typeof createAgentSession>[0]);
```

### タスク・サブタスク・証拠のモデル

- 木構造（深さの上限 `subtaskDepth`）。状態は pending／complete／skipped。`blockCompletion` が真なら、未完了があると完了できない（`taskCompletionBlockWarning`。
  skipped を pending と数える不具合は #110 で修正済み）
- `update_goal_task` は `evidence`（文字列）を受け、ledger の `task_complete` に残す。**内容の検証は無い**（監査役が見る）
- `set_goal_tasks`（計画の提示）は利用者の確認を要する。**UI が無いとき（`!ctx.hasUI`）は既定で承認される**
  （`goal-task-confirmation.ts:36-37`。`PI_GOAL_AUTO_CONFIRM=0` で拒否）
- 実行の焦点 `currentTaskId`・タスクごとの検証契約・verify の契約（`Verification contract:` 行を目標から抜き出す。`goal-contract.ts`）

### `/sisyphus` の順序の論理

**順序は prompt の約束だけで、コードでは強制しない**。`/sisyphus` は (a) 目的に番号つきの手順（`1)`・`Step N`）を要求する
（`sisyphusObjectiveSufficient`）、(b) prompt に「順に進める・勝手に偵察や検証を足さない・詰まったら報告」を足す（`sisyphusDisciplineBlock`）、
(c) 進捗の表示 N/M を数える（`sisyphusStepProgress`）。`update_goal_task` が順序を検査する処理は無い（`goal-task-tools.ts`・`goal-policy.ts` を grep）。

### recovery / refresh の意味

- `/goal-refresh`: メモリ上のキャッシュ（目標の pool・ledger・設定）を捨ててディスクから読み直し、差分を報告する
- `/goal-recovery`: 保存の診断（壊れた目標ファイル・壊れた ledger 行・古いロック・孤児のスナップショット）。`repair` は確認＋バックアップのうえ、
  古いロックの削除とスナップショットの再生成だけを行う。**壊れた目標ファイルは直さない・報告だけ**（`goal-recovery.ts` の冒頭の注記）。
  「進捗が止まったときの再開」ではない
- `pi-goal-x-recover`: 別物。issue #30 で肥大した古いセッションファイルの checkpoint を縮める offline の修復

### `maxAutonomousRuns` と無進捗・停滞の検知

- `maxAutonomousRuns`: `claim()` のたびに `used++`。上限に達すると pause。**既定は無制限**。「作成時と利用者の `/goal-resume`」だけが `used` を戻す
- 無進捗の検知: ① `idleContinuationBackoff`（**既定オフ**）: 作業ツールを呼ばず目標の内容も変わらなかった run を数え、継続の間隔を指数的に広げる
  （最大 300 秒）② `stallTimeoutMinutes`（**既定 0 ＝無効**）: 無活動を検知しても、通知と「[GOAL STALLED]」の prompt を足すだけで**止めない**（`goal-state.ts:633-653`）
  ③ blocked は「同じ障害が 3 ターン連続したときだけ」だが、これは **prompt の約束**で、コードの検査は無い（`goal-core-tools.ts:246` のコメント）
- 実際に起きたループ: 空の応答の無限継続（#53）、`read` や `update_goal_task` だけの「何もしない」ターンの再継続（#55）、
  サブエージェント待ちで「Standing by」を何時間も繰り返す（#100）。#100 の保守者の返答は「#105 で opt-in の backoff を足した」。
  **既定の動作は変わっていない**（0 ms で再継続）

### 圧縮との合成・承認待ち

- 圧縮: `session_before_compact` で課金を確定、`session_compact` で溜めたバッファを書き、決定的な「圧縮後の差分」（目標の状態＋ ledger から
  復元した要点）を次の 1 ターンだけ注入し、継続を積む。`session_compact_failed` では書いてから警告（`goal-events.ts:379-412`）
- チェックポイントは約 160 文字の小さな印（`<pi_goal_continuation .../>`）で、本文は毎回リクエストの末尾に注入する（#30 の修正。1 セッションで同じ 6.4K の本文が
  850 回入っていた不具合）。prompt cache のため、注入ブロックの再送を `LiveTailRetention` で抑える（が、状態が変わるたびに cache の前置が壊れる設計の問い
  が #108・#126 で open）
- 承認待ち（ask など）: **目標側に「承認待ちで止まる」処理は無い**。継続は `agent_settled` で出るので、承認の確認が出ている間は pi が settle しない（推測）。
  ただし、他拡張のダイアログで Esc を押すと目標が pause される問題は #114 で修正済み（フォーカスのある側に Esc を渡す）

### 保存の実装

| 項目 | 内容（出典） |
| --- | --- |
| 保存先 | 既定 `<cwd>/.pi/goals/`（`storage/goal-root.ts`）。`active_goal_<日時>_<id>.md`（先頭が JSON のメタ、本文が目標と進捗の表示）、`archived/goal_*.md`、`goal_events.jsonl`（ledger）、`.goals-pool-snapshot.json`（起動の高速化。`.pi/` 直下）、`.goal-ledger-checkpoint.json`、`.locks/<id>.lock`、`.recovery-backup/`。`goalsRoot` で別の絶対パスにできる |
| 形式 | 目標: `JSON.stringify({version: 3, ...goal})` ＋ Markdown の本文（`serializeGoalFile`）。**目的（objective）は本文側が正**（人が直せる）で、読み込み時に本文から取る。ledger: JSON Lines |
| 書き込み | `atomicWriteGoalFile`（`goal-files.ts:274-296`）: 同じディレクトリに `<file>.<pid>.<時刻>.tmp` を `wx` で作って書き、`renameAtomicSync`。失敗時は temp を消す。Windows の `EPERM/EACCES/EBUSY` は最大 4 回（5・10・20・40 ms）再試行（`atomic-rename.ts`）。シンボリックリンクの目標は拒否 |
| **fsync** | **目標ファイル・ledger・スナップショットには無い**。設定ファイルの書き込み（`goal-settings.ts:1112,1128`）と復旧スクリプトにだけある（`grep fsync`） |
| ロック | `.locks/<id>.lock` を `wx` で作る排他（`goal-lock.ts`）。待ちは **約 8 ms（8 回×1 ms）**、`persist` は 4×25 ms。古いロックは「mtime が 30 秒より古い」**または**「pid が死んでいる」（`process.kill(pid, 0)`）で、読んだ側が削除して奪う。取れなければ**書き込みを見送る**（`persist()` が null を返す。`goal-service.ts:755`） |
| 楽観的な競合検知 | 目標の `revision`。書く前にロック下で目標ファイルを読み直し、メモリの revision と違えば**書かずに競合を返す**（`apply`・`updateTask`）。`persist` は差があれば使用量の増分だけを加算して書く |
| ターン内バッファ | `GoalService.beginTurn`〜`flushTurn`（`goal-service.ts:183-248`）。**ターン中のタスク更新・状態・使用量・ledger 行はメモリに溜め、`turn_end`・監査の前・pause・圧縮・session 終了などの境界で 1 回だけ**ロック＋書き込み＋ ledger 追記。flush のロックが取れなければバッファを残して次の境界で再試行。**revision が違えば溜めた分を捨てる**（`:224`「buffered changes were rejected」）が、使用量だけは disk に加算 |
| ledger | `fs.appendFileSync`（O_APPEND）の 1 行 JSON（`goal-ledger.ts:134`）。読む側が末尾の torn 行を数えて無視（`malformed`）。チェックポイントファイルで起動を速くする。**ledger は状態の正本ではない**（目標ファイルが正本） |
| 起動時の復元 | `loadState`（`goal-state.ts:747`）: pool（目標ファイルの一覧＋スナップショット）を読み、セッションの `custom` エントリ（`FOCUS_ENTRY`）から**フォーカスする目標**を決める。エントリが無く、`autoSelectSingleGoal` が false（既定）なら**フォーカスしない**。復元後、`scheduler.restore()` が `claimed/running` を pause に倒す |
| キャッシュ | pool・ledger・パースの 3 層。**拡張経由でない編集は、セッションの途中では見えない**（`goal-files.ts` の注記。README の `/goal-refresh` で再読込） |

引用（`goal-service.ts` 220-232。MIT）:

```ts
const freshDisk = this.readFreshDiskGoal(ctx, goal);
const expected = this.turnBase ?? goal;
if (!freshDisk || (freshDisk.revision ?? 0) !== (expected.revision ?? 0)) {
 this.flushError = `Goal ${goal.id} changed in another process; buffered changes were rejected. Refresh and retry.`;
 // Reject the speculative transaction, never overwrite another writer.
 this.turn.active = false;
 this.turn.goal = null;
 this.turn.ledger = [];
 if (freshDisk && this.ref.getFocusedGoalId() === goal.id) {
  const tokens = Math.max(0, goal.usage.tokensUsed - expected.usage.tokensUsed);
  const seconds = Math.max(0, goal.usage.activeSeconds - expected.usage.activeSeconds);
  this.ref.setFocused({ ...freshDisk, usage: {tokensUsed: freshDisk.usage.tokensUsed + tokens, activeSeconds: freshDisk.usage.activeSeconds + seconds} });
```

### 進捗が消える原因の仮説（**コードの読みによる推測。実行して再現していない**）

| # | 仮説 | 根拠 | 起きる条件 | 実害 |
| --- | --- | --- | --- | --- |
| H1 | ターン内の変更が kill で消える | `flushTurn` が境界でしか書かない（`goal-service.ts:183,202`）。`persist()` も turn 中はバッファに積むだけ（`:744`）。fsync 無し | 長いターンの最中にプロセスが落ちる・端末を閉じる・OOM | 最大 1 ターン分のタスク完了・証拠・使用量・ledger が失われる。**目標ファイルの破損ではない**（rename は原子的）。直前のターン終わりの状態に戻る |
| H2 | 競合時にターンの変更を捨てる | `flushTurn` の `:224`。`apply`・`updateTasks` も競合で変更なしを返す | 同じ `.pi/goals` を 2 つの pi が書く（別の端末・別の会話・サブエージェントではない）。タスクの完了を溜めた側が負ける | タスクの完了と証拠が消える（使用量は加算される）。メッセージは出る（警告） |
| H3 | 新しい会話が目標にフォーカスしない | `loadState`＋`resolveSessionFocus`（`goal-pool.ts:39-64`）。コメントに「既定では会話を unfocused で始める。同じ `.pi/goals/` を共有する会話に目標が漏れるのを防ぐ」とある（**意図した設計**）。`autoSelectSingleGoal=false`（`goal-settings.ts:784`） | `pi` を新規に起動して、フォーカスの記録（セッションの `custom` エントリ）が無いとき。同じセッションの再開（`resume`）ならエントリから復元され、複数あれば選択ダイアログ | **データは残る**が、会話は目標を持たず、モデルには「[PI GOAL UNFOCUSED]」だけが入る。利用者には「進捗が消えた」と見える。**これが「跨会話の保存が当てにならない」の最有力の説明（推測）** |
| H4 | cwd が違うと見えない | `goalStoragePath`＝`<cwd>/.pi/goals`。issue #73（worktree をまたぐ断片化） | 別の worktree・サブディレクトリで起動 | 目標が見えない（`goalsRoot` で回避できる。既定は無効） |
| H5 | 壊れた目標ファイルが黙って消える | `parseGoalFile` が不正な JSON で null、`scanActiveGoalFiles` が null を除外（`goal-files.ts` の `.filter`）。`normalizeGoalRecord` は `objective` が空なら null | 外部の編集・不完全な書き込み・古い版のファイル | 目標が pool から消える。`/goal-recovery` が**報告**はするが直さない。起動時に警告は出ない（推測：通知のコードを見つけられなかった） |
| H6 | スナップショットが古いまま | 起動の高速化のため、ディレクトリの mtime か「ファイル名の集合」が同じなら**ファイルの中身を読まずに**スナップショットを信じる（`readPoolWithSnapshotSync`）。内容だけの編集は mtime が変わらない | 手で目標ファイルを直した直後の起動 | 古い内容で動く（`/goal-refresh` で直る） |
| H7 | ロックの誤った奪取 | mtime 30 秒超で他プロセスのロックを奪う（`goal-lock.ts:114`）。pid の生存は同じホストだけ有効 | 同期的な書き込みが 30 秒超かかる、NFS・コンテナ越しの共有 | 同時書き込み → ただし revision の再検査が後ろにあり、実害は小さい（推測） |
| H8 | rename の原子性は保つが耐久性は保証しない | fsync 無し | 停電・OS のクラッシュ（プロセスの kill ではない） | ファイルが 0 バイトになる可能性（一般のファイルシステムの性質。実測していない） |

**実報告との突き合わせ**: issue に「進捗が消えた」「データが壊れた」という直接の報告は **0 件**（`grep` した語: lost progress・disappear・vanish・wiped・data loss・corrupt・overwrit・truncat）。
過去の保存に関する修正は CHANGELOG にある（「Usage/accounting no longer lost on revision conflicts」・「Buffered writes now reject competing revisions before overwriting state」）。
よって「消える」は、**H3（フォーカス）が主因で、H1・H2 が副因**という見立て。いずれも**確証は無い**。

## D 品質

### 試験・CI・エラー処理

- 試験は厚い: `tests/` 87 ファイル約 27,000 行。保存まわりの題名: `fault-injection.test.ts`（torn な目標ファイル・torn な ledger の末尾・死んだ pid のロック・
  複数プロセスの目標ファイルの書き込みが破れない・別プロセスの追記を検知）、`goal-atomic-rename.test.ts`、`goal-files.test.ts`、`goal-ledger-checkpoint.test.ts`、
  `goal-turn-transaction.test.ts`、`goal-settings-race.test.ts`、`goal-session-safety.test.ts`、`goal-network-recovery.test.ts`、`goal-scheduler.test.ts`（56 KB）
- **ただし `kill -9` のような「本物の」プロセス中断を使う試験は無い**（`SIGKILL` を含むのは `fault-injection` と `goal-oracle` の各 1 件。`fault-injection` は
  「rename と temp の途中で落ちた状態」を**手で作ったファイルで模擬**している。`tests/fault-injection.test.ts:45-77`）。H1（ターン内バッファの消失）を直接見る試験は無い
- 形式検証の試み: TLA+ の検査用の skill を `GoalService.flush` と監査フローに足した PR（#101・#102）は close（**取り込まれていない**。ただし README に runtime verification の skill 追記 #103 は close）
- 実機の検証: `experiments/`（PTY で pi を動かすスクロールの再現、`harness/`、`live/`、ベンチの回帰ゲート）。メンテナーは**ベンチのゲートと
  プロンプトキャッシュの測定**に熱心で、保存の耐久性より性能を測っている
- エラー処理: 失敗を握りつぶす `catch {}` が多い（best-effort の ledger・スナップショット・デバッグ）。ledger の追記の失敗は診断に流すだけで状態は巻き戻さない。
  `onDiagnostic` は通知（warning）に出る

### issue の整理（全 38 件。open 5 件・closed 33 件。2026-11-05 取得）

#### open の全件

| # | 主題 | 内容 | 評価 |
| --- | --- | --- | --- |
| 108 | prompt cache | 目標の状態が変わるたびに保持した末尾を捨てるため、リクエストが前の接頭辞でなくなる。`goal-live-retention.ts:145-149` | 設計上の選択（回答待ち） |
| 119 | i18n | 対話の文字列が英語固定 | 機能要望 |
| 122 | 起案 | 起案の prompt の節の見出し（`Boundaries` など）が引数名に見え、最初の `propose_goal_draft` が拒否される（34 件・23 セッション）。PR #121 が open | 不具合（修正案あり） |
| 125 | **継続の停止** | 一時的でないと分類されたプロバイダのエラー（HTTP 499 など）で run が終わっても、目標は「running」のまま継続が予約されない。`networkRecovery.maxAttempts` を有限にして使い切っても同様 | **不具合（無言の停止）**。未対応 |
| 126 | prompt cache | Anthropic で pause／resume のたびにツール配列が変わり cacheRead=0、thinking ブロックが落ちる | 不具合（cache の費用） |

#### closed の主題別（重要な 30 件を抜粋。本文を読んだものは ◆）

| 主題 | issue | 要点 |
| --- | --- | --- |
| 無限・過剰な継続 | #53◆・#55◆・#100◆・#124◆（利用者が離脱して close） | 空応答・無作業の再継続・サブエージェント待ちの空回し。測定: 1 時間 25〜45M トークン（#55 の報告）。対策は opt-in の backoff（#105）と allowance。**既定は変えていない** |
| 完了監査 | #16・#20・#17・#21（Devin の自動指摘） | 印を本文のどこでも拾う → 最後の行だけに、目的を生で埋め込む → エスケープ。#31◆ 監査役が OAuth の認証を引き継がない（親の runtime を共有して修正）、#48◆ 監査の表示イベントがツール呼び出しの間に入って 400（settle まで保留） |
| 更新ツールの検証 | #18・#22（blocked/paused が失敗でも成功と報告）、#59◆・#115◆（Responses の strict 正規化で任意引数が全部埋まり、1 トークン予算ができる・`update_goal` が全件拒否される）、#110◆（skipped が pending 扱い） | **「モデルが何を渡してくるか」への耐性の問題が繰り返し出る**（5 件） |
| pi 側の変更・ホスト差 | #45・#47・#52◆（RPC に `ui.custom` が無い）、#77（peer 範囲）、#78◆・#90・#113（stale な ExtensionContext で pi が終了）、#49◆（forked サブエージェントに継続が割り込む）、#114◆（他拡張の Esc で pause） | 拡張 API の変化に追従する費用が高い（**vendor の維持費の根拠**） |
| 設定・UI | #10・#15・#19（設定メニューが `subtaskDepth` を書く）、#72（unfocused の prompt）、#76（累計トークンが文脈の枯渇に読まれる）、#120 | 軽い |
| 保存・複数 worktree | #73（`goalsRoot` で解決）、#30◆（チェックポイントが毎ターン丸ごと入り肥大） | **データ消失の報告は無い** |
| 機能要望 | #26（Oracle）、#63（strict）、#124 | 取り込み済みが多い |

### PR の傾向

- 85 件: マージ 58・closed 24・open 3。作者は tmonk が 38、他は 1〜4 件ずつ。**外部の PR が「close」され、保守者が同じ内容を自分で入れ直す**例が多い
  （#116・#117 → #118 が一括して取り込み）
- open: #123（omp 対応のバッジ）・#121（起案 prompt の修正。#122 の対応）・#96（`goal-resume` の追加テキスト）。取り込みは約 1〜2 週間で滞留がある

### コードを読んで見つかる欠陥の候補（**実行していない。推測を含む**）

| # | 領域 | 内容 | 根拠 |
| --- | --- | --- | --- |
| F1 | データ消失 | H1・H2・H5（上の表） | `goal-service.ts`・`goal-files.ts` |
| F2 | 無限ループ | 既定で上限なし・idle の backoff 無し・stall は通知のみ。**最大の費用の穴** | `goal-settings.ts:849-863`・#55・#100 |
| F3 | 予算の穴 | `assistantTurnTokens` は `usage.input + usage.output` だけ（`goal-format.ts:305-311`。**cache の読み書きを含むかは pi の `usage` の定義次第で未確認**）。監査役・Oracle の入れ子のセッションは**数えない**（`goal-auditor.ts`・`goal-oracle.ts` に usage の集計なし。grep）。`tokenBudget` は任意で既定なし | 同左 |
| F4 | 無言の停止 | #125（499 などで継続が止まるが目標は running のまま）。一時エラーの分類は**正規表現**（`goal-format.ts:239-255`） | #125 |
| F5 | prompt 注入 | 目標・タスクの文字列は `<untrusted_objective>` で囲み、閉じタグだけをエスケープする（`promptSafeObjective`）。**目標ファイルの本文は人が書き換えられ、objective は本文が正**。ファイル書き込みを遮断する処理は無い | `goal-contract.ts`・`goal-files.ts` |
| F6 | **目標ファイルへの書き込みを止めない** | エージェントの `write`/`edit` で `.pi/goals/active_goal_*.md` の JSON（`status`・タスクの `complete`・`evidence`）を直接書き換えられる。`tool_call` の遮断は「古いチェックポイント」と「停止後」だけ（`goal-events.ts:133-160`）。`.pi/goals` を見る例外は「進捗とみなさない」だけ（`goal-format.ts:317`）。**完了の監査を経ずに状態を変えられる可能性（推測。未実行）** | 同左 |
| F7 | 監査の迂回 | `skipAuditor`／`disabled`／Esc の「監査なしで完了」。モデルは直接はできない（設定と UI）が、`/goal-direct` と `update_goal` の `skipAuditor` の扱いは**未確認** | `goal-completion.ts:75` |
| F8 | 非対話の既定 | `!ctx.hasUI` で計画の提案を**自動承認**（`goal-task-confirmation.ts:36-37`）。RPC・print で人の確認が要らない | 同左 |
| F9 | ロック | 8 ms の窓は短く、長く保持されると書き込みを**見送る**（失敗は黙って null）。mtime 30 秒の奪取 | `goal-lock.ts` |

## E 権限と安全

| 観点 | 内容 |
| --- | --- |
| 実行できること | 拡張自身は**外部コマンドもネットワークも呼ばない**（`extensions/` に `child_process`・`node:net/http`・`fetch(` の import が無い。grep）。LLM への通信は、監査役・Oracle の `createAgentSession`（pi 経由）だけ |
| ファイルの書き込み範囲 | `<cwd>/.pi/goals/`（または `goalsRoot`）と設定ファイル（`.pi/pi-goal-x-settings.json`、global は agent ディレクトリ）。`goalStoragePath` が `.pi/goals` の外へ出るパスを拒否し、`goalsRoot` のシンボリックリンクも拒否する（`storage/goal-root.ts`）。fs の呼び出しは約 87 か所 |
| 環境変数 | `PI_GOAL_DEBUG`・`PI_GOAL_AUTO_CONFIRM`・`PI_GOAL_PROMPT_PROFILE`・`PI_GOAL_ROOT`・`PI_GOAL_OBJECTIVE_MAX_CHARS`・`PI_GOAL_NETWORK_RECOVERY_*`（`grep`）。**秘密の環境変数は読まない** |
| テレメトリ | **見つからない**（上の通り通信の import が無い）。`pi.dev` の公開ランキングの更新は別（`scripts/update-ranking.py`。配布物に入らない） |
| 秘密 | 取り扱いなし。ただし目標の本文・ledger に監査役の出力（`report`）が残り、`.pi/goals/` に平文で書かれる。**リポジトリに入れない設定が要る**（`.gitignore` の自動追加は見つからなかった） |
| **フルガード下での穴（推測・未実行）** | ① 監査役の入れ子セッションは**拡張を読まない**（`getExtensions: () => ({extensions: []...})`）ので、このリポジトリの判定器（`pi.on("tool_call")`・`landlock_exec.py` を介した `guarded_bash`）は**かからない**。道具は組み込みの `bash` で、`createAgentSession` のまま素の bash が動く。「ファイルを変更しない」は prompt の約束だけ（`goal-auditor.ts:350`）。pis の OS レベルのサンドボックスは別に効く（未確認）。② 継続の起点が `agent_settled` からの `triggerTurn` なので、**ガードの確認待ち（ask）を継続が追い越す**かは未確認（`pi-message-queue-experiments.md` で `agent_settled` からの連鎖は観測済み）。③ F6（目標ファイルの書き換え）。④ `PI_GOAL_AUTO_CONFIRM`・`!hasUI` の自動承認 |

## F 機能比較表

「今の pi」は、このリポジトリの自作（`home/dot_pi/agent/extensions/todo/index.ts` 425 行＋ `view.ts`・`guarded_task`・`ask`・`plan`・
`home/dot_config/pi/harness/`）。`todo` は `agent_before_settle` で作業中の項目のリマインドを**最大 1 回**出す（`index.ts:216-243`）。
状態は `pi.appendEntry`＋ツール結果の `details`（セッションの entries。分岐・再開・圧縮に追随）で、跨会話の保存・自動継続・独立の監査は無い。

判断: ◎同等が必須／○取り入れる／△上回る設計／×不要

| 機能 | 公開実装の仕様（出典） | 今の pi | 判断 | 上回る設計の案 | 上回ったと言える検証 |
| --- | --- | --- | --- | --- | --- |
| `/goal` の対話による起案 | questionnaire 1,073 行＋ drafting 533 行。目的・計画・完了条件・検証契約を利用者が確認（`goal-questionnaire.ts`） | `plan` 拡張・`ask` | ○（小さく） | 起案を 1 回の `ask`＋検証契約の必須欄だけにし、起案ツールの schema を**目標の項目と同じ名前**にする（#122 の再発防止） | 起案の prompt の見出しと tool schema のキーが一致することを自動で試す。faux モデルで「見出し名を引数に埋めても受理される」 |
| 目標の永続・複数目標 | `.pi/goals/*.md`＋focus。複数目標・フォーカス | セッション内の todo のみ | ◎（跨会話）／×（複数目標） | 目標は**1 件・プロジェクトの状態ファイル 1 つ**。新しい会話は**明示の再開の 1 画面**（フォーカスの迷子を無くす＝H3） | 新規会話で「再開しますか」が必ず出る（faux の UI）。kill 後の再起動で最終の完了タスクまで戻る |
| 保存の信頼性 | temp＋rename・revision・ロック。ターン内バッファ。fsync 無し | session の entries | △ | **変更ごとに追記（JSONL）＋ fsync、ターンの境界を待たない**。競合は捨てずに別名で退避 | 保存の途中で `kill -9`（fd を開いたまま）を 200 回注入して、完了したタスクが**0 件**失われない。2 プロセスの同時書き込みで 0 件の無言の消失 |
| 自動継続 | `agent_end`→`agent_settled`→claim→`triggerTurn`。永続の所有者・世代 | `todo` が 1 回だけ | ◎ | 予算（回数・トークン・時間）を**必須の引数**にし、既定の上限を持つ | 予算を省略した `/goal` が拒否される。上限で 100% 止まる（faux で 1,000 ターン回して超過 0） |
| 継続の二重配送の防止 | generation・dispatchId・claim（`goal-scheduler.ts`） | 無し | ◎ | 同じ方式（小さく） | 古い世代のチェックポイントが 0 件作業する（faux で再送を注入） |
| 無進捗・停滞 | idle backoff（既定オフ）・stall（通知のみ）。ループの実害が複数 | 無し | △ | **無進捗 N 回で pause を既定**にする（ツールの種類でなく「状態の差分」と「同一出力」で判定） | #55・#100 の再現（空の返答の無限継続）が N 回で止まる |
| 完了の独立監査 | 入れ子の `createAgentSession`、道具は read/grep/find/ls/bash、最後の行の印 | `guarded_task` の `review` | △ | 監査役は**フルガードの下の子（guarded_task）**にして、道具に読み取りだけ＋検査コマンドの実行を判定器の通る形で与える。**評価役の費用を可視化**。監査の入力から実行役の主張を落とす | 監査役が書き込みを試みると拒否される（判定器の記録に deny）。不承認の再現: 偽の「完了」を faux が出して 100% 不承認 |
| 完了判定の厳しさ | 印の位置・エスケープ・UNTRUSTED の主張 | 無し | ◎ | 判定を「印」でなく**構造化された出力**（スキーマ）にする | 印を本文に含む出力・偽の印を、全件誤承認しない（fuzz） |
| タスク・サブタスクと証拠 | 木・証拠の自由文・`blockCompletion` | `todo`（フラット・note） | ○ | 木は持たず**フラット＋依存**。証拠は**ファイルパス＋コマンド出力の参照**を型にする | 証拠が空のタスクを完了にできない |
| `/sisyphus` の順序 | prompt の約束のみ（コードで強制せず） | 無し | △ | 順序つきの目標は**タスクの前提（依存）をコードで強制** | 順序を飛ばした完了の呼び出しが拒否される |
| `maxAutonomousRuns`・`tokenBudget` | 任意（既定は無制限） | 無し | △ | **必須**。監査役・子の費用も合算 | 子・監査役の使用量が合算されて上限が効く |
| ダッシュボード・widget・status | 3,300 行強の UI | `todo` の overlay | ×（大きなダッシュボード）／○（1 行の status） | 1 行の status（残り予算・次の継続・最後の判定） | 目標の状態が widget に出る |
| `/goal-tweak`・pause・resume・clear | 利用者専用の制御 | `todo`の clear/tidy | ○ | 同等。`pause` は即時に turn を止めて評価役にも停止を渡す | 利用者の停止が監査役にも**必ず**届く（faux） |
| `/goal-recovery`・`/goal-refresh` | 診断と修復。キャッシュの読み直し | 無し | ×（キャッシュが無いので不要）／○（診断） | キャッシュ層を作らない。診断は `status` に統合 | キャッシュ起因の古い表示が 0 |
| Oracle（ブロック時の相談） | 既定無効。read-only の入れ子 | `ask`・`review` | × | 不要（`review` の子で足りる） | — |
| ネットワーク障害の再試行 | 正規表現の分類・指数 backoff（#125 に未解決あり） | pi 本体の再試行 | ○ | 分類は pi 側のエラー型に任せ、**上限で pause** | 499 で止まらず、上限後は pause と通知 |
| 圧縮との合成・prompt cache | 差分の注入・live tail の保持（#108・#126 は未解決） | `autocheckpoint.ts`・自作の圧縮 | ○ | 状態は 1 行のサマリに留め、cache の前置を壊さない | リクエストの前置が前回と一致する割合 |
| 状態の追記ログ（ledger） | JSONL＋チェックポイント | 無し | ○ | 状態の正本を追記ログ 1 本にする | リプレイで同じ状態が復元される |

## G 上回るための方針

### 公開実装の実際の弱点 → 自作での解消

| 弱点（根拠） | 自作での解消 |
| --- | --- |
| 既定で無制限に自走。無進捗の検知が弱い（F2・#55・#100） | 予算を必須にし、状態の差分が無い継続は N 回で pause |
| ターン内バッファで kill 時に最大 1 ターン分を失う。fsync 無し（H1・H8） | 変更ごとの追記＋ fsync（性能は目標の更新が 1 ターン数回なので許容） |
| 競合でターンの変更を捨てる（H2） | 追記ログでは競合は「後勝ち」でなく両方を残す（マージは読み出し時） |
| フォーカスの迷子（H3） | 再開の 1 画面。目標は 1 件 |
| 監査役が判定器の外（E 節の穴①） | 監査役を `guarded_task` の子にして同じ判定器に通す |
| 監査役・Oracle の費用が予算に入らない（F3） | 費用を 1 つの台帳へ。子の使用量を合算 |
| 目標ファイルへの書き込みを止めない（F6） | 状態の置き場をフルガードの書き込み拒否の対象にする（エージェントは専用ツールだけで更新） |
| 順序・blocked の 3 ターンが prompt の約束だけ | コードで強制（依存・連続回数の検査） |
| 維持費: pi の API の変化への追従（#77・#78・#90・#113） | 自作でも同じ費用は発生する。ただし**自分の pi の版に固定でき、互換を広げなくてよい** |

### 自作でしか得られない強み

1. **フルガード下で迂回しない**: 継続・監査・保存がすべて自作の判定器を通る。公開拡張は「入れ子のセッションが拡張を読まない」設計で、判定の外が残る
2. **予算を必須にする**（回数・トークン・時間。子と監査役を合算）
3. **評価役の独立と費用の可視化**: 評価役のモデル・費用・所要を毎回 ledger に出す（公開実装は監査役の費用を数えない）
4. **faux モデルでの再現可能な試験**: 継続・監査・kill を決定的に試す。公開実装の試験は厚いが、本物の kill を使わず、実モデルの検証が重い（`experiments/live`）
5. **このリポジトリの `todo`・`guarded_task`・`ask` との統合**（二重の状態を持たない）

### 上回れない・価値が薄い点（正直に）

- **試験の厚み**（27,000 行・TLC の検討・PTY の実機）は、追いつくのに数週間かかる。到達しない可能性が高い
- **ダッシュボード・対話の起案・複数目標・i18n・キーの設定**は、自作で作る価値が薄い。公開実装の方が上
- **Windows の rename の再試行**・**シンボリックリンクの拒否**・**stale な ExtensionContext への対処**のような「地味な実機の不具合の修正」は、公開実装が 6 か月の運用で積んだ資産で、自作は初めから持たない（自作の pi の版に固定でも、`/reload` などは踏む）
- **公開実装が既に直したモデルごとの癖**（#59・#115 の strict 正規化・#122 の起案の見出し）は、自作でも踏む

### 最小で上回るセット（MVP）と後回し

**MVP（約 1.5〜2.5 千行＋試験。推測）**:

1. `/goal <目標> --budget N(回|トークン|分)`（必須）と、状態ファイル 1 つ（追記ログ＋fsync。エージェントは専用ツールだけで更新）
2. 継続: `agent_settled` で 1 回ずつ、claim・世代で二重配送を防ぐ。無進捗 N 回で pause
3. 完了: `guarded_task` の評価役に構造化された出力を返させる。不承認は理由を差し戻す。費用を台帳へ
4. 利用者の制御: pause・resume・clear・予算の変更。pause は評価役にも届く
5. 試験: faux モデルで、kill 注入・予算超過・偽の完了・二重配送を決定的に試す

**後回し**: ダッシュボード・複数目標・Oracle・i18n・`/sisyphus`（依存をコードで強制する版は第 2 段階）・対話の起案の高度化

## H vendor 判断の材料

| 項目 | 値・根拠 |
| --- | --- |
| 検査すべきコード量 | 全体 19,526 行。**安全に関わる核**は保存 973＋service 843＋scheduler 436・100＋events 676＋state 1,099＋auditor 480＋oracle 346＋completion 173＋commands 866＋settings 1,370（fs・env）≒ **7,000 行強**。UI・questionnaire・drafting（約 6,000 行）は見る優先度を下げられる |
| 依存 | 実行時 0。peer は pi 自身と typebox のみ。**サプライチェーンの面積は小さい** |
| install script・通信・exec | install 系の script 無し。`fetch`・`http`・`net`・`child_process` の import は `extensions/` に無し（grep）。fs の呼び出し約 87 か所。ネットワークは入れ子のセッション経由のみ |
| ライセンス適合 | MIT。著作権表示とライセンス文の同梱で足りる。vendor して改変しても問題ない（このリポジトリは公開） |
| 更新頻度 | 直近 90 日 316 commit・30 日 52 commit・タグ 95。保守者 1 人が週に数回リリース。**追従費用は大きい**（各リリースで pi の API・prompt の表現が動く）。最後の commit は 9 日前で、いまは静か |
| fork の追従 | 2 つの fork は★0・本家と同日の push で、独自の差は未確認。fork の追従は誰も実質的に実証していない |
| 概算の費用（**推測。見積もりの前提つき**） | **vendor＋検査＋パッチ**: 核 7,000 行を 1 時間 300〜400 行で読むとして約 20 時間、残りを粗く見て約 15 時間、パッチ（保存・予算・監査役のガード・F6）に約 20〜30 時間。**初期 約 55〜65 時間**＋追従（月 4〜8 時間程度）。**自作の MVP**: 約 1.5〜2.5 千行＋試験で約 30〜50 時間、追従は自分の pi だけで月 1〜2 時間。公開拡張の「ガードの外」を埋めるパッチは**入れ子セッションの作り方そのもの**（`goal-auditor.ts`）に及び、上流と衝突する（推測） |
| 結論 | **自作が上回れる条件**: ①安全の方針（予算の必須・フルガードの下・監査役のガード）が機能の幅より重要 ②pi の版を固定して追従を減らせる ③`todo`・`guarded_task` と統合したい。**vendor した方が良い領域**: ダッシュボード・対話の起案・複数目標・Windows の細かい互換（これらは自作しない、または公開拡張を **UI だけ**使う案は、状態を共有できず現実的でない）。**折衷案**: 自作の MVP を先に作り、公開実装の**テスト（87 ファイル）と issue の履歴を要件の一覧として使う**（vendor ではなく読み物として）。ADR-0016 とも整合する |

## I 未確認・限界

- **コードを 1 行も実行していない**。H1〜H8・F1〜F9 は読んだ範囲の推測。`kill -9` の注入・競合・目標ファイルの書き換え（F6）・監査役の bash がガードの外で動くこと
  （E 節の穴①）は、**再現して確かめていない**（次の候補: faux の入れ子セッションで確認）
- 配布物（npm の tarball）とリポジトリ（HEAD `b0fc15e`）の一致は未確認（`npm view` の件数のみ）。fork の差・npm の同名 scope 版の中身は未確認
- 貢献者は上位 10 名のみ。PR の本文・差分は読んでいない（題名と作者のみ）。issue は本文とコメントを**全件取得**したが、読んだのは主要なもの（◆）と grep の範囲
- `usage.input`／`usage.output` に cache の読み書きが含まれるかは、pi の定義を見ていない（F3）
- 承認待ち（ask）と継続の競合（E 節②）は未確認
- 試験の数と行数は `wc`・`ls` による。試験が実際に通るかは未確認（CI の結果は見ていない）
- 公開リポジトリの制約: 私物以外の環境の具体は書いていない

## 出典

取得日はすべて 2026-11-05。

- ソース: `https://github.com/tmonk/pi-goal-x`（HEAD `b0fc15ebb658a1e9ea60ae65496717a780080f37`、v0.34.1。`git clone` で全体を取得）
- npm: `npm view pi-goal-x time.modified version dist.unpackedSize dist.fileCount`（v0.34.1・2026-10-27・79 ファイル・1,066,675 byte）
- issue/PR: `gh issue list --repo tmonk/pi-goal-x --state all`、`gh pr list ...`、`gh api repos/tmonk/pi-goal-x`（★125・fork 60）
- 主な issue: [#30](https://github.com/tmonk/pi-goal-x/issues/30)・[#53](https://github.com/tmonk/pi-goal-x/issues/53)・[#55](https://github.com/tmonk/pi-goal-x/issues/55)・
  [#73](https://github.com/tmonk/pi-goal-x/issues/73)・[#100](https://github.com/tmonk/pi-goal-x/issues/100)・[#108](https://github.com/tmonk/pi-goal-x/issues/108)・
  [#122](https://github.com/tmonk/pi-goal-x/issues/122)・[#125](https://github.com/tmonk/pi-goal-x/issues/125)・[#126](https://github.com/tmonk/pi-goal-x/issues/126)
- このリポジトリ: `home/dot_pi/agent/extensions/todo/index.ts`・`home/dot_config/pi/harness/index.ts`・[CHG-0025](../../change/closed/0025-goal-autonomous-loop.md)
- 原文の保存: `.tmp/research/pi-goal-x/`（`sources/SOURCES.md`）。ライセンス: MIT
