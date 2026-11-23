---
name: feature-orchestration
description: "feature を起票して worker に実装を切り出し、成果を確かめて develop へ取り込むまでの手順 (起票・依頼文・取り込み前の検査・登録漏れ・コミット・利用者の指示での統合)。「worker に任せて」「並列で進めて」「feature を切って実装して」「worker の結果を取り込んで」で使う。調査・レビュー・計画だけの委譲 (scout / reviewer / oracle) や、単発の小さな変更には使わない。"
---

# feature の並列実装 (起票 → worker → 確認 → 取り込み)

独立した実装を worker に切り出し、`develop` へ取り込むまでの手順。運用は pi の `subagent` ツール。
ここは**手順と落とし穴だけ**。事実・雛形は資料へ（どれも SKILL.md から 1 段）:
[pi-facts.md](references/pi-facts.md)（権限・子の事実）・[worker-contract.md](references/worker-contract.md)（依頼の契約）・[bundle-and-stack.md](references/bundle-and-stack.md)（束ねる・積み重ねる）・[pi-subagents.md](references/pi-subagents.md)（子の起動の詳細）・[plan-contract.md](references/plan-contract.md)（計画から自走へ移る契約）。

## 使う条件

- 担当ファイルを分けられる実装が 2 件以上ある。または 1 件でも、設計が固まっていて指示を完全に書ける。
- 設計判断が連続する作業・利用者と対話で詰める設計は、親で行う。調査・レビュー・計画は feature を切らず、読み取り専用の子（`scout` / `reviewer` / `oracle`）に任せる。
- 会話を複数並行しているときは、統合の窓口を 1 つにし、ほかはコミットまでで止める。

## 工程

1. **分ける**: 1 worktree = 1 feature = 1 worker。担当ファイルを重ねない。共有されやすいファイル（docs の索引・`scripts/verify.py`・`pi-mcp-servers.toml`）は、1 人か親だけが触る。依存があるときは、契約の「前提」に書く。
2. **起票**: `git flow feature start <名前> --worktree --no-fetch`（名前は小文字・数字・`.`・`_`・`-`）。worktree は `.tmp/worktrees/<名前>/`。まだ統合していない feature A の変更が要る B は、`git flow feature start <B> feature/<A> --worktree --no-fetch`（[積み重ね](references/bundle-and-stack.md)）。
3. **依頼**: worktree を作った**あとで**、契約を worktree の `.tmp/keep/plan/<名前>.md` に書く（同時だと作成が失敗する）。続けて `subagent({ agent: "worker", cwd: "<worktree の絶対パス>", async: true, options: { timeoutMs, checkpointBeforeDeadlineMs }, task: "契約 … を読み、…" })`。`task` は契約のパスと 1〜2 行だけ。契約の中身は [worker-contract.md](references/worker-contract.md)。権限や境界を**緩める**変更は、反例の試験を先に足して現状で落ちることを確かめてから直し、前後で `reviewer` に見せる。
4. **確認**: 完了通知で再開する。**子の自己申告は信じず、親が同じコマンドを再実行する**（子が「確認していない」と書いたことは、未確認のまま）。複数ファイル・設計・安全に関わる変更は、コミット前に `reviewer` に監査させる（差分は親が依頼文に貼る）。担当外のファイルが変わっていないか `git diff --stat`。整形 hook が書き込み直後にファイルを空にすることがあるので、`git add -A` のあと `git diff --cached --numstat` で行数の急減を見る。
5. **登録の漏れを先に潰す**: 新しい試験ファイルは `scripts/verify.py` の該当の `Rule` へ（対象が実在するか確かめてから書く。ほかの feature と隣り合わない位置。同じ位置は取り込みで衝突する）。`uv run --with pytest --with pyyaml --no-project pytest test/test_verify.py -q`（2 秒）で確かめる。docs を触ったら `lint_docs.py`・`check_refs.py`（`home/dot_agents/skills/sdd-docs/scripts/`）。日付は `date '+%F %H:%M'` で確かめる。
6. **全件検査**: `bg_run` で `mise run verify:all` を**1 本ずつ**（完了通知を待つ。worker の試験が走っている間も重ねない。重なると負荷で時間依存の試験が落ちる。落ちたら、単独で再実行して確かめる）。
7. **コミット**: `commit` スキルの形式（Conventional Commits）。
8. **統合**: **利用者が自分から「統合して」と言ったときだけ**（AI が聞いて得た返事は数えない。許可を求める質問もしない）。2 件以上は[束ねる](references/bundle-and-stack.md)。積み重ねた B を `finish` すると未統合の A も入るので、指示の範囲に A が無ければ実行しない（A → B の順）。`finish` の前に、(1) **消える全 worktree**（束ねた各 feature の worktree も）で工程 9 の①を済ませ、(2) 本体の `develop` が `origin/develop` に追い付いているか確かめる（遅れていると `finish` は拒否される。本体で `git merge --ff-only origin/develop`。分岐していて進められなければ、止めて報告する）。追い付いたら、`develop` を取り込む（単件は `git flow feature update <名前> --rebase`、束ねた枝は `git -C <絶対パス> merge develop`。merge commit を保つ）。全件検査をやり直し、`git flow feature finish <名前> --no-ff --no-squash -M "<メッセージ>" --keepremote --no-fetch --no-push --notag`（確認が出る。push はしない）。docs の更新表や `Rule` の同じ位置の衝突は、両方の行を残す。指示が無いときは、コミットと要約（メッセージ案・確かめたこと・未確認）で止め、「準備ができた」と報告する（「統合しましょうか」とは問わない）。
9. **後始末**: ① **`finish` の前**（消える全 worktree で）: `git -C <worktree の絶対パス> clean -ndX`（git の対象外のファイルの一覧）を見る。`.venv`・`__pycache__`・`.pytest_cache`・`.ruff_cache` は再生成できるので無視し、ほかを確かめる。残したい資料は、`.tmp/keep/` から本体の `.tmp/keep/<feature 名>/` へ写す。**再利用するスクリプトはコミットし、調査の結果は `docs/research/` に書く。`.tmp/<話題>/` は使い捨て**（worktree の削除は、git の対象外のファイルを警告なしで消す。[経緯](../../../docs/research/agents/worktree-lifecycle-2026-11.md)）。② **`finish` のあと**: `git log --oneline -3`・`git worktree list`・`git status --short` で `develop` に merge が入ったことを確かめ、**残った worktree だけ** `git worktree remove .tmp/worktrees/<名前>`（`--force` なし）で消す。統合済みの枝は、統合先の worktree から `git -C <その worktree> branch -d <枝>`（`-D` は拒否される。統合前の枝は消さない）。
10. **止まらずに次へ**: コミットと要約を出したら、統合の指示を待たずに、ほかの作業へ進む。止まるのは、利用者の判断が無いと進められる作業が無いときだけ。

## 落とし穴

- **worktree の中だけで完結させる**: 本体と他の worktree は作業ツリーの外で、`cd`・`ls`・`cat` に確認が出る（子は拒否される）。本体の内容は `git show develop:<パス>`、ほかの feature は `git show feature/<名前>:<パス>`。子へ渡す資料は worktree の中へ写す（[理由](../dotfiles-conventions/SKILL.md#feature-の-worktree-で作業するとき本体のパスへ出ない)）。
- **統合のあとの反映は `chezmoi apply`**（`chezmoi update` は使わない。事実は [pi-facts](references/pi-facts.md#取り込み反映)）。sudo が要るスクリプトで止まったら、`chezmoi apply --exclude=scripts` でファイルだけ反映し、スクリプトは利用者の端末に任せる。
- **`develop` の取り込み**: feature へは `git flow feature update <名前> --rebase`（枝は未公開なので rebase してよい）。feature 同士は `git -C <絶対パス> merge feature/<名前>`。`git rebase` の直接の使用は勧めない（[ADR-0039](../../../docs/adr/0039-merge-to-develop.md)）。
