# pi-subagents で委譲する: 既定は F（親が feature worktree を作る）

拡張 `pi-subagents`（nicobailon 版。`home/.chezmoitemplates/pi-stock-packages` で版固定）を使うときの手順。方針は [ADR-0031](../../../../docs/adr/0031-evaluate-existing-extensions-first.md)（拡張の意図に沿って使う）。評価と根拠は [orchestration の評価](../../../../docs/research/agents/pi-stock-packages-evaluation-2026-11.md)。工程は [SKILL.md](../SKILL.md)、権限・子の事実は [pi-facts.md](pi-facts.md)。

## F（既定）

親が `git flow feature start <名前> --worktree` で feature worktree を作り、`subagent({ agent: "worker", task, cwd: "<その worktree の絶対パス>", async: true, options: { timeoutMs, checkpointBeforeDeadlineMs } })` を、feature ごとに呼ぶ。枝・commit・統合が、従来の git flow のまま使える（`worktree: true` は使わない）。契約の雛形は [worker-contract.md](worker-contract.md)。

## 運用の規則

1. **検査は feature ごとに親が 1 本ずつ**（子に全件検査を回させない。`bg_run` で背景に出す）。
2. **verify が通るまで review に進まない。** review の修正で通った verify を無効にしたら、verify からやり直す。
3. **同時数**: 設定の上限は外してある（`maxActiveAsyncRunsPerSession: 0`）。先に詰まるのは全件検査の CPU（推測）なので、親が通知を見て、検査が重ならないよう次を起動する。
4. **子が使うツール名**（permission の許可）: `subagent`・`subagents_enable`・`bg_wait`・`subagent_supervisor`・`subagent_launch`。`subagent_launch`（workflow の子の起動）は allow（確認は出ない。内容を毎回見たいときは、方針の `subagent_launch` を `ask` へ戻す）。`gate`・`acceptance.verify` は使わない運用なので、`commands` が検査されない点は実害が出にくい。

## 見送った案（再検討の条件つき）

- **N（拡張ネイティブの workflow と `worktree: true`）**: F で枝・commit・統合が従来の git flow のまま使えるので採らない。実機で未確認の点が 4 つある（完了通知で idle の親が起きること、背景の子の bash が止められること、子の ask が親の画面へ転送されること、patch を親の worktree へ適用できること）。再検討の条件: F では並列の書き手を分けられない作業が出て、この 4 点を確かめられたとき。
- **Ralph ループ（毎回新しい子を起こす）**: 既定の `/goal` で足りる見込みなので採らない（[評価](../../../../docs/research/agents/pi-stock-packages-evaluation-2026-11.md#ralph-wiggum-ループ系の評価と決定2026-11-09)）。再検討の条件: 文脈の肥大が作業の質を落としていると分かったとき。完了の判定は、子の自己申告でなく別の `reviewer` の子に任せる。
