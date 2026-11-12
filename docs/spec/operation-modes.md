# 運用モード（pi 単独と PR ビューア併用）

> **凍結した自作基盤の文書**（[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md)。保存のみ・開発しない）。ここに出てくるコマンド・ツール（`guarded_task`・`/bypass`・`/pending`・`/orchestrate` など）は、stock の pi には**存在しない**。いまの stock の pi のコマンドは [早見](pi-commands.md)。

pi の使い方は 2 通りある。**pi 単独**（pi と TUI だけで完結）と、**PR ビューア併用**（人の操作盤を足す）。
どちらでも同じ層 0・1 が動き、ビューアは任意で足すだけ。背景は [CHG-0062](../change/closed/0062-pr-hub-simplify.md) の D5（アプリへ切り出し、pi を通常のコーディングエージェントへ戻す）。

入口は [pi / pis マニュアル](pi-manual.md)。機能の一覧は [オーケストレーション](orchestration.md)、ガードの総覧は [guard/index.md](guard/index.md)、ビューアの設計は [pr-viewer.md](pr-viewer.md)。

## 1. 3 層モデル

| 層 | 中身 | ビューア |
| --- | --- | --- |
| 層 0 | pi + ガード。通常のコーディングエージェント。単独で完結する | 不要 |
| 層 1 | pi の中のオーケストレーション。親が `guarded_task` で worker を並列に起動する。git-flow の worktree、`scripts/wt_owner.py`・`scripts/bundle.py`・`scripts/wt_clean.py` | 不要 |
| 層 2 | PR ビューア。人の操作盤（見る・統合ボタン）。**任意** | 本体 |

## 2. 段階 × 運用モード

| 段階 | pi 単独 | ビューア併用 |
| --- | --- | --- |
| 起票 | 親が `git flow feature start <名前> --worktree --no-fetch` | 同左（画面の起票は撤去した） |
| 実装 | 親が worker を起動（起動前に `wt_owner.py claim`） | 同左。画面からの「pi に依頼」ジョブは撤去済み |
| 検査 | 親が `mise run verify`・`verify:all` | worker 経路のみ（ジョブ経路は撤去済み） |
| commit | 親が `git add -A` → `git_commit`（`dir` に worktree。feature の worktree では確認なし） | worker 経路は同左（ジョブ経路は撤去済み） |
| レビュー | TUI の会話と差分の確認だけ | 画面で差分と pi のサマリーを読む。指摘・依頼はチャットで伝える（画面からのコメント送信は撤去済み。[pr-viewer.md §5](pr-viewer.md#5-レビューコメント送信の撤去2026-11-05)） |
| 統合 | 人が TUI の必須確認に答える。または `merge-cli`（§3） | 人が画面の「統合する」を 2 段確認で押す（`--allow-merge`） |
| 掃除 | `git flow feature finish` なら finish が枝と worktree を消す。ビューア/`merge-cli` で統合した場合は `scripts/wt_clean.py <名前>`（§3 の統合の節） | 統合時の cleanup 指定。または `wt_clean.py` |
| 複数 feature のまとめ取り込み | `scripts/bundle.py`（統合用の枝 `feature/bundle-N`）→ 1 回統合 | 同左。bundle の枝を画面で統合（構成員の枝は、bundle に含まれている間は PR 一覧に並ばない。切り替えで表示） |

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
9. 統合待ちの一覧: `mise run prs`（`python3 scripts/prs.py`。枝名・先行コミット数・最新の件名だけ。bundle に含まれる枝は既定で隠し、`-- --all` で全部出す。詳細・統合・掃除はエージェントに指示する）。
10. 統合（下）。複数をまとめるなら先に `python3 scripts/bundle.py start <feature>...`（`continue`・`verify`・`status`・`summary`。衝突は止めて終了コード 3。詳細は [統合用の枝](orchestration.md#統合用の枝bundle)）。
11. 掃除: `git flow feature finish` を使った場合は不要（finish が消す。下の統合の節）。ビューア/`merge-cli` で統合した場合は `python3 scripts/wt_clean.py <名前>`（`--dry-run` あり）。

### 統合

保護ブランチへの統合（`git merge`・`git flow feature finish` など）は、判定器（`home/dot_config/pi/harness/integration-gate.ts`）が**必須確認**にする（bypass でも省略不可。feature の linked worktree の中の、現在のブランチを動かす操作は日常として除く）。承認画面は TUI でその場で答える。このリポジトリの運用規約では、統合は既定では利用者が行う（ビューアのボタン）。**利用者がチャットで統合を明示的に指示したときに限り**、AI が統合コマンドを実行してよい。
実行すると上の必須確認の画面が出て、利用者が TUI で承認する（指示が無いときは実行しない。[AGENTS.md](../../AGENTS.md)）。
チャット経由には、ビューアの統合器（衝突の事前検査・排他・取り消し手順）・2 段の確認・リスクのあるパスの警告が無い。実行の前に、本体が `develop` で clean・
全件検査が合格・`git merge-tree` が衝突なし、を AI が確かめる。チャット経由の標準の統合コマンドは、本体（`develop`）で次の 1 行（**コマンドの先頭を `git flow feature finish` にし、`cd` や `&&` を付けない**。確認画面は先頭だけを解釈する）。

```text
git flow feature finish <名前> --no-ff --no-squash -M "$(cat <メッセージファイル>)" --keepremote --no-fetch --no-push --notag
```

メッセージはサマリーの `mergeMessage` を `.tmp/keep/pr-merge/<名前>-message.txt` に書く。**2026-11-05 の bundle-4 で、確認画面を通して成功した**（merge commit を作り、メッセージは `-M` の内容。ボタンと同じ形。統合の枝 `feature/<名前>` は消え、その worktree は切り離されてディレクトリだけ残る）。`--squash` を付けない理由: この repo の `.gitflow` は feature の既定を squash にしているが、bundle を squash すると取り込み元の枝が `develop` の祖先にならず、掃除（`wt_clean.py`）と「統合済み」の判定が壊れる。
2026-11-05 の bundle-3 は、finish の確認画面が squash 前提だったため、代わりに `git merge --no-ff -F <メッセージファイル> feature/<名前>` で統合した（成功）。
統合後は `python3 scripts/wt_clean.py <名前>...`（取り込み元の枝もまとめて。統合した枝自身は、finish で枝が消えて detached のディレクトリだけ残るが、これも `wt_clean.py <名前>` で消せる（HEAD が統合済みで変更なしのときだけ））と、`apps/pr-viewer/**` を更新したときは `python3 scripts/pr_app.py restart`。外出先から承認する手段は、pi 単独には無い（保留・非同期承認は撤去済み。[履歴](guard/pi-pending.md)）。

TUI を使わず端末で統合するときは `apps/pr-viewer/merge-cli.ts`。ビューアのサーバなしで同じ統合器が動く。結果は JSON 1 行。終了コードは成功 0・拒否 2・想定外の例外 1。

**利用者が自分の端末で実行するもの。AI の直接呼び出し（`merge`・`recover`）は判定器が deny する**（`home/dot_config/pi/harness/judge/rules_guard.ts`。`plan` は拒否しない）。

- 対象は `feature/`・`bugfix/` の枝 → `develop`。Git 2.43 以上が要る。
- **他の git 操作・エディタの自動保存・生成処理を止めてから**実行する（別プロセスの CLI はビューアを知らない）。
- `plan` で見た OID を `--expect-source`・`--expect-target` に渡すと、計画後に動いた枝を拒否できる。
- **画面の統合にあって CLI に無いもの**: リスクのあるパス（`risk_paths`）の警告と追加の確認、レビュー記録への統合結果の書き込み（PR の状態は git から決まるので、画面は「統合済み」と表示する）、2 段の確認。CLI は `merge` を実行した時点で統合するので、`plan` の変更ファイル一覧を自分で見てから実行する（統合器本体、つまり衝突の事前検査・排他・取り消し手順は同じ）。

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

利用者の私用の補助 `pk merge` はこのリポジトリの外にあり、ここの手順には使わない。正本はこの `merge-cli`。

### pi 単独の限界

- 非同期の承認・離れた場所からの確認ができない。
- 差分を見る画面は無い（TUI と git）。

## 4. ビューア併用の運用

起動: `node apps/pr-viewer/server.ts --repo <repo>`（既定のポートは 8780）。常駐・公開の道具は `scripts/pr_app.py` が正本（`pk pr-app` はその薄い別名）。起動と安全規則は [pr-viewer.md §6](pr-viewer.md#6-アプリ)。

| 旗 | 有効になるもの | 目安 |
| --- | --- | --- |
| （なし） | 閲覧だけ | まず無旗で使う |
| `--allow-merge` | 画面の「統合する」 | 統合を画面で押したいとき。有効化の手順を先に読む |

権限の旗（`--allow-merge`）は**既定で無効**。取り込みだけでは有効にならず、旗を付けた起動が要る。`--state-dir <パス>` は権限ではなく、統合の退避の保存先の指定（絶対パス。省略時は `$XDG_STATE_HOME/pr-viewer`、未設定なら `~/.local/state/pr-viewer`。リポジトリの中には置けない）。

レビューの流れ: 画面は差分と pi のサマリーを読むだけで、コメントは送らない（撤去済み。[理由と範囲](pr-viewer.md#5-レビューコメント送信の撤去2026-11-05)）。指摘・依頼はチャットで pi に伝える。

統合ボタンは 2 段確認で、衝突を事前に検査する。取り消し手順は [統合を取り消す](pr-viewer.md#統合を取り消す巻き戻し利用者が行う手順は試験-test_pr_viewer_merge_undopy-が実-git-で固定)。起票は [起票](pr-viewer.md#起票段-b1chg-0062-5)、掃除は統合時の cleanup 指定か `wt_clean.py`。

安全の前提（待ち受け先・公開の禁止・Origin 検査）は [pr-viewer.md の統合の節](pr-viewer.md)を読む。ここには写さない。

## 5. モードの切り替えと共存

- **ビューアを外す**: 層 0・1 は動く。失うのは、画面・画面の統合ボタン（既存の `refs/pi/review` の記録は残り、pi は読める）。統合は §3 に戻る。
- **併用で増えるもの**: `refs/pi/review/*`（レビューの記録）と、統合の退避（`--state-dir`）。
- **同じ worktree を複数の主体（worker・人）で触らない**。`wt_owner` の lock が止める。lock を忘れた経路は検出できない。[worktree の所有の表明](orchestration.md#worktree-の所有の表明)。
- **ビューアあり→なしへの移行は、静止点で行う**（途中で止めると残骸が出る）。次が片付いてから、サービスを止める・旗を外す。(1) 統合が途中でない（`merge-cli plan` が `recover_needed` を返さない）。(2) `python3 scripts/wt_owner.py status` に lock が残っていない（残骸は `reap`）。`refs/pi/review/*` の記録は残り、pi はそのまま読める。逆（なし→あり）は、旗を付けて起動するだけ（PR の一覧と状態は git から導く）。
- **ビューアが落ちた**: 状態は git の ref にあるので、まずビューアを再起動する（多くはこれで戻る）。統合の途中だったなら、他の git が動いていないことを確かめてから `merge-cli.ts recover <repo>`。残した lock は `python3 scripts/wt_owner.py reap`（pid が死んでいるものだけ）。どうしても急ぐときだけ `merge-cli`（上の「画面の統合にあって CLI に無いもの」に注意）。

## 6. よくある疑問

**ビューアがないと AI は統合できないのか。**
できる。ただし統合は必須確認で、人が TUI で答える。AI が自分で承認する手段は無い。

**pi 単独で外出先から承認できるか。**
できない。保留・非同期承認は撤去済み。外出先の承認はビューア併用（`--allow-merge`）が前提。

**「pi に依頼」ジョブと対話の pi の違いは。**
ジョブは撤去済み。依頼はチャットで足りる。

**どのモードを選ぶか。**
手元で完結するなら pi 単独。画面で差分を見たい・離れた場所から統合したいなら、無旗で使い始め、必要な旗だけ足す。

**ビューアを入れたら pi の動きは変わるか。**
層 0・1 は変わらない。対話の pi が画面から受け取るものは無い（レビューコメントの送信は撤去済み）。

**レビューの記録はどこに残るか。**
`refs/pi/review/<prKey>`（pi のサマリーと統合の結果。撤去前のコメントの記録も残り、読める）。ビューアを止めても残る。
