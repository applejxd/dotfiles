# 公開拡張 `pi-tasks`（2 種）のソース調査と、自作 `todo` が上回れるかの判断

<!-- 現在の運用の正本は docs/spec/guard/pi-extensions.md（自作の拡張 todo）。ここは「いつ何を読み・測ったか」を積む場所 -->

## 記録 T1 — 2026-11-05

- **問い**: 自作の `todo` 拡張（`home/dot_pi/agent/extensions/todo/`）は、公開の `pi-tasks` を**上回れるか**。上回れないなら、公開実装を検査して vendor する方が良いか
- **対象の版**（同名が 2 つある）:
  - **(a) `@tintinweb/pi-tasks` 0.9.1**（`tintinweb/pi-tasks`、master `c820715`、2026-10-13。npm は月 4,220 DL・★243）
  - **(b) npm の `pi-tasks` 0.3.1**（作者 `nczz`、`nczz/pi-tasks` main `464b3f9`、2026-10-31。npm は月 2,150 DL・★8）
  - (a) と (b) は**別物**。(a) は Claude Code の Task 系ツール互換のタスクボード、(b) は「証拠つき完了ゲート」の実行契約。以降、(a)(b) で書き分ける
- **方法**: ソースを GitHub の raw から取り、全文を `.tmp/research/pi-tasks/sources/` に保存して読んだ（作業ツリー内・git 管理外）。issue / PR は `gh` の読み取りだけ。
  **対象コードは実行していない**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)・oss-research の約束）。したがって、欠陥の指摘は**コードを読んだ結果**で、実機の再現ではない（各項に「読んだ／未実行」と書く）
- **ライセンス**: (a)(b) とも MIT。本文の引用は 1 か所 40 行以内に収めた。コードは写していない
- 行番号の書き方: `a:task-store.ts:34` は保存した写し（`sources/tintinweb-task-store.ts.md`）の 34 行目。(a) の写しは master `c820715` 時点
  （`sources/tintinweb-task-paths.test.ts.md` の中身は `test/store-scope.test.ts`。保存名を誤った）

## 結論（先頭）

1. **規模**: (a) は src 約 3,060 行（`index.ts` が 1,417 行の一枚岩）＋試験 約 242 KB、実行時の依存 0。(b) は src 約 6,300 行（一部は推定）＋試験 約 138 KB、依存 0。自作は 640 行（`index.ts` 425・`view.ts` 215）
2. **(a) の強み 3 つ**: ①Claude Code 互換の 7 ツール名と説明文（モデルが学習済みの語彙）②subagent との連携（auto-cascade・遅延返信の回収・再接続）が試験つきで厚い ③CI が堅い（lint・型・試験を、pi の下限版と最新版の両方で回す）
3. **(a) の弱点 3 つ**: ①共有ファイルのロックに**排他が破れる経路**がある（`a:task-store.ts:40-47` の回収競合・PID 再利用で永久に回収されない・破損ファイルを黙って上書き）②**循環の依存は 2 者の直接循環しか警告せず、拒否もしない**（`a:task-store.ts:289`）③バックグラウンドプロセスの追跡は**配線されていない**（`tracker.track` の呼び出しが無い。README が認めている）。(b) の最大の弱点は、完了ゲートの語彙判定が実運用で 72 時間に 314 回の失敗を出し（issue #14）、モデル判定へ置き換えたこと（費用と遅延が増える）
4. **自作で上回れるか**: **上回れる**（共有を除く）。分岐に追従する状態・子の結果を完了と見なさない設計・faux モデルでの試験は、すでに (a) より強い。足りないのは**依存の宣言と循環の拒否**・**破損からの回復の明示**・**長い実行の途中のドリフト検知**で、最小の追加で埋まる。**vendor は勧めない**（理由は H）
5. **共有ファイルの信頼性**: (a) の方式（O_EXCL のロック＋tmp→rename）は、**通常の競合では更新を失わない設計**だが、**ロックを持ったまま死んだ後の回収と、破損ファイルの扱いに欠陥がある**（読んだ範囲）。試験は同一プロセス内の順次の交互で、**同時の複数プロセス・回収競合は試験されていない**。自作は「書き手を 1 つに固定する（セッションごとの単独書き込み＋読み取り専用の集約）」ことで、ロック自体を要らなくできる

## A 規模と体制

| 項目 | (a) `@tintinweb/pi-tasks` | (b) `pi-tasks`（nczz） |
| --- | --- | --- |
| 版・日付 | 0.9.1（2026-10-13） | 0.3.1（main の package.json。2026-10-31 まで更新） |
| 作成 | 2026-03-11 | 2026-06-19 |
| ライセンス | MIT | MIT |
| 実行時の依存（再帰） | **0**（`peerDependencies`: pi 本体 2 つと `typebox`）。`TaskExecute` だけ別拡張 `@tintinweb/pi-subagents` が要る | **0**（`dependencies` 無し。`node:crypto` のみ） |
| 開発時の依存 | 7（biome・typescript・vitest・pi 本体 2・typebox・@types/node）。`package-lock.json` 123 KB | 4（biome・typescript・vitest・@types/node）＋ `overrides` |
| src の行数 | `index.ts` 1,417／`task-store.ts` 402／`task-widget.ts` 325／`settings-menu.ts` 174／`auto-clear.ts` 134／`process-tracker.ts` 140／`task-glyphs.ts` 110／`task-sort.ts` 90／`reminder-cadence.ts` 90／`tasks-config.ts` 77／`task-paths.ts` 65／`types.ts` 約 36。**計 約 3,060** | `reducer.ts` 1,756／`tools.ts` 1,586／`semantic-assessment.ts` 1,145／`model.ts` 403。`render.ts`（21 KB）・`semantic-capability.ts`（9 KB）ほかは行数を取らず**推定 約 1,300**。**計 約 6,300（一部推定）** |
| 試験 | 21 ファイル（補助 3 を除く）約 242 KB（src の約 1.9 倍）。`subagent-integration.test.ts` だけで 51 KB | 10 ファイル（補助 1 を含む）約 138 KB（src の約 0.7 倍） |
| CI | あり（`.github/workflows/ci.yml`）: lint・型・試験。さらに **pi の下限版（0.80.5）と最新版**で型と試験を回す（最新は失敗を許容） | **無し**（リポジトリに `.github` が無い）。`scripts/release-check.sh` と実機の dogfood 記録（`docs/DOGFOOD.md` 80 KB） |
| commit | 全期間 約 80 件。**直近 90 日（2026-08-07〜）に 26 件**。最終 2026-10-13（23 日前）。リリース v0.7.3〜v0.9.1 の 4 回が 90 日以内 | 全期間 約 50 件。**直近 90 日に 25 件**。最終 2026-10-31 |
| 貢献者 | 13 人（Copilot 含む）。`tintinweb` が 66 件（**約 82%**）。ほか 1〜2 件ずつ | 3 人。`nczz` が 47 件（**約 94%**） |
| バス係数 | **1**。ただし外部の PR は受け入れている（merged 19・open 6・closed のみ 21） | **1**。外部の PR は 3 件 |
| fork・利用 | fork 61・npm 月 4,220 | npm 月 2,150 |

- (a) の README は「Status: Early release」と自称する（`a:README.md:5`）。
- 他の `pi-tasks` 系（GitHub 上の説明文と `gh repo view` の値だけ。**ソースは読んでいない**）:

| リポジトリ | 説明 | ★ | 最終 push | ライセンス |
| --- | --- | --- | --- | --- |
| `Soleone/pi-tasks` | beads などのバックエンドでタスクを管理 | 26 | 2026-10-24 | MIT |
| `edxeth/pi-tasks` | Claude Code 風。常時のウィジェット・セッションごとの永続・ドリフト時の穏やかなリマインド | 18 | 2026-09-30 | MIT |
| `eleqtrizit/pi-tasks` | Claude Code のタスク系の移植 | 2 | 2026-10-17 | **無し（ライセンス不明）** |
| `harms-haus/pi-tasks` | 段階的なワークフロー・依存・状態の厳格なゲート | 0 | 2026-05-25 | MIT |

→ 取り込み・参考の対象になるのは、規模と保守の点で (a)。`eleqtrizit` はライセンスが無いので取り込めない。

## B アーキテクチャ

### B1 (a) の入口と、使う pi の API

- 入口は `src/index.ts` の `export default function (pi)`。`package.json` の `pi.extensions` が `./src/index.ts`（TypeScript をそのまま読み込む）
- **使うイベント**（`a:index.ts`）: `turn_start`:503・`agent_settled`:517・`turn_end`:525・`tool_result`:553・**`context`:581**・`session_start`:599・
  `session_shutdown`:645・`before_agent_start`:651・`tool_execution_start`:664
- **使わないイベント**: **`session_tree`・`session_before_compact`・`appendEntry` は無い**。状態は会話の外のファイル（または記憶）に持つので、
  `/tree` で過去へ戻っても**タスクは巻き戻らない**（コードにその処理が無いことからの帰結。実機では未確認）。fork だけは `session_start` の `reason === "fork"` でスナップショットを複製する（`a:index.ts:610`）
- **登録**: ツール 7 つ（`registerTool`）＋コマンド `/tasks`（`registerCommand`）＋ウィジェット（`setWidget("tasks", …)`、`a:task-widget.ts:303`）
- **他拡張との通信**: pi のイベントバスの RPC（`subagents:rpc:ping`・`spawn`・`stop`・`consume`、通知 `subagents:completed`・`failed`・`ready`）。プロトコル版は 2（`a:index.ts:271`）

### B2 データ型（原文。`a:types.ts`）

```ts
export type TaskStatus = "pending" | "in_progress" | "completed";

export interface Task {
  id: string;
  subject: string;
  description: string;
  status: TaskStatus;
  activeForm?: string;
  owner?: string;
  metadata: Record<string, any>;
  blocks: string[];
  blockedBy: string[];
  createdAt: number;
  updatedAt: number;
}

/** Serialized store format on disk. */
export interface TaskStoreData {
  nextId: number;
  tasks: Task[];
}
```

- 状態は **3 つだけ**。`blocked` と `cancelled` は無い（`TaskUpdate` は `deleted` も受けるが、それは削除）。子の失敗は `pending` に戻して `metadata.lastError` に入れる（`a:index.ts:386-405`）
- `metadata` は任意の JSON。`agentType`・`agentId`・`result`・`lastError` がここに入る（型は `any`）

### B3 保存先と形式

| `taskScope`（既定は `session`） | 保存先 | 共有 |
| --- | --- | --- |
| `memory` | 記憶だけ | しない |
| `session`（**既定**） | `<cwd>/.pi/tasks/tasks-<sessionId>.json` | セッションごとに 1 ファイル（**共有ではない**） |
| `session-global` | `<agent-dir>/tasks/sessions/--<cwd 由来>--/tasks-<sessionId>.json` | 同上 |
| `project` | `<cwd>/.pi/tasks/tasks.json` | **共有**（プロジェクトで 1 つ） |
| 環境変数 `PI_TASKS=<名前>` | `~/.pi/tasks/<名前>.json` | **共有**（名前つきリスト） |
| `PI_TASKS=/abs/path`・`./rel` | そのパス | 共有 |
| `PI_TASKS=off` | 記憶だけ | しない |

出典: `a:index.ts:136-168`・`a:task-paths.ts`・`a:README.md:219-232,282-286`。形式は JSON 1 ファイル（`{ nextId, tasks[] }`、2 スペース整形）。
**複数セッションの共有は、既定では有効でない**（`PI_TASKS` か `taskScope: "project"` を選んだときだけ）。

### B4 設定のスキーマ（`a:tasks-config.ts`）

`taskScope`・`autoCascade`（既定 false）・`autoClearCompleted`（`never` / `on_list_complete` 既定 / `on_task_complete`）・`collapseCompleted`・`showAll`・`maxVisible`（10）・`sortOrder`・
`hiddenAt`・`glyphs`。置き場は `<agent-dir>/tasks-config.json`（全体）と `<cwd>/.pi/tasks-config.json`（プロジェクト。キーごとに上書き）。**設定は常にデータで、実行できる設定ファイルは無い**（`.pi/` が clone したリポジトリの中にあるため。`a:tasks-config.ts:1-6`）

### B5 UI

- **常駐ウィジェット**（`setWidget`）: 状態の記号・スピナー・経過時間・トークン数を、最大 10 件まで表示。**150 ms ごとのタイマー**で `update()` を呼ぶ（`a:task-widget.ts:135-139`）
- **`/tasks`**: `ui.select` の入れ子のメニュー（一覧・作成・完了を消す・全部消す・設定）。詳細画面の操作は「開始・完了・削除」だけで、**依存や note は画面から編集できない**（`a:index.ts:1362-1400`）

### B6 (b) の構造

- 入口 `index.ts`（約 65 行）。`registerTool`・`registerCommand`・`appendEntry`・`ctx.sessionManager.getBranch()`・`session_start`・`session_tree`・`session_before_compact`・`ui.setStatus`・`ui.setWidget`（`b:README.md` の「Oh My Pi support」節）
- **イベントソーシング**: 状態は pi の**セッション JSONL に `pi-tasks:event` の custom エントリとして追記**し、`session_start` / `session_tree` で枝の全イベントを**再生**して復元する（`b:store.ts` の `replayBranchEntries`）。**ファイルを書かない**（`node:fs` の import が src に無い）。したがって**分岐・再開・圧縮に自然に追従し、共有はしない**
- 型（`b:model.ts`）: 状態は `pending / active / blocked / review / done / cancelled`。`Task` は `planSteps`（順序つきの手順）・`acceptanceCriteria`・`evidence`・`decisions`・`blockers`・`dependencies: string[]`・`linkedFiles`・`linkedCommits` を持つ
- ツールは 12 個: `task_plan`・`task_next`・`task_focus`・`task_resume`・`task_checkpoint`・`task_granularity_check`・`task_decompose`・`task_list`・`task_update`・`task_evidence`・`task_decision`・`task_complete`
- 新しいセッションでは `task_plan` と `task_resume` だけを公開し、タスクが出来てから残りのツールを有効にする（`setActiveTools`。`b:tools.ts:189-307`）。ツール一覧を動的に変えるので、**pi のツール許可リスト（フルガード）との相性は未確認**

## C アルゴリズム

### C1 (a) の 7 ツールの意味と引数

| ツール | 引数 | 意味 |
| --- | --- | --- |
| `TaskCreate` | `subject`・`description`・`activeForm?`・`agentType?`・`metadata?` | 1 件作る（`pending`）。複数件は**同じ応答で複数回呼ぶ**（一括の引数は無い。バッチ作成の PR 4 件（#16・#18・#24・#25）は閉じられた） |
| `TaskList` | 無し | 全件。**並びは pending → in_progress → completed**（ID 順）。未完了のブロッカーを表示 |
| `TaskGet` | `taskId` | 詳細（説明・ブロッカー・metadata）。存在しない ID は `"Task not found"` を成功として返す（issue #70。0.9.1 で修正） |
| `TaskUpdate` | `taskId`・`status`（`pending`/`in_progress`/`completed`/`deleted`）・`subject`・`description`・`activeForm`・`owner`・`metadata`（null で消す）・`addBlocks`・`addBlockedBy` | 部分更新。**依存の削除（`removeBlocks`）は無い**（issue #28 が open） |
| `TaskOutput` | `task_id`・`block`・`timeout` | バックグラウンドの出力、または subagent の結果を待って返す |
| `TaskStop` | `task_id` | プロセスか subagent を止める。**成否にかかわらず `completed` にする**（README が明記。`a:README.md:179`） |
| `TaskExecute` | `task_ids`・`additional_context`・`model`・`max_turns` | `agentType` つきの `pending` で、ブロッカーが全て `completed` のタスクを subagent として起動 |

### C2 依存グラフの扱い（読んだ範囲）

- **辺の保存**: `addBlocks` / `addBlockedBy` は**両端に書く**（双方向）。対象が存在しなくても**辺は保存し、警告だけ返す**（`a:task-store.ts:273-319`）
- **警告の条件**（拒否はしない）: 自己依存（`targetId === id`）・存在しない ID・**直接の 2 者循環**（`target.blocks.includes(id)`、`a:task-store.ts:289`・`311`）。
  **3 者以上の循環（A→B→C→A）は検出しない。辺の削除手段も無い**ので、一度できた循環はタスクを削除しないと消せない（issue #28）
- **自動の unblock は無い**: ブロッカーが `completed` になっても何も書き換えない。`TaskList` / `TaskGet` が**表示時に**「未完了のブロッカー」を数え直す（`a:index.ts:796-805`・`861-868`）。状態は 3 つだけなので、`blocked` という状態は無い
- **ブロッカーを無視した状態遷移**: `TaskUpdate` は `in_progress` / `completed` への変更を**そのまま適用し、警告を添える**（0.9.1 で追加。`a:task-store.ts:318-327`）。`TaskExecute` だけが拒否する（`a:index.ts:1225-1230`）
- **削除時**: 他のタスクの辺を掃除する（`a:task-store.ts:228-236`・`clearCompleted` は 382-400）

状態遷移（コードから起こした。遷移の検査は無いので、全ての組が許される）:

| から＼へ | pending | in_progress | completed | deleted |
| --- | --- | --- | --- | --- |
| pending | – | 可（ブロッカーがあれば警告） | 可（同上） | 可 |
| in_progress | 可 | – | 可（同上） | 可 |
| completed | **可**（再オープン） | 可 | – | 可 |

- subagent の完了通知は `completed`、失敗は `pending`＋`lastError`、意図した停止（`status === "stopped"`）は `completed`＋途中の結果（`a:index.ts:340-405`）。**子の終了＝タスクの完了と見なす**（結果の検証は無い）

### C3 複数セッションの共有（重点）

**ファイル**: JSON 1 つ（`{ nextId, tasks[] }`）。隣に `<file>.lock`（ロック）。書き込みは `<file>.tmp` へ書いて `rename`。

**ロックの取り方**（原文。`a:task-store.ts:25-58`。MIT・tintinweb）:

```ts
function acquireLock(lockPath: string): string {
  mkdirSync(dirname(lockPath), { recursive: true });
  const token = `${process.pid}:${randomUUID()}`;

  for (let i = 0; i < LOCK_MAX_RETRIES; i++) {
    try {
      // O_EXCL: fail if file exists
      writeFileSync(lockPath, token, { flag: "wx" });
      return token;
    } catch (e: any) {
      if (e.code === "EEXIST") {
        // Check for stale lock (process no longer running)
        try {
          const pid = parseInt(readFileSync(lockPath, "utf-8"), 10);
          if (pid > 0 ? !isProcessRunning(pid) : i >= 2) {
            unlinkSync(lockPath);
            continue;
          }
        } catch { /* ignore read errors */ }
        // Wait and retry
        const start = Date.now();
        while (Date.now() - start < LOCK_RETRY_MS) { /* busy wait */ }
        continue;
      }
      throw e;
    }
  }
  throw new Error(`Failed to acquire lock: ${lockPath}`);
}
```

（途中のコメントを一部省いた。`LOCK_RETRY_MS = 50`・`LOCK_MAX_RETRIES = 100`＝最大 5 秒。）

- **ロック中の手順**（`withLock`、`a:task-store.ts:166-176`）: ロックを取る → **ファイルを読み直す**（`load`）→ 変更 → `save`（tmp に書いて `rename`）→ 解放。読み直しがあるので、**通常の競合（2 つのセッションが別々のタスクを更新）では他方の更新を失わない**。`get` / `list` はロックを取らず、毎回ファイルを読む（`rename` が原子的なので、部分的な内容は読まない）
- **解放**: 自分のトークンと一致するときだけ消す（`a:task-store.ts:68-73`）。別の PID 名前空間（コンテナ・NFS）で自分の PID が「死んでいる」と誤判定され、後継が奪った場合に、後継のロックを消さないため
- **古いロックの回収**: ロックファイルの PID が**ローカルのプロセス表に無い**と回収する。PID が読めないもの（空・文字列）は、**3 回目以降の再試行**で回収する
- **破損時の回復**（`load`、`a:task-store.ts:126-150`）: JSON でない・`tasks` が配列でない場合は**何もせず、手元の状態を保つ**。`nextId` が不正なら最大の ID + 1 から再計算する

**競合時の勝敗**: ロックを先に取った側が先に書く。待つ側は最大 5 秒で `Error` を投げる。順序の公平性は無い。

**読んで見つかった欠陥**（いずれも**未実行**。コードの読みからの指摘。重い順）:

| # | 欠陥 | 根拠 | 影響 |
| --- | --- | --- | --- |
| L1 | **古いロックの回収に競合がある**。待つ側 W1・W2 が同じ「死んだ PID のロック」を読み、W1 が `unlink`→`wx` で新しいロックを取った**後に**、W2 が自分の判定を使って `unlink` する。W2 が W1 の生きたロックを消し、W2 も `wx` に成功する → **2 つのセッションが同時に臨界区間に入る** | `a:task-store.ts:40-47`（判定と `unlink` の間に原子性が無い）。解放側のトークン検査（68-73）は、この `unlink` を防がない | 後に `rename` した側の内容で、他方の更新が消える。**発生条件**: 死んだ保持者のロックが残っている状態で、2 つ以上のセッションが同時に待つ（確率は低いが、まさに「クラッシュ後」に起きる） |
| L2 | **PID 再利用でロックが回収されない**（永久） | `a:task-store.ts:45`: PID が**別の無関係なプロセスで生きていれば**回収しない。期限（mtime や心拍）の判定が無い | 以降、全ての変更が 5 秒待って `Failed to acquire lock` で失敗する。**手で `.lock` を消すまで直らない** |
| L3 | **PID 名前空間をまたぐと、生きたロックを回収する** | `a:task-store.ts:60-67` のコメントが自認 | 排他が破れる（解放側の保護だけ入っている） |
| L4 | **破損ファイルを黙って上書きする**。`load` は壊れたファイルを**無視して手元の状態（起動直後は空）を保つ**ため、**次の変更の `save` が、空の状態（`nextId = 1`）で壊れたファイルを上書き**する。**退避・警告が無い** | `a:task-store.ts:149`（`catch { /* … keep the state we have */ }`）と `save`。PR #15（「黙った消失を出す」）が 2026-04-27 から open のまま | 破損の原因（途中で切れた書き込み・手編集）が追えなくなり、ID が 1 から再び振られて、subagent の対応表と衝突しうる |
| L5 | **待機が busy-wait（50 ms の空ループ）で、最大 5 秒、Node のイベントループを止める** | `a:task-store.ts:50-52` | 競合中は pi の TUI が固まる |
| L6 | `fsync` が無い | `a:task-store.ts:161-162`（`writeFileSync`→`renameSync`）。src の全 12 ファイルに `fsync` の語が無い（grep） | 電源断で空・部分のファイルが残りうる（**推測**。OS・ファイルシステム依存） |
| L7 | ロックの外での**読み→書き**がある。`bindAgent` と完了の通知は、ロックの外で `store.get` した `metadata` を**展開して** `store.update` に渡す | `a:index.ts:232-236`・`348` | 他のセッションが更新した同じキーを、古い値で戻す。範囲は `metadata` の既存キーだけ（影響は小さい） |
| L8 | **試験が弱い**。`task-store-concurrency.test.ts` は、**同一プロセス内で `a.update(); b.update()` と順に呼ぶ**交互の試験で、**同時に動く複数プロセスの試験が無い**。「生きた保持者に対して再試行を使い切る」ことは**意図して試験しない**と明記（5 秒かかるため） | `a:task-store-concurrency.test.ts:1-9`・`33-50`・`96-125` | L1・L2・L5 は試験の外 |

→ **共有ファイルの信頼性の結論**: 原子的な書き込みと、ロック中の読み直しは妥当で、**平常時の更新の取りこぼしは起こりにくい**。一方、**回収の競合（L1）・永久に回収されないロック（L2）・破損の黙った上書き（L4）は、読んだだけで分かる欠陥**で、試験にも無い。「ロックを持ったまま kill しても次が回復する」は**条件つき**（回収の競合が無く、PID が再利用されていないとき）。

### C4 リマインダーの注入（`a:index.ts:53-130`・`503-596`、`a:reminder-cadence.ts`）

- **条件**: タスクツールを**最後に使ってから 4 ターン**（`in_progress` があるときは **2 ターン**）が経ち、タスクが 1 件以上あるとき。空のリストにも、「空です。無視してよい」という注意を出す。`turn_end` で、`in_progress` が残ったまま文章だけのターンが続いた場合も予約する（`a:index.ts:525-543`）
- **注入の仕方**: `tool_result` では**カウントだけ**行い（他のツールの出力を書き換えない。issue #20 の修正）、**`context` フックで、次の LLM 呼び出しのメッセージ配列の末尾に `user` ロールのメッセージを 1 つ足す**。**会話には保存しない**（`a:index.ts:581-596`）
- **内容**: `<system-reminder>` で包み、「このことを利用者に言うな」「最新のタスクは次の JSON」＋ `[{id, content, status, activeForm?}]`。**10 件を超えたら、`in_progress` → `pending` → `completed` の順で 10 件に切る**。件名は改行と `<system-reminder>` タグを除去（`a:index.ts:76-78`）
- **弱点**: PR #72（open）の指摘では、`context` フックが返す配列を pi が `restoreSystemMessages` で組み直すため、**途中でシステムプロンプトやツール構成が変わったセッションでは、リマインダーのたびに先頭のシステムメッセージが変わり、プロンプトキャッシュが最初から外れる**（Anthropic・OpenAI Responses・Codex）。読んだ範囲では、この指摘は pi のソースの説明で、**未確認**。issue #40 は、リマインダーの「続けよ」が、委譲を意図した流れで「自分でやれ」に聞こえることを指摘している

### C5 バックグラウンドプロセスの追跡

- `ProcessTracker`（`a:process-tracker.ts`、140 行）は、出力の蓄積・待機・停止（SIGTERM→5 秒→SIGKILL）を持つ
- **`tracker.track(...)` の呼び出しが、src のどこにも無い**（`a:index.ts` の `tracker.` は `getOutput`・`waitForCompletion`・`stop` だけ。grep で確認）。README の「Future Work」が、「pi の bash に `run_in_background` が無いので、フックする先が無い」と認めている（`a:README.md:405`）
- → **この機能は現状、実質的に死んだコード**（README の機能一覧 `a:README.md:22` は、動くかのように書いている）。`TaskOutput` / `TaskStop` が有効に働くのは、subagent のタスクだけ

### C6 subagent での実行と auto-cascade

- `TaskExecute`: ①存在・`pending`・`agentType`・ブロッカーの完了を確認 → ②`in_progress` にして RPC で起動（30 秒の期限）→ ③返ってきた agent ID を `metadata.agentId` に書く
- **期限切れでも起動した可能性がある**ので `pending` に戻さず、5 分間の遅延返信を待ち、**タスクが既に変わっていたら、その子を止める**（`adoptLateAgent`、`a:index.ts:243-253`。issue #48 の修正）
- **auto-cascade**（`autoCascade: true` のとき）: 子の完了通知で、**ブロッカーが全て完了した `agentType` つきの `pending` を続けて起動**する。**先行タスクの結果（4,000 字まで）を後続のプロンプトに入れる**（`a:index.ts:306-331`・`340-383`）
- **リロードからの再接続**: `metadata.agentId` を持つ `in_progress` から対応表を作り直す（`reattachAgents`、`a:index.ts:465-475`）
- **弱点**: 子が終了＝タスク完了（結果の検証が無い）。`TaskStop` が失敗の RPC でも `completed`（README が明記）。**子はフルガードの外**（E を参照）

### C7 compaction・resume との合成

- (a): 状態はファイルにあり、会話の外なので、**圧縮で状態自体は失われない**。モデルは、リマインダー（C4）に入る**最新のリスト**で思い出す。`session_before_compact` は使わない
- (b): 圧縮の直前に `task.snapshot` を会話へ追記し（`b:index.ts:45-64`）、`task_resume` が**次の 1 手の指示**（`resume` の契約）を返す。**再生は決定的で、モデルを呼ばない**（`b:README.md`「Native semantic assessment」節）

### C8 タスクが多いときの性能

- (a): ファイルを使うモードでは、**`list()` / `get()` が呼ばれるたびにファイル全体を `readFileSync` + `JSON.parse`** する。ウィジェットは**150 ms ごとのタイマーで `update()`（＝`store.list()`）を呼び**（`a:task-widget.ts:135-139`・`268`）、描画でも `list()` と、ブロッカーごとの `get()` を呼ぶ（216・160）。タイマーが動いている間は、**毎秒 10 回を超えるファイル読み**になりうる（タイマーの起動条件は未読。**実測なし**）。issue #11（スピナーの再描画で CPU が高い）は、描画率の削減で対処済み。リマインダーは 10 件で打ち切る
- (b): **再生が 2 乗**（issue #12）。`reduceTaskState` が、イベントごとに**蓄積した全イベント履歴を `cloneState` で深いコピー**して捨てていた。実際の大きなセッションで、**pi の RPC `get_state` が 32.2 秒**かかった（プロファイルでは 22.5 秒が `structuredClone`）。2026-10-16 の 0.2.9 で修正済み

### C9 (b) の完了ゲート（参考）

`task_complete` が拒否する条件（`b:README.md`「Completion Gates」）: 証拠が無い・順序つきの手順が残っている・必須の基準が未達・証拠の無い達成・未解決のブロッカー・未解決の範囲逸脱・`not_verified` だけ・後の再実行で置き換えられていない失敗。`force_with_reason` で強制でき、低い確信度の警告が付く。
**計画と証拠の質の判定**は、初期は正規表現（語彙）で、**72 時間の実運用で 314 回のツール呼び出しが失敗**した（issue #14。「implement」「fix」を曖昧と判定し、再試行の案内も同じ語を使わせた）。0.3.x で**ホストのモデル（分類器・`streamSimple`・OMP の `runEphemeralTurn`）に判定させる**方式に置き換えた。**費用・遅延が増え、モデルが使えないときは「失敗側に倒す」**（`b:README.md`「Native semantic assessment」節）。
**依存（`dependencies`）は、保存するだけで検証・使用をしていない**（`b:reducer.ts:168` の代入のみ。grep で他の使用箇所は見つからなかった）

## D 品質

### D1 試験・CI・エラー処理

- (a): 試験は厚い（C2・C3 の周辺、subagent 連携、auto-clear、reminder、widget）。**ただし L8 のとおり、共有ファイルの同時実行は試験されていない**。ツールの例外は `throw`（pi が結果にする。`tool-error-reporting.test.ts`）。widget の描画は `try/catch` で空にして落とさない（`a:task-widget.ts:140-150`）
- (b): 単体の試験は reducer・schema・tools・semantic。**CI 無し**。実機の dogfood の記録が厚い

### D2 issue と PR（取得: 2026-11-05。本文を読んだのは一部で、残りは題名と日付）

#### (a) open の issue 全件（6）

| # | 題名 | 起票 | 備考 |
| --- | --- | --- | --- |
| 73 | ウィジェットのトークン数が膨らむ（同じターンの二重配信・新セッションが ID で引き継ぐ） | 2026-10-23 | PR #74（open）。再現手順つき。`turn_end` に識別子が無い（`a:index.ts:525-530`） |
| 50 | nicobailon/pi-subagents へのアダプタ | 2026-08-10 | 機能要望 |
| 40 | `TaskExecute` の委譲が、プロンプトの誘導と `agentType` の既定値の欠落で成立しない | 2026-07-24 | PR #64（open）。`agentType` が任意・リマインダーが委譲を促さない・「Agent ツールを使うな」で行き止まり |
| 28 | `removeBlocks` / `removeBlockedBy` が無い | 2026-06-25 | 依存を直せず、タスクを消して作り直すため metadata を失う |
| 9 | タスクごとの基本統計 | 2026-04-13 | 要望 |
| 8 | ウィジェットの様式 | 2026-04-01 | 要望 |

#### (a) closed の issue 24 件（主題別）

| 主題 | 件 | 内容 |
| --- | --- | --- |
| 保存先・復元 | 8 | #29 再起動後に表示されない・#33 旧形式のファイルで widget が落ちる（`blockedBy` が undefined）・#43 `--no-session` で `.pi/tasks` が残る・#53/#56/#57 セッションのファイルをプロジェクトの外へ・#3 ほか（#3 は題名のみ） |
| subagent・RPC | 8 | #6 RPC の封筒の不一致で黙って失敗・#26・#46 **`TaskStop` が RPC 失敗でも成功**・#47 リロード後に再接続されない・#48 **期限切れの後に子が二重起動**・#49 別名の解決・#62 結果を消費せず完了通知が二重・#69 `TaskStop` が無条件で completed |
| ツールの意味 | 3 | #70 存在しない ID に成功を返す・#71 **ブロッカーを無視した状態変更に警告が無い**（0.9.1 で警告のみ）・#59（題名のみ） |
| リマインダー | 1 | #20 `tool_result` に混ぜると無関係なツールの出力が汚れる（`context` へ移した） |
| 性能・UI | 1 | #11 スピナーの再描画が CPU を食う |
| 依存・移行 | 3 | #23 `@mariozechner` → `@earendil-works`・#66/#68 `typebox` を peer へ |
| その他 | 1 | #44 |

- **傾向**: 不具合の約半数が **subagent の状態（二重起動・成否の取り違え・再接続）**。**#46・#48・#69・#70・#71 は 2026-08〜10 に起票され、2026-10-13 の 0.9.1 でまとめて閉じられた**（修正までに約 1〜2 か月）。依存の循環・ロックに関する issue は**起票されていない**（L1〜L4 は誰も指摘していない）

**(a) PR（46 件）**: merged 19・open 6（#15・#42・#64・#72・#74・#76）・merged されず closed 21。**「一括作成」の 4 件（#16・#18・#24・#25）と、独自の並び替えの 2 件（#35・#54）は取り込まれなかった**（その後 0.8.0 で維持者が並び替えを実装）（維持者が README の記述と並列呼び出しの案内で済ませた）。外部の取り込みは、小さな修正が中心（#13・#27・#34・#36・#45・#58・#60・#65・#67）。open の PR #15（失敗の可視化）は **6 か月超**放置

**(b) issue（9 件、すべて closed）**: #3・#4・#8・#9・#10・#11・#12・#13・#14 の **9 件のうち 8 件が、完了ゲート・計画ゲートの誤判定（弱いモデルが再試行の無限ループに入る）**、1 件（#12）が再生の性能。**単独の維持者が、起票の翌日〜数日で直している**

### D3 コードを読んで見つかる欠陥の一覧（(a)。未実行）

- L1〜L8（C3）
- **D-1 循環の検出が 2 者だけ**（C2）。3 者以上は黙って保存する。`TaskExecute` は循環したタスクを決して起動できない（互いがブロッカー）。**無限ループにはならない**（起動の条件を満たさず止まる＝**停止せず待つだけ**）
- **D-2 `TaskStop` が常に `completed`**（C1）。停止できなかった子が走り続けても、タスクは完了に見える。後の失敗通知で `pending` に戻る可能性がある
- **D-3 `completed` を `pending` に戻せる**（再オープンは許される）ので、`autoClear` が先に消したタスクを、モデルが追い続ける（PR #15 の指摘）
- **D-4 バックグラウンド追跡が配線されていない**（C5）
- **D-5 トークン数の二重計上**（issue #73）

## E 権限と安全

- **実行できること**: 外部コマンドの起動は**無い**（`child_process` は `process-tracker.ts` の型の import だけ。`spawn` / `exec` は src に無い。grep）。通信も**無い**（`http`・`fetch` が src に無い）。**テレメトリも無い**。副作用は、イベントバスの RPC（`subagents:rpc:*`）と、ファイルの読み書き
- **ファイルの書き込み範囲**（src の呼び出し箇所: 約 17。`task-store.ts` 11・`tasks-config.ts` 4・`task-paths.ts` 2）: `<cwd>/.pi/tasks/`・`<cwd>/.pi/tasks-config.json`・`~/.pi/tasks/`・`<agent-dir>/tasks/`・`PI_TASKS` が指す**任意のパス**（絶対パスを許す）
- **セキュリティの方針**（`a:SECURITY.md`）: 共有のタスクファイルは「**信頼できる入力**」で、**モデルへそのまま戻される**。ロックは「並行の正しさ」のためで、安全の機構ではない。プロンプトインジェクション・悪意のあるタスクファイル・書き込み権限を要する報告は**範囲外**。サンドボックスは持たない
- **フルガード下で動かしたときの穴**（**推測**を含む。実機では動かしていない）:
  1. **`TaskExecute` は `@tintinweb/pi-subagents` が必要**で、これは[導入しない判断（no-go）](pi-public-extensions-survey.md)（子が親と同じプロセスで組み込みの `bash` を持ち、判定を通らない経路になりうる）。(a) を入れても、`TaskExecute` と auto-cascade は使わない前提になる（残りの 6 ツールは単独で動く。`a:README.md`「Standalone Mode」）
  2. **ファイルの置き場がワークスペースの中**（`<cwd>/.pi/tasks/`）。**子エージェントがワークスペースに書ける権限を持つなら、タスクのファイルを書き換えて、親の次のリマインダー（`context` に挿入される `user` ロールのメッセージ）の中身を変えられる**。リマインダーは件名と `activeForm` を整形する（改行と `<system-reminder>` を除去。`a:index.ts:76-78`）が、`TaskGet` / `TaskOutput` が返す `description`・`metadata.result` は**整形されない**。方針が「信頼できる入力」なので、**ガードの境界を越える注入経路を、設計上、拡張の側が持つ**（推測。ワーカーが `.pi/` に書けるかは、この調査では未確認）
  3. **共有（`PI_TASKS=<名前>`・`project`）は、ワークツリーの外（`~/.pi/tasks/`）または複数のワークツリーにまたがる**。pis の sandbox が `~` を既定で不可視にするなら、そもそも書けない可能性が高い（推測。未確認）
  4. **拡張のコードは pi プロセスの内側で動く**ので、`guarded_*` の判定を通らずに、プロセスの権限でファイルを書く。**書き込み先の検査は sandbox の境界だけ**
  5. ツール名が `TaskCreate` などで、`guarded_*` ではない。フルガードの許可・承認の設計とどう合うかは**未確認**
  6. `PI_TASKS` の絶対パスは**任意の場所**を書き込み先にできる（環境変数を握る側に依存。ガードの許可の範囲との関係は**未確認**）
- **(b) の穴**: ファイルも通信も無い（`node:fs`・`child_process`・`process.env` が src に無い。grep）。**ただし意味判定でホストのモデルを呼ぶ**（分類器 → `streamSimple` → OMP の `runEphemeralTurn`）。pi のモデル呼び出しは、フルガード下では**ブローカー経由・課金・待ち時間**が付く。OMP では「現在の会話のスナップショット」が判定に含まれうる（`b:README.md`）。ツール一覧を動的に変える（`setActiveTools`）点は、許可リストと衝突しうる（未確認）

## F 機能比較表

判断: **◎** 同等が必須／**○** 取り入れる／**△** 上回る設計がある／**×** 不要。「今の pi」は `home/dot_pi/agent/extensions/todo/`（`index.ts` 425 行・`view.ts` 215 行）、
`home/dot_config/pi/harness/index.ts` の `guarded_task` の `todo` 引数（1592・1475-1490 行）、`/todos`、フッター（`setStatus("todo", …)`）を読んで確かめた。

| # | 機能 | 公開実装の仕様（出典） | 今の pi | 判断 | 上回る設計の案 | 上回ったと言える検証 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 状態の種類 | (a) `pending`・`in_progress`・`completed`（`a:types.ts:5`）。(b) `pending`・`active`・`blocked`・`review`・`done`・`cancelled`（`b:model.ts`） | `pending`・`in_progress`・**`blocked`**・`done`・**`cancelled`**＋ `note`（`index.ts:12-14`） | ◎ 既に同等以上 | `blocked` の待ち先を note に書かせる警告が既にある（`index.ts:93`）。`blocked` には待ち先の種別（子・ジョブ・利用者）を任意で持たせ、`/todos` で束ねる | 試験: `blocked` を note 無しで置くと警告（既存）。追加の検証は要らない |
| 2 | タスクの一括操作 | (a) 一括の引数は無い（並列呼び出しで代用。PR 4 件は却下）。(b) 該当なし | `batch`（原子的）・`replace`・`add` の複数件（`index.ts:23-55`・`run` 191-201） | ◎ 既に**上回る** | 既に原子的（1 件でも失敗なら全体を適用しない） | 既存: `test_todo_batch_is_atomic_and_names_the_failing_operation`（`test_pi_harness.py:1755`） |
| 3 | note（完了の根拠・引き継ぎ） | (a) `metadata`（任意）。(b) `evidence`（型・参照・再現性つき）・`completionSummary` | `note`（80 字でたたんで表示）。`done` の根拠は任意 | △ | **`done` にするときに note が無ければ警告**（`blocked` と同じ方式）。子の結果の由来は `note` に自動で入る（`linkTodo`）。(b) の語彙・モデル判定は**取らない**（C9 の 314 回の失敗が反例） | 試験: `done` で note 無し → 警告を返す／あり → 無警告。faux モデルで、ゲートが**再試行のループを起こさない**（警告のみで拒否しない）こと |
| 4 | 依存（blocks/blockedBy） | (a) 双方向・警告のみ（自己・欠落・2 者循環）・**3 者以上は未検出**・**削除不可**（#28）・遷移は拒否しない。(b) `dependencies: string[]` を保存するだけ | **無い** | ○ | `after`（依存先の ID の配列）を `add` / `update` / `batch` に足す。**適用の内側で循環を DFS で検出して拒否**（警告でなく）。拒否は原子的（状態を変えない）。**削除（`unafter`）もできる**。未完了の依存がある項目の `in_progress` は警告（拒否しない）。`/todos` に「着手できる」表示 | 性質試験: ランダムな add / remove の 1 万手で**常に非循環**・**拒否時に状態が不変**・3 者循環の拒否・自己依存の拒否・削除で解ける。(a) の `TaskUpdate` が 3 者循環を保存することを（コードの読みだけでなく）**同じ入力で比較**できると強い |
| 5 | 依存の自動 unblock・表示 | (a) 自動の書き換えは無く、表示時に未完了のブロッカーを数える。`TaskExecute` だけが拒否 | 無し | ○ | 状態は書き換えず、**導出**（未完了の依存が全て `done`/`cancelled` なら「着手可」）。`list` の本文に `[待ち: #3]` を付ける。`cancelled` の依存は「解決」と見なす（(a) は `completed` だけ） | 試験: 依存先を `cancelled` にしても詰まらない。`list` の出力の試験 |
| 6 | 複数セッションでの共有 | (a) 既定は**共有しない**。`PI_TASKS`・`project` のときだけ、ファイル＋O_EXCL のロック＋tmp→rename（C3。欠陥 L1〜L8）。(b) 共有しない | **無い**（セッションごと） | △（価値は限定的。G で検討） | **ロックを使わない設計**: 各セッションが**自分のファイルだけを書き**（単独の書き手）、他セッションの状態は**読み取り専用**で集約表示（`/todos all`）。書き手が 1 つなので競合が原理的に無い。書き込みは tmp→fsync→rename | 障害の注入: ①書き込みの途中で SIGKILL → 旧か新の完全な内容のどちらか（部分が見えない）②8 プロセスが同時に更新しても、**各自のファイルは常に有効**③他セッションの破損ファイルを読んでも**表示側が落ちず**、破損の旨だけ出す。(a) の L1（回収競合）は**構造的に起きない**ことを、設計で示す |
| 7 | 保存先と分岐への追従 | (a) 会話の外のファイル。`session_tree`・圧縮のフックを使わず、**`/tree` で戻っても巻き戻らない**。fork は複製。(b) セッション JSONL へイベント追記・`session_tree` で再生 | **セッション JSONL**（ツール結果の `details`＋利用者の操作の custom エントリ）から枝ごとに再構築（`index.ts:165-180`、`session_start`・`session_tree` 185） | ◎ 既に**上回る**（(a) に対して）。(b) と同等 | 弱点: **`todo` を呼ぶたびに、リスト全体を `details` として JSONL へ書く**（項目が多いほど増える）。差分の記録か、一定件数ごとの全量にする案 | 既存: `test_todo_state_survives_resume_and_reads_the_old_format`・`..._survives_compaction`。**追加**: `/tree` で過去へ戻ると状態も戻ること（枝の試験。現状、`session_tree` の faux 試験は見当たらない）。N 件のリストで JSONL の増分を実測 |
| 8 | 破損・手編集への耐性 | (a) 不正な型は `normalizeTask` で補う。**JSON 破損は黙って空で上書き**（L4） | JSONL の各エントリを `normalize`（旧形式を読む。`index.ts:56-65`）。会話の枝が正で、**別の保存ファイルが無いので、ファイルの破損という故障モードが無い** | ◎ | 共有ファイル（#6）を入れるなら、**破損は退避（`.corrupt-<時刻>`）して警告**し、上書きしない | 障害の注入: 切り詰めた JSON を読ませて、①退避ファイルができる②警告が出る③元の内容が失われない |
| 9 | リマインダー | (a) 4 ターン（`in_progress` あり 2）ごとに `context` フックで `user` メッセージを注入（キャッシュを外す疑い・PR #72）。(b) 無し（`task_next`・`task_resume` を呼ばせる） | `agent_before_settle` で、**応答を終えようとしたときだけ**、利用者の発言ごとに最大 1 回（in_progress が残る／待ちがあり着手できる未着手がある）（`index.ts:216-245`）。**会話に残る**（`custom_message`） | △ | 現状は**長い実行の途中のドリフトを検知できない**（(a) の強み）。案: 設定したターン数（例 30）ツール呼び出しが続いて `todo` が触れられていなければ、`turn_end` で**1 回だけ**フォロー（`sendMessage` の `followUp`）。**`context` フックでの注入は、キャッシュを外すので避ける**（#72） | 実測: ①(a) 方式（`context`）と自作方式で、プロバイダのキャッシュヒット率が変わるか（faux では測れない。実モデル 1 本で）②faux モデルで、ターンの閾値を超えたときだけ 1 回出ること・利用者の発言ごとにリセットされること |
| 10 | 子エージェントとの紐づけ | (a) `TaskExecute` が子を起動し、**子の完了＝`completed`**。失敗は `pending`＋`lastError`。auto-cascade で後続を自動起動。(b) 無し | `guarded_task` の `todo` 引数: 子が正常終了しても **`done` にせず `blocked`（親の確認待ち）**、失敗は note のみ。既に done/cancelled の項目は触らない（`harness/index.ts:1476-1490`）。必須の役割（`TODO_REQUIRED_AGENTS`） | ◎ 既に**上回る**（意味の点） | (a) の弱点 D-2・C6 を回避済み。さらに、**子の結果の要点（変更ファイル・検査の結果）を note に添える**。auto-cascade は**取り入れない**（権限と承認の境界を動かす。依存（#4）の「着手可」表示までにする） | 既存: `test_child_result_updates_the_assigned_todo`・`..._does_not_touch_an_already_done_todo`。**追加**: 子が失敗・中断したとき note だけが付く／done の項目は不変、を faux で |
| 11 | 完了の検証（証拠） | (b) `task_complete` が証拠・基準・ブロッカーを検査（モデル判定）。(a) 無し | 無し（#3 の note の警告のみ予定） | △ | **決定的な検査だけ**: 子の結果と紐づく項目は、`done` にするとき、親が「確認した」note を要求（警告）。LLM 判定は費用・遅延・失敗の連鎖（C9）があり**取らない** | 試験: 警告の有無。**反例の確認**: (b) の issue #14 の入力（「implement」「fix」を含む普通の計画）が、自作では**拒否されない**こと |
| 12 | 常駐の表示 | (a) 常駐ウィジェット（スピナー・経過・トークン・最大 10 件・並び替え・折りたたみ・記号の設定）。150 ms のタイマー | フッターの 1 行（`📌 done/total ▶ 現在の項目`）と、`/todos` の overlay（スクロール・折り返し・全角幅対応。`view.ts`） | ○（低） | 狭い端末（スマホ）を考えて、**行数を増やさない**方針を維持。必要なら、`in_progress` と `blocked` だけの 3 行の `setWidget`（タイマー無し・変更時のみ再描画）。(a) は 150 ms のポーリングでファイルを読む（C8）が、自作は記憶なので I/O が 0 | 実測: 1,000 件のリストで、描画 1 回の時間とファイル I/O の回数（自作は 0）。画面幅 40 列での折り返し（`test_pi_todo_view.py` と `test_todo_footer_truncates_a_long_title_by_display_width` に既存の幅の試験） |
| 13 | `/tasks`・`/todos` の操作 | (a) `ui.select` の入れ子のメニュー（開始・完了・削除・作成・設定）。依存・note は編集できない | `/todos`（overlay 表示）・`/todos tidy`・`/todos clear`。**項目の編集の画面は無い**（モデル経由） | ○（低） | 利用者が `blocked`・`cancelled` を押せる最小の操作（overlay 内のキー）。**優先度は低い**（利用者は普段モデルに頼む） | 試験: キー入力 → 状態の遷移の純関数（`step` と同じ形） |
| 14 | 圧縮・再開 | (a) 状態は会話の外。リマインダーで復帰。(b) `task.snapshot` を圧縮の直前に追記・`task_resume` | 状態は JSONL から再構築（圧縮後も残る）。**モデルが圧縮後にリストの存在を思い出す仕掛けは、`todo` 側には無い**（`NEXT.md` と圧縮指示が別にある。未確認） | △ | 圧縮の直後の最初のターンで、**未完了の先頭数件を 1 回だけ**注入（`session_compact` の後）。`NEXT.md` との重複は避ける（引き継ぎは 1 か所） | 試験: faux モデルで圧縮を起こし、直後のターンの入力に未完了の件が入ること／2 回目は入らないこと。実モデルで「圧縮後にモデルが `list` を呼ぶか」（未確認） |
| 15 | バックグラウンドのプロセス追跡 | (a) 配線されておらず**動かない**（C5） | `bg_run`・`bg_kill`（別の機構。`blocked` の note に待ち先のジョブ ID を書く） | × 不要 | – | – |
| 16 | subagent の自動連鎖（auto-cascade） | (a) 既定で無効。有効なら、完了通知で後続を自動起動 | 無し。親が確認してから次を起動 | × 不要（意図して持たない） | 承認・権限の境界（親が実差分を確認してから進める）を保つ。`after` の「着手可」表示で代える | – |
| 17 | 一覧の導出・並び | (a) `TaskList`: pending→in_progress→completed の ID 順。ウィジェットは `sortOrder` を設定可能 | `list`: 未完了だけ（完了・中止は件数にたたむ）。`/todos`: 状態の区分けで表示（進行中・待ち・未着手・完了・中止） | ◎ | 完了を件数にたたむ点は、**文脈を占めない**点で (a) より良い（(a) の `TaskList` は全件） | 実測: 100 件（完了 90）で、`list` の戻り値のバイト数を (a) の `TaskList` の形式と比較 |
| 18 | 設定の持ち方 | (a) JSON 2 層（全体・プロジェクト）。`/tasks` の設定画面。10 項目 | 環境変数 `PI_TODO_NO_REMINDER` だけ。設定ファイルは無い | ×（不要） | 設定を増やさない（個人の運用で、既定が決まっている） | – |
| 19 | 説明文（プロンプト） | (a) Claude Code の Task 系の説明文を、ほぼそのまま（`a:index.ts:676-1170` の各ツールの `description`）。モデルが学習した語彙 | 日本語の説明＋ `promptGuidelines`（`index.ts:249`）。1 つのツール `todo`＋`action` | △ | モデルが `TaskCreate` / `TaskUpdate` の**語彙に慣れている**利点は (a) にある。自作は `action` の列挙で、**1 回の呼び出しで複数を変えられる**点は上（`batch`）。**実モデルで、誤用率（不正な action・ID の取り違え）を比べる**まで、どちらが良いかは**未確認** | 実測（実モデル 2〜3 本）: 同じ 20 の作業指示で、①ツール呼び出しの失敗率②1 作業あたりの呼び出し回数③`in_progress` の同時 1 件の遵守率。**faux では測れない**（モデルの挙動の問い）。費用は小さい。**要・利用者の判断（実測の費用）** |
| 20 | 状態の巻き戻し・複製（fork） | (a) fork で複製（`snapshot`/`seed`）。`/tree` は非対応 | 枝ごとに状態が決まる（fork は自動） | ◎ | – | #7 の枝の試験 |

## G 上回るための方針

### G1 公開実装の実際の弱点 → 自作での解消

| 公開実装の弱点（根拠） | 自作での解消 |
| --- | --- |
| 共有ファイルの回収競合・永久ロック・破損の上書き（C3 の L1・L2・L4） | **共有ファイルのロックを作らない**。単独の書き手のファイル＋読み取り専用の集約（F の #6）。破損は退避 |
| 循環が 2 者だけ・削除不可（C2・issue #28） | 適用の内側で DFS・拒否・`unafter`（F の #4） |
| 子の終了＝完了（C6・D-2） | 既に `blocked`（親の確認待ち）にする。維持する |
| `/tree`・圧縮のフックを使わない（B1） | 既に枝ごとに再構築。**枝の試験を足す**（F の #7） |
| リマインダーがキャッシュを外す疑い・委譲と矛盾（C4・issue #40・PR #72） | 応答を終えるときの 1 回だけ（既存）。途中のドリフトは**キャッシュを外さない**形で足す（F の #9） |
| バックグラウンド追跡が死んだコード（C5） | 持たない（`bg_run` がある） |
| (b): 語彙の完了ゲートの誤判定（issue #14）・再生の 2 乗（issue #12） | 決定的な警告だけにする。再構築は枝の一回の走査（線形）。**N 万件の実測**を足す |

### G2 自作でしか得られない強み

- **フルガードと整合した、セッションをまたぐ状態**: 状態を**会話の JSONL に持つ**ので、書き込み先が増えず（`.pi/tasks/` や `~/.pi/tasks/` を要らない）、sandbox の許可を広げずに済む。ワーカーがタスクのファイルを書き換えて親へ注入する経路（E の 2）が**原理的に無い**
- **子エージェントの結果と紐づく完了条件**: `guarded_task` の `todo` 引数が、子の終了を `blocked`（親の確認待ち）にする（`harness/index.ts:1480-1490`）。(a) の「子の終了＝完了」より厳しい
- **`NEXT.md` などの引き継ぎとの一体化**: `blocked` の note に待ち先（ジョブ ID）を書く運用と、`agent_before_settle` の「待ちを理由に止まらない」注意（`index.ts:216-245`）が、`AGENTS.md` の「止まってよいのは…」と同じ方針で動く。公開実装には無い。**今後**: `/todos` と `NEXT.md` の「次にやること」を二重に持たないために、**どちらを正にするか**を決める（未決。G3 の「後回し」）
- **faux モデルでの再現可能な試験**: `test_pi_harness.py` に 25 本の `todo` の試験（原子性・再開・圧縮・リマインダーの 1 回・フッターの全角幅）。(a) は vitest の模擬 `pi` で試験するが、**実際の pi プロセスを起こした統合の試験はこの調査では見つからなかった**（`test/helpers/mock-pi.ts` の模擬のみ）。(b) は CI 無し
- **日本語・全角幅**（`view.ts` の `cellWidth`・`foldNote`）。(a) の文言と記号は英語固定（設定できるのは記号のみ）
- **規模が小さい**（640 行）。(a) の約 1/5・(b) の約 1/10。監査・変更の費用が小さい

### G3 上回れない・価値が薄い点（正直に）

- **複数セッションでの書き込みの共有は、価値が薄い**。理由（**事実**）: (a) 自身が、既定ではセッションごとに別ファイル（`taskScope: "session"`）で、共有は `PI_TASKS` か `project` を選んだときだけ（B3）。(**このリポジトリの事情**) 取り込みの窓口を 1 つにする運用で、各会話は自分の worktree（feature）を持ち、リストを共同で編集する場面が見当たらない（`AGENTS.md`）。(**残る価値**) 窓口の会話が、**他の会話の進み具合を見る**こと。これは**読み取り専用**で足り、ロックは要らない。→ 「共有の書き込み」は**作らない**。「他会話の読み取り専用の一覧」は**後回し（需要が出たら）**
- **Claude Code 互換のツール名・説明文は、(a) の方が良い可能性**（F の #19）。モデルが学習済みの語彙に乗る利点で、自作の `todo`（`action` の列挙）が劣るかは**実モデルで測らないと分からない**（未確認）
- **常駐ウィジェットの見た目は (a) が上**（F の #12）。ただし、費用（150 ms のポーリング）と画面の行数を考えると、**同等にする価値は低い**
- **長い実行の途中のドリフトの検知は (a) が上**（F の #9）。自作は応答の終わりだけ
- **subagent の統合の深さ（遅延返信の回収・再接続）は (a) が上**。ただし、自作は子が別プロセスで、親が完了を直接受け取る（`guarded_task`）ので、**同じ問題の多く（RPC の期限切れ・二重起動）が構造的に起きにくい**（推測。比較の実測なし）
- **(b) の「順序つきの手順」と「受け入れ基準」は、自作に無い**。ただし、運用（案件・docs・`feature-orchestration`）が同じ役を担っている。**足す必要は薄い**

### G4 最小で上回るセット（MVP）と後回し

#### MVP（小さい順に）

1. **`after`（依存）＋循環の拒否＋`unafter`**（F の #4・#5）。原子的・DFS。〜80 行＋試験
2. **`done` で note 無しの警告**（F の #3）。数行＋試験
3. **`/tree` で戻ったときの状態の試験・JSONL の増分の実測**（F の #7）。試験だけ
4. **(a) との同一入力の比較の試験**（3 者循環・ブロッカー無視）。(a) のコードは**実行せず**、仕様の差を表にするだけにするか、利用者が許せば隔離環境で実行する（**判断が要る**）

#### 後回し

- 途中のドリフトの検知（F の #9。キャッシュへの影響の実測が先）
- 圧縮直後の復帰の注入（F の #14。`NEXT.md` との役割分担が先）
- 他会話の読み取り専用の一覧（F の #6。需要が出てから）
- 実モデルでの語彙の比較（F の #19。費用の判断が要る）
- 3 行の `setWidget`（F の #12）

## H vendor 判断の材料

### H1 検査の対象（(a)）

| 項目 | 値 |
| --- | --- |
| 検査すべきコード量 | src 約 3,060 行（うち `index.ts` が 1,417 行）。subagent の統合（RPC・再接続・auto-cascade）が `index.ts` の約 270 行（148〜420 行付近。約 2 割）。**フルガードの方針では使わない部分**が大きい |
| 依存 | 実行時 0（peer のみ）。開発時 7 |
| install スクリプト | **無い**（`package.json` に `postinstall` 等が無い） |
| ネットワーク | src に **0 か所** |
| exec | src に **0 か所**（`ProcessTracker` は外から子プロセスを渡される設計で、渡す側が無い） |
| fs | 約 **17 か所**（読み・書き・rename・unlink・mkdir・rmdir） |
| pi のイベント・API | `on`: 9 種、`events.on/emit`: 約 7 種のチャネル、`registerTool` 7、`registerCommand` 1、`setWidget`、`ui.select`・`ui.input` |
| 更新頻度 | 直近 90 日に 26 commit・リリース 4 回 |
| fork の追従費用 | `index.ts` が一枚岩で、不具合の修正と機能がここに集中する（0.9.1 の修正も `index.ts`・`task-store.ts`）。**パッチが `index.ts` の広い範囲に及ぶと、上流の更新のたびに衝突しうる**（推測） |
| ライセンス | MIT（表示を残せば適合）。`eleqtrizit/pi-tasks` はライセンス無しで不可 |
| pi の版 | peer `>=0.80.5`。(a) は pi の内部に依存する（`getAgentDir`・`agent_settled` など。pi を上げるたびに CI が通るかは (a) 側の対応待ち） |

### H2 「vendor＋検査＋パッチ」と「自作」の概算（**推測**。根拠つき）

| 項目 | vendor＋検査＋パッチ | 自作（今の todo に足す） |
| --- | --- | --- |
| 初回の検査 | 3,060 行の通読＋欠陥（L1〜L8）の確認。この調査で約 60% は読了（**約 2 時間**の実績） | 0（既に監査済みの 640 行） |
| 初回の改造 | ①subagent の統合を外す（約 270 行）②ロックの修正（L1・L2・L4。〜100 行）③死んだコード（追跡）の除去④英語の文言を日本語へ⑤`guarded_task` の `todo` 引数との結線⑥ツール名・許可・フルガードとの整合⑦`/tree` の追従（B1）⑧リマインダーをキャッシュを外さない形へ（#72）。**ほぼ全ての層に及び、実質は fork** | MVP の 1〜3: 約 100〜150 行＋試験（`test_pi_harness.py` に 6〜8 本）。**半日〜1 日**（推測） |
| 継続の費用 | 上流の更新（4 リリース／90 日）ごとに、差分の再検査（1 回あたり 100〜400 行を読む。推測）＋衝突の解消。上流の修正は、**自分が直した箇所と同じ場所**に入りやすい | 自分の変更だけ。pi の API の変更への追従は、どちらも必要 |
| 得られるもの | 7 ツールの説明文・ウィジェット・設定画面・subagent の連携（使わない）・(a) の試験資産 | 依存・循環・警告。既存の強み（枝・子の紐づけ）を保つ |
| 失うもの | 状態の置き場（JSONL → ファイル）の変更で、**枝・圧縮・fork への追従を作り直す** | – |
| リスク | 共有ファイルの欠陥（L1・L2・L4）を**自分で直す責任**を負う。注入経路（E の 2） | 依存の拡張による複雑さ（小さい） |

### H3 結論

- **自作が上回れる条件**: ①状態を会話の JSONL に置いたままにする（枝・圧縮・fork の追従と、書き込み先を増やさないため）②依存（`after`）と循環の拒否を足す③共有ファイルを作らない（作るなら、単独の書き手の方式）④`done` の note の警告を足す⑤子の結果を完了と見なさない設計を保つ。**この 5 つで、(a) の主要な機能のうち使うものは同等以上になり、(a) の欠陥（L1〜L8・D-1〜D-5）は構造的に持たない**
- **vendor した方が良い領域**: **コードとしては無い**。理由: (a) の価値の中心（共有ファイル・subagent の統合・ウィジェット）は、**フルガードの方針（E）と衝突する**か、**需要が薄い**（G3）。**借りるなら「設計と説明文」**（MIT。出典を明記し、コードは写さない）: ①Claude Code 互換の説明文の語彙（F の #19。実測のあとで）②リマインダーの間隔の純関数の考え方（`reminder-cadence.ts`、90 行）③`normalizeTask` のような読み込み時の補正
- **(b) は取り込まない**: 状態を会話に置く点は自作と同じ設計で、**新しく得るものは完了ゲートだけ**。それは決定的な警告の範囲に絞って、自作に足せる（F の #3・#11）。モデル判定のゲートは、**費用・遅延・失敗の連鎖**（issue #14）が実績で出ており、取らない

## I 未確認・限界

- **対象コードを一度も実行していない**。L1〜L8・D-1〜D-5 は、**コードを読んだ結果**であり、再現はしていない。特に **L1 の競合は、解釈（`readFileSync` → `isProcessRunning` → `unlinkSync` の間に別のプロセスが割り込めること）に基づく**。再現するなら、2 つのプロセスと待機の挿入（`renameHook` と同様の継ぎ目）が要る。実行を許すなら、**隔離した一時ディレクトリで**、`TaskStore` に対して試験する（依頼で許可が要る）
- (b) の `tools.ts`・`reducer.ts` は、**ツールの一覧・状態の型・完了のゲートの条件・イベントの構造**だけ読み、全行は読んでいない。「`dependencies` は保存するだけ」は、`reducer.ts` を `dependenc` で grep した結果（他の使用が見つからなかった）で、読み落としがありうる
- (b) の `render.ts`・`semantic-capability.ts` は未読。行数は推定
- (a) の closed の issue は 24 件中、本文を読んだのは #20・#29（コメント）・#46・#48・#70・#71 の一部。ほかは題名と日付だけ。**「30 件程度の主題別の整理」は (a) 24 件＋(b) 9 件の題名ベース**
- (a) の PR の本文は #15・#72 だけ読んだ。open の PR #42・#64・#74・#76 は題名のみ
- 他の `pi-tasks` 系（harms-haus・eleqtrizit・Soleone・edxeth）は**ソース未読**（`gh repo view` の値のみ）
- ウィジェットのタイマーの起動条件、設定画面（`settings-menu.ts`）、`task-sort.ts`・`task-glyphs.ts` の中身は未読（行数のみ）
- フルガード下での (a)(b) の挙動（ツールの許可・書き込み先・イベントの扱い）は**実機で確かめていない**（E は読みと推測）
- キャッシュの外れ（PR #72）は、**その PR の説明を読んだだけ**で、pi のソースでは確かめていない
- 費用の概算（H2）は**推測**で、実績の工数ではない
- 自作の `todo` の `session_tree` の試験が無い点は、`git ls-files` と `grep` で確認した範囲（`test_pi_harness.py` に該当の名前が見当たらない）。別の名前で試験されている可能性は残る

## 出典

取得日はすべて 2026-11-05。原文は作業ツリーの `.tmp/research/pi-tasks/sources/`（git 管理外）に保存した。

- (a) リポジトリ: <https://github.com/tintinweb/pi-tasks>（master `c820715be1bf05db36d0739e88061b97b8c2c9d3`、v0.9.1）
  - `src/index.ts`・`src/task-store.ts`・`src/types.ts`・`src/task-paths.ts`・`src/tasks-config.ts`・`src/process-tracker.ts`・`src/reminder-cadence.ts`・`src/auto-clear.ts`・`src/ui/task-widget.ts`・
    `src/ui/settings-menu.ts`・`src/task-glyphs.ts`・`src/task-sort.ts`・`README.md`・`SECURITY.md`・`CHANGELOG.md`・`package.json`・`.github/workflows/ci.yml`・
    `test/task-store-concurrency.test.ts`・`test/store-scope.test.ts`（raw: `https://raw.githubusercontent.com/tintinweb/pi-tasks/master/<パス>`）
  - issue: <https://github.com/tintinweb/pi-tasks/issues/40>・`/28`・`/73`・`/71`・`/70`・`/48`・`/20`、PR <https://github.com/tintinweb/pi-tasks/pull/15>。一覧は `gh issue list`・`gh pr list`（2026-11-05）
  - npm の月間 DL: <https://api.npmjs.org/downloads/point/last-month/@tintinweb/pi-tasks>（4,220、2026-10-05〜11-03）
- (b) リポジトリ: <https://github.com/nczz/pi-tasks>（main `464b3f97a974e88ea5214eef094a57a2a76ab1f7`）、npm <https://www.npmjs.com/package/pi-tasks> 0.3.1
  - `src/store.ts`・`src/model.ts`・`index.ts`・`src/reducer.ts`・`src/tools.ts`・`src/semantic-assessment.ts`・`README.md`・`package.json`、npm の中身 <https://unpkg.com/pi-tasks@0.3.1/?meta>・
    レジストリ <https://registry.npmjs.org/pi-tasks>。issue #12・#14（`gh issue view`）、一覧は `gh issue list`
  - npm の月間 DL: <https://api.npmjs.org/downloads/point/last-month/pi-tasks>（2,150）
- 他の `pi-tasks` 系: `gh repo view` で `harms-haus/pi-tasks`・`eleqtrizit/pi-tasks`・`Soleone/pi-tasks`・`edxeth/pi-tasks`（説明・★・最終 push・ライセンス）。検索: `websearch.py search "pi-tasks pi coding agent extension github …"`（2026-11-05）
- 自作側（読んだ範囲）: `home/dot_pi/agent/extensions/todo/index.ts`・`view.ts`、`home/dot_config/pi/harness/index.ts`（`linkTodo`・`todo` 引数）、`test/agents/test_pi_harness.py`（`todo` の試験）、
  [pi の公開拡張の調査](pi-public-extensions-survey.md)（`@tintinweb/pi-subagents` の no-go の判断）、[ADR-0016](../../adr/0016-pi-extensions-own-first.md)
