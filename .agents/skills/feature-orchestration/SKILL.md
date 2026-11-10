---
name: feature-orchestration
description: "feature を起票して worker に実装を切り出し、成果を確かめて develop へ取り込むまでの手順 (起票・依頼文・取り込み前の検査・登録漏れ・コミット・利用者の指示での統合)。「worker に任せて」「並列で進めて」「feature を切って実装して」「worker の結果を取り込んで」で使う。調査・レビュー・計画だけの委譲 (scout / reviewer / oracle) や、単発の小さな変更には使わない。"
---

# feature の並列実装 (起票 → worker → 確認 → 取り込み)

このリポジトリの親エージェントが、独立した実装を worker に切り出して `develop` へ取り込むまでの工程。
**既定は stock の pi（拡張 `pi-subagents` の `subagent` ツール）の運用**（[ADR-0030](../../../docs/adr/0030-freeze-agent-stack-return-to-stock-pi.md)）。
ここは、その工程の**チェックリストと、踏みやすい落とし穴**だけを持つ。

- 子の起動の詳細（N と F・同梱の agent・Ralph ループ）: [references/pi-subagents.md](references/pi-subagents.md)。**既定は F**（親が feature worktree を作り、`cwd` で渡す）。
- 契約（worker への依頼文）の雛形: [references/worker-contract.md](references/worker-contract.md)。計画から自走へ移るときの実行の契約: [references/plan-contract.md](references/plan-contract.md)。
- 並列度の運用: [references/parallel-ops.md](references/parallel-ops.md)（`guarded_*` 前提。stock では `subagent` に読み替える）。
- 凍結した custom（`pis`。`guarded_*`・`wt_owner.py`・`bundle.py`・PR ビューア）の運用: [references/custom-harness.md](references/custom-harness.md)。旧 `AGENTS.md` の運用規則: [references/repo-rules.md](references/repo-rules.md)。

## 使う条件

- 担当ファイルを分けられる実装が 2 件以上ある、または 1 件でも設計が固まっていて指示を完全に書ける。
- 設計判断が連続する作業・利用者と会話しながら詰める設計は、親で行う（worker に任せない）。
- 調査・レビュー・計画は feature を切らず、読み取り専用の子（`scout` / `reviewer` / `oracle`）に任せる。
- 会話（pi のセッション）を複数並行しているときは、統合（工程 8）の窓口を 1 つにし、ほかの会話はコミットまでで止める。

## stock の事実（確かめ済み）

- 子の起動は `subagent({ agent, task, cwd, async: true, options: { timeoutMs, checkpointBeforeDeadlineMs } })`。同梱の agent は worker・scout・reviewer（読み取り専用・shell なし）・evidence-auditor・researcher・oracle・delegate など。
- 前景の子には権限の確認機構が載らないので、**`async: true`（背景）で起動する**。完了は通知で届き、アイドルの親が自動で再開する（`sleep` やポーリングは要らない）。同時に動かせる子は **4 つまで**。
- コミット: bash の `git commit` は確認なしで通る（feature の worktree でも同じ）。`git push*`・`sudo *` は拒否される。`git worktree remove`・`git config`・`gh` の変更系・`chezmoi apply` は強制の確認（無人では 5 分で拒否される）。
- 破壊的な git（`git reset --hard`・`git checkout -- <path>`・`git restore`・`git clean -f`・`git branch -D`）は、cc-safety-net が拒否する。
- `python3 ~/.agents/skills/…/*.py` は確認なしで実行できる。`uv run …`・`node …` は向きを証明できないので、作業ツリーの外のパスでは確認になりうる。

## 工程

1. **分ける**: 1 worktree = 1 feature = 1 worker（同じ worktree に複数の書き手を置かない）。担当ファイルが重ならない単位にする。
   **共有されやすいファイルは 1 人か親だけが触る**: `common.toml.tmpl`・golden・docs の索引・`scripts/verify.py`。依存があるときは、契約の「前提」に書く。
2. **起票**: `git flow feature start <名前> --worktree --no-fetch`（名前は小文字・数字・`.`・`_`・`-`）。worktree は `.tmp/worktrees/<名前>/`。
3. **依頼**: **worktree を作ってから**、契約を `.tmp/keep/plan/<名前>.md`（worktree の中）に書く（同時に書くと worktree の作成が失敗する）。続けて
   `subagent({ agent: "worker", cwd: "<worktree の絶対パス>", async: true, options: { timeoutMs, checkpointBeforeDeadlineMs }, task: "契約 … を読み、…" })`。
   大きな JSON・長い文章を `task` に直接入れず、パスを渡す。契約に入れるもの（担当ファイル・変えてはいけないもの・合格条件のコマンド・報告形式）は [worker-contract.md](references/worker-contract.md)。
   権限や境界を**緩める**変更は、「反例を先に試験として足し、現状で落ちることを確かめてから直す」と書き、実装の前後で `reviewer` に見せる。
4. **確認**: 子の完了通知で再開する。報告を鵜呑みにせず、**親が同じコマンドを自分で再実行して確かめる**。担当外のファイルが変わっていないか `git diff --stat`。
   `git add -A` のあと `git diff --cached --numstat` で行数の急減（整形 hook が空にしたファイル）がないか見る。
5. **登録の漏れを先に潰す**（全件検査を無駄にしない。対象が `scripts/` に実在するか確かめてから書く）:
   - 新しい試験ファイルは `scripts/verify.py` の `_PI_TESTS`（または該当の `Rule`）へ。**ほかの feature と隣り合わない位置に**足す（同じ位置だと取り込みで衝突する）。
     `uv run --with pytest --with pyyaml --no-project pytest test/test_verify.py -q`（2 秒）で確かめる。
   - docs を触ったら `lint_docs.py` と `check_refs.py`（`home/dot_agents/skills/sdd-docs/scripts/`）。docs に日付を書くときは `date '+%F %H:%M'` で確かめる。
6. **全件検査**: `bg_run` で `mise run verify:all` を **1 本ずつ**（完了通知を待つ。`sleep` や `bg_log` の連打はしない）。worker の試験が走っている間も重ねない。
7. **コミット**: bash の `git commit`（`cd <worktree の絶対パス> && git commit …`。件名＋本文 1〜3 行の Conventional Commits）。
8. **統合**: **利用者が「統合して」と言ったときだけ**、`git flow feature finish <名前> --no-ff --no-squash -M "<メッセージ>" --keepremote --no-fetch --no-push --notag` を実行する（push はしない）。
   指示が無いときは、コミットと要約（統合メッセージの案・確かめた内容・未確認）までで止める。`finish` で確認が出るかは未確認（出たら利用者の承認を待つ）。
   docs の更新表や `_PI_TESTS` の同じ位置の衝突は、両方の行を残す。
9. **後始末の確認**: `git log --oneline -3`・`git worktree list`・`git status --short`。残った worktree を `git worktree remove` で消すときは、強制の確認が出る（利用者の承認を待つ）。
10. **止まらずに次へ**: コミットと要約を出したら、統合の指示を待たずに、他の feature・docs・検査へ進む。止まるのは、利用者の方針決定がないと進められる作業が無いときだけ。

## 積み重ね (依存する feature)

B が、まだ develop に入っていない A の変更を要るとき、A の統合を待たずに B を進められる。**依存は宣言しない**（git の祖先関係から導く。宣言は古くなる）。

1. **起票**: A をコミットしたあと、`git flow feature start <B> feature/<A> --worktree --no-fetch`（B は A の先頭から始まる）。
2. **A がさらに進んだら**: `cd <B の worktree の絶対パス> && git merge feature/<A> -m "merge: feature/<A> を取り込む"`。B の worker が動いていないときに、**親が行う**。**衝突したら、止めて利用者に報告する**（子に直させない）。
3. **統合は、利用者の指示で A → B の順**。統合は merge commit（`--no-ff --no-squash`）なので、A を先に統合すると B から見て A は祖先になり、順序の問題は起きない。B を先に統合すると A の変更も一緒に入る。
4. **全件検査**は B の worktree でも回せる（A の変更を含む。A が壊れていれば B も落ちる）。

関門（`feature_gate.py`）・複数 feature をまとめて取り込む（`bundle.py`）は custom の道具。stock での動作は未確認。[custom-harness.md](references/custom-harness.md)。

## 落とし穴

- **整形 hook が書き込み直後にファイルを書き換える**。すぐ `git add` すると空のファイルをステージする。`git add -A` のあと `git diff --cached --numstat` で見る（必要なら少し待ってから）。
- **全件検査は 1 本ずつ回す**。重なると負荷が上がり、時間に依存する試験が落ちる。落ちたら、負荷が下がってから**単独で再実行して確かめる**（再実行で通るなら負荷が原因）。
- **feature への `develop` の取り込み**（と、feature 同士のマージ）は、`cd <絶対パス> && git merge develop`（`&&`・直接の git 1 コマンド・パイプなし・相対パスにしない）の形で行う。
  stock での確認の有無は未確認。
- **子の自己申告は当てにならない**。親が、同じコマンドを自分で再実行して確かめる。子の報告が「確認していない」と書いたことは、親が確かめるまで未確認として扱う。
- **子の `stop` は、子のサブプロセスを止めない**。子に長く動くコマンドを実行させるときは、契約で `timeout` を付けさせる。
- **確認が出たかどうかは、子の自己申告でなく審査ログが正**: `~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl`。子の確認は、親の画面へ転送される。
- **AI は、利用者の指示が無いのに保護ブランチへ統合しない**（`develop`・`main` に直接コミットもしない）。`finish`・`merge` は、利用者が明示的に指示したときだけ。
- 凍結した custom の落とし穴（`git_commit` の 1200 字の上限・時間制限など）は [custom-harness.md](references/custom-harness.md)。
