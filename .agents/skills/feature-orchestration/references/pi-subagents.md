# pi-subagents（stock の pi）で委譲する: 拡張ネイティブの運用（N）

> 凍結した自作基盤の運用（`guarded_task`・`bundle.py`・PR ビューア）の代わりに、stock の pi で、拡張 `pi-subagents`（nicobailon 版。`home/.chezmoitemplates/pi-stock-packages` で版固定）を使うときの手順。
> 方針は [ADR-0031](../../../../docs/adr/0031-evaluate-existing-extensions-first.md)（拡張の意図に沿って使う）。評価と根拠は [orchestration の評価](../../../../docs/research/agents/pi-stock-packages-evaluation-2026-11.md)。**まず N（拡張ネイティブ）で体感する。合わなければ F（feature worktree を親が作り `cwd` で渡す）へ切り替える**（下の「F に切り替えるとき」）。

## N の基本

- **複数の子を回すときは、`async: true` の workflow を、トップレベルで 1 回だけ呼ぶ。** 子は workflow の中で起動する（`runs.run`・`runs.all`）。同じ応答に、```` ```js workflow ```` のブロックを 1 つだけ書く。
- **書き込む子には `worktree: true` を付ける。** 子は、きれいな HEAD から使い捨ての worktree と枝（`pi-subagents/…`）を作り、終わると **patch と handoff の記録**を取って片付ける。親（あなたの feature の worktree）が、patch を確認して適用する。並列で書く子には必ず付ける（付けないと同じ作業ツリーを共有する）。読み取り専用の子（`scout`・`reviewer`）には要らない。
- **元の作業ツリーがきれいなこと**（未コミットの変更がないこと）が、`worktree: true` の前提。**先に commit する。**
- 子は全部背景で動く（`forceTopLevelAsync: true`。前景の子には permission-system と cc-safety-net が載らないため）。完了は通知で親が起きる。親は応答を終えて待つ（`bg_wait` は通常は要らない）。

## 書き方の例（2 つの実装を並列に）

契約（`.tmp/keep/plan/<話題>.md`）を先に作り、worker の task には、その**パス**と、担当ファイル・守る条件を書く。

```js workflow
const [api, ui] = await runs.all([
  { key: "api", agent: "worker", worktree: true,
    task: "契約 .tmp/keep/plan/<話題>.md の C1〜C3 を実装する。担当ファイル: src/api/**。担当外は変えない。コミットはしない。検査のコマンドを実行して、出力を結果に書く。判断が要るときは contact_supervisor で聞く。" },
  { key: "ui", agent: "worker", worktree: true,
    task: "契約 ... の C4〜C5 を実装する。担当ファイル: src/ui/**。..." }
]);
return { api: api.artifactPaths, ui: ui.artifactPaths };
```

- 子の結果は、**自己申告では合格にしない**。`outputSchema` に状態の欄を持たせて確認するか、親が patch を適用してから**検査を自分で実行する**。
- **`gate`・`acceptance.verify`（子の後にシェルで検査するコマンド）は使わない。** permission-system の bash の方針が、その検査には及ばない（`subagent_launch` の呼び出しに `commands` として出るだけ）。検査は、親が `bash` で実行する（方針の許可・確認が効く）。
- 読み取り専用の調査・レビューは、`scout`・`reviewer`・`oracle`（組み込み）に任せる。計画の下書きも読み取りだけにする。

## 運用の規則（凍結した運用から引き継ぐもの）

1. **検査は、feature ごとに親が 1 本ずつ。** 子には全件検査（`mise run verify:all`）を回させない。回す前に、`pi-background` の `bg_run` で背景に出す（12 分）。
2. **verify が通るまで review に進まない。** review の修正で、通った verify を無効にしたら、verify からやり直す（`pi-gauntlet` の考え方。package は入れない）。
3. **同時数の上限**: 設定の `maxActiveAsyncRunsPerSession`（既定の案は 4）。空きが出たら、親が通知を見て次を起動する。上限を超えたときの挙動（拒否かキューか）は実機で確認する。
4. **統合は利用者が行う。** 親は、commit・サマリーまで。
5. **子が使うツール名**（permission の許可）: `subagent`・`subagents_enable`・`bg_wait`・`subagent_supervisor`。`subagent_launch`（workflow の子の起動ごとの確認）は **ask のまま**にして、最初は内容（担当・`cwd`・`worktree`・`commands`）を見ながら使う。ダイアログの `s`（セッション中は許可）で、確認を省ける。

## 実機で確かめる 4 点（初回）

1. idle の親が、完了通知で実際に起きること。
2. 背景の子の bash が、permission-system と cc-safety-net に止められること（`/subagents-doctor`）。
3. 子の ask が、親の画面へ転送され、離席から戻ってから答えて続くこと（最大の不確実性。`pi-subagents` 0.87.0 のコードは `PI_SUBAGENT_PARENT_SESSION` を渡す。permission-system の docs は別の package にしか触れていない）。
4. `worktree: true` の子が作った patch を、親の feature worktree へ適用できること（patch の場所は、結果の `artifactPaths` の handoff の記録）。worktree の置き場の既定は、リポジトリの隣の `worktrees/<プロジェクト名>/`（リポジトリの中は拒否される）。

## F に切り替えるとき

N の体感で、patch の適用や lane の記録が重いと感じたら、F に切り替える: 親が `git flow feature start <名前> --worktree` で feature worktree を作り、`subagent({ agent: "worker", task, cwd: "<その worktree の絶対パス>", async: true })` を、feature ごとに呼ぶ。枝・commit・統合が、従来の git flow のまま使える（`worktree: true` は使わない）。同時数と検査の規則は同じ。

## Ralph ループ（毎回新しい子を起こす。新しい文脈が要るときだけ）

Ralph Wiggum ループ＝同じ依頼を、**新しい文脈で繰り返し**、進捗はファイル・git に残して、完了まで続ける自走の技法。**既定は `/goal`（`pi-goal`。同じセッションで続ける）。** 追加の package は入れない（評価: [Ralph 系の評価](../../../../docs/research/agents/pi-stock-packages-evaluation-2026-11.md#ralph-wiggum-ループ系の評価と決定2026-11-09)）。新しい文脈が要るときだけ、`pi-subagents` の workflow で書く。

- **使うとき**: 文脈の肥大が実際に作業の質を落としていると分かったとき。利用者の過去のセッションの集計では、長い文脈による質の低下の兆候は見つからなかった（[圧縮の方針](../../../../docs/research/agents/long-context-compaction-paper-2026-11.md)）ので、**今は `/goal` で足りる見込み**。
- **前提（未確認。最初に確かめる）**: 背景の子に permission-system と cc-safety-net が載ること（上の「実機で確かめる 4 点」の 2）。載らなければ、この方式は判定の迂回になる。確かめるまで、離席中には使わない。
- **permission**: workflow の子の起動は `subagent_launch` の確認が毎回出る（ask のまま。`s` でセッション中は許可できる）。
- **完了の判定は独立させる**: 子の自己申告（`STATUS: DONE`）だけで終えず、別の `reviewer` の子が「全項目が満たされ、検査が通る」を確かめて `PASS` を返したときだけ終える。**`gate`・`acceptance.verify` は使わない**（上の規則）。検査のコマンドは reviewer の子が、`bash`（permission の方針が効く）で実行する。
- **上限**: 反復数（`maxIterations`）・`timeoutMs`・`usageBudget`・`toolBudget` を必ず付ける。無進捗の検出は書いていない（`PROGRESS.md` の更新の有無を、reviewer に見させる）。

例（**検証は未実施**。`subagent({ workflow: true, async: true, args: { maxIterations: 8, verify: "..." }, options: {...} })` のスクリプト本体。進捗は `PLAN.md`・`PROGRESS.md`〔作業ツリーの外の `.tmp/` を推奨〕に子が書く）:

```js workflow
const max = args.maxIterations ?? 8;
let last = null;
for (let i = 1; i <= max; i += 1) {
  const work = await runs.run("work-" + i, {
    agent: "worker",
    task: [
      "PLAN.md の未完了の項目を 1 つ進める。進捗と次の一手は PROGRESS.md に追記する。",
      "コミットはしない。git の状態を変えない。",
      "最後の行に STATUS: CONTINUE か STATUS: DONE か STATUS: BLOCKED を書く。"
    ].join("\n")
  });
  if (/STATUS: DONE/.test(work.output)) {
    const check = await runs.run("verify-" + i, {
      agent: "reviewer",
      task: "PLAN.md の全項目が満たされ、検査コマンド（" + args.verify + "）が通るか確かめ、PASS か FAIL と理由を書く。"
    });
    if (/\bPASS\b/.test(check.output)) return { done: true, iterations: i };
    last = check.output;
  } else if (/STATUS: BLOCKED/.test(work.output)) {
    return { done: false, blocked: true, iterations: i, why: work.output.slice(-500) };
  }
}
return { done: false, iterations: max, lastCheck: last };
```

呼び出し側の `options` の例: `{ timeoutMs: 3600000, usageBudget: { tokens: { soft: 2000000, hard: 3000000 } }, toolBudget: { soft: 80, hard: 120 } }`。
