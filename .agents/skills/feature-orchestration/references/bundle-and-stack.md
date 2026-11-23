# 束ねる・積み重ねる（複数の feature の統合）

工程 8（統合）の前後で、feature が複数・依存つきのときに使う。

## 束ねる (複数の feature を 1 回の merge で統合する)

**利用者が 2 件以上の feature の統合を指示したときは、feature ごとに `finish` せず、束ねて 1 回で統合する**（`develop` の履歴に merge commit が 1 つだけ残る）。
標準の `git flow` と `git merge` だけで行う。自作は増やさない（ADR-0031）。`develop` は他のホストも取り込むので、書き換えない merge で入れる（[ADR-0039](../../../../docs/adr/0039-merge-to-develop.md)）。

1. **前提を確かめる**: 束ねる feature がすべてコミット済みで、それぞれ単体で検査が通っている（工程 4〜7）。担当ファイルが重なるものは、衝突しうるので順序を決める。
2. **束ね用の feature を切る**: `git flow feature start bundle-<日付か話題> --worktree --no-fetch`（worktree は `.tmp/worktrees/bundle-…/`）。
3. **各 feature を束ね用へ取り込む**: `git -C <束ねの worktree の絶対パス> merge feature/<名前> -m "merge: feature/<名前> を取り込む"` を feature ごとに。`git -C <絶対パス> merge` は判定表（`test/agents/pi_stock/permission_cases.json`）で allow と確認済み。`cd … && git merge …` の連結は表に無く、確認が出たことがあるので使わない。
   **衝突したら止めて利用者に報告する**（子に直させない。docs の索引・`scripts/verify.py` の同じ位置は、両方の行を残す）。
4. **束ねた先で全件検査**: `bg_run` で `mise run verify:all`（1 本だけ。積み重ねの検査を兼ねる）。落ちたら、どの feature が原因かを切り分ける。
5. **利用者の指示で 1 回だけ統合**（ここだけ確認が出る。規則 `git flow * finish*` が ask。束ね用の作成・取り込み・コミット・`worktree list` は、確認なしで通る）: `git flow feature finish bundle-<…> --no-ff --no-squash -M "merge: <feature の一覧> を統合する" --keepremote --no-fetch --no-push --notag`（メッセージに取り込んだ feature の名前を並べる）。
6. **後始末**: 取り込んだ各 feature の worktree は、`finish` の前に、[工程 9 の①](../SKILL.md)（git の対象外のファイルの確認と救出）を済ませる。そのあと `git worktree remove .tmp/worktrees/<名前>`（`--force` なし）で消す。枝は `develop` から到達できるので、`git -C <develop の worktree> branch -d feature/<名前>` で消せる（`-D` は拒否される）。

1 件だけの統合は、これまでどおり工程 8 の `finish` を直接使う（束ねない）。

## 積み重ね (依存する feature)

B が、まだ develop に入っていない A の変更を要るとき、A の統合を待たずに B を進められる。**依存は宣言しない**（git の祖先関係から導く。宣言は古くなる）。

1. **起票**: A をコミットしたあと、`git flow feature start <B> feature/<A> --worktree --no-fetch`（B は A の先頭から始まる）。
2. **A がさらに進んだら**: `git -C <B の worktree の絶対パス> merge feature/<A> -m "merge: feature/<A> を取り込む"`。B の worker が動いていないときに、**親が行う**。**衝突したら、止めて利用者に報告する**（子に直させない）。
3. **統合は、利用者の指示で A → B の順**。統合は merge commit（`--no-ff --no-squash`）なので、A を先に統合すると B から見て A は祖先になり、順序の問題は起きない。B を先に統合すると A の変更も一緒に入る。
4. **全件検査**は B の worktree でも回せる（A の変更を含む。A が壊れていれば B も落ちる）。
