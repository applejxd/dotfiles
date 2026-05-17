# 典型ワークフロー

> github MCP と gh CLI を組み合わせた典型的なエンドツーエンド手順。
> 各手順は **dry-run → ユーザー承認 → 実行** を徹底する。

## 1. issue を作って Project に入れて Status を In Progress にする

### 手順

1. **issue 作成** (MCP)

   ```text
   mcp__github__create_issue
     owner=OWNER repo=REPO
     title="..." body="..."
     labels=[...] assignees=[...]
   → 戻り値の number と html_url を保持
   ```

2. **project / field 解決** (CLI)

   ```bash
   ~/.claude/skills/github-issue/scripts/resolve-project.sh OWNER NUMBER
   → project_id, fields.Status.id, fields.Status.options["In Progress"] を保持
   ```

3. **issue を project に追加** (CLI)

   ```bash
   ~/.claude/skills/github-issue/scripts/add-issue-to-project.sh \
     $PROJECT_ID $ISSUE_URL
   → itemId を保持
   ```

4. **Status を In Progress に変更** (CLI)

   ```bash
   ~/.claude/skills/github-issue/scripts/set-project-field.sh \
     $PROJECT_ID $ITEM_ID $STATUS_FIELD_ID single_select $INPROGRESS_OPTION_ID
   ```

5. **検証** (CLI): `gh project item-list NUMBER --owner OWNER --format json` で
   Status カラムが期待値か確認

## 2. issue 一覧から Priority フィールドを bulk 更新する

例: `label:hotfix` の open issue 全件を Priority=P0 にする。

### 手順

1. **対象 issue 列挙** (MCP)

   ```text
   mcp__github__search_issues
     query='repo:OWNER/REPO is:open is:issue label:hotfix'
   → numbers / html_urls を保持
   ```

2. **project / field 解決** (CLI) — 1 回だけ
3. **未登録 issue を project に追加** (CLI) — `item-list` と差分を取る
4. **bulk mutation** (CLI, GraphQL)

   ```bash
   gh api graphql -f query='
     mutation($p:ID!,$i:ID!,$f:ID!,$o:String!) {
       updateProjectV2ItemFieldValue(input:{
         projectId:$p, itemId:$i, fieldId:$f,
         value:{ singleSelectOptionId:$o }
       }) { projectV2Item { id } }
     }' \
     -F p=$PROJECT_ID -F i=$ITEM_ID -F f=$PRIORITY_FIELD_ID -F o=$P0_OPTION_ID
   ```

   N 件分ループ。レート制限に注意し、エラー時は exponential backoff。

5. **検証**: `gh project item-list --format json | jq '.items[] | select(.priority=="P0")'`

## 3. Iteration を現在スプリントに設定する

### 手順

1. **project / field 解決** (CLI) — `Iteration` field の `configuration.iterations[]` から、
   `startDate <= today < startDate + duration` を満たす iteration を抽出
2. **issue を project に追加** (CLI) — 既登録なら skip
3. **Iteration field を更新** (CLI)

   ```bash
   ~/.claude/skills/github-issue/scripts/set-project-field.sh \
     $PROJECT_ID $ITEM_ID $ITERATION_FIELD_ID iteration $ITERATION_ID
   ```

4. **検証**: `gh project item-list` で iteration title を確認

## 共通ガード

- 各ステップの実行前に、何を変更するかを 1 段落で要約してユーザーに提示
- 破壊的操作（close / item-delete / item-archive）は **必ず承認後**
- レート制限 / scope 不足 / network エラーで失敗したら即停止しユーザーに報告
- 出力に token / secret を含めない（`gh auth status -t` などは使わない）
