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
| 検査 | 親が `mise run verify`・`verify:all` | worker 経路は同左。ジョブ経路は、アプリが変更の規則（ファイルの種類・モード・大きさ・`risk_paths` など）を検査する。pre-commit・`verify`・`verify:all` を通したことにはならない |
| commit | 親が `git add -A` → `git_commit`（`dir` に worktree。feature の worktree では確認なし） | worker 経路は同左。ジョブ経路は、規則を通った変更をアプリが commit する（[ジョブ](pr-viewer.md#ジョブ段-a4achg-0062-34)） |
| レビュー | TUI の会話と差分の確認だけ | 画面でコメント → 送信（`refs/pi/review/<prKey>`）→ 対話 pi またはジョブが受け取る（§4） |
| 統合 | 人が TUI の必須確認に答える。または `merge-cli`（§3） | 人が画面の「統合する」を 2 段確認で押す（`--allow-merge`） |
| 掃除 | `git flow feature finish` なら finish が枝と worktree を消す。ビューア/`merge-cli` で統合した場合は `scripts/wt_clean.py <名前>`（§3 の統合の節） | 統合時の cleanup 指定。または `wt_clean.py` |
| 複数 feature のまとめ取り込み | `scripts/train.py`（統合用の枝 `feature/train-N`）→ 1 回統合 | 同左。train の枝を画面で統合 |

## 3. pi 単独の運用

手順:

1. `git flow feature start <名前> --worktree --no-fetch`（worktree は `.tmp/worktrees/<名前>/`）。
2. worker の起動前に `python3 scripts/wt_owner.py claim <worktree> --kind worker --id <id>`。
3. worker が実装する（担当外は触らない）。完了し、worker が止まったことを確かめる。
4. 日常の検査: `mise run verify`。
5. `git add -A`（新規ファイルの秘密検出はステージ後でないと見ない）。
6. コミット前に `mise run verify:all` を 1 回。
7. `git_commit`（`dir` に worktree）。
8. 所有の解除: `python3 scripts/wt_owner.py release <worktree> --id <id>`。
9. 統合（下）。複数をまとめるなら先に `python3 scripts/train.py start <feature>...`（`continue`・`verify`・`status`・`summary`。衝突は止めて終了コード 3。詳細は [統合用の枝](orchestration.md#統合用の枝train)）。
10. 掃除: `git flow feature finish` を使った場合は不要（finish が消す。下の統合の節）。ビューア/`merge-cli` で統合した場合は `python3 scripts/wt_clean.py <名前>`（`--dry-run` あり）。

### 統合

保護ブランチへの統合（`git merge`・`git flow feature finish` など）は、判定器（`home/dot_config/pi/harness/integration-gate.ts`）が**必須確認**にする（bypass でも省略不可。feature の linked worktree の中の、現在のブランチを動かす操作は日常として除く）。承認画面は TUI でその場で答える。このリポジトリの運用規約では、統合は利用者が行うものとし、AI は実行しない（[AGENTS.md](../../AGENTS.md)）。外出先から承認する手段は、pi 単独には無い（保留・非同期承認は撤去済み。[履歴](guard/pi-pending.md)）。

TUI を使わず端末で統合するときは `apps/pr-viewer/merge-cli.ts`。ビューアのサーバなしで同じ統合器が動く。結果は JSON 1 行。終了コードは成功 0・拒否 2・想定外の例外 1。

**利用者が自分の端末で実行するもの。AI の直接呼び出し（`merge`・`recover`）は判定器が deny する**（`home/dot_config/pi/harness/judge/rules_guard.ts`。`plan` は拒否しない）。

- 対象は `feature/`・`bugfix/` の枝 → `develop`。Git 2.43 以上が要る。
- **実行中のジョブ・他の git 操作・エディタの自動保存・生成処理を止めてから**実行する（別プロセスの CLI はビューアのジョブを知らない。[ジョブの制限](pr-viewer.md#止められるもの止められないものジョブ正直に)）。
- `plan` で見た OID を `--expect-source`・`--expect-target` に渡すと、計画後に動いた枝を拒否できる。
- **画面の統合にあって CLI に無いもの**: リスクのあるパス（`risk_paths`）の警告と追加の確認、ジョブ実行中の検査、レビュー記録への統合結果の書き込み（PR の状態は git から決まるので、画面は「統合済み」と表示する）、2 段の確認。CLI は `merge` を実行した時点で統合するので、`plan` の変更ファイル一覧を自分で見てから実行する（統合器本体、つまり衝突の事前検査・排他・取り消し手順は同じ）。

```sh
node apps/pr-viewer/merge-cli.ts plan <repo> --source <枝>
```

```sh
node apps/pr-viewer/merge-cli.ts merge <repo> --source <枝> --message-file <F>
```

```sh
node apps/pr-viewer/merge-cli.ts recover <repo>
```

`plan` は計画だけ（副作用は object の書き込みだけ）。`recover` は異常終了の後の復旧で、他の git が動いていないことを確かめてから使う。`merge` の任意引数:

| 引数 | 意味 |
| --- | --- |
| `--message-file -` | メッセージを標準入力から渡す（メッセージはファイルか標準入力だけ） |
| `--target <枝>` | 統合先（既定は `develop`） |
| `--cleanup <値>` | `none`・`branch`・`branch_and_worktree` |
| `--expect-source <OID>` | 統合元の先頭が一致しなければ拒否 |
| `--expect-target <OID>` | 統合先の先頭が一致しなければ拒否 |

**統合方式の違い**: このリポジトリの `.gitflow` は feature の統合を `squash` にしているが、ビューアと `merge-cli` は **merge commit**（target と source が親）を作る。`scripts/wt_clean.py` の掃除は、**枝が残り、先頭が統合先の祖先であるときだけ**成立する（squash で内容を取り込んだだけだと満たさない）。モードで履歴の形が違う: `git flow feature finish` は squash（履歴は一直線）、画面と `merge-cli` は merge commit。

- ビューア/`merge-cli` で統合した場合 → `wt_clean.py`（または統合時の cleanup）。
- `git flow feature finish` を使った場合（公式の記述。**実機の挙動は未確認**。旗 `--force-worktree`（`-W`）と `--keep-worktree` の存在は、入っている版の `finish --help` で確認済み）: finish は枝を消す前に、その枝がチェックアウトされた worktree を解放する。`git flow feature start <名前> --worktree` で作った worktree（git-flow が作った印つき）は**削除**され、枝も消える（`wt_clean.py` は不要）。`git worktree add` で作った worktree（画面の「＋ 起票」で作ったものを含む）は**削除されず、HEAD を枝から外して（detach）残る**（中身はそのまま）。git-flow が作った worktree に未コミット・未追跡の変更があると、マージの前に中断する（worktree も枝も無傷）。強制は `--force-worktree`（`-W`）、残すのは `--keep-worktree`（CLI のみ。git config には無い）。無視ファイル（`__pycache__` など）が未追跡の変更として数えられるかは**未確認**（`git flow feature finish --help` と、使い捨てのリポジトリで確かめる）。出典: git-flow-next の [Issue #175](https://github.com/gittower/git-flow-next/issues/175)（2026-08-02 起票）と公式の [commands](https://git-flow.sh/docs/commands/)・[configuration](https://git-flow.sh/docs/configuration/)（取得 2026-11-05。全文は未読）。

私用の補助 `pk merge` はこのリポジトリの外にある。正本はこの `merge-cli`。

### pi 単独の限界

- 非同期の承認・離れた場所からの確認ができない。
- コメントを画面から入力する入口が無い（会話の中だけ）。
- 差分を見る画面は無い（TUI と git）。

## 4. ビューア併用の運用

起動: `node apps/pr-viewer/server.ts --repo <repo>`（既定のポートは 8780）。常駐・公開の道具は `scripts/pr_app.py` が正本（`pk pr-app` はその薄い別名）。起動と安全規則は [pr-viewer.md §6](pr-viewer.md#6-アプリ)。

| 旗 | 有効になるもの | 目安 |
| --- | --- | --- |
| （なし） | 閲覧・コメント・送信だけ | まず無旗で使う |
| `--allow-merge` | 画面の「統合する」 | 統合を画面で押したいとき。有効化の手順を先に読む |
| `--allow-create` | 画面の「＋ 起票」 | 画面から feature を作りたいとき |
| `--allow-jobs` | 「pi に依頼」ジョブ（Linux のみ） | 実機で `pis -p` を確かめた後 |

権限の旗（`--allow-merge`・`--allow-create`・`--allow-jobs`）は**既定で無効**。取り込みだけでは有効にならず、旗を付けた起動が要る。`--state-dir <パス>` は権限ではなく、ジョブの記録・退避の保存先の指定（絶対パス。省略時は `$XDG_STATE_HOME/pr-viewer`、未設定なら `~/.local/state/pr-viewer`。リポジトリの中には置けない）。

レビューの流れ:

送信時に**宛先の worktree を選ぶ**（選ぶ画面は `apps/pr-viewer/web/send.js`）。宛先で行き先が変わる。送ると `refs/pi/review/<prKey>` に未受領のバッチとして積まれる（[配送](pr-viewer.md#5-配送)）。

(1) 対話 pi 向け:

1. その pi の worktree（既定は主 worktree）を宛先にして送信する。
2. 次の利用者入力の前に、pi が受け取る（`home/dot_config/pi/harness/pr-review.ts` の `before_agent_start`）。

(2) ジョブ向け:

1. **feature の worktree を宛先**にして送信する。
2. 「変更を依頼…」→ 渡すコメントの確認 → 最終確認 → 「依頼する」。

ジョブは**未受領でコメントありのバッチだけ**を渡す（`review-api.ts`・`job-api.ts`）。先に対話 pi が受領したものは渡せない。ジョブの受領は、アプリが起動前に記録する（[ジョブ](pr-viewer.md#ジョブ段-a4achg-0062-34)）。

統合ボタンは 2 段確認で、衝突を事前に検査する。取り消し手順は [統合を取り消す](pr-viewer.md#統合を取り消す巻き戻し利用者が行う手順は試験-test_pr_viewer_merge_undopy-が実-git-で固定)。起票は [起票](pr-viewer.md#起票段-b1chg-0062-5)、掃除は統合時の cleanup 指定か `wt_clean.py`。

安全の前提（待ち受け先・公開の禁止・Origin 検査）は [pr-viewer.md の統合の節](pr-viewer.md)を読む。ここには写さない。

## 5. モードの切り替えと共存

- **ビューアを外す**: 層 0・1 は動く。失うのは、画面・新しいコメントを画面から入力する入口・ジョブ・画面の統合ボタン（既存の `refs/pi/review` の記録・未受領のレビューは残り、pi は読める）。統合は §3 に戻る。
- **併用で増えるもの**: `refs/pi/review/*`（レビューの記録）と、`--state-dir` のジョブの記録。
- **同じ worktree を複数の主体（worker・ジョブ・人）で触らない**。`wt_owner` の lock とジョブの起動前検査（`worktree_busy`）が止める。lock を忘れた経路は検出できない。[worktree の所有の表明](orchestration.md#worktree-の所有の表明)。
- **ビューアあり→なしへの移行は、静止点で行う**（途中で止めると残骸が出る）。次が片付いてから、サービスを止める・旗を外す。(1) 実行中のジョブがない（残っていたら取り消す。ジョブの記録は `--state-dir` に残るが、移行後は使わない）。(2) 統合が途中でない（`merge-cli plan` が `recover_needed` を返さない）。(3) 送信済みで pi が未受領のレビュー（宛先の worktree の pi が次の入力で受け取る。不要なら無視してよい）。(4) `python3 scripts/wt_owner.py status` に `owner=job` の lock が残っていない（残骸は `reap`）。`refs/pi/review/*` の記録は残り、pi はそのまま読める。逆（なし→あり）は、旗を付けて起動するだけ（PR の一覧と状態は git から導く）。
- **ビューアが落ちた**: 状態は git の ref にあるので、まずビューアを再起動する（多くはこれで戻る）。統合の途中だったなら、他の git が動いていないことを確かめてから `merge-cli.ts recover <repo>`。ジョブは `interrupted` になり、自動では再開しない（画面の「再送」）。ジョブが残した lock は `python3 scripts/wt_owner.py reap`（pid が死んでいるものだけ）。どうしても急ぐときだけ `merge-cli`（上の「画面の統合にあって CLI に無いもの」に注意）。

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
`refs/pi/review/<prKey>`。ビューアを止めても既存の記録は残り、pi は読める。新しいコメントの入力にはビューアが要る。
