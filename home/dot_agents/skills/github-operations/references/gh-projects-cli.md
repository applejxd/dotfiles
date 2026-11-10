# gh CLI: Projects v2 の注意点

> サブコマンドの一覧とフラグは `gh project --help` / `gh project <cmd> --help` を見る。
> ここには --help に無い落とし穴と GraphQL の例だけを置く。

## 認証

Projects v2 は read に `read:project`、write に `project` scope が要る。不足していたら
**ユーザーに `gh auth refresh -s project` を案内する**（対話が要り、勝手にスコープを足さない）。

## ID 解決

`scripts/resolve-project.sh` が project ID・field ID・option ID・iteration ID を 1 回で返す。
`gh project field-list` は既定 30 件で打ち切るため、スクリプトは `--limit 200` を付け、
取得数が `totalCount` 未満なら失敗する。`totalCount` 欠落・型不正、`fields` が配列でない、
project id 欠落、field の id / name 欠落、Iteration に `configuration.iterations` が無い場合も
失敗する（黙って補完しない）。直接呼ぶときも `--limit` を明示する。

入力 JSON の形（`fields` / `totalCount` / `configuration.iterations` など）は gh のヘルプと
ソースからの推定で、実 API では未検証（この環境の token に `read:project` が無い）。

Iteration field は `configuration.iterations[]`（現在・未来）を持つ（推定）。
終了済みは `configuration.completedIterations[]` に分かれる。
現在のスプリントは `startDate <= today < startDate + duration 日` で選ぶ。

## GraphQL

`gh api graphql` で書き込むとき、mutation は承認の対象になる。読み取りは query を使う。

### mutation: single select の更新

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

### query: item の取得（cursor で続きを取る）

```bash
gh api graphql -f query='
  query($owner:String!,$number:Int!,$after:String) {
    user(login:$owner) {
      projectV2(number:$number) {
        items(first:100, after:$after) {
          pageInfo { hasNextPage endCursor }
          nodes { id content { ... on Issue { number title } } }
        }
      }
    }
  }' -F owner=OWNER -F number=NUMBER
```

org の場合は `user(...)` を `organization(...)` に置き換える。`hasNextPage` が true の間は
`-f after=<endCursor>` で続きを取る。取り切るまで「全件」と言わない。

## 落とし穴

| 落とし穴 | 症状 | 対応 |
| --- | --- | --- |
| project number と ID の混同 | `--project-id` に number を渡して失敗 | `resolve-project.sh` の `project_id`（`PVT_xxx`）を使う |
| user / org の取り違え | `Could not resolve to a node` | `--owner` を正しく指定。GraphQL は `user` / `organization` を切り替える |
| option / iteration を名前で渡す | `option not found` | ID を解決してから渡す |
| `item-add` の URL | `not a valid issue/pr URL` | `https://github.com/OWNER/REPO/issues/N` のフル URL |
| bulk のレート | `secondary rate limit` | 応答の待ち時間に従う。mutation を 1 リクエストに複数まとめる |
