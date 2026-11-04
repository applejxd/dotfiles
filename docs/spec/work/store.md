# 作業台帳の永続 (work-store)

台帳 (work ledger) は追記専用のイベントログ。永続の実装は `home/dot_config/pi/harness/work/store.ts`（node 標準の `node:fs` のみ・Unix 前提）、
置き場の決定は `work/root.ts`。型の契約は `work/types.ts`。試験は `test/agents/test_work_store.py`（障害注入つき）。

## 置き場

`<git-common-dir>/pi-work`。書けなければ `<cwd>/.tmp/work` へ退避する（`resolveStoreRoot`。`canWrite` は注入。どちらを選んだかと書けるかを返す）。

**書き込みの保護**: `**/.git/pi-work/**` と `**/.tmp/work/**` は、モデルからは書けない（ハーネスだけが fs で書く）。ファイルツールは `[file] write_deny_globs`、bash のリダイレクト・`mv` / `cp` / `rm` / `tee`・インラインコードは `judge/rules_guard.ts` の `GUARD_TARGETS` で拒否する（読み取りは許す。試験は `test_pi_control_files_bash.py`）。サンドボックスの `denyWrite` には足さない（ハーネス自身が内側で書くため）。
`pis` のサンドボックスで前者へ書けるかは未確認のため、退避を残している。

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
