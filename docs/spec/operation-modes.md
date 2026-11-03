# 運用モード（pi 単独と PR ビューア併用）

pi の使い方は 2 通りある。**pi 単独**（pi と TUI だけで完結）と、**PR ビューア併用**（人の操作盤を足す）。
どちらでも同じ層 0・1 が動き、ビューアは任意で足すだけ。背景は [CHG-0062](../change/0062-pr-hub-simplify.md) の D5（アプリへ切り出し、pi を通常のコーディングエージェントへ戻す）。

入口は [pi / pis マニュアル](pi-manual.md)。機能の一覧は [オーケストレーション](orchestration.md)、ガードの総覧は [guard/index.md](guard/index.md)、ビューアの設計は [pr-viewer.md](pr-viewer.md)。

## 1. 3 層モデル

| 層 | 中身 | ビューア |
| --- | --- | --- |
| 層 0 | pi + ガード。通常のコーディングエージェント。単独で完結する | 不要 |
| 層 1 | pi の中のオーケストレーション。親が `guarded_task` で worker を並列に起動する。git-flow の worktree、`scripts/wt_owner.py`・`scripts/train.py`・`scripts/wt_clean.py` | 不要 |
| 層 2 | PR ビューア。人の操作盤（見る・コメント・統合ボタン・「pi に依頼」ジョブ・起票）。**任意** | 本体 |

## 2. 段階 × 運用モード

| 段階 | pi 単独 | ビューア併用 |
| --- | --- | --- |
| 起票 | 親が `git flow feature start <名前> --worktree --no-fetch` | 同左、または画面の「＋ 起票」（`--allow-create`） |
| 実装 | 親が worker を起動（起動前に `wt_owner.py claim`） | 同左。加えて画面の「pi に依頼」ジョブ（`--allow-jobs`）が `pis -p` で実装 |
| 検査 | 親が `mise run verify`・`verify:all` | 同左（ビューアは検査しない） |
| commit | 親が `git add -A` → `git_commit`（`dir` に worktree。feature の worktree では確認なし） | 同左 |
| レビュー | TUI の会話と差分の確認だけ | 画面でコメント → 送信（`refs/pi/review/<prKey>`）→ pi が受け取る |
| 統合 | 人が TUI の必須確認に答える。または `merge-cli`（§3） | 人が画面の「統合する」を 2 段確認で押す（`--allow-merge`） |
| 掃除 | `scripts/wt_clean.py <名前>`（枝は統合済みのものだけ） | 統合時の cleanup 指定。または `wt_clean.py` |
| 複数 feature のまとめ取り込み | `scripts/train.py`（統合用の枝 `feature/train-N`）→ 1 回統合 | 同左。train の枝を画面で統合 |

## 3. pi 単独の運用

手順:

1. `git flow feature start <名前> --worktree --no-fetch`（worktree は `.tmp/worktrees/<名前>/`）。
2. worker の起動前に `python3 scripts/wt_owner.py claim <worktree> --kind worker --id <id>`。
3. worker が実装する（担当外は触らない）。
4. 親が `git add -A` → `git_commit`。完了で `python3 scripts/wt_owner.py release <worktree>`。
5. 検査: 日常は `mise run verify`、コミット前に `mise run verify:all`。
6. 統合（下）。複数をまとめるなら先に `python3 scripts/train.py start <feature>...`（`continue`・`verify`・`status`・`summary`。衝突は止めて終了コード 3。詳細は [統合用の枝](orchestration.md#統合用の枝train)）。
7. 統合後に `python3 scripts/wt_clean.py <名前>`（`--dry-run` あり）。

### 統合

保護ブランチへの統合（`git merge`・`git flow feature finish` など）は、判定器（`home/dot_config/pi/harness/integration-gate.ts`）が**必須確認**にする（bypass でも省略不可。feature の linked worktree の中の、現在のブランチを動かす操作は日常として除く）。承認画面は TUI でその場で答える。外出先から承認する手段は、pi 単独には無い（保留・非同期承認は撤去済み。[履歴](guard/pi-pending.md)）。

TUI を使わず端末で統合するときは `apps/pr-viewer/merge-cli.ts`。ビューアのサーバなしで同じ統合器が動く。結果は JSON 1 行。終了コードは成功 0・拒否 2・想定外の例外 1。

| コマンド | 用途 |
| --- | --- |
| `node apps/pr-viewer/merge-cli.ts plan <repo> --source <枝> [--target <枝>]` | 統合の計画（副作用は object の書き込みだけ） |
| `node apps/pr-viewer/merge-cli.ts merge <repo> --source <枝> --message-file <F\|-> [--target <枝>] [--cleanup <none\|branch\|branch_and_worktree>] [--expect-source <OID>] [--expect-target <OID>]` | 統合の実行。メッセージはファイル（`-` は標準入力）だけで渡す |
| `node apps/pr-viewer/merge-cli.ts recover <repo>` | 異常終了の後の復旧（他の git が動いていないことを確かめてから） |

私用の補助 `pk merge` はこのリポジトリの外にある。正本はこの `merge-cli`。

### pi 単独の限界

- 非同期の承認・離れた場所からの確認ができない。
- コメントの履歴が残らない（会話の中だけ）。
- 差分を見る画面は無い（TUI と git）。

## 4. ビューア併用の運用

起動: `node apps/pr-viewer/server.ts --repo <repo>`（既定のポートは 8780）。常駐させる `pk pr-app` は私用の補助。起動と安全規則は [pr-viewer.md §6](pr-viewer.md#6-アプリ)。

| 旗 | 有効になるもの | 目安 |
| --- | --- | --- |
| （なし） | 閲覧・コメント・送信だけ | まず無旗で使う |
| `--allow-merge` | 画面の「統合する」 | 統合を画面で押したいとき。有効化の手順を先に読む |
| `--allow-create` | 画面の「＋ 起票」 | 画面から feature を作りたいとき |
| `--allow-jobs` | 「pi に依頼」ジョブ（Linux のみ） | 実機で `pis -p` を確かめた後 |
| `--state-dir <パス>` | ジョブの記録・退避の置き場 | 既定でよい。リポジトリの中には置けない |

**既定はすべて無効**。取り込みだけでは有効にならず、旗を付けた起動が要る。

レビューの流れ:

1. 画面でコメントし、「レビューを送る」。`refs/pi/review/<prKey>` に未受領のバッチとして積まれる（[配送](pr-viewer.md#5-配送)）。
2. 対話中の pi が、次の入力の前に受け取る（`home/dot_config/pi/harness/pr-review.ts` の `before_agent_start`）。
3. または「pi に依頼」のジョブ（`pis -p`）が受け取って実装する（[ジョブ](pr-viewer.md)）。

統合ボタンは 2 段確認で、衝突を事前に検査する。取り消し手順は [統合を取り消す](pr-viewer.md)（「統合を取り消す」の節）。起票は [起票](pr-viewer.md)（「起票」の節）、掃除は統合時の cleanup 指定か `wt_clean.py`。

安全の前提（待ち受け先・公開の禁止・Origin 検査）は [pr-viewer.md の統合の節](pr-viewer.md)を読む。ここには写さない。

## 5. モードの切り替えと共存

- **ビューアを外す**: 層 0・1 は動く。失うのは、画面・コメントの履歴・非同期のレビュー・ジョブ・画面の統合ボタン。統合は §3 に戻る。
- **併用で増えるもの**: `refs/pi/review/*`（レビューの記録）と、`--state-dir` のジョブの記録。
- **同じ worktree を複数の主体（worker・ジョブ・人）で触らない**。`wt_owner` の lock とジョブの起動前検査（`worktree_busy`）が止める。lock を忘れた経路は検出できない。[worktree の所有の表明](orchestration.md#worktree-の所有の表明)。
- **ビューアが落ちた**: 統合の途中なら、他の git が動いていないことを確かめてから `merge-cli.ts recover <repo>`。ジョブは `interrupted` になり、自動では再開しない（画面の「再送」）。

## 6. よくある疑問

**ビューアがないと AI は統合できないのか。**
できる。ただし統合は必須確認で、人が TUI で答える。AI が自分で承認する手段は無い。

**pi 単独で外出先から承認できるか。**
できない。保留・非同期承認は撤去済み。外出先の承認はビューア併用（`--allow-merge`）が前提。

**ジョブと対話の pi の違いは。**
対話の pi は人が TUI で操作し、次の入力でレビューを受け取る。ジョブは画面から起動する `pis -p` で、人が張り付かずにコメントを実装する。同じ worktree を同時に触らせない。

**どのモードを選ぶか。**
手元で完結するなら pi 単独。画面で差分を見たい・離れた場所から統合したいなら、無旗で使い始め、必要な旗だけ足す。

**ビューアを入れたら pi の動きは変わるか。**
層 0・1 は変わらない。対話の pi は、未受領のレビューがあれば次の入力で受け取るだけ。

**コメントはどこに残るか。**
`refs/pi/review/<prKey>`。pi 単独では残らない。
