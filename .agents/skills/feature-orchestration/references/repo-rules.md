# リポジトリの運用規則（旧 AGENTS.md の親向けの規則）

凍結（[ADR-0030](../../../../docs/adr/0030-freeze-agent-stack-return-to-stock-pi.md)）した自作基盤（フルガード・`guarded_task` など）が前提の運用規則。custom プロファイルの pi で feature を並列に実装するときに読む。工程は [SKILL.md](../SKILL.md)、並列度の運用は [parallel-ops.md](parallel-ops.md)。

## 開発の場所と統合

- **dotfiles のこのリポジトリは、サンドボックスの中（`pis` の既定）で開発しない。`pis --no-sandbox`（フルガードだけ）で行う**（[ADR-0025](../../../../docs/adr/0025-dotfiles-dev-without-os-sandbox.md)）。内側では隠した秘密の追跡ファイルが `/dev/null` に見えて `git status` が dirty になり、統合（`git merge`）が `stash failed` で失敗する。**「`pis`（サンドボックスあり）で dotfiles を開発できる」「内側で統合できる」と言わない・判断しない。** 内側の合図（`git status` が dirty に見える・読めないファイルがある）が出たら、作業を止めて、サンドボックスなしの起動へ切り替えるよう利用者に伝える。サンドボックスは、外部のコード・依存・Web アプリ・GPU を実行するほかのリポジトリで使う。
- **develop / main に直接コミットしない。** 実装は feature の worktree（`.tmp/worktrees/<名前>/`）で行う。feature の起票とクローズ（`git flow feature start` / `finish`）は機械では止めないので指示で守る。AI は、feature の worktree で起動した pi から `guarded_action` の `git_commit` を使う（[CHG-0050](../../../../docs/change/0050-slim-guarded-action.md)）。**feature の linked worktree（`feature/*`）の `git_commit` は確認なしで実行される**（自由区。[CHG-0053](../../../../docs/change/0053-worktree-integration-gate.md)）。それ以外のコミットは確認する。
- **`git flow feature finish`・`git merge` など、保護ブランチへの統合は、既定では利用者が PR ビューアの「統合する」を押す。利用者がチャットで統合を明示的に指示したときに限り、AI が統合コマンドを実行してよい**（必須確認の承認画面が出て、利用者が TUI で承認する。bypass でも省略できない。指示が無いときは実行しない。実行前に、本体が `develop` で clean・全件検査が合格・`git merge-tree` が衝突なしを確かめる。チャット経由は統合器・2 段確認・リスクパスの警告が無いので、ボタンを既定とする。[運用モード](../../../../docs/spec/operation-modes.md#統合)・[CHG-0053](../../../../docs/change/0053-worktree-integration-gate.md)）。
- 共有されやすいファイル（`common.toml.tmpl`・golden・docs の索引）は、同時に複数の worker に触らせない。衝突するなら、親が順に取り込む。

## 委譲と並列

- **並列にできる作業は子エージェントに任せる。** 調査・レビュー・独立したファイル範囲の実装を並列にする。
- **1 worktree = 1 feature = 1 worker。** 親が `git flow feature start <名前> --worktree --no-fetch` で起票し、worker に worktree の絶対パスと担当ファイルを渡す。担当外の worktree や本体を編集させない。
- worker はコミットしない。親が結果を根拠で確かめ、`git_commit`（`dir` に worktree）→ `guarded_pr_summary` で `mergeMessage` の下書きを出す → 利用者が PR ビューアの「統合する」を押す。worker は `finish`・`merge` を実行しない。
- 子の結果は、パスと行・コマンドの出力で確かめてから採用する（子は「通った」を実行できないことが多い）。
- 重い検査を同時に回さない。worker には対象の試験と `pre-commit --files` だけ回させ、全件（`mise run verify:all`）は親が 1 回だけ回す。並列度は `VERIFY_JOBS` で下げられる。

## 見込みの並列実装と配線

**対象は、利用者が確認した契約があるものだけ**（判断項目が未回答の設計や、AI が自分で書いた草案は、見込みでも実装しない）。

- 確認済みの契約を前提に、未完成の部品・別 feature の取り込み待ちを待たず、I/F を**契約書**（`.tmp/keep/<話題>/api-contract-*.md`。API の形・関数の署名・担当ファイルの分担。短く、ずれる前提で書く）で先に固定し、担当ごと（部品・画面・撤去・docs・試験）に別の worker で**同時に**実装する。配線は接続できる部品から行う。I/F を変えるときは契約書を先に更新し、動いている worker へ `steer` で知らせる（契約の外に及ぶときは先に利用者へ相談）。
- 部品が揃ったら、配線の枝へ各部品の枝・develop を `git merge` で取り込んで**接続し、実物どうしの試験を回して I/F を調整する**（調整は配線の側で直すのを基本にする）。見込みの実装を直す・捨てる費用は、待つ時間より安いとみなす。
- **見込みで進めないもの**: 承認が要る操作の実行（統合・push）・既定で有効になる権限の拡大・元に戻せない操作。新しい書き込み権限は既定で無効の旗で入れる。上流の設計が根本から変わったら、見込みの部分は捨てる。
- 並列の限界は、子の同時数（`guarded_task` は 6）と全件検査の排他。空きが出たらすぐ次の worker を起動し、全件検査は feature ごとに 1 回（日常は `mise run verify` の選択実行）にする。
- 親は読む量を絞る: 子の返答は先頭の結論と申し送りだけ読み、詳細・全文はファイルに任せて、親のコンテキストを節約する。

## 並列度を保つ

- 親は、子の完了・利用者の応答のたびに子の一覧（`guarded_task` の list）を見て、**空きをキュー（`.tmp/keep/queue/`）の先頭の依頼文で埋める**（契約が確定した依頼文だけ。決定待ちのものはキューに入れず blocked）。次の依頼文は空きを待つ間に先に書く。子の返答は結論と申し送りだけを読む。手順は [parallel-ops.md](parallel-ops.md)。
- **pi の会話（セッション）を複数並行して使うときは、取り込み（利用者の「統合する」の押下）の窓口を 1 つにする。** ほかの会話は feature のコミットまで。全件検査は排他ロックが自動で 1 本ずつにする。規則は [複数の会話を並行して使う運用](../../../../docs/spec/guard/pi-subagents.md#複数の会話を並行して使う運用)。

## 完璧より完了

守る境界（権限・秘密・元に戻せない操作）を満たせば、細部の磨き込みで保存を止めない。

1. 新しい権限・書き込みは既定で無効の旗で入れ、先に develop へ入れてから実機で確かめる（完璧な確認を待たない。違っていたら別で直す）。
2. 独立 review は**権限の境界を動かす変更だけ**を保存前に行い、それ以外は保存後でよい。
3. 指摘は BLOCKER（境界を破る）だけ保存前に直し、MAJOR 以下は追加の小さな変更に回す。
4. docs のみ・定数 1 つのような小さな変更は、関連の試験だけで保存する（全件検査を回さない）。
5. 磨き込み・未確認・「あとで直す」は todo に起こして続ける（保存の条件にしない）。

この原則は守る境界を緩めるものではない。

## 手順・雛形

- 手順・依頼文の雛形・踏みやすい落とし穴は [SKILL.md](../SKILL.md) と [並列実装の運用](../../../../docs/spec/guard/pi-subagents.md#並列実装の運用隔離なしの-worktree)。worker への依頼文は、共通の約束（[worker-common.md](worker-common.md)）をファイルで参照させて短くする。
