# gh CLI: Projects v2 操作早見表

> GitHub Projects v2 のカスタムフィールド更新は `gh project` サブコマンドと
> `gh api graphql` で行う。github MCP には Projects v2 のツールがないため
> CLI へのフォールバックが必須。

## 認証 (must read)

Projects v2 は通常の repo scope では触れない。`gh auth status` で
`project` scope の有無を確認する。不足していれば:

```bash
gh auth refresh -s project
```

これは対話を伴うため、**skill から自動実行せずユーザーに案内する**。
read のみなら `read:project` でも可。

## サブコマンド早見表

| 操作 | コマンド | 補足 |
| --- | --- | --- |
| project 一覧 | `gh project list --owner OWNER --format json` | OWNER は user / org |
| project 詳細 | `gh project view NUMBER --owner OWNER --format json` | `project_id` 取得 |
| フィールド一覧 | `gh project field-list NUMBER --owner OWNER --format json` | field ID / option ID 取得 |
| item 一覧 | `gh project item-list NUMBER --owner OWNER --format json` | 各 item の itemId / 既存値確認 |
| item 追加 | `gh project item-add NUMBER --owner OWNER --url ISSUE_URL --format json` | 戻り値の `id` が itemId |
| item フィールド編集 | `gh project item-edit --project-id PID --id ITEM_ID --field-id FID ...` | field 種別ごとにフラグが異なる |
| item アーカイブ | `gh project item-archive --id ITEM_ID --project-id PID` | 復元可 |
| item 削除 | `gh project item-delete --id ITEM_ID --project-id PID` | 不可逆、要承認 |

## item-edit のフィールド種別ごとのフラグ

| field 種別 | gh フラグ | 値 |
| --- | --- | --- |
| Single select | `--single-select-option-id OPTION_ID` | option ID（field-list で解決） |
| Iteration | `--iteration-id ITERATION_ID` | iteration ID（field-list で解決） |
| Date | `--date YYYY-MM-DD` | ISO 8601 日付 |
| Number | `--number N` | 数値 |
| Text | `--text "..."` | 任意文字列 |
| クリア | `--clear` | フラグ単独で値を削除 |

全フラグ共通で `--project-id`, `--id` (itemId), `--field-id` が必要。

## ID 解決の典型コマンド

### project ID

```bash
gh project view NUMBER --owner OWNER --format json | jq -r .id
```

### field ID と option ID（Single select）

```bash
gh project field-list NUMBER --owner OWNER --format json \
  | jq '.fields[] | select(.name == "Status")'
```

出力例:

```json
{
  "id": "PVTSSF_xxx",
  "name": "Status",
  "type": "ProjectV2SingleSelectField",
  "options": [
    { "id": "abc", "name": "Todo" },
    { "id": "def", "name": "In Progress" },
    { "id": "ghi", "name": "Done" }
  ]
}
```

`scripts/resolve-project.sh` がこの整形を 1 コマンドで行う。

### Iteration ID

`field-list` の Iteration field 配下に `configuration.iterations[]` がある。
`id` と `title` / `startDate` / `duration` を組で扱う。

## GraphQL フォールバック

`gh project item-edit` でカバーできないケース（複数 field 同時更新の bulk、
特殊なフィールド型など）は `gh api graphql` を使う。

### 例: Status を In Progress に変更

```bash
gh api graphql -f query='
  mutation($project:ID!,$item:ID!,$field:ID!,$option:String!) {
    updateProjectV2ItemFieldValue(input:{
      projectId:$project, itemId:$item, fieldId:$field,
      value:{ singleSelectOptionId:$option }
    }) { projectV2Item { id } }
  }' \
  -F project=$PROJECT_ID -F item=$ITEM_ID -F field=$FIELD_ID -F option=$OPTION_ID
```

### 例: project items を bulk 取得

```bash
gh api graphql -f query='
  query($owner:String!,$number:Int!) {
    user(login:$owner) {
      projectV2(number:$number) {
        items(first:100) {
          nodes { id content { ... on Issue { number title } } }
        }
      }
    }
  }' -F owner=OWNER -F number=NUMBER
```

org の場合は `user(...)` を `organization(...)` に置き換える。

## 落とし穴

| 落とし穴 | 症状 | 対応 |
| --- | --- | --- |
| **project number と project ID の混同** | `--project-id` に number を渡して `node id required` | `gh project view --format json` で `id` (`PVT_xxx`) を取る |
| **user / org スコープの取り違え** | `Could not resolve to a node` | `--owner` を user / org 名で正しく指定。GraphQL は `user` / `organization` を切替 |
| **scope 不足** | `Your token has not been granted the required scopes` | `gh auth refresh -s project` をユーザーに案内 |
| **OPTION_ID をオプション名で渡す** | `option not found` | `field-list` から option ID を解決してから `item-edit` |
| **Iteration が title 渡し** | 同上 | iteration ID を解決してから渡す |
| **closed Iteration** | 更新自体は通るが UI に出ない | current / 直近のみ使う運用に |
| **`gh project item-add` の URL 不一致** | `not a valid issue/pr URL` | `https://github.com/OWNER/REPO/issues/N` フル URL で渡す |
| **bulk 操作のレート** | `secondary rate limit` | GraphQL の mutation を 1 リクエストで複数まとめる |
