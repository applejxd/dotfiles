# GitHub MCP: Issue 操作早見表

> github-mcp-server が提供する issue 関連ツールの早見表。
> Copilot CLI では内蔵 `github-mcp-server` が最初から有効。
> Claude Code では `home/dot_claude/modify_settings.json.py.tmpl` 等で
> 個別有効化が必要（このスキルは「MCP が使える前提」で書く）。

## 認証

- MCP server 側で済んでいる前提。エージェントは PAT を扱わない。
- 失敗時の典型エラー: `401 Bad credentials` / `403 Resource not accessible`
- 対応: ユーザーに `gh auth status` の確認と、MCP server 再認証を案内する

## ツール対応表（よく使うもの）

| やりたいこと | MCP ツール | 主な引数 |
| --- | --- | --- |
| issue 詳細を取る | `mcp__github__issue_read` (method=`get`) | `owner`, `repo`, `issue_number` |
| コメント一覧 | `mcp__github__issue_read` (method=`get_comments`) | 同上 |
| ラベル一覧 | `mcp__github__issue_read` (method=`get_labels`) | 同上 |
| issue 検索（自リポ） | `mcp__github__list_issues` | `owner`, `repo`, `state`, `labels` |
| issue 検索（横断） | `mcp__github__search_issues` | `query` (GitHub search syntax) |
| issue 作成 | `mcp__github__create_issue` | `owner`, `repo`, `title`, `body`, `labels`, `assignees` |
| issue 更新（title/body/state/labels/assignees/milestone） | `mcp__github__update_issue` | 同上 + `issue_number` |
| コメント追加 | `mcp__github__add_issue_comment` | `owner`, `repo`, `issue_number`, `body` |
| ラベル付与 | `mcp__github__add_labels` | `owner`, `repo`, `issue_number`, `labels[]` |
| assignee 変更 | `mcp__github__assign_issue` または `update_issue` | `assignees[]` |
| sub-issue 一覧 | `mcp__github__issue_read` (method=`get_sub_issues`) | `issue_number` |

> ツール名・引数名は github-mcp-server の実装に依存する。実行前に
> `/mcp` でツール一覧を確認するか、エラー時はツール名を引数なしで叩いて
> スキーマを取得する。

## できないこと（gh CLI にフォールバック）

- **Projects v2 全般** — `add_to_project` / `set_project_field` 相当の MCP ツールはない
  - issue を project に追加 → `gh project item-add`
  - field 更新 → `gh project item-edit` / `gh api graphql`
  - 詳細は `gh-projects-cli.md` を参照
- **複雑な GraphQL クエリ** — `gh api graphql` を使う
- **リリース / branch protection / Actions の起動 等** — 別 skill / 別ツール

## 典型 prompt 例

### issue 作成

```text
mcp__github__create_issue を呼んで:
  owner=octocat repo=hello-world
  title="Bug: foo crashes on bar"
  body="## Repro\n1. ...\n2. ..."
  labels=["bug","priority:high"]
  assignees=["alice"]
```

戻り値の `number` と `html_url` を以降のステップ（Project 追加など）に使う。

### issue 検索 → 一括コメント

1. `mcp__github__search_issues` で `query='repo:octocat/hello-world is:open label:stale'`
2. 取得した issue 群に対して `mcp__github__add_issue_comment` を順に呼ぶ
   （bulk が必要ならエージェント側でループ。レート制限に注意）

### issue クローズ（要承認）

```text
mcp__github__update_issue で state=closed
  owner=... repo=... issue_number=...
  state_reason="completed"  # or "not_planned"
```

クローズは破壊的操作。**必ずユーザー承認を得てから実行**。
