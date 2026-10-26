# commit の確認（素の pi）の仕様メモ

> `docs/spec/guard/pi-guard.md#commit-の確認-素の-pi` から移した記録。移設時点で再測定していない。

## 記録 — 観測日は各文に記載（移設 2026-10-26）

- **対象バージョン**: 各文に記載（pi 1.3.0 前後）
- **環境**: 各文に記載

### 問い

素の pi 用の補助拡張 `commit-confirm` の、確認の表示例・一時 index の再現方法・退避 ref の鎖の実装は、どうなっているか。

### 根拠

`home/dot_config/pi/commit-confirm/`（`parse.ts`・`describe.ts`・`pending.ts`）、`test/agents/test_pi_commit_parse.py`、`test/agents/test_pi_commit_confirm.py`。元の文のとおり。

### 結果（元の節の全文。現行の仕様は spec 側に残してある）

フルガードを読まない `pi`（フルガードの読み込みに失敗した起動など）では、bash の git は素通りになる。その補助として、
小さな拡張 `~/.config/pi/commit-confirm` を用意している。**今は `settings.json` の `extensions` に入れていない**（Unix・Windows とも、フルガードに `git commit` の確認があるため。Windows でも settings から外した。拡張本体の配備は残るが、Windows の settings は読まない）。必要なときは `-e` で明示して読ませる。
**保護ではなく補助**で、別名・スクリプト越しの git は検出しない。`!git commit`（利用者が手で打つ）も対象外。

| コマンド | 扱い |
| --- | --- |
| `git push`（`-C dir`・`sh -c '…'`・`commit && push` も） | **確認せずに拒否**する。push は完全手動。連結した commit も実行しない |
| `git commit` | 構造にして見せて確認する（下） |
| それ以外 | 何もしない |

検出は、引用符の外のコマンドの先頭だけを見る小さな字句解析（`parse.ts`）。引用符の中の文字列
（`echo "git commit"`）や `git commit-tree`・`git stash push` は拾わない。

#### 確認の表示

事実は git から取り、メッセージだけコマンドから読む（`describe.ts`）。生のコマンドは出さない。

```text
リポジトリ: https://github.com/applejxd/dotfiles.git
ブランチ:   main  → origin/main (1 ahead, 0 behind)

対象:       2 ファイル  +2 −1
  M a.txt (+2 −0)
  D c.txt (+0 −1)
  (含まれない未ステージの変更: 2 ファイル)

メッセージ:
  feat(pi): 構造化表示を作る
  - 本文…

注意:
  --no-verify: コミットの hook を飛ばす
```

- リポジトリは origin の URL（`https://user:token@…` の認証情報は出さない。origin が無ければパス）
- 対象は、**実行したらコミットされる内容**を一時のインデックスに再現して数える。通常はインデックス、`-a` は
  `add -u`、`add … &&` は追加後、`git commit <パス>` は土台にそのパスの今の内容を足したもの。`--amend` は
  直前のコミットの親との差。HEAD・本物のインデックス・作業ツリーは変えない（`GIT_OPTIONAL_LOCKS=0`）
- メッセージは `-m`（複数も）、`-F file`、`-F - <<'EOF'`、**`-m "$(cat <<'EOF' … EOF)"`**（エージェントの定番）を読む。
  本文は 72 桁・8 行まで、件名は切らない
- `--no-verify`・`--amend`・`-S`・`--allow-empty` は「注意」に出す。コミットする変更が無いときも書く
- **読めない形は「読めない」と言う**。`VAR=値 git commit`・`sudo git commit`・連結（`&&` 以外・`add`/`cd` 以外が付く）・
  パイプ・リダイレクト・`$VAR`・`$(…)`・`-e`（エディタ）・メッセージ無しは、
  「解釈できない形のコマンドです。次がそのまま実行されます:」と生のコマンドを（12 行まで）見せる。
  構造化の表示が、後ろに付いた操作を隠さないための規則
- **並んだ commit の限界**: pi は同じ応答の全呼び出しの `tool_call` を終えてから実行を始めるので、2 件目の表示は、1 件目の確認が済んだ後に組むが、1 件目のコミットはまだ入っていない（2 件目は 1 件目の対象も含めて見せる）。実行の終わりを待つ案は、全呼び出しの確認が終わるまで実行が始まらないため、安全弁の時間まで止まって採れなかった
- 確認で実行する `git add` は一時のインデックスに対してだけ動くが、`.gitattributes` の clean filter は走る
  （`git commit` を承認すれば同じものが走る）。`core.fsmonitor` は切り、diff は `--no-ext-diff`

#### 時間切れと退避

確認が取れなかったとき（時間切れ・不在・画面なし）は、**コミットせず、内容を退避して作業を続けさせる**。

- 期限は TUI が **15 分**（画面に残り秒が出る）、RPC など（Zed）が **5 分**。時間切れは拒否と同じ `false` で返るので、
  経過時間で見分ける。利用者が拒否したときは退避しない（「拒否した。続け方を確認する」と返す）
- 退避は、コミットの**オブジェクトだけ**を作り（`write-tree` → `commit-tree`）、`refs/pi/pending/<時刻>` に置く。
  ブランチ・HEAD・インデックス・作業ツリーは動かない。hook は呼ばれず、`commit.gpgsign` に左右されない。
  `user.name` が無い環境では代わりの身元を渡す
- 直前の保留を親にして**鎖**にする（2 つ目の差分は 1 つ目からの増分）。その間に本物のコミットがあれば、HEAD から
  始め直す。ref 名の順で先頭を選ぶ（`creatordate` は同じ秒で崩れる）
- モデルには「コミットは実行していない。内容は `refs/pi/pending/…` に退避した。**再試行しない**。コミットが要らない
  作業を続け、最後に『保留したコミット』として ref・件名・対象を報告する」と返す。実際のモデルで、`b.txt` を作り、
  ref を報告し、`--no-verify` や plumbing での迂回をしないことを確かめた
- **不在**: 時間切れの後は、利用者の入力（`input` イベント。拡張が起こしたものを除く）があるまで、次の確認で待たずに
  退避する。1 回の応答に並んだ commit も、先の確認が時間切れなら後ろを待たない
- **連結したコマンド**（`git commit … && 別の操作`。モデルがよく書く）はコマンド全体を止める。退避は最初の
  `git commit` から**近似**する（今ステージされている内容と、そのメッセージ。連結の他の操作は再現しない）。
  理由に「連結していた他の操作も実行していないので、commit と分けて実行し直す」と書く。変数入りのメッセージなど、
  最初の commit も読めないものは退避できない（その旨を返す）
- `--amend` は退避できない（直前のコミットの書き換えは HEAD の子として表せない）

後から見る・取り込む:

```sh
git log --oneline refs/pi/pending/<名前>          # 保留したコミット (鎖の全体)
git reset --soft refs/pi/pending/<最後の名前>     # HEAD だけ進める。作業ツリーは変わらない
git for-each-ref --format='%(refname)' refs/pi/pending/ | xargs -n1 git update-ref -d   # 全部捨てる
```

試験の期限は `PI_COMMIT_CONFIRM_TIMEOUT_MS` で縮める（本番では使わない）。

- `pis` は `-ne` で外れるので、フルガード自身の確認と二重にならない（試験済み）
- Windows にも配る。`.chezmoiignore` は `.config/pi/` を戻し、除外するのは `landlock_exec.py` だけ（`harness` は Windows にも配る）。
  Windows 実機は未検証
- 試験: `test_pi_commit_parse.py`（解釈・表示・退避。node で直接）、`test_pi_commit_confirm.py`
  （pi + 偽のモデル。RPC・非対話・TMUX の TUI）

### 解釈・次の候補

現行の仕様は [pi-guard.md](../../spec/guard/pi-guard.md#commit-の確認-素の-pi)。この記録は経緯・実装の詳細・確認の記録で、再測定していない。
