# CHG-0062: PR の管理・統合を、人が操作するアプリへ移す（保留・受信箱を撤去し、pi を通常のコーディングエージェントへ戻す）

- **状態**: Planned
- **実装の前提**: 方針は決定済み（2026-11-03）。実験 X1（git）は**合格**、X2（Fence）は loopback が合格・tailnet の名前は未確定、X3（`pis -p`）は軽量版を実施済み（[実験記録](../research/agents/pr-merge-spike.md)）。役割ごとの X3 は段 A4 の前に行う
- **更新日**: 2026-11-03
- **基準**: pi 1.4.0、[CHG-0060](0060-local-pr-viewer.md)（PR ビューア）・[CHG-0061](0061-pr-inbox.md)（受信箱。**この案件で方針を置き換える**）・[CHG-0055](0055-async-approval.md)（非同期承認。撤去対象）・[CHG-0056](0056-orchestrator.md)（配車。見直し対象）

## 1. 要約

PR の管理・統合を、**LLM を載せた pi の TUI の外**にある小さなアプリ（既存の PR ビューアを拡張）へ移す。統合は、あなたの押下（スマホ可）で、アプリが同期的に実行する。pi は、考える仕事（設計・実装・レビュー反映・衝突解消）だけを、**押下契機の `pis -p`（worktree 単位・1 回ずつ）**で行う。最終的には、オーケストレーションも、アプリ（機械的な処理）と補助のマネージャーエージェント（判断・生成）へ移し、**pi をガード付きの通常のコーディングエージェントへ戻す**。

| 項目 | 内容 |
| --- | --- |
| きっかけ | 2026-11-03 の実機での摩擦（§2）。利用者の依頼: 「どう設計するとシンプルになるか、俯瞰して再設計して。機械的操作が大きいなら、システム化を検討して」 |
| 方法 | 計画役が、現状の事実とコードを読み、3 案を比べた。サンクコストは理由にせず、将来の費用と便益で選んだ |
| 決定 | §4（2026-11-03）。**案 2、merge commit、押下契機のヘッドレス、衝突解消に LLM を許す（結果は人が承認）** |
| 置き換える | CHG-0061 の方針（受信箱・`queue`・`auto`・2b）。CHG-0060 の「承認はアプリで閉じ、実行は窓口の pi」。保留系（`pending-*`・`exclusive-lock`・`integrate-*`・`git_integrate`） |
| 実装 | 未着手（実験 X1〜X3 が先） |

## 2. 根本原因（実測）

| # | 原因 | 今日の摩擦 |
| --- | --- | --- |
| R1 | 承認の「記録」が、承認する対象（枝の先頭）と別の永続物になっている。承認の時点で枝の先頭から再計画するので、記録は枝の写しにすぎない | 古い保留がごみとして残る（旧版を承認したら新版が統合され、新版の保留が対象を失った） |
| R2 | 決定的な実行（squash）が、LLM を載せた TUI の中にある（モデルの実行中は承認できない。他プロセスと hook を前提にした排他・停止確認・`unknown`） | スマホで統合まで閉じられない。Windows では統合を拒否する |
| R3 | 人の非同期な操作を、会話の入力ループへ pull で届けている（注入・take・受信箱の 3 経路。ポーリング・世代・stale） | 受信箱の独立 review で MAJOR 2 件。窓口・宛先などの概念が増えた |
| R4 | 機械的な手順（合流確認・develop の取り込み・復旧）の状態が、親の会話と規則に載っている | 親が毎回同じ手順を踏む。会話が巨大化し、圧縮が失敗した（要約が 4〜6 万字） |
| R5 | squash は元コミットとの祖先関係を断つので、積み重ね（A の上に B）で衝突する | 6 本の積み重ねのうち 4 本目から衝突した |

過去の実測として、独立 review の BLOCKER/MAJOR は、保留・承認・受信箱の系統に集中している（CHG-0055・0058・0061 の記録の合計 43 件）。

## 3. 設計

### 3.1 役割

| 登場人物 | 役割 | しないこと |
| --- | --- | --- |
| あなた | 差分を見る・コメント・計画の承認・統合ボタン | |
| アプリ（非 LLM。PR ビューアを拡張。Fence の外） | PR 一覧・差分・レビュー、**統合の実行**、合流可否の常時計算、worktree の作成・ジョブの起動・コミット・検査・後片付け（段 B） | LLM の判断。承認の保存（押した瞬間に実行して終わる） |
| マネージャーエージェント（`pis -p` を 1 回ずつ。段 B） | 依頼の分解と worker への指示、独立 review、衝突解消 | 統合の実行。長い会話を持つこと |
| worker（`pis -p`） | feature の worktree での実装・レビュー反映 | commit・統合 |
| 親の pi（あなたが対話で使う通常の pi） | ガード付きの通常のコーディング | PR・統合・オーケストレーションの専用機能（段 C で撤去） |
| git | 唯一の状態。枝と、表示用の `refs/pi/review/<prKey>` | |

### 3.2 統合（「統合する」ボタン）

1. 承認シート: 統合元の先頭 OID・合流可否・統計・リスクのあるパス・メッセージ（`mergeMessage` が既定値。編集可）・cleanup・2 段の確認。
2. POST: シートを開いたときの統合元・統合先の OID（`expect`）を付ける。違えば 409（画面が古い）。
3. アプリが同期で実行: 衝突・dirty・外部 driver・保護対象を検査 → `git merge-tree --write-tree` で結果の tree → `git commit-tree <tree> -p <develop> -p <枝>`（merge commit。squash の文面がメッセージ）→ develop の worktree で `git merge --ff-only`（develop が動いていれば失敗。**CAS の代わり**）→ cleanup → `merge_result`（表示用）を ref に書く。
4. 承認の記録は作らない。保留・鍵・期限・古い保留・排他ロックは要らない。
5. **事前検査・排他・復旧**（X1 で確かめた。詳細は[実験記録](../research/agents/pr-merge-spike.md)と §3.5）: develop の worktree の HEAD が develop、統合済みでない（`merge-base --is-ancestor`）、統合が触るパスが dirty・untracked・**ignored** と重ならない。同時に 1 件だけ実行する（ff-only の敗者が作業ツリーを汚すことがあるため）。**復旧は診断と状態の解除だけで、作業ツリー・index・ref を自動では書き換えない**（2 回の独立 review で、自動の復旧・削除は、確認と実行の間に割り込む書き込み（エディターの自動保存・生成処理）やパスの特殊文字で、利用者のデータを失う経路が見つかったため。§3.5）。

### 3.3 統合方式: merge commit

squash（1 つ親）は祖先関係を断つので、積み重ねで衝突する。merge commit（枝を第 2 親）なら、A を入れると B から見て A は祖先になり、順序の問題が消える。develop の履歴に feature のコミットが入るが、`git log --first-parent` では 1 feature = 1 コミットに見える。docs・skill の「squash」の記述を改訂する。実験 X1 で、積み重ね・同時実行・中断・dirty を確かめる。

### 3.4 衝突のとき・レビュー反映

- 衝突: アプリが一覧に「develop と衝突」と出し、統合ボタンを使えなくする。「衝突を解決」で、feature の worktree で `pis -p` を 1 回起動する（develop を枝に取り込み、衝突を解消してコミットする）。結果は feature 側のコミットで、あなたが差分を承認してから統合する。**LLM が人の承認なしに develop へ入れることはない**。
- レビュー反映: 「変更を依頼」で、コメントを引用データとして囲んで `pis -p` に渡す。終わったら、アプリが決定的な関門（範囲・登録漏れ・空ファイル）を実行する。
- 1 worktree に同時 1 run。時間切れで終了し、アプリの終了でプロセスグループを止める。
- **A4a の実装（2026-11）**: 「変更を依頼」だけを、feature の実 worktree で `pis --role worker --allowlist -p` を 1 回起動する形で実装した。コメントは乱数の囲みの引用データとして渡し、アプリは pi の出力を解釈せず、終了後に照合（起動前の記録との比較）・検査（A/M/D の通常ファイルだけ・上限・`risk_paths` など）を通った変更だけを commit する（通らなければ `needs_review` で commit しない）。上限は 1 回 10 分・同時 1・日 30 回。X3-a（本物の `pis` と LLM での実測）は未実施で、既定で無効。A4b（衝突を解決）は、同じ起動・検査・commit の仕組みの上に、develop の取り込みを足す予定（まだ設計のみ）。

### 3.4.1 安全

| 論点 | 設計 |
| --- | --- |
| 権限の源 | **ブラウザからの POST だけ**。ref の「承認」は読まない（Fence の内側から共有 `.git` の ref を書けるので、ref は偽造できる。[fence-boundary](../spec/sandbox/fence-boundary.md)） |
| 誤操作・CSRF | Origin 必須（既存の検査は Origin 無しを許すので改訂）・`X-PRV`・`expect` による版の固定 |
| 既定で無効 | `--allow-merge` を付けたときだけ統合を受け付ける |
| 自分で統合できない | Fence の内側から localhost は届かない（既定。tailnet の名前は X2 で確かめる）。素の pi（Fence なし）には、判定器の curl 拒否を**必須**で足す（2026-11-03 の実測: Fence の外の pi から、アプリへの curl が届いた） |
| 限界 | 素の pi が意図的に迂回する経路は、完全には塞げない（ガードは境界ではなく、うっかり防止） |

### 3.5 統合器の実装（段 A1。`apps/pr-viewer/merge.ts`・`merge-git.ts`・`merge-cli.ts`）

HTTP・画面にはつなげていない（A2）。`planMerge`（読み取りだけ）・`executeMerge`・`recoverMerge`と、CLI（`node apps/pr-viewer/merge-cli.ts plan|merge|recover <repo> …`。結果は JSON を 1 行。終了コード: 成功 0・拒否 2・想定外 1。メッセージは `--message-file` だけで受ける）。試験は `test/agents/test_pr_viewer_merge.py`（実 git の使い捨てリポジトリ）。

| 項目 | 内容 |
| --- | --- |
| 守る条件 | hook・外部の merge driver・filter・fsmonitor・`include` を動かさない（固定の先頭引数・絞った環境変数。設定に外部のコードを動かしうる項目があれば、書く前に `external_code` で拒否）。ref の書き込みは CAS だけ（`merge --ff-only`、または旧先頭を渡した `update-ref`）。入力（枝名・OID・cleanup・メッセージ）は検査を通ったものだけを git に渡す。出力（reason・例外）に絶対パス・git の生の出力を出さない |
| 事前検査 | policy（source は `feature/`・`bugfix/`、target は `develop`）、ref 名の形、存在、`expect`（古い版は `stale`）、統合済み、衝突、HEAD が target、進行中の操作が無い、`index.lock` が無い、統合が触るパスが dirty・untracked・ignored と重ならない（無関係な dirty は通す）。ff の直前に、ロックの保持と HEAD をもう一度確かめる |
| 前提の検査（git 堅牢化 P1） | **git は最新版を使う前提**で、古い版への互換は作らない。何かを書く前に、次を断る: (1) git の版が 2.40 未満、または版を確認できない（`git_version`。`merge-tree --write-tree` は 2.38、`check-attr --source` は 2.40） (2) `core.sparseCheckout` が有効なリポジトリ（`unsupported_repo`。統合器は `core.sparseCheckout=false` で動かすので、作業ツリーの展開が変わる。`config.worktree` も見る） (3) サブモジュール（mode 160000）の追加・更新・削除を含む変更、と `filter` 属性（LFS など）を持つファイルを含む変更（`unsupported_change`。統合器は利用者の global 設定と filter の設定を読まないので、展開すると実ファイルではなくポインターテキストが書かれうる。属性は統合後の tree で見る。`-filter`（解除）と `filter` 以外の属性は通す）。これらを確かめる git が失敗したときも、「問題なし」にせず `failed` で断る |
| 排他 | `<common-dir>/pr-viewer-merge.lock`（中身を書いた一時ファイルを `link` で置く。待たずに `busy`）。**持ち主の pid が死んだ古いロックは奪わない**（`recover_needed`。奪う処理は確認と削除の間で競合し、両方が保護区間に入るため）。解除は利用者が実行する `recover` だけ |
| 結果の tree（P2） | `git merge-tree --write-tree` に `--attr-source=<target の OID>`（git 2.40 以上）を付け、target の `.gitattributes` を読ませる。worktree の外で動かすと属性（`binary` など）が読まれず、素の `git merge` と結果が変わる（差分試験で発見）。差分試験 `test_pr_viewer_merge_oracle.py`（既定 40 シナリオ、`MERGE_ORACLE_N`・`MERGE_ORACLE_SEED` で増やせる。oracle の git が merge-ort の BUG で abort する seed は skip）と、失敗注入 `test_pr_viewer_merge_faults.py`（git の全呼び出しを失敗・実行後失敗・クラッシュの 4 方式で壊し、どこで止まっても「統合前」か「統合後」の整合した状態であるか、`recover` が診断することを確かめる）。反映の確認だけ失敗したときは `unverified`（状態ファイルを残し、`recover` が統合済みと確かめる）を返す |
| 状態ファイル | ff の直前に `<common-dir>/pr-viewer-merge.state` を書く（統合が触るパス・新しく作られるパス・コミット・旧先頭）。成功で消し、失敗でも作業ツリーが無傷だと確かめられたときだけ消す。残っている間は新しい統合を断る（`recover_needed`） |
| `recover` | **確かめて、状態を解除するだけ**。ref が統合後の先頭なら `completed`、旧先頭のままで、統合が触るパスに差（変更・untracked・ignored）・`index.lock`・進行中の操作が無ければ `cleared`、状態が無ければ `clean`。差があれば何も変えず、診断（`details`: 差のあるパスの一覧・`indexLock`・`operation`・`cause`）を返す。**`index.lock` も消さない**（他の git が使っているかもしれない） |
| cleanup | `none`・`branch`・`branch_and_worktree`。枝は、どの worktree でも checkout されていないときだけ、承認した先頭を指定した `update-ref -d`（CAS）で消す（`branch -d` は upstream 基準の判定で、統合していない先頭を消しうる）。worktree は、source の worktree に未コミットの変更・untracked・ignored・外部のコードを動かしうる設定が無いときだけ `git worktree remove`（git 自身は ignored を守らず再帰的に消すため、検査は `--ignored` 込み）。失敗は警告で、統合の成功は取り消さない |

#### 運用の前提（アプリが守る・利用者に伝える）

- 統合・cleanup・`recover` の間は、同じリポジトリへの別の git 操作・エディターの自動保存・ビルドなどの生成処理を止める。この部品は排他を、アプリのロックでしか取れない。**A2 のアプリは、実行中のジョブのある PR の統合を断る**。
- 残る窓（実害は低いが、ゼロではない）: (1) `merge --ff-only` は実行時の現在の枝を進めるので、ff の直前の再確認の後に外部の git が HEAD を切り替えると防げない。(2) cleanup の worktree 削除は、`--ignored` を含む検査の後に、ビルド処理などが ignored ファイルを作ると、それも消える。(3) ロックの持ち主の pid が再利用されると、古いロックが生きていると見なされて `busy` のまま残る。(4) Windows・macOS は未検証。

#### 異常終了の後の手順（`recover_needed`）

1. 他の git が動いていないことを確かめる（`ps` などで `git` の子を確認する）。
2. `recover` を実行する。`cleared`・`completed`・`clean` なら、ここで終わり（状態と古いロックが解除される）。
3. 診断が返ったら、`details.paths` の一覧と `git status` を見て、統合が書いたものを手で戻す（利用者のファイルを消さない）。`index.lock` は、他の git が無いことを確かめてから手で消す。
4. もう一度 `recover` を実行する。
5. どうしても解除できない（状態ファイルが壊れている等）ときは、手で確認してから `<common-dir>/pr-viewer-merge.state` と `<common-dir>/pr-viewer-merge.lock` を削除する。

**統合は成功したが取り消したい**ときは `recover` ではなく、[統合を取り消す手順](../spec/pr-viewer.md)（`reset --keep`・`update-ref` の期待値つき・`revert -m 1`、消えた枝の復元）を使う。統合の結果を確認できなかった（`unverified`）ときも、状態ファイルが残るので `recover` を実行する（統合済みなら「統合済み」として解除される）。

### 3.6 pi を通常のコーディングエージェントへ戻す（段 C）

エージェントは git の書き込み（add・commit・merge）をしない。アプリが、範囲を検査してから機械的に行う。pi 側に残るのは、ガード（判定器・Fence・確認画面）と普通のツール、対話用の最小の `git_commit` だけ。`pr_summary`・`pr_comments`・注入・`guarded_task`・盤面・`guarded_action` の統合系は、アプリがジョブの最終出力をサマリーとして保存するようになってから撤去する。

## 4. 決定（2026-11-03）

| # | 決めること | 決定 |
| --- | --- | --- |
| D1 | 全体の案 | **案 2**（統合をアプリへ移す）。案 1（保留を残して自動化）・案 3（PR ハブ + 都度起動）は採らない |
| D2 | 統合方式 | **merge commit**（squash の文面をメッセージにする。統合時に hook は走らせない）。X1 が不合格なら見直す |
| D3 | pi の起動 | **押下契機のヘッドレス**（`pis -p`。X3 に合格してから）。受信箱は撤去する |
| D4 | 衝突解消に LLM を許すか | **許す**（結果は feature 側のコミットで、人が差分を承認する）。「LLM に直させない」規則（pi-subagents）を改訂する |
| D5 | 切り出しの理想 | アプリ（機械的な処理）と補助のマネージャーエージェント（判断・生成）でオーケストレーションを賄い、pi を通常のコーディングエージェントへ戻す（段 B・C。段 A の後に、実際に回してから進める） |
| D6 | 実装中・取り込み済みの部品 | 保留のごみ対策（`feature/pending-supersede`）は止め、差分を退避した。受信箱（S2）は配備せず凍結し、押下契機の起動が試験に通ってから撤去する |

## 5. 段階（各段階で動く状態を保つ。見積りは推測）

| 段 | 内容 | 進める条件 |
| --- | --- | --- |
| 0 | 実験 X1〜X3（§7）。結果を `docs/research/agents/` に残す | — |
| A1 | 統合器（`merge.ts`）と CLI（`merge-cli.ts`）を、実 git の試験で作る（アプリへは未接続。**実装済み**。2 回の独立 review を経て、自動の復旧をやめた。§3.5） | X1 合格 |
| A2 | アプリへ接続: `POST .../merge-plan`・`POST .../merge`・承認シート。Origin 必須・`--allow-merge`・Funnel ヘッダーの拒否・判定器の curl 拒否・`risk_paths` に `apps/pr-viewer/**`。旧経路とは**併用禁止**（事前検査で断る。窓は残る）。**実装済み**（G: 判定器・S: サーバ API・U: 画面の 3 feature。計画・実装とも独立 review 済み。設計は [pr-viewer.md §6「統合」](../spec/pr-viewer.md)。有効化には取り込みの後の `chezmoi apply`・pi 再起動・実機確認が要る） | A1 |
| A3 | 合流可否・「develop が N 進んだ」・「未 push N 件」の表示（読み取りのみ）。**実装済み**（`behind`・`overlap`・`unpushed`。設計は [pr-viewer.md §6](../spec/pr-viewer.md)） | A2 |
| A4 | 「変更を依頼」「衝突を解決」（`pis -p` の起動）。**A4a（変更を依頼）は実装済み**（`--allow-jobs` 既定無効・X3-a の実機実測は未実施。設計は [pr-viewer.md §6「ジョブ」](../spec/pr-viewer.md)）。A4b（衝突を解決）は未着手 | X3 合格（X3-a は A4a の有効化の前に実施） |
| A5 | 撤去（保留・受信箱・`git_integrate`・`/pending approve` など。約 2,900 行 + 試験約 20 ファイル） | A2〜A4 の運用で足りること |
| B1 | 起票: アプリが新しい feature（枝と worktree）を作り、依頼文 brief をレビュー記録へ残す（`POST /api/repos/<repoId>/features`。LLM・pis は呼ばない）。**実装済み・既定で無効**（`--allow-create`）。設計は [pr-viewer.md §6「起票」](../spec/pr-viewer.md) | A2 |
| B | アプリのジョブ実行（worktree の作成・worker の起動・コミット・検査）とマネージャー役（計画・review・衝突） | A の運用。`pis -p` の役割の試験 |
| C | pi 側の撤去（`guarded_task`・`git_commit` の guarded_action 統合系・盤面など）。pi をガード + 通常のツールへ戻す | B が実際に回ってから |

## 6. 撤去・残す・縮小

| 区分 | 部品 |
| --- | --- |
| 残す | PR ビューア本体、`review-log.ts`・`review-git.ts`、`git_commit`（自由区。対話用）、`integration-gate.ts`・`[pi.integrate]` の保護（素の pi の必須確認）、`integrate-plan.ts`（算出は統合器が再利用） |
| 縮小 | `integrate-exec.ts`（542 行 → 3 コマンド）、`/pending`（旧 `git_commit` 退避の list・show・drop だけ）、`/board` |
| 撤去（段 A5） | `pending-ops`・`pending-approve`・`pending-command`（巡回・approve）・`pending-pick`・`pending-owner`・`pending-adapters`・`pending-request`・`native-action`・`integrate-action`・`exclusive-lock`・`pr-inbox`、`git_integrate` 操作 |
| 撤去（段 C） | `guarded_task`（`children.ts` など）・`/fleet`・`/orchestrate`・`worktree.ts` の隔離など。`pr_summary`・`pr_comments`・注入（アプリが最終出力を保存するようになってから） |

## 7. 実験（段 0。使い捨て）

| # | 確かめること | 合格の基準 | 結果（2026-11-03） |
| --- | --- | --- | --- |
| X1 | git: 積み重ね（A→B）で、merge commit なら B の `merge-tree` が衝突しない。squash は衝突する（再現）。2 並行の `merge --ff-only` で 1 つだけ成功。ff 中の `kill -9` の状態。dirty・untracked との重なり | 仮説どおり。中断・dirty の扱いを決められる | **合格**（2026-11-03）。仮説と違った点: 敗者が作業ツリーを汚す・ignored は黙って上書きされる・統合済みの枝の再統合が空の merge commit になる・中断で `index.lock` が残る（いずれも事前検査・排他・復旧で対応。§3.2 の 5） |
| X2 | Fence（`pis`）の内側から、(a) `127.0.0.1` のアプリ、(b) tailnet の名前、(c) `refs/pi/review/*` の書き込みを試す | (a)(b) が届かず、(c) が通る | (a) **合格**（外=200・内=接続できない）。(b) 未確定（基準が無い。中継のコードは共有アドレス空間を拒否するので届かない見込み。**funnel は届く**）。(c) 未実施 |
| X3 | `pis -p` を feature の worktree で動かす: 実装・レビュー反映・衝突解消・計画（構造化出力）の役が動くか。所要時間・費用・TTY の有無。Windows の素の pi の `-p` | 役割ごとに、期待どおりの出力と終了コード | 軽量版: 編集は約 13.5 秒で動く。**Fence 内の `git_commit` は pre-commit がマスクされたファイルで失敗する** → commit は Fence の外のアプリで行う。役割ごと・費用・Windows は未測定 |

## 8. リスクと未確認

| 項目 | 内容 |
| --- | --- |
| 実行権限の移動（最大） | アプリが Fence の外で、利用者権限で git を実行する。HTTP 層の欠陥が影響を広げる。統合器は自由入力を取らない（メッセージは `-F`、OID と列挙値のみ）。実装の前後の独立 review は外せない |
| Fence の内側から tailnet の名前で届くか | 未確認（X2）。届けば `[pis.network] deny` に足す |
| `pis -p` の質・費用・時間 | 未確認（X3） |
| Windows | 統合は標準 git だけなので動く見込み（今は統合を拒否している）。ジョブ実行（`pis`）は Unix から始める。Windows 実機は未検証 |
| 履歴の形 | merge commit で、develop の履歴に feature のコミットが入る（`--first-parent` で 1 feature = 1 コミット） |
| 共存期間 | 旧実行器は `refs/pi/lock` を使い、アプリはそれを見ない。A2 で「lock・running があれば拒否」を入れ、A5 で解消する |
| 見積り | 行数・工数はすべて推測 |

## 9. 却下・見送り

| 案 | 理由 |
| --- | --- |
| 案 1（保留を残して自動化） | スマホで統合を閉じられず、独立 review が毎回 MAJOR を出す部品群の保守が続く |
| 案 3（PR ハブ + 都度起動の pi を最初から） | 需要が実測されていない。案 2 から連続して到達できる |
| GitHub の本物の PR・merge queue | 公開リポジトリで WIP が公開される。エージェントに push・merge の権限を渡すと、人だけが統合する前提が崩れる。便益（スマホ UI・通知）は自作で足りる |
| rebase + ff | 枝の履歴を書き換え、レビューログの OID が壊れる |
| 保留の古い記録の自動整理（`pending-supersede`） | 撤去する部品に足す変更になる |

## 10. 履歴

- 2026-11-03: 実機の摩擦（保留のごみ・積み重ねの衝突・承認が TUI に縛られる・受信箱の複雑さ・圧縮の失敗）を受け、利用者が「俯瞰した再設計」を依頼。計画役が 3 案を比べ、利用者が案 2 を選んだ（D1〜D4）。併せて「アプリへ切り出し、pi を通常のコーディングエージェントへ戻す」を理想とした（D5）。
- 2026-11-04: 起票（B1）の独立 review の指摘 M1〜M4 を直した。競合に負けた側は相手の枝・worktree を消さない（`worktree add` 失敗は診断のみ）・brief は新規専用 CAS（既存 ref に追記しない）・記録結果を recorded / not_recorded / unknown に分けて unknown は読み直し（確定できなければ残して `create_partial`）・巻き戻しの外部コード設定の検査を `git status` より先に。検査後の symlink 差し替え（TOCTOU）は対象外のまま（[pr-viewer.md §12](../spec/pr-viewer.md)）。
