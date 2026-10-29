# オーケストレーションと並列作業の機能一覧

親エージェントが、子エージェント（`guarded_task`）と feature ブランチを使って、作業を分けて並列に進めるための機能を、カテゴリ別にまとめた一覧。**今どうなっているか**だけを書き、仕様の細部は各行の正本に任せる。
未実装・保留の項目は、最後の表に案件へのリンクつきで置く。

**状態の凡例**: 実装済（試験あり）/ 試作（実機の確認が一部）/ 運用（手順として使う。強制はしない）/ 保留（案件で止めている）。実機の確認が済んでいない範囲は、各行に書く。

`pi` の機能全体の中の位置は [機能の地図](pi-features.md)。

対象は、フルガードを付けた `pi`（Unix）。Windows の子エージェント・素の `pi` での違いは [pi の子エージェント](guard/pi-subagents.md#windows-の子エージェント)。

## 1. 親子の分担と委譲の方針

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 親と子の分担 | 運用 | 親は対話・判断・委譲・承認・ToDo の管理。調査・計画・実装・検証は子へ（全体の指示は `agent-instructions.md`。親の文脈を重い読み物で占めない） | [CHG-0045](../change/0045-orchestrator-parent.md) |
| 子が止まらない条件 | 実装済（判定器の決定表で確認。実際の子の RPC 起動での再確認は未） | 子が確認なしで動けるのは、親の bypass を継ぐか、証明済みの境界（`pis`）の内側のとき。`mustConfirm` は常に確認 | [CHG-0045](../change/0045-orchestrator-parent.md)、[判定器](guard/pi-decide.md) |
| `/fleet` | 実装済 | 依頼を、並列に動かせる作業に分け、`worker` を 1 回の応答に並べて起動させる | [fleet](guard/pi-extensions.md#fleet) |
| 委譲の統計（`delegate-nudge`） | 試作 | 読み取り系ツールの回数と、子の起動数だけを、セッションに記録する（通知しない。子では動かない） | [自作の拡張](guard/pi-extensions.md#自作の拡張-todo--plan--btw) |

## 2. 子の起動と実行の制御（`guarded_task`）

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 単発の起動 | 実装済 | `{agent, task}`。完了まで待つ。新しい子（`explore`・`review`・`worker`）は ToDo の項目 ID（`todo`）が必須 | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| バックグラウンド | 実装済 | `background: true`。ID をすぐ返し、完了は通知で届いてターンが再開する | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| 並列 | 実装済 | `tasks: [...]`（最大 12 件）。同時に生かす子は 4 まで。超えた分は空きを待つ | 同上 |
| 保持と追加依頼（job） | 実装済 | `keep: true` で残し、`{jobId, task}` で履歴を保って続ける。`close` で止める | [job](guard/pi-subagents.md#子を保持して追加依頼するjob) |
| 状態・steer・abort | 実装済 | `status`・`list`・`steer`・`abort`（今の往復だけ止める） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| 往復の上限 | 実装済 | 役割ごとの `timeout_minutes`（既定 15 分、`plan` は 30 分）。上限の 80% で「まとめに入れ」を送る | 同上 |
| モデルと effort | 実装済（Bedrock の実機確認は未） | カタログから選ぶ。**利用者が指示したときだけ指定する**。結果に使った値を必ず出す | [CHG-0043](../change/0043-model-catalog.md)、[モデルの割り当て](agent-model-assignment.md#子エージェントのモデルのカタログ) |
| 子の質問・親への通信 | 未対応 | 子から親への通信は無い（結果の返却と完了通知だけ） | [job](guard/pi-subagents.md#子を保持して追加依頼するjob) |

## 3. 子の役割と権限

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| 役割 `explore` / `review` | 実装済 | 読み取り専用（`wc` と読み取りの git）。`review` は別系統のモデル（`second_opinion`） | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| 役割 `plan` | 実装済（`/plan` での深い計画への切替は未） | bash なしの読み取り専用。深く考える階層。大きな変更の計画を作る | [CHG-0044](../change/0044-plan-agent.md) |
| 役割 `commit` | 実装済 | コミットの計画（対象ファイルとメッセージ）を返すだけ。ステージもコミットもしない | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| 役割 `worker` | 実装済 | 実装役。`git add`/`commit`/`checkout`/`reset`/`stash` と `git flow` は deny。`git status`・`git diff` は通常は ask（bypass か境界で通る。許可を足す案は保留） | [pi の子エージェント](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| bypass の継承 | 実装済 | 役割ごとの `inherit_bypass`。`/bypass` の切替で、動いている子は止まる | [pi の子エージェント](guard/pi-subagents.md#子エージェント) |
| 既定が deny の役割の扱い | 実装済 | `explorer`・`reader`・`committer` は、`[bash] ask` に当たる操作も、bypass で通さず deny にする | [判定器](guard/pi-decide.md#既定が-deny-の役割の-ask) |
| 計画モード中の子の制限 | 実装済 | `/plan` の間は、書き込む役割の子の起動・追加依頼・steer を拒否する | [pi の子エージェント](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| 入れ子 | しない | 子から子は作れない（指揮役の工程は親に残る） | [CHG-0045](../change/0045-orchestrator-parent.md) |

## 4. 作業場所の分離とブランチ（gitflow）

| 機能 | 状態 | 内容 | 正本 |
| --- | --- | --- | --- |
| ブランチモデル | 運用 | main / develop / feature（squash。release・hotfix なし）。リポジトリごとに `.gitflow` で決める。`main` への取り込みと push は利用者 | [CHG-0047](../change/0047-gitflow.md)、[開発](development.md#ブランチモデルgitflow-lite) |
| `gitflow_feature_start` | 実装済・実機確認済 | `develop` から feature と worktree（`.tmp/worktrees/<名前>/`）を作る。確認なし | [guarded_action](guard/pi-extensions.md#guarded_action承認つきの外部操作) |
| `gitflow_feature_commit` | 実装済・実機確認済 | feature の worktree で `git add -A` して commit。確認なし。保護対象のパスは止まる | 同上 |
| `gitflow_feature_finish` | 実装済・実機確認済 | `develop` へ squash。確認あり。リモートに触れない。本体にステージ済みの変更があれば拒否 | 同上 |
| 安全な構成の検査 | 実装済 | 実効設定が許可リストに合うときだけ動く（push の設定・hook・原点の変更などは拒否） | [CHG-0047](../change/0047-gitflow.md#許可の形の設計の修正review-の反映上の案に優先する) |
| develop / main の直接編集・コミットの拒否 | 実装済（実機は未検証） | gitflow-lite のリポジトリで、`edit` / `write` と `git_commit` を拒否。bash 内の書き込み・直接のブランチ作成は保証外（段 1c で deny 予定）。利用者の逃がし口は未実装 | [CHG-0049](../change/0049-gitflow-convention-guard.md)、[仕様](guard/pi-gitflow-guard.md) |
| `git flow` の直接実行 | 実装済 | implementer と worker の bash では deny（固定引数の操作だけを使わせる） | 同上 |
| 隔離なしの worktree | 運用 | 親が feature を切り、子には worktree の中だけで作業させる。強制の囲いではない | [並列実装の運用](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| 子の隔離（`isolation: "worktree"`） | 保留（素の `pi` では認証のロックの書き込みが拒否される） | Landlock で書き込みを狭める。`pis` では認証の写しが既にある | [CHG-0029](../change/0029-worktree-isolation.md) |

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
| ToDo の連動 | 実装済 | 子が完了すると、`todo` の項目を `done` にして結果を `note` へ書く | 同上 |
| セッションごとの一時置き場 | 実装済 | `$TMPDIR` は `.tmp/s/<ID>/`。セッションの終わりに消える。残すものは `.tmp/keep/` 以下 | [一時置き場](guard/pi-extensions.md#セッションごとの一時置き場tmpsid) |
| 圧縮に備えた復帰の記録 | 実装済 | `checkpoint`（圧縮の前後の記録） | [圧縮](guard/pi-extensions.md#圧縮旧-checkpoint) |

## 8. 利用者向けのコマンドと表示

| 機能 | 内容 | 正本 |
| --- | --- | --- |
| `/agents`・`/agent <名前> <依頼>` | 子の一覧と、子の直接の起動（モデルは呼べない） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |
| `/bypass` | ask を確認なしで通す。切替で、動いている子は止まる | [pi のガード](guard/pi-guard.md) |
| `/plan` | 計画モード（書き込む役割の子を止める） | [CHG-0044](../change/0044-plan-agent.md) |
| `/pending` | 保留したコミットの一覧・表示・破棄（利用者専用） | [CHG-0046](../change/0046-guarded-action-timeout.md) |
| `/worktrees` | 隔離の worktree の掃除・回収のやり直し（利用者専用） | [pi の子エージェント](guard/pi-subagents.md#worktree-隔離の場所と承認) |
| フッター | 動いている子の数・経過時間（3 件以下は名前つき） | [子の操作](guard/pi-subagents.md#子の操作-バックグラウンド状態steer並列モデルtodo) |

## 9. 未実装・保留（案件）

仕様ではなく、決まっていることの置き場。着手するときは、案件の記述が正本になる。

| 項目 | 状態 | 案件 |
| --- | --- | --- |
| 親の道具を絞る（orchestrator ロール） | 未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 6 |
| スキルの工程化（親の判断 → 子の成果物 → 次へ進む条件） | 未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 3・5 |
| 待ち合わせ・DAG・予算 | 未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 7、[調査 O1](../research/agents/pi-orchestrator-survey.md) |
| 子の質問・承認の中継 | 未着手 | [CHG-0045](../change/0045-orchestrator-parent.md) 段 4 |
| 子へ feature のコミットを許す（`guarded_action` を子へ） | 見送り（親の手数が許容できないと分かるまで作らない） | [並列実装の運用](guard/pi-subagents.md#並列実装の運用隔離なしの-worktree) |
| 素の `pi` での子の隔離 | 保留 | [CHG-0029](../change/0029-worktree-isolation.md) |
| `pis` での gitflow の片付けと `abort` | 後回し | [CHG-0047](../change/0047-gitflow.md) |
| 保留したコミットの取り込み（`/pending` から） | 未着手 | [CHG-0046](../change/0046-guarded-action-timeout.md) 段 4 |
| `docker rm` などが、ask 既定の役割（親・`worker`）の bypass で通る | 範囲外として残す | [判定器](guard/pi-decide.md#既定が-deny-の役割の-ask) |
