# 保留（非同期承認）【撤去済み・履歴】

確認が取れないとき操作を保留し、利用者があとで `/pending approve` で実行する仕組み（`git_integrate`）は、**撤去済み**。
統合は PR ビューアの「統合する」ボタンへ移った（[CHG-0062](../../change/0062-pr-hub-simplify.md) 段 A5）。経緯は [CHG-0055](../../change/closed/0055-async-approval.md)・[ADR-0023](../../adr/0023-pending-approval.md)。
撤去は 1 つの feature・1 回の保存で行った。**revert 1 つで旧経路が復活する**。

## 今の統合の流れ

1. AI が feature の worktree で `git_commit`（自由区。確認なし）する。
2. AI が `guarded_pr_summary` で、PR に要約（`mergeMessage` の下書き）を出す。
3. 利用者が [PR ビューア](../pr-viewer.md)の「統合する」ボタンを押す（アプリが merge commit で同期統合する）。

`git flow feature finish`・`git merge` を AI が実行するときは、素の pi の必須確認のまま（`integration-gate`。[pi の拡張](pi-extensions.md)）。

## 撤去したもの

- `guarded_action` の `git_integrate`、`/pending` の `approve`・`resolve`・`unlock`・`log`、承認の巡回、排他ロック、フッターの「保留 N 件」
- 設定 `[pi.pending]`、`[pi.integrate] enabled`（`protected_refs`・`risk_paths`・`skip_confirm_in_free_zone` は残る）
- 実装 `integrate-plan.ts`・`integrate-exec.ts` など

## 残るもの

`/pending`（利用者専用。モデルは呼べない）のうち、旧形式（`git_commit` の時間切れ退避）を扱う次の 3 つだけが残る。詳細は [pi の拡張](pi-extensions.md#guarded_action承認つきの外部操作)。

| サブコマンド | 内容 |
| --- | --- |
| `list` | 退避の一覧（新しい順） |
| `show <ref>` | 詳細（差分の本文まで） |
| `drop <ref>` | 到達用の ref を外す |

## 残骸の ref の掃除

新形式の分の ref（`refs/pi/{pending,running,done,key,lock}/*`）は、撤去後は使われない。利用者が一度だけ、補助スクリプトで掃除する。**先に dry-run で対象を確かめる**。

```sh
pk pending-clean
```

旧形式の退避の ref（`/pending list` に出るもの）は対象にしない。
