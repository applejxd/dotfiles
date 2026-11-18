# pi-subagents で委譲する: 既定は F（feature worktree を親が作る）。N（拡張ネイティブ）は代案

> 拡張 `pi-subagents`（nicobailon 版。`home/.chezmoitemplates/pi-stock-packages` で版固定）を使うときの手順。
> 方針は [ADR-0031](../../../../docs/adr/0031-evaluate-existing-extensions-first.md)（拡張の意図に沿って使う）。評価と根拠は [orchestration の評価](../../../../docs/research/agents/pi-stock-packages-evaluation-2026-11.md)。**既定は F（親が feature worktree を作り、`cwd` で渡す。下の「F（既定）」と [SKILL.md](../SKILL.md) の工程）。** 当初は「まず N で体感し、合わなければ F」としたが、実際の運用は F になった。N（拡張ネイティブの workflow と `worktree: true`）と Ralph ループは、見送った案として下に短く残す。

## 運用の規則

1. **検査は、feature ごとに親が 1 本ずつ。** 子には全件検査（`mise run verify:all`）を回させない。回す前に、`pi-background` の `bg_run` で背景に出す（12 分）。
2. **verify が通るまで review に進まない。** review の修正で、通った verify を無効にしたら、verify からやり直す（`pi-gauntlet` の考え方。package は入れない）。
3. **同時数の上限**: 設定の `maxActiveAsyncRunsPerSession`（既定の案は 4）。空きが出たら、親が通知を見て次を起動する。上限を超えたときの挙動（拒否かキューか）は実機で確認する。
4. **統合は利用者の明示的かつ自発的な指示があるときだけ。** 親は、commit・サマリー（「準備ができた」という報告）まで。許可を求める質問はしない。
5. **子が使うツール名**（permission の許可）: `subagent`・`subagents_enable`・`bg_wait`・`subagent_supervisor`・`subagent_launch`。`subagent_launch`（workflow の子の起動）は、2026-11-09 に当面の運用として **allow** にした（確認は出ない）。内容（担当・`cwd`・`worktree`・`commands`）を毎回見たいときは、方針の `subagent_launch` を `ask` へ戻す（`s` でセッション中は許可できる）。`gate`・`acceptance.verify` を使わない運用（上）なので、`commands` が検査されない点は実害が出にくい。

## F（既定）

親が `git flow feature start <名前> --worktree` で feature worktree を作り、`subagent({ agent: "worker", task, cwd: "<その worktree の絶対パス>", async: true, options: { timeoutMs, checkpointBeforeDeadlineMs } })` を、feature ごとに呼ぶ。枝・commit・統合が、従来の git flow のまま使える（`worktree: true` は使わない）。同時数と検査の規則は同じ。契約の雛形は [worker-contract.md](worker-contract.md)。

## 見送った案: N（拡張ネイティブの workflow と `worktree: true`）

`async: true` の workflow をトップレベルで 1 回呼び、書き込む子に `worktree: true`（使い捨ての worktree と枝を作り、patch と handoff の記録を残す）を付ける方式。採っていない理由: F（親が feature worktree を作る）で枝・commit・統合が従来の git flow のまま使え、実際の運用も F になった。次の 4 点を実機で確かめていない（未確認）: 完了通知で idle の親が起きること、背景の子の bash が permission-system と cc-safety-net に止められること、子の ask が親の画面へ転送されること、`worktree: true` の patch を親の worktree へ適用できること。再検討の条件: F では並列の書き手を分けられない作業が出て、上の 4 点を確かめられたとき。

## 見送った案: Ralph ループ（毎回新しい子を起こす）

同じ依頼を新しい文脈で繰り返し、進捗をファイル・git に残して完了まで続ける自走の技法（評価: [Ralph 系の評価](../../../../docs/research/agents/pi-stock-packages-evaluation-2026-11.md#ralph-wiggum-ループ系の評価と決定2026-11-09)）。採っていない理由: 既定の `/goal`（`pi-goal`。同じセッションで続ける）で足りる見込みで、利用者の過去のセッションの集計に、長い文脈による質の低下の兆候が見つからなかった（[圧縮の方針](../../../../docs/research/agents/long-context-compaction-paper-2026-11.md)）。この方式は未検証で、背景の子に permission-system と cc-safety-net が載ること（上の N の確認の 2 点目）が前提になる。再検討の条件: 文脈の肥大が作業の質を落としていると分かったとき。完了の判定は子の自己申告でなく、別の `reviewer` の子に任せ、`gate`・`acceptance.verify` は使わない。
