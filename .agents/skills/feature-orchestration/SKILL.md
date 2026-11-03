---
name: feature-orchestration
description: "feature を起票して worker に実装を切り出し、成果を確かめて develop へ取り込むまでの手順 (起票・依頼文・取り込み前の検査・登録漏れ・コミット・PR の要約と利用者の統合の押下)。「worker に任せて」「並列で進めて」「feature を切って実装して」「worker の結果を取り込んで」で使う。調査・レビュー・計画だけの委譲 (explore / review / plan) や、単発の小さな変更には使わない。"
---

# feature の並列実装 (起票 → worker → 確認 → 取り込み)

このリポジトリの親エージェントが、独立した実装を worker に切り出して `develop` へ取り込むまでの工程。
**仕様と依頼文の雛形の正本**は [並列実装の運用](../../../docs/spec/guard/pi-subagents.md#並列実装の運用隔離なしの-worktree)。
ここは、その工程の**チェックリストと、踏みやすい落とし穴**だけを持つ。

## 使う条件

- 担当ファイルを分けられる実装が 2 件以上ある、または 1 件でも設計が固まっていて指示を完全に書ける。
- 設計判断が連続する作業・利用者と会話しながら詰める設計は、親で行う（worker に任せない）。
- 調査・レビュー・計画は feature を切らず、読み取り専用の子（`explore` / `review` / `plan`）に任せる。

- 会話（pi のセッション）を複数並行しているときは、取り込み（工程 8 の、利用者の「統合する」の押下）の窓口を 1 つにし、ほかの会話は
  コミットまでで止める（[規則](../../../docs/spec/guard/pi-subagents.md#複数の会話を並行して使う運用)）。

## 工程

1. **分ける**: 1 worktree = 1 feature = 1 worker。担当ファイルが重ならない単位にする。書き込む worker は 3〜5 体まで
   （読み取り専用の子とは別枠。生きている子は最大 4）。**共有されやすいファイルは 1 人か親だけが触る**:
   `common.toml.tmpl`・golden・docs の索引・`index.ts`・`actions.ts`・`scripts/verify.py`・試験用のコピー一覧。
   依存があるときは、案件の「実施計画」表の「前提」列（計画）と todo の note（状態）に置く。
2. **起票**: `git flow feature start <名前> --worktree --no-fetch`（名前は小文字・数字・`.`・`_`・`-`）。
   worktree は `.tmp/worktrees/<名前>/`。
3. **依頼**: `guarded_task`（`agent: "worker"`、`background: true`、`todo` に項目 ID）。依頼文は雛形に従い、次を必ず入れる。
   - worktree の絶対パスと、**担当ファイル（これだけ編集）** と読み取りだけのファイル。同じ worktree に別の worker がいるなら、そのファイル。
   - 優先順位つきの「作ること」、「変えてはいけないもの」、合格条件（実行するコマンド）。
   - **共通の約束は [references/worker-common.md](references/worker-common.md) を読ませる**（ツールの制約・報告形式・時間制限を毎回書かない）。
   - 権限や境界を**緩める**変更は、「反例を先に試験として足し、現状で落ちることを確かめてから直す」と書き、実装の前後で `review` に見せる。
4. **確認**（完了通知のたびに。子は「通った」を実行できないことがある）:
   - 報告の主張を、パスと行・コマンドの出力で確かめる。担当外のファイルが変わっていないか `git diff --stat`。
   - `python3 scripts/parallel_check.py --owned <名前>=<glob>,…`（本体の変更・範囲の外・重複）。終了コード 1 なら、原因が分かるまでコミットしない。
   - **`sleep 4` のあとで** `git add -A` し、`git diff --cached --numstat` で行数の急減（空のファイル）がないか見る。
5. **登録の漏れを先に潰す**（全件検査を無駄にしない）:
   - 新しい試験ファイルは `scripts/verify.py` の `_PI_TESTS` へ（**ほかの feature と隣り合わない位置に**足す。同じ位置だと取り込みで衝突する）。`uv run --with pytest --with pyyaml --no-project pytest test/test_verify.py -q`（2 秒）で確かめる。
   - `index.ts` から（間接にも）import される新しい `.ts` は、試験用のコピー一覧 3 か所
     （`test/agents/test_pi_harness.py`・`test/agents/test_pi_commit_confirm.py`・`scripts/pi-harness-spike/compact-real.py`）へ。
   - docs を触ったら `lint_docs.py` と `check_refs.py`。docs に日付を書くときは `date '+%F %H:%M'` で確かめる（0 時をまたぐ）。
6. **全件検査**: `bg_run` で `mise run verify:all` を **1 本ずつ**（完了通知を待つ。`sleep` や `bg_log` の連打はしない）。
   互いに独立した小さな feature を続けて取り込むときは、各 feature は対象の試験・変異試験・関門までにし、全件検査は取り込み後の develop で **バッチに 1 回**でよい（落ちたら追加の feature で直す。部品ごとに 6 分前後を重ねない）。
7. **コミット**: `guarded_action` の `git_commit`（`dir` に worktree。
   **`message` は 1200 字以下**。feature の linked worktree なら確認なし）。bash の `git commit` は拒否される。
8. **PR の要約と統合**: `guarded_pr_summary` で、PR に要約（`mergeMessage` の下書き。develop のコミットメッセージになる）を出す。
   **統合は、利用者が PR ビューアの「統合する」を押す**（アプリが merge commit で同期統合する）。AI は `git flow feature finish`・`git merge` を実行しない
   （素の pi で実行すると、bypass でも必須確認になる。[CHG-0053](../../../docs/change/0053-worktree-integration-gate.md)）。
   押されたあとの衝突・復旧は、ビューアの表示と [PR ビューア](../../../docs/spec/pr-viewer.md) の手順に従う。
   docs の更新表や `_PI_TESTS` の同じ位置の衝突は、両方の行を残す。
9. **後始末の確認**: `git log --oneline -3`・`git worktree list`・`git status --short`。todo を done にする。
10. **押下待ちで止まらない**: PR の要約を出したら（統合は、あとで利用者が「統合する」を押す）、待たずに他の feature・docs・検査へ進む。止まるのは、利用者の方針決定がないと進められる作業が無いときだけ。実機や操作の確認待ちも同じ（確認が要る項目を記録して次へ）。

## 積み重ね (依存する feature)

B が、まだ develop に入っていない A の変更を要るとき、A の承認を待たずに B を進められる。**依存は宣言しない**（git の祖先関係から導く。宣言は古くなる）。正本は [積み重ね](../../../docs/spec/guard/pi-subagents.md#積み重ね依存する-feature)。

1. **起票**: A をコミットしたあと、`git flow feature start <B> feature/<A> --worktree --no-fetch`（B は A の先頭から始まる）。
2. **A がさらに進んだら**: `cd <B の worktree の絶対パス> && git merge feature/<A> -m "merge: feature/<A> を取り込む"`（`&&`・パイプなし）。**マージするのは親だけ**（worker は git を書けない）。**衝突したら、止めて利用者に報告する**（LLM に直させない）。
3. **関門**: `feature_gate.py check <B> --owned <B の glob>`。A の変更は「継承したパス」として引かれ（出力に `depends on: feature/<A>`）、担当外・重複を誤検知しない。既知の制限: B が A のファイルをコミットで編集しても検知されない。
4. **統合は、A・B とも利用者の押下**。統合は merge commit なので、A を先に統合すると B から見て A は祖先になり、順序の問題は起きない（squash では B が衝突した。[CHG-0062](../../../docs/change/0062-pr-hub-simplify.md) の実験 X1 で確かめ、合格）。B を先に押すと A の変更も一緒に入り、あとの A は「統合しても内容が変わらない」状態になる（A のブランチは手で片付ける）。
5. **全件検査**は B の worktree でも回せる（A の変更を含む。A が壊れていれば B も落ちる）。

## 落とし穴

- **整形 hook が書き込み直後にファイルを書き換える**。すぐ `git add` すると空のファイルをステージする（工程 4 の `sleep 4` と `--numstat`）。
- **worker の時間制限は約 15 分**。範囲を絞り、優先順位をつける。報告なしで打ち切られても成果物が揃っていることがある（実物で確かめる）。
- **feature への `develop` の取り込み**（と、feature 同士のマージ）は、`cd <絶対パス> && git merge develop`（`&&`・直接の git 1 コマンド・パイプなし）なら、**統合の必須確認にはならない**（判定器の結果のまま。通常モードでは通常の確認、bypass では確認なし）。
  相対パス・`;`・パイプ・`2>&1`・`env` や `sh -c` で包む形は、必須確認になる（[CHG-0053](../../../docs/change/0053-worktree-integration-gate.md)）。
- **AI は保護ブランチへ統合しない**（統合は利用者の押下）。`finish`・`merge`・`update-ref` などを素の pi で実行すると、`bypass` でも必須確認になる。
- `git_commit` の `message` が 1200 字を超えると拒否される。短い版でコミットし、全文は `guarded_pr_summary` の要約（`mergeMessage`）に置く。
- **全件検査は 1 本ずつ回す**（worker の試験が走っている間も重ねない）。重なると負荷が上がり（16 コアで負荷平均 18 超）、pi を実際に起動する時間依存の試験
  （`test_pi_harness.py` の `FAUX_DELAY_MS` を使うもの）が落ちる。落ちたら、負荷が下がってから**単独で再実行して確かめる**（再実行で通るなら負荷が原因）。
- 子の報告が「確認していない」と書いたことは、親が確かめるまで未確認として扱う。
