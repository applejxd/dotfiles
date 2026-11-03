# 統合方式と実行環境の実験（CHG-0062 の段 0）

2026-11-03。[CHG-0062](../../change/0062-pr-hub-simplify.md) の案（統合を、人が操作するアプリが同期的に行う）の中核の仮説を、使い捨てのリポジトリと実際の `pis` で確かめた記録。環境は Ubuntu（WSL）・git 2.43.0・pi 1.4.0。macOS・Windows は未確認。

## X1: 統合方式（git）

統合器の手順: `git merge-tree --write-tree <develop> <feature>` で結果の tree → `git commit-tree <tree> -p <develop> -p <feature> -F <message>`（merge commit。方式 M）→ develop が checkout されている worktree で `git merge --ff-only <commit>`。比較は、親が 1 つの squash コミット（方式 S）。

| 確かめたこと | 結果 |
| --- | --- |
| 積み重ね（A の上に B。B は A のファイルをさらに直す）を、A を先に統合した後に B を `merge-tree` | **M は衝突しない**（結果の tree は B の tree と一致）。**S は add/add で衝突する**（merge-base が両者の共通の祖先になり、A と B の同じファイルが両方「追加」に見える） |
| S の回避: `merge-tree --merge-base=<A の先頭>` | 衝突せず、M と同じ tree。ただし A の先頭（積み重ねの親）を統合器が知る必要がある |
| 逆順（B を先に統合） | M: B が A を含むので A も入る。その後 A を統合すると**中身が空の merge commit が増える**（A は develop の祖先）→ 事前に `git merge-base --is-ancestor <feature> <develop>` で弾く。S: A が add/add で衝突する |
| 無関係なファイル | どちらの方式でも、どの順でも成功 |
| 2 並行の `merge --ff-only`（同じ先頭から別々のコミット。10 回 + 追加 32 回） | **毎回ちょうど 1 つだけ成功**（競合の防止として足りる）。敗者の失敗は 3 種: `index.lock` の競合（rc=1）、`cannot lock ref 'HEAD': is at <勝者> but expected <旧先頭>`（rc=128。CAS として働く）、先に進んだ後の `Not possible to fast-forward`（rc=128。作業ツリーは無傷） |
| 同上の敗者（rc=128 の CAS 失敗）の後 | **作業ツリーと index を先に書き換えてから ref の更新で失敗するので、汚れが残ることがある**（`D  P.txt / A  Q.txt / ?? P.txt`。追加分の約 1/10〜1/6 で観察）。`git fsck` は問題なし |
| `merge --ff-only` の最中に `kill -9`（3000 ファイルのコミット。6 回） | ref は変わらない。`.git/index.lock` と途中までの作業ツリー（untracked 扱い）が残る。`fsck` は問題なし。ref の更新が最後なので、更新の後に kill した場合は統合済みになる（未観察） |
| dirty・untracked との重なり（develop の worktree） | 統合で変わる追跡ファイルの変更と、新規ファイルと同名の untracked は**拒否される**（何も変わらない）。無関係な変更・untracked・staged は**通る**。**統合で新規作成されるファイルと同名の ignored ファイルは、拒否されず黙って上書きされる**（データ消失の危険） |
| 履歴の見え方（M） | `git log --first-parent --oneline` は 1 feature = 1 コミット（積み重ねの a1+a2 も 1 つ）。`git log --oneline --graph` は feature の個別コミットが第 2 親側に入る。`git branch --merged develop` は統合済みの枝を示し、積み重ねの下の枝は上を統合すると自動で統合済みになる |
| 版 | `merge-tree --write-tree` と `--merge-base` は 2.43.0 で動いた。必要な最小の版は、`git help merge-tree` に記述が無く確認できていない |

### 統合器の設計への反映

- 統合方式は M（merge commit）。積み重ねの衝突が構造的に消える。squash を維持するなら、積み重ねの親を知る `--merge-base` が要る。
- 競合の防止は `merge --ff-only` の CAS に任せ、**アプリ内の排他（同時に 1 件）**を足して、敗者が作業ツリーを汚す経路をなくす。
- 事前検査: (1) develop の worktree の HEAD が develop（`git symbolic-ref HEAD`）、(2) すでに統合済みでない（`merge-base --is-ancestor`）、(3) 統合が触るパス（`git diff --name-only <develop> <統合コミット>`）が、`git status --porcelain` と `git status --porcelain --ignored` のどちらにも出ない（無関係な dirty は通してよい）。
- 失敗・中断の復旧は**統合が触るパスだけ**に限る（`git checkout HEAD -- <パス>` と、統合で新しく作られる untracked の削除。`git reset --hard` は、無関係な未コミットの変更を消すので使わない）。残った `.git/index.lock` は、他の git プロセスが無いことを確かめてから消す。アプリの起動時に検出して、「前回が途中かもしれない」と表示する。

## X2: Fence（`pis`）の内側からアプリへ届くか

手順: 外側（シェル）と内側（`pis -p` が実行した curl）で、同じ URL を試す。

| 対象 | 外側（基準） | 内側 | 判定 |
| --- | --- | --- | --- |
| アプリの loopback（`127.0.0.1` のポート） | 200 | 接続できない（000） | **遮断している（合格）** |
| tailnet の名前 | 届かない（この端末の WSL からは） | 届かない | **未確定**（基準が無い） |

- tailnet の名前について、コードの読解: 中継（`relay.py` の `blocked_address`）は、グローバルなアドレスだけを通し、共有アドレス空間（100.64.0.0/10。tailnet の IP を含む）・私設・ループバック・リンクローカルを常に拒否する（fail closed）。tailnet の名前は 100.x に解決されるので、内側からは届かない見込み。**公開（funnel）は別で、公開側のアドレスは「グローバル」なので、内側から届く**。funnel を使わないことを運用の前提にする。
- 残り: アプリを tailnet に公開した状態で再実験し、基準が 200 のときに内側が届かないことを確かめる。Fence の内側からの `refs/pi/review/*` の書き込み（E9）は未実施。

## X3（軽量版）: `pis -p` を feature の worktree で使う

| 試験 | 結果 |
| --- | --- |
| 自明な依頼 | 約 15 秒（起動・境界チェック込み）。出力に毎回、境界チェックの結果（`OK …` が数十行）が出る → アプリは最後の応答だけを取り出す必要がある |
| feature の worktree で、README に 1 行足す | 約 13.5 秒で完了。変更は `README.md` だけ |
| 上の変更を `guarded_action` の `git_commit` でコミットする | **失敗**（約 36 秒）。Fence の内側では、秘密系のファイルが `/dev/null` 相当の特殊ファイルに置き換わっていて、pre-commit（`git diff-index`）が `unsupported file type` で止まる。変更はステージ済みのまま止まった |

- **結論**: Fence の内側からのコミットは、pre-commit と相性が悪く、信頼できない。**コミットは、Fence の外のアプリが、範囲を検査してから行う**。worker は編集だけをする（CHG-0062 の方針と一致する）。
- 未測定: トークン数・費用、役割ごと（計画・review・衝突解消）の構造化出力、Windows の素の `pi -p`。
