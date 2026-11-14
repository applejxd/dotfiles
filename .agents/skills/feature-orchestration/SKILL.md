---
name: feature-orchestration
description: "feature を起票して worker に実装を切り出し、成果を確かめて develop へ取り込むまでの手順 (起票・依頼文・取り込み前の検査・登録漏れ・コミット・利用者の指示での統合)。「worker に任せて」「並列で進めて」「feature を切って実装して」「worker の結果を取り込んで」で使う。調査・レビュー・計画だけの委譲 (scout / reviewer / oracle) や、単発の小さな変更には使わない。"
---

# feature の並列実装 (起票 → worker → 確認 → 取り込み)

このリポジトリの親エージェントが、独立した実装を worker に切り出して `develop` へ取り込むまでの工程。
運用は pi（拡張 `pi-subagents` の `subagent` ツール）。自作の並列基盤（`guarded_*`・`bundle.py`・PR ビューア）は撤去した（ADR-0037）。
ここは、その工程の**チェックリストと、踏みやすい落とし穴**だけを持つ。

- 子の起動の詳細（N と F・同梱の agent・Ralph ループ）: [references/pi-subagents.md](references/pi-subagents.md)。**既定は F**（親が feature worktree を作り、`cwd` で渡す）。
- 契約（worker への依頼文）の雛形: [references/worker-contract.md](references/worker-contract.md)。計画から自走へ移るときの実行の契約: [references/plan-contract.md](references/plan-contract.md)。

## 使う条件

- 担当ファイルを分けられる実装が 2 件以上ある、または 1 件でも設計が固まっていて指示を完全に書ける。
- 設計判断が連続する作業・利用者と会話しながら詰める設計は、親で行う（worker に任せない）。
- 調査・レビュー・計画は feature を切らず、読み取り専用の子（`scout` / `reviewer` / `oracle`）に任せる。
- 会話（pi のセッション）を複数並行しているときは、統合（工程 8）の窓口を 1 つにし、ほかの会話はコミットまでで止める。

## pi の事実（確かめ済み）

- 子の起動は `subagent({ agent, task, cwd, async: true, options: { timeoutMs, checkpointBeforeDeadlineMs } })`。同梱の agent は worker・scout・reviewer（読み取り専用・shell なし）・evidence-auditor・researcher・oracle・delegate など。
- 前景の子には権限の確認機構が載らないので、**`async: true`（背景）で起動する**。完了は通知で届き、アイドルの親が自動で再開する（`sleep` やポーリングは要らない）。同時に動かせる子は **4 つまで**。
- コミット: bash の `git commit` は確認なしで通る（feature の worktree でも同じ）。`git push*`・`sudo *` は拒否される。`git config`・`gh` の変更系・`chezmoi apply` は強制の確認（無人では 5 分で拒否される）。`git worktree remove` は、`.tmp/worktrees/` の下で `--force`・`-f`・`..` が無いときだけ確認なし（それ以外は確認）。
- 子（`worker`・`reviewer`・`scout`・`oracle`）は、作業ツリーの外の読み書きが**確認なしで即座に拒否**される（`~/.pi/agent/agents/` の写しの `permission: external_directory: deny`。離席中に 5 分止まらない）。引き継ぎは worktree の中のファイルで行う。モデルは設定で役割ごとに決めてある（`reviewer` は実装と別系統。依頼で指定しない）。
- 上限（同時数・入れ子・起動数）は取り払ってある。並列度は CPU と、親の確認の手間で決まる。
- 破壊的な git（`git reset --hard`・`git checkout -- <path>`・`git restore`・`git clean -f`・`git branch -D`）は、cc-safety-net が拒否する。
- `python3 ~/.agents/skills/…/*.py` は確認なしで実行できる。`uv run …`・`node …` は向きを証明できないので、作業ツリーの外のパスでは確認になりうる。

## 工程

1. **分ける**: 1 worktree = 1 feature = 1 worker（同じ worktree に複数の書き手を置かない）。担当ファイルが重ならない単位にする。
   **共有されやすいファイルは 1 人か親だけが触る**: docs の索引・`scripts/verify.py`・`pi-mcp-servers.toml`。依存があるときは、契約の「前提」に書く。
2. **起票**: `git flow feature start <名前> --worktree --no-fetch`（名前は小文字・数字・`.`・`_`・`-`）。worktree は `.tmp/worktrees/<名前>/`。
3. **依頼**: **worktree を作ってから**、契約を `.tmp/keep/plan/<名前>.md`（worktree の中）に書く（同時に書くと worktree の作成が失敗する）。続けて
   `subagent({ agent: "worker", cwd: "<worktree の絶対パス>", async: true, options: { timeoutMs, checkpointBeforeDeadlineMs }, task: "契約 … を読み、…" })`。
   大きな JSON・長い文章を `task` に直接入れず、パスを渡す。契約に入れるもの（担当ファイル・変えてはいけないもの・合格条件のコマンド・報告形式）は [worker-contract.md](references/worker-contract.md)。
   権限や境界を**緩める**変更は、「反例を先に試験として足し、現状で落ちることを確かめてから直す」と書き、実装の前後で `reviewer` に見せる。
4. **確認**: 子の完了通知で再開する。報告を鵜呑みにせず、**親が同じコマンドを自分で再実行して確かめる**。
   複数ファイルにまたがる変更・設計や安全に関わる変更は、コミットの前に `reviewer`（読み取り専用で shell なし。差分は親が依頼文に貼る）に監査させる。worker の完了ごとに、並列で起動できる（利用者の常設の指示で、依頼を待たずに起動してよい）。担当外のファイルが変わっていないか `git diff --stat`。
   `git add -A` のあと `git diff --cached --numstat` で行数の急減（整形 hook が空にしたファイル）がないか見る。
5. **登録の漏れを先に潰す**（全件検査を無駄にしない。対象が `scripts/` に実在するか確かめてから書く）:
   - 新しい試験ファイルは `scripts/verify.py` の該当の `Rule`へ。**ほかの feature と隣り合わない位置に**足す（同じ位置だと取り込みで衝突する）。
     `uv run --with pytest --with pyyaml --no-project pytest test/test_verify.py -q`（2 秒）で確かめる。
   - docs を触ったら `lint_docs.py` と `check_refs.py`（`home/dot_agents/skills/sdd-docs/scripts/`）。docs に日付を書くときは `date '+%F %H:%M'` で確かめる。
6. **全件検査**: `bg_run` で `mise run verify:all` を **1 本ずつ**（完了通知を待つ。`sleep` や `bg_log` の連打はしない）。worker の試験が走っている間も重ねない。
7. **コミット**: bash の `git commit`（`cd <worktree の絶対パス> && git commit …`。件名＋本文 1〜3 行の Conventional Commits）。
8. **統合**（[ADR-0039](../../../docs/adr/0039-merge-to-develop-rebase-between-features.md)）: **利用者が自分から「統合して」と言ったときだけ**（AI が「統合してよいですか」と聞いて得た返事は数えない。許可を求める質問はしない）行う。`develop` へは **merge** で入れる（`develop` は他のホストも取り込むので、書き換えない）。
   - **1 件**: `git flow feature finish <名前> --no-ff --no-squash -M "<メッセージ>" --keepremote --no-fetch --no-push --notag`（push はしない。**ここだけ確認が出る**。規則 `git flow * finish*` が ask）。
   - **2 件以上は、束ねて 1 回の merge にする**（下の「束ねる」）。
   指示が無いときは、コミットと要約（統合メッセージの案・確かめた内容・未確認）までで止める。要約は「準備ができた」という報告で、「統合しましょうか」と問う形にしない。
   docs の更新表や `Rule` の同じ位置の衝突は、両方の行を残す。
9. **後始末の確認**: `git log --oneline -3`・`git worktree list`・`git status --short`。残った worktree は `git worktree remove .tmp/worktrees/<名前>`（`--force` なし）で消す。枝は残るので、統合済みなら統合先の worktree から `git -C <その worktree> branch -d <枝>` で消す（`-D` は拒否される。統合前の枝は消さない）。
10. **止まらずに次へ**: コミットと要約を出したら、統合の指示を待たずに、他の feature・docs・検査へ進む。止まるのは、利用者の方針決定がないと進められる作業が無いときだけ。

## 束ねる (複数の feature を 1 回の merge で統合する)

feature 同士は、**rebase で 1 本の線に積み重ねて**から、一番上だけを `finish` する。`develop` の履歴には merge commit が 1 つだけ残り、確認（ask）も検査も 1 回で済む。
**rebase してよいのは feature の枝だけ**（まだ誰も持っていない。push・`publish` した feature は、rebase しない）。`develop` と `main` は書き換えない。

1. **前提**: 束ねる feature がすべてコミット済みで、単体で検査が通っている（工程 4〜7）。順序を決める（A → B → C。担当ファイルが重なるものは、衝突しうるので前後に置く）。
2. **積み重ねる**: `git -C <B の worktree の絶対パス> rebase feature/<A>`、続けて `git -C <C の worktree の絶対パス> rebase feature/<B>`。
   `.tmp/worktrees/` の下の worktree で、`feature/*` へ載せるだけの形は確認なしで通る（判定表で確認済み。`--exec`・`-x`・`-i` を付けると確認が出る）。`cd … && git rebase …` の連結は使わない。
   **衝突したら止めて利用者に報告する**（子に直させない。docs の索引・`scripts/verify.py` の同じ位置は、両方の行を残す）。
3. **検査は一番上で 1 回**: C の worktree で `bg_run` の `mise run verify:all`（A・B の変更を含む）。落ちたら、どの feature が原因かを切り分ける。
4. **1 回だけ統合**（利用者の指示で）: `git flow feature finish <C> --no-ff --no-squash -M "merge: <A>・<B>・<C> を統合する" --keepremote --no-fetch --no-push --notag`（ここだけ確認が出る）。A・B・C のコミットが、1 つの merge commit でまとめて入る。
5. **後始末**: A・B の worktree を `git worktree remove .tmp/worktrees/<名前>`（`--force` なし）で消す。枝は C の祖先なので `develop` から到達でき、`git -C <develop の worktree> branch -d feature/<名前>` で消せる（`-D` は拒否される）。

`develop` が進んだときの追従は、feature ごとに `git flow feature update <名前> --rebase`（確認なしで通る）。積み重ねの最下段（A）だけに行えば、B・C は A の続きとして載り直す（`git -C <worktree> rebase feature/<前の段>` をもう一度）。

## 積み重ね (依存する feature)

B が、まだ develop に入っていない A の変更を要るとき、A の統合を待たずに B を進められる。**依存は宣言しない**（git の祖先関係から導く。宣言は古くなる）。

1. **起票**: A をコミットしたあと、`git flow feature start <B> feature/<A> --worktree --no-fetch`（B は A の先頭から始まる）。
2. **A がさらに進んだら**: `git -C <B の worktree の絶対パス> rebase feature/<A>`（B の worker が動いていないときに、**親が行う**。衝突したら、止めて利用者に報告する）。
3. **統合は、利用者の指示で**。A だけ先に統合してもよいし、上の「束ねる」で B をまとめて統合してもよい（B を `finish` すると A の変更も一緒に入る）。
4. **全件検査**は B の worktree でも回せる（A の変更を含む。A が壊れていれば B も落ちる）。

## 落とし穴

- **整形 hook が書き込み直後にファイルを書き換える**。すぐ `git add` すると空のファイルをステージする。`git add -A` のあと `git diff --cached --numstat` で見る（必要なら少し待ってから）。
- **全件検査は 1 本ずつ回す**。重なると負荷が上がり、時間に依存する試験が落ちる。落ちたら、負荷が下がってから**単独で再実行して確かめる**（再実行で通るなら負荷が原因）。
- **統合したあとの実機への反映は、`chezmoi apply`**（この PC の chezmoi のソースは `develop`。pull しない）。`chezmoi update` は `git pull --autostash --rebase` を固定で実行するので、**未 push の merge commit がある `develop` では、merge commit が平らに作り直される**（2026-11-14 に実際に起きた）。`chezmoi update` は、未 push のコミットが無いとき（`git rev-list --count @{u}..HEAD` が 0）に限る。他のホストの更新は、利用者が push したあとに `chezmoi update --init`。
- **feature への `develop` の取り込み**は `git flow feature update <名前> --rebase`（確認なしで通る）。feature の枝は未公開なので、rebase してよい。
- **子の自己申告は当てにならない**。親が、同じコマンドを自分で再実行して確かめる。子の報告が「確認していない」と書いたことは、親が確かめるまで未確認として扱う。
- **子の `stop` は、子のサブプロセスを止めない**。子に長く動くコマンドを実行させるときは、契約で `timeout` を付けさせる。
- **確認が出たかどうかは、子の自己申告でなく審査ログが正**: `~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl`。子の確認は、親の画面へ転送される。
- **AI は、利用者の指示が無いのに保護ブランチへ統合しない**（`develop`・`main` に直接コミットもしない）。`finish`・`merge` は、利用者が明示的に指示したときだけ。
