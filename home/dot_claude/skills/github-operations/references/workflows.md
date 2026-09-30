# 典型ワークフロー

> すべて **事前確認（現在の状態を取得して提示）→ 承認 → 実行 → 読み戻し** の順で行う。
> 各コマンドは直接 `gh` を呼ぶ。repo は `--repo OWNER/REPO` で明示する。

## 1. issue を作って Project に入れ、Status を変更する

1. issue 作成: `gh issue create --repo OWNER/REPO --title ... --body-file FILE`
   （承認が要る。URL を保持）
2. `resolve-project.sh OWNER NUMBER` → `project_id`、`fields.Status.id`、該当 option ID を保持
3. `gh project item-add NUMBER --owner OWNER --url ISSUE_URL --format json` → item ID を保持
   （登録済みなら既存 item が返るかを読み戻して確認する）
4. `gh project item-edit --project-id PID --id ITEM_ID --field-id FID --single-select-option-id OPT`
5. 読み戻し: `gh project item-list NUMBER --owner OWNER --limit 200 --format json` で Status を確認

## 2. 条件に合う issue の field を bulk 更新する

例: `label:hotfix` の open issue を Priority=P0 にする。

1. 対象列挙: `gh issue list --repo OWNER/REPO --label hotfix --state open --limit 200 --json number,url`
   件数が `--limit` に達したら続きを取得するか、途中までと明記する
2. `resolve-project.sh` は 1 回だけ実行
3. 未登録の issue を `item-add`（`item-list --limit` で既登録との差分を取る）
4. 更新: 1 件ずつ `item-edit`、または GraphQL mutation。件ごとの成否を記録する
5. 失敗した分だけを再実行する。読み戻しで全件を確認する

## 3. Iteration を現在のスプリントに設定する

1. `resolve-project.sh` の `fields.Iteration.iterations[]` から
   `startDate <= today < startDate + duration 日` の iteration を選ぶ
2. item 追加（登録済みなら不要）
3. `gh project item-edit --project-id PID --id ITEM_ID --field-id FID --iteration-id ITER_ID`
4. 読み戻して iteration の title を確認する
