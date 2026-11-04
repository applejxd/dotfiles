# 作業台帳の永続 (work-store)

台帳 (work ledger) は追記専用のイベントログ。永続の実装は `home/dot_config/pi/harness/work/store.ts`（node 標準の `node:fs` のみ・Unix 前提）、
置き場の決定は `work/root.ts`。型の契約は `work/types.ts`。試験は `test/agents/test_work_store.py`（障害注入つき）。

## 置き場

`<git-common-dir>/pi-work`。書けなければ `<cwd>/.tmp/work` へ退避する（`resolveStoreRoot`。`canWrite` は注入。どちらを選んだかと書けるかを返す）。

**書き込みの保護**: `**/.git/pi-work/**` と `**/.tmp/work/**` は、モデルからは書けない（ハーネスだけが fs で書く）。ファイルツールは `[file] write_deny_globs`、bash のリダイレクト・`mv` / `cp` / `rm` / `tee`・インラインコードは `judge/rules_guard.ts` の `GUARD_TARGETS` で拒否する（読み取りは許す。試験は `test_pi_control_files_bash.py`）。サンドボックスの `denyWrite` には足さない（ハーネス自身が内側で書くため）。
**bash の判定**（`rules_guard.ts` の `checkLedgerWrite`。追加の判定で、既存の拒否は変えない）: 置き場は成分境界で照合する（`.tmp/work` そのもの・末尾の `/` なし・絶対パスを含み、`.tmp/worktrees` は当たらない）。引数が cwd 基点の絶対パスか symlink の実体で置き場に当たるとき、コマンドが**既知の読み取り専用**（`cat`・`ls`・`grep`・`find`〔`-delete`・`-exec`・`-fprint*` なし〕・`git log` など）でなければ拒否する（`git --output`・`sort -o`・`curl -o`・`dd of=`・`sed -i`・`touch` も該当）。`git -C` の基点は反映し、置き場へ `cd` した後は相対パスを字面で見られないので拒否する。
`pis` のサンドボックスで前者へ書けるかは未確認のため、退避を残している。
**`.git` 以外の名前の common-dir**（`--separate-git-dir`・`GIT_DIR`・worktree）: 判定器は新しい文脈を受けず、`judge/ledger_root.ts` の `ledgerRoots(cwd, env)` が fs だけで置き場の実体を解く（プロセスは起動しない）。cwd から上へ `.git` を探し、ファイルなら `gitdir:`（相対は `.git` の場所基点）を読み、`commondir` があれば common-dir を求める。`GIT_COMMON_DIR`・`GIT_DIR` の環境変数も加え、`<common>/pi-work` と cwd 直下の `.tmp/work` を返す。結果は cwd・環境変数ごとに最大 64 件、**2 秒の TTL** でキャッシュし（期限後に `.git` の出現・変更を拾う。置き場を 1 件も解けなかった結果は保持しない）、読めない・不正な形は例外にせず解決できた分だけ返す（名前の照合は常に残る）。`.git` の探索は元の cwd と symlink を解いた実体の両方から行い、見つかった common-dir を合算する。bash（`ledgerHit`）と、ファイルツールの write / edit（`decide.ts` の `decideFile`。pi のパス解釈の各形 `@`・`file://`・Unicode 空白・`~` の全てを候補にする）が、名前の照合に加えて成分境界つきで照合する。**common-dir 自身**（`rm -rf git-meta`・`mv`・`find -delete`。`.git` 名の通常構成は既存の判定に任せる）の削除・移動も bash で拒否する（`checkLedgerWrite`。読み取りと兄弟のパスは対象外）。

## ログの形式

- `log/NNNN.jsonl`: 1,000 イベントごとにセグメントを切り替える（seq から番号が決まる。先頭の seq は `(NNNN-1)*1000+1`）。
- 1 行 = 1 イベント: `<JSON>\t<crc32 の 16 進 8 桁>\n`。crc は JSON のバイト列に対する IEEE crc32。
- `seq` は 1 からの連番、`ts` は store が付ける。追記は書いてから **fsync してから** ack する（新しいセグメントを作ったときはディレクトリも fsync）。

## 回復（`load()`）

| 状態 | 扱い |
| --- | --- |
| 末尾の改行の無い行（torn write） | 切り詰める。`recovered: true` |
| 途中の行の破損（crc 不一致・JSON 不正・seq の欠番・欠けたセグメント） | その行以降を `quarantine/<時刻>.jsonl` へ逐語で隔離し、`degraded: {quarantined, reason}`。`DEGRADED.json` を置き、以後 `append` は `DEGRADED` で拒否（再起動しても残る。解除は人が確認して消す） |

物理的な切り詰め・隔離は **lease を持つ書き手だけ**が行う。読み手（lease 無し）はファイルに触らず、結果だけ返す。
`loadSince(seq)` は該当セグメントだけ読む。

## スナップショット

`snapshot-<seq>.json`（tmp → fsync → rename → ディレクトリ fsync。新しい 2 つだけ残す）。内容は呼び出し側が渡す文字列で、crc つき。
壊れたものは読み飛ばす。**高速化のためだけ**で、全ログから必ず再構成できる。`snapshotDue(seq)` は 200 件ごとの目安。

## lease

`lease/`（`mkdir` の排他）+ `owner.json`（holder・pid・startedAt・heartbeat・token）。`heartbeat()` は 30 秒ごとに呼ぶ想定。
heartbeat が 90 秒切れ、または pid の死亡で古いとみなし、`lease.lock`（mkdir の mutex）の下で再確認して引き継ぐ（同時に引き継いで取れるのは 1 人）。
同じ pid・同じ holder の再取得は許す（拡張の再読み込み）。**lease を持たない・失った書き手の `append` は `NO_LEASE` で拒否する**（変更を捨てない）。

## 失敗

ENOSPC・EROFS・EACCES など書き込みの失敗は例外（`IO`）を投げ、store を読み取り専用に落とす。`readonlyReason` で理由を返す（alert 用）。

## 限界

- fsync の実効性はファイルシステム依存。pid の再利用と、append の直前の lease 確認から書き込みまでの間の引き継ぎは防げない。
- Windows は対象外。
- 台帳の書き込み保護は**判定器の層**で、OS の境界ではない。任意のスクリプトの中の書き込み（`python -c`・シェルの変数・動的な展開・コマンド置換）は防げない。symlink の実体の照合は、判定時に実体が引ける範囲だけ。
- 読み取り専用コマンドの一覧と書き込みオプションの一覧は網羅ではない（新しいコマンドは fail-closed なので拒否側へ倒れる）。ラッパー（`env`・`timeout` など）は自身のオプションを読み飛ばして実コマンドを判定するが、`env -u NAME`・`stdbuf -o MODE` の分離形は正規化の段で名前が実コマンドに見えるため、読み取りでも拒否側へ倒れる。
