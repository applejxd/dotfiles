# オーケストレーションと並列作業の機能一覧

親エージェントが、子エージェント（`guarded_task`）と feature ブランチを使って、作業を分けて並列に進めるための機能を、カテゴリ別にまとめた一覧。**今どうなっているか**だけを書き、仕様の細部は各行の正本に任せる。
未実装・保留の項目は、最後の表に案件へのリンクつきで置く。

**状態の凡例**: 実装済（試験あり）/ 試作（実機の確認が一部）/ 運用（手順として使う。強制はしない）/ 保留（案件で止めている）。実機の確認が済んでいない範囲は、各行に書く。

`pi` の機能全体の中の位置は [機能の地図](pi-features.md)。pi 単独と PR ビューア併用の使い分けは [運用モード](operation-modes.md)。

対象は、フルガードを付けた `pi`（Unix）。Windows の子エージェント・素の `pi` での違いは [pi の子エージェント](guard/pi-subagents.md#windows-の子エージェント)。

## 1. 親子の分担と委譲の方針

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 親と子の分担 | 運用 | 親は対話・判断・委譲・承認・ToDo の管理。調査・計画・実装・検証は子へ（全体の指示は `agent-instructions.md`。親の文脈を重い読み物で占めない） | [CHG-0045](../change/0045-orchestrator-parent.md) |
| 子が止まらない条件 | 実装済（判定器の決定表で確認。実際の子の RPC 起動での再確認は未） | 子が確認なしで動けるのは、親の bypass を継ぐか、証明済みの境界（`pis`）の内側のとき。`mustConfirm` は常に確認 | [CHG-0045](../change/0045-orchestrator-parent.md)、[判定器](guard/pi-decide.md) |
| `/fleet` | 実装済 | 依頼を、並列に動かせる作業に分け、`worker` を 1 回の応答に並べて起動させる | [fleet](guard/pi-extensions.md#fleet) |
| feature の並列実装の手順（起票 → worker → 確認 → 取り込み） | 運用（スキルとして工程化） | チェックリストと落とし穴をスキル `feature-orchestration` に、worker 共通の約束を `references/worker-common.md` に置く。依頼文の雛形と手順の正本は「並列実装の運用」 | [pi-subagents](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| 委譲の統計（`delegate-nudge`） | 試作 | 読み取り系ツールの回数と、子の起動数だけを、セッションに記録する（通知しない。子では動かない） | [自作の拡張](guard/pi-extensions.md#自作の拡張-todo--plan--btw) |

## 2. 子の起動と実行の制御（`guarded_task`）

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 単発の起動 | 実装済 | `{agent, task}`。完了まで待つ。新しい子（`explore`・`review`・`worker`）は ToDo の項目 ID（`todo`）が必須。`cwd` で実行場所（登録済みの worktree）を指定でき、worker は担当の worktree を `cwd` に指定して起動する（edit / write は担当 worktree と明示した一時領域の外を書けない。shell・試験・hook は未強制） | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| バックグラウンド | 実装済 | `background: true`。ID をすぐ返し、完了は通知で届いてターンが再開する | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| 並列 | 実装済 | `tasks: [...]`（最大 12 件）。同時に生かす子は 6 まで（正本は `home/dot_config/pi/harness/index.ts` の `MAX_JOBS`）。超えた分は空きを待つ | 同上 |
| 保持と追加依頼（job） | 実装済 | `keep: true` で残し、`{jobId, task}` で履歴を保って続ける。`close` で止める | [job](guard/pi-subagents.md#子を保持して追加依頼するjob) |
| 状態・steer・abort | 実装済 | `status`・`list`・`steer`・`abort`（今の往復だけ止める） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| 往復の上限 | 実装済 | 役割ごとの `timeout_minutes`（既定 15 分、`worker` と `plan` は 30 分）。上限の 80% で「まとめに入れ」を送る | 同上 |
| モデルと effort | 実装済（Bedrock の実機確認は未） | カタログから選ぶ。**利用者が指示したときだけ指定する**。結果に使った値を必ず出す | [CHG-0043](../change/0043-model-catalog.md)、[モデルの割り当て](agent-model-assignment.md#子エージェントのモデルのカタログ) |
| 子の質問・親への通信 | 未対応 | 子から親への通信は無い（結果の返却と完了通知だけ） | [job](guard/pi-subagents.md#子を保持して追加依頼するjob) |

## 3. 子の役割と権限

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 役割 `explore` / `review` | 実装済 | 読み取り専用（`wc` と読み取りの git）。`review` は別系統のモデル（`second_opinion`） | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| 役割 `plan` | 実装済（`/plan` での深い計画への切替は未） | bash なしの読み取り専用。深く考える階層。大きな変更の計画を作る | [CHG-0044](../change/0044-plan-agent.md) |
| 役割 `commit` | 実装済 | コミットの計画（対象ファイルとメッセージ）を返すだけ。ステージもコミットもしない | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| 役割 `worker` | 実装済 | 実装役。`git add`/`commit`/`checkout`/`reset`/`stash` は deny。`git status`・`git diff` は通常は ask（bypass か境界で通る。許可を足す案は保留） | [pi の子エージェント](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| bypass の継承 | 実装済 | 役割ごとの `inherit_bypass`。`/bypass` の切替で、動いている子は止まる | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| 既定が deny の役割の扱い | 実装済 | `explorer`・`reader`・`committer` は、`[bash] ask` に当たる操作も、bypass で通さず deny にする | [判定器](guard/pi-decide.md#既定が-deny-の役割の-ask) |
| 計画モード中の子の制限 | 実装済 | `/plan` の間は、書き込む役割の子の起動・追加依頼・steer を拒否する | [pi の子エージェント](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| 入れ子 | しない | 子から子は作れない（指揮役の工程は親に残る） | [CHG-0045](../change/0045-orchestrator-parent.md) |

## 4. 作業場所の分離とブランチ（gitflow）

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| ブランチモデル | 運用 | main / develop / feature（squash。release・hotfix なし）。リポジトリごとに `.gitflow` で決める。feature の起票は親が行い、feature の linked worktree の `git_commit` は確認なしで実行される（自由区）。統合は利用者（TUI の必須確認・`merge-cli`・ビューアのボタン。[運用モード](operation-modes.md)）、`main` への取り込み・push は利用者が自分のシェルで行う | [CHG-0047](../change/0047-gitflow.md)、[開発](development.md#ブランチモデルgitflow-lite)、[CHG-0050](../change/0050-slim-guarded-action.md) |
| develop / main の直接編集・コミット | 機械では止めない（指示で運用） | `edit` / `write` / `git_commit` の gate と `/gitflow-allow`、`gitflow_feature_*` の 4 操作、`git flow` の bash 拒否は 2026-10-31 に撤去 | [CHG-0050](../change/0050-slim-guarded-action.md)、[ADR-0021](../adr/0021-conventions-as-instructions-slim-guarded-action.md) |
| 隔離なしの worktree | 運用 | 親が feature の分割を決め、子には worktree の中だけで作業させる。起票は利用者。強制の囲いではない | [並列実装の運用](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| 子の隔離（`isolation: "worktree"`） | 保留（素の `pi` では認証のロックの書き込みが拒否される） | Landlock で書き込みを狭める。`pis` では認証の写しが既にある | [CHG-0029](../change/0029-worktree-isolation.md) |

### worktree の所有の表明

調査: `.tmp/keep/wt-research/synthesis.md` の P1（利用者の選択）。他ツールで所有を機械で強制するものはなく、`git worktree lock` を表明に使うのは一部（pid 付きのものがある）。

- **理由欄**は 1 行 `owner=<kind> id=<id> pid=<pid> started=<unix 秒>`。`id` は空白を含まない 1 語。
- **kind**: `worker`（親が起動した子エージェント）・`job`（PR ビューアのジョブ。撤去済み）・`create`（起票の作成中だけ。撤去済み）・`bundle`（統合用の枝の組み立て）・`interactive`（人の対話 pi。任意）。
- **生死**: `pid` が生きている間だけ「有効」（`kill -0`）。死んでいれば「残骸」。**残骸は `claim` が自動では奪わない**（`unlock`→`lock` は原子的でなく、古い観測で他方の新しい lock を外しうるため。終了コード 3・「`reap` で解除してから」）。解除は明示の回復操作 `reap` だけが、観測した理由欄を再読して一致する場合に限り行う。`owner=` で始まらない lock（人が付けたもの・理由なし）は「不明の lock」として自動では解除しない。
- **道具**: `scripts/wt_owner.py`（本体は `home/dot_claude/skills/feature-orchestration/scripts/wt_owner.py`。`scripts/` のは転送。`wt_clean.py`・`bundle.py`・`parallel_check.py`・`feature_gate.py`・`prs.py` も同じ）（`claim <wt> --kind <k> --id <id> [--pid N]`・`release <wt> [--id <id>]`・`status [<wt>]`・`reap`。他の有効な owner・残骸・不明の lock で終了コード 3）。同じ規則の TS 実装が `apps/pr-viewer/worktree-owner.ts`。`--pid` を省くと、シェルではない最初の祖先（= 呼び出した AI）の pid になる。
- **排他**: git の `worktree lock` 自体が「lock 済みか確認 → `locked` ファイルを書く」の非原子で、負荷下では 2 件が同時に成功した（実測）。そのため `claim`・`release`・`reap` の臨界区間は、共通 git-dir の `pi-wt-owner.guard`（`O_EXCL` 作成。既定の待ち 10 秒、30 秒より古いガードは残骸として削除）で排他にする（Python・TS 共通。取れなければ fail closed: `claim` は終了コード 3、他は失敗）。`claim` は lock 後に理由欄を再読して自分のものか確かめる。待ち時間は `PI_WT_OWNER_GUARD_WAIT_MS` で変えられる（試験用）。
- **4 経路**: (1) 子エージェント = 親が起動の直前に手で `claim`、commit 後に `release`（ハーネスは改造しない）。(2) ジョブ = 起動前検査（`preflight`）が他の有効な owner・残骸・不明の lock・cwd が worktree の中のプロセスを `worktree_busy`（HTTP 409）で拒否し、開始で `claim(kind=job, id=<jobId>)`（起動前検査の後に残骸が現れて拒否されたときは、ジョブは `failed`・理由 `worktree_busy`＋`stale_lock`。`reap` で解除してからやり直す）、終了・失敗・キャンセル・回復で `release`（**停止を確認できなかったジョブ（`stop_unconfirmed`）は lock を残す**）。(3) 起票 = （撤去済み。画面の起票が `worktree add --lock` で作成中だけ `kind=create` を表明していた）。(4) 人の対話 pi = 任意。
- **限界**: lock を忘れた経路は検出できない。cwd 走査は、cwd が別の場所の子エージェントを見つけられない。pid の再利用は見分けない（`kill -0` だけ）。全件検査の前に `status` で worker の lock が無いことを確かめる（検査中の編集による誤失敗の防止）。

### worktree の掃除の規則

取り込み済みの worktree を、PR ビューアの統合の cleanup（[後始末](pr-viewer.md)）と CLI `scripts/wt_clean.py <名前>... [--dry-run] [--repo <パス>]` で同じ規則で消す。

1. **統合済み**（枝が統合先の祖先）だけが対象。未統合・追跡ファイルの変更・未追跡（無視されないもの）は拒否。
2. 無視ファイル（`__pycache__`・`.pytest_cache`・`node_modules` など）だけなら、それごと削除する。`git worktree remove`（`--force` なし）が無視ファイルごと消す。status が空と確かめた後だけ呼ぶ。（pi の親・worker が bash で直接呼べる `git worktree remove` は、単純な 1 行の force なしだけで、退避は無い。[例外と限界](guard/pi-decide.md#git-worktree-remove-の例外)）`filter`・hooks など外部コードが動きうる設定があれば、status も動かさず残す。
3. 削除前に無視ファイルを tgz へ退避する（ビューアは `--state-dir` 配下の `cleanup-backups/`、CLI は `<共通 git-dir>/pi-cleanup-backups/`。`<名前>-<時刻>.tgz`）。200 MB 超・数えられない・失敗なら worktree を残して警告。退避は新しい順に 5 件まで。
4. **有効な owner の lock**（pid が生きている）・人が付けた lock・**残骸の lock**（pid が死んだ lock）は、いずれも掃除しない（worktree も枝も残す）。残骸は解除もしない（古い観測で他方の新しい lock を外しうるため）。「`python3 scripts/wt_owner.py reap` で解除してから、もう一度」と案内する（CLI は拒否・終了コード 3。ビューアは統合の成功のまま警告に載せる）。
5. 枝は `git branch -d`（ビューアは承認した先頭を指定した CAS で削除）。

CLI の終了コード: 0 = 全て処理、3 = 一部を残した・拒否、2 = 使い方の誤り。

## 5. ガードとの接点（承認・確認・保留）

ガードの機能の正本は [ガード](guard/index.md)。ここには、並列作業で効く点だけを置く（[機能の地図](pi-features.md#柱をまたぐ機能の置き場)）。

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| `guarded_action` | 実装済 | `git commit` と `gh` の書き込みなどを、固定の引数と確認つきで実行する。親だけが持つ（子には登録されない） | [guarded_action](guard/pi-extensions.md#guarded_action承認つきの外部操作) |
| bypass でも確認する操作 | 実装済 | 外部への送信・公開と、元に戻せないローカルの git 操作（`branch -D`・`clean`・`tag -d` など）。子では UI が無いので拒否される | [判定器](guard/pi-decide.md#confirm) |
| 承認の時間切れ | 実装済（実機で動作確認。実 TUI・Windows は未） | 時間切れ・不在・UI なしのとき、実行せず内容を `refs/pi/pending/…` に退避して作業を続ける。利用者が `/pending` で確認・破棄 | [CHG-0046](../change/0046-guarded-action-timeout.md) |
| 保留の自動片付け | 実装済 | 取り込み済み・重複・30 日を超えた退避を、コミットの成功後と `session_start` で消す | 同上 |

## 6. 検査と検証

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 並列作業の混線の検査 | 実装済 | `scripts/parallel_check.py`。本体の変更・宣言した範囲の外・複数 worktree の同じファイルの変更を、取り込み前に見つける（読み取りだけ） | [並列実装の運用](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| 変更に応じた試験の選択 | 実装済 | `mise run verify`（日常）と `mise run verify:all`（コミット前に 1 回） | [テスト](testing.md)、[開発](development.md#検証の方針と選択実行) |
| 子の結果の形式の検査 | 実装済 | 結論・根拠・未確認・次の候補が欠ければ警告（拒否はしない） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |

## 7. 記録と復帰

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 子の結果の保存 | 実装済 | 完了通知に、結果の全文を `.tmp/subagents/<通番>-<job id>.md` に書く（50 件・7 日） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| ToDo の連動 | 実装済 | 子が完了しても、`todo` の項目は `done` にせず `blocked`（親の確認待ち）にして結果を `note` へ書く | 同上 |
| セッションごとの一時置き場 | 実装済 | `$TMPDIR` は `.tmp/s/<ID>/`。セッションの終わりに消える。残すものは `.tmp/keep/` 以下 | [一時置き場](guard/pi-extensions.md#セッションごとの一時置き場tmpsid) |
| 圧縮に備えた復帰の記録 | 実装済 | `checkpoint`（圧縮の前後の記録） | [圧縮](guard/pi-extensions.md#圧縮旧-checkpoint) |

## 8. 利用者向けのコマンドと表示

| 機能 | 内容 | 正本 |
| --- | --- | --- |
| `/agents`・`/agent <名前> <依頼>` | 子の一覧と、子の直接の起動（モデルは呼べない） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| `/bypass` | ask を確認なしで通す。切替で、動いている子は止まる | [pi のガード](guard/pi-guard.md) |
| `/orchestrate` | 親を計画・判断・委譲に絞る（作業のツールを隠す）。`on`・`off`・`status` | [pi の子エージェント](guard/pi-subagents.md) |
| `/plan` | 計画モード（書き込む役割の子を止める） | [CHG-0044](../change/0044-plan-agent.md) |
| `/pending` | 退避したコミットの一覧・表示・破棄（利用者専用）。非同期承認の `approve` などは撤去済み（[履歴](guard/pi-pending.md)） | [CHG-0046](../change/0046-guarded-action-timeout.md) |
| `/board` | **盤面**（読み取り専用・利用者専用）。feature ごとの `↑`（統合先に無い commit）・`↓`（統合先にあって無い）・`dirty`・最後の commit からの経過、保留（旧形式の退避の件数）・子・隔離 worker・モード。44 桁の 1 行で、状態の側を欠かさず名前の側を先に切る。集めるのは読み取りの git だけ（`runGit`。hook・外部 diff を無効にし、`status` は index を更新させない）。リポジトリの設定に外部 filter（clean・smudge・process）があるときは、`status` を実行せず `dirty` を出さない。bg ジョブは見られないので行を出さない。承認・操作の入口は持たない） | [CHG-0056](../change/0056-orchestrator.md#10-実施計画) |
| `/worktrees` | 隔離の worktree の掃除・回収のやり直し（利用者専用） | [pi の子エージェント](guard/pi-subagents.md#worktree-隔離の場所と承認) |
| フッター | 動いている子の数・経過時間（3 件以下は名前つき） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |

## 計画と自走

計画は利用者と対話し、実装は止めずに自走して最後に報告する。統合前の変更は元に戻せる。ただし、作業領域（共有 `.git` は書き込める）・試験や hook の実行・ホストへの影響は、統合の前に起こりうる。ガードは「うっかり防止」であり、敵対的な迂回への防御を保証しない（[保証の範囲](guard/index.md#目的と保証の範囲)）。見込みの実装は、この範囲の保証のもとで進める。コードは変えない取り決め（規約）で、全体の指示はグローバル指示（`agent-instructions.md`）にある。

| 段 | 内容 |
| --- | --- |
| ① 相談（計画） | 利用者と対話して決める。`/plan`（書き込み・実行を外した読み取り専用）が使える |
| ② 実行の契約 | 計画の終わりに、目的・守る条件・決めた分岐と既定・止まる条件・確認トピックを `.tmp/keep/plan/<話題>.md` に固定。計画へ戻ったら更新 |
| ③ 自走 | 契約に沿って、実装・検査・取り込み準備（commit・サマリー投稿・全件検査）まで止めずに進め、最後に報告。統合は利用者の押下 |

自走中に止まって `ask` で聞くのは、(a) 元に戻せない操作・権限を広げる変更、(b) 複数 feature に波及し手戻りが大きい分岐、(c) 要件の矛盾、(d) 費用の大きい実測、(e) 確認トピックに当たるもの、だけ。それ以外は推奨案で進め、契約末尾の「決定ログ」に残して最終報告で一覧にする。聞きたいことがあっても進められる作業があるなら、todo の blocked に「決定待ち（既定: X）」として残し、既定で進める。`ask` はターンを止めるので、全体が止まるときだけ使う。

利用者が確認したいときの手段:

| 手段 | 内容 |
| --- | --- |
| その場で一言 | 「ここは確認」「聞いて」。親は止まって選択肢つきで `ask` |
| 契約の確認トピック | 例: 「権限に関わる変更は必ず聞く」。契約に登録しておく |
| 親が止まる条件 | 上の (a)〜(d) に当たると、親が自分で止まる |

契約の雛形と決定ログの書き方: [plan-contract.md](../../.agents/skills/feature-orchestration/references/plan-contract.md)。

## 統合用の枝（bundle）

複数の feature を 1 回の全件検査・1 回の「統合する」で取り込むため、統合用の枝 `feature/bundle-N`（worktree `.tmp/worktrees/bundle-N`）を `scripts/bundle.py` で作る。旧称は train（merge train の比喩）。旧名の枝 `feature/train-N` は bundle の枝として扱わない。`git flow` は呼ばない（`.gitflow` の接頭辞と基点を読む）。

| コマンド | 内容 |
| --- | --- |
| `python3 scripts/bundle.py start [--name bundle-N] <feature>...` | develop の最新から枝と worktree を作り、指定順に `git merge` する。`a` でも `feature/a` でもよい。名前を省くと空き番号を選ぶ |
| `continue [--name bundle-N]` | 衝突が解消され `git add -A` 済みならコミットし、残りの枝を続ける |
| `add [--name bundle-N] <feature>...` | 既存の bundle に枝を足して取り込む（手で取り込み済みの枝は飛ばす）。**シェルから `git merge` を打つと、対象が develop でなくても保護ブランチへの統合と同じ確認が出る**ので、bundle へ枝を足すときはこれを使う |
| `verify [--name bundle-N]` | その worktree で `mise run verify:all` を回し、件数と終了コードを要約する（`BUNDLE_VERIFY_CMD` で差し替え可） |
| `status` / `summary` | 取り込み済み・未取り込み・衝突中の一覧 / PR 要約の材料（枝ごとのコミット数・変更ファイル数） |

各枝の前に、「存在する」「develop に未統合」「worktree に生きた pid の owner lock（`locked owner=<kind> id=<id> pid=<pid> started=<秒>`）が無い」を確かめ、満たさなければ何も作らず止まる。

**終了コード**: 0 成功 / 1 verify 失敗 / 2 使い方・前提違反・git の失敗 / 3 衝突で停止。

**衝突の扱い**: 衝突したら、そこで止めて衝突ファイルの一覧を出す（終了コード 3）。**自明に見える衝突でもスクリプトは直さない**。設計上、衝突は worker が直す（取り違えると片方の変更を黙って捨てるため、解消は意味を読める役が責任を持つ）。worker が worktree で解消し、`git add -A` したあと `continue` を呼ぶ。マーカーが残っていると `continue` は拒否する。

AI のガードが `git merge` を直接は通さない場合に備え、`python3 scripts/bundle.py ...` の形で呼ぶ想定。ガード側で通るかは未確認。Windows は未検証。

## 9. 未実装・保留（案件）

仕様ではなく、決まっていることの置き場。着手するときは、案件の記述が正本になる。

| 項目 | 状態 | 案件 |
| --- | --- | --- |
| 親の道具を絞る（orchestrator ロール） | **実装済み**（`/orchestrate`）。段 3・4・5・7 は未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 6 |
| スキルの工程化（親の判断 → 子の成果物 → 次へ進む条件） | 未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 3・5 |
| 待ち合わせ・DAG・予算 | 未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 7、[調査 O1](../research/agents/pi-orchestrator-survey.md) |
| 子の質問・承認の中継 | 未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 4 |
| 子へ feature のコミットを許す（`guarded_action` を子へ） | 見送り（親の手数が許容できないと分かるまで作らない） | [並列実装の運用](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| 素の `pi` での子の隔離 | 保留 | [CHG-0029](../change/0029-worktree-isolation.md) |
| `pis` での gitflow の片付けと `abort` | 撤去（AI の `git flow` 操作をやめたため。CHG-0050） | [CHG-0050](../change/0050-slim-guarded-action.md) |
| 保留したコミットの取り込み（`/pending` から） | 未着手 | [CHG-0046](../change/0046-guarded-action-timeout.md) 段 4 |
| `docker rm` などが、ask 既定の役割（親・`worker`）の bypass で通る | 範囲外として残す | [判定器](guard/pi-decide.md#既定が-deny-の役割の-ask) |

## リポジトリのプロファイルの検出（`orch.py profile`）

並列実装の道具を、リポジトリの形（git-flow-next・git-flow AVH・素の git）を検出して動かすための土台。`home/dot_claude/skills/feature-orchestration/scripts/` の `orchlib.py`（検出）と `orch.py`（入口。いまは `profile` だけ）。

- **出力**（`--json`、`v:1`）: `flow`・`integration`（`branch`/`ref`）・`trunk`・`topic`（`prefixes`/`new_prefix`/`start_point`/`also_list`）・`worktrees`（`template`/`base_abs`/`inside_repo`/`ignored`。`{name}` は接頭辞を除いた名前）・`verify`・`overlay`・`gate_checks`・`repo`・`sources`（項目ごとの出所）・`ambiguous`・`warnings`。
- **優先順**（項目ごとに独立）: CLI（`--integration`・`--prefix`・`--worktrees-dir`）→ `git config --local orchestration.*` → `.gitflow` の `[orchestration]` 節と `.agents/config/orchestration.gitconfig`（同順位。食い違うと曖昧）→ git-flow-next の型設定（local、無ければ `.gitflow`。主トピック型 `feature` の `parent`・`prefix`・`startpoint`、`worktreePath` の `{{ branchName }}` は `{name}`）→ AVH（`gitflow.branch.develop`・`gitflow.prefix.feature`）→ 形の検出（幹の枝の有無・枝名の分布）→ 既定（候補が 1 つのときだけ）。
- **global/system の設定は読まない**。global にだけ `gitflow.*` / `orchestration.*` があると warning。
- **曖昧**（同順位の候補が複数、local に next と AVH が両方、`feature/` 系の名前空間が複数）は推測せず、`ambiguous` に候補と設定例を入れて**終了コード 4**。必要な項目が曖昧なコマンドだけが止まる（`orchlib.blocking_ambiguities`）。
- **終了コード**: 0=確定、2=使い方・前提違反（bare・コミット無し・git リポジトリでない）、4=曖昧。
- **設定の鍵**（git-config 構文）: `integration`・`topicPrefix`（複数可）・`newPrefix`・`alsoList`・`worktreeDir`・`verifyCmd`・`overlay`・`gateChecks`。
- 試験は `test/test_orch_profile.py`（形 a〜l と、この repo の `.gitflow`）。既存スクリプトの移設・profile 経由化・`start`/`list`・SKILL.md は後の段（S2 以降。計画: `.tmp/keep/plan/orchestration-general.md`）。
