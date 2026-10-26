# testing 仕様の実測メモ

`docs/spec/testing.md` から移した記録。移設時点で再測定していない。

> **現行の仕様**: [テストと検証の仕組み](../../spec/testing.md)

## 記録 E1 — 素の runner の近似での全件実行（2026-10-22）

- **観測日**: 2026-10-22（元の文の日付）。`docs/spec/testing.md#linux-の-github-actions` から移した

### 問い

push 前に、素の GitHub Actions runner を近似した環境で全件が通るか。

### 結果（元の文）

> push 前に、空の `HOME`、最小の `PATH`、git の identity なしで素の runner を近似して全件を回した
（2026-10-22、`node` も `pi` も無い状態。HOME は作業ツリーの外に置く。作業ツリーの中だと
「作業ツリー内の読み取り」と判定されて偏る）。ここで見つかった 2 点を直した:

- `test_pi_harness_extensions.py` に `pi` が無いときの skip が無く、`TypeError` で落ちていた
  （`test_pi_harness.py` にはあった）
- `test_pis_no_sandbox_marks_the_environment_and_warns` が、配備済みの
  `~/.config/pi/harness/rules.json` に依存していた

直したあとの近似での全件の再実行はしていない（直した 2 ファイルだけ近似環境で通った）。
**本物の runner での結果は未確認で、push 後の初回の実行で確かめる。**

（元の文は引用ブロックにせず通常の段落だった。上の行頭だけ引用記号を付けている。）

## 記録 E2 — その他の実測の注記

元の文のまま。

- `docs/spec/testing.md#ソースは既定で-clone-する`: `git -c safe.directory=...` は clone の所有者検査まで届かない（git 2.43 で実測）。
- `docs/spec/testing.md#環境都合と切り分けるもの`: apply が上限（`APPLY_TIMEOUT`、既定 15 分）で打ち切られる件。実測で mise の取得が 23〜145 kB/s まで落ちた。
- `docs/spec/testing.md#失敗を握り潰さない`: 以前は代替 config を書いて続行していたが、これは検出したい不具合そのものを隠す。
- `docs/spec/testing.md#既知の未達`: `ubuntu2204` の `apply` と `update`（2 回の apply と残差分 0 件）は通る（2026-09-27 時点）。
- `docs/spec/testing.md#pytest-の全件`: 初回の `linux.yml` の実行結果は未確認だった。
