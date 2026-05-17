---
name: github-issue
description: "GitHub issue の CRUD・コメント・ラベル・assignee 操作と、GitHub Projects v2 のカスタムフィールド更新を行う。「issue 作って」「issue を Project に入れて」「Project のステータスを In Progress にして」等で使う。標準操作は github MCP、Projects v2 は gh CLI を使い分ける。"
context: fork
agent: general-purpose
allowed-tools: mcp__github__*, Bash(gh project list:*), Bash(gh project view:*), Bash(gh project field-list:*), Bash(gh project item-list:*), Bash(gh issue view:*), Bash(gh issue list:*), Bash(gh api graphql:*), Bash(gh auth status:*), Bash(*resolve-project.sh*), Bash(*add-issue-to-project.sh*), Bash(*set-project-field.sh*)
---

# github-issue skill

GitHub issue の標準操作は **github MCP** で、GitHub Projects v2 のカスタム
フィールド操作は **gh CLI** で行う。両者の役割分担を明確にし、典型的な
エンドツーエンド手順を再現可能にするための skill。

## 適用範囲

- Issue の作成 / 取得 / 更新 / 検索 / コメント / ラベル / assignee / クローズ
- Issue を Projects v2 に追加 / 除去
- Projects v2 のカスタムフィールド（Single select / Iteration / Date / Number / Text）の更新
- Projects v2 の bulk 操作（GraphQL 経由）

スコープ外:

- Projects (classic) — 既に GitHub から廃止予定であり扱わない
- リポジトリ管理（branch / release / workflow 等）— 別 skill に委ねる
- GitHub MCP server / `gh auth` のセットアップ — 前提として済んでいる想定

## 前提確認（1 メッセージにまとめて質問）

ユーザー指示から下記が不足している場合のみ、まとめて確認する:

1. **対象リポジトリ**: `owner/repo`
2. **対象 Project**: owner（user / org）+ project number（`gh project list --owner OWNER` で取得可能）
3. **対象 issue**: number または URL（作成系の場合は title / body の素材）
4. **目的とする操作**: 例「Status を In Progress にして、Iteration を current sprint にする」
5. **破壊的操作の許容**: クローズ / item-delete / item-archive を伴うか

会話の文脈で答えが既に明らかな項目は再確認しない。

## 役割分担（must read）

| 操作 | 手段 | 補足 |
|---|---|---|
| Issue CRUD / コメント / ラベル / assignee / 検索 | **github MCP** (`mcp__github__*`) | 構造化 JSON で扱える、認証共有 |
| Project への issue 追加・除去 | **gh CLI** (`gh project item-add` / `item-archive` / `item-delete`) | MCP 未提供 |
| Project カスタムフィールド更新 | **gh CLI** (`gh project item-edit`) | field / option ID 解決が必要 |
| Projects v2 GraphQL（bulk / 詳細取得） | `gh api graphql` | item-edit でカバーできないケース |

判断に迷ったらまず MCP を試し、ツールが存在しない / Projects v2 領域なら
`gh` にフォールバックする。

## 判断フロー

1. **Issue 単体への操作か?** → github MCP の対応ツールを参照
   - 早見表: `${CLAUDE_SKILL_DIR}/references/github-mcp-issue.md`
   - フォールバック: `~/.claude/skills/github-issue/references/github-mcp-issue.md`
2. **Projects v2 が関わるか?** → gh CLI を使う
   - 早見表と落とし穴: `${CLAUDE_SKILL_DIR}/references/gh-projects-cli.md`
   - フォールバック: `~/.claude/skills/github-issue/references/gh-projects-cli.md`
3. **エンドツーエンドな典型手順か?** → workflows を参照
   - `${CLAUDE_SKILL_DIR}/references/workflows.md`
   - フォールバック: `~/.claude/skills/github-issue/references/workflows.md`

Copilot CLI では `${CLAUDE_SKILL_DIR}` が展開されないため、絶対パス
（`~/.claude/skills/github-issue/...`）の方を採用する。Claude Code では
どちらでも動くが `${CLAUDE_SKILL_DIR}` を優先。

## Projects カスタムフィールド更新の標準 3 ステップ

同梱スクリプトは `~/.claude/skills/github-issue/scripts/` 配下にある。
Copilot からも同じパス（`~/.copilot/skills/github-issue/scripts/` の symlink 経由）で見える。

### Step 1: project と field の ID 解決

```bash
~/.claude/skills/github-issue/scripts/resolve-project.sh <owner> <project-number>
```

出力（例）:

```json
{
  "project_id": "PVT_xxx",
  "fields": {
    "Status": {
      "id": "PVTSSF_xxx",
      "type": "ProjectV2SingleSelectField",
      "options": { "Todo": "...", "In Progress": "...", "Done": "..." }
    },
    "Iteration": {
      "id": "PVTIF_xxx",
      "type": "ProjectV2IterationField",
      "iterations": { "Sprint 12": "..." }
    },
    "Priority": {
      "id": "PVTSSF_xxx",
      "type": "ProjectV2SingleSelectField",
      "options": { "P0": "...", "P1": "..." }
    }
  }
}
```

エージェントはこの JSON をセッション内に保持し、以降の呼び出しで参照する。

### Step 2: issue を project に追加（itemId 取得）

```bash
~/.claude/skills/github-issue/scripts/add-issue-to-project.sh \
  <project-id> <issue-url>
```

既に登録済みの場合は冪等に既存 itemId を返す。

### Step 3: カスタムフィールド更新

```bash
~/.claude/skills/github-issue/scripts/set-project-field.sh \
  <project-id> <item-id> <field-id> <type> <value>
```

`<type>` は `single_select` / `iteration` / `date` / `number` / `text`。
`single_select` / `iteration` の場合、`<value>` は **option ID / iteration ID**
（resolve 済みの値）を渡す。

## 典型ワークフロー

代表 3 パターンを `references/workflows.md` に時系列で記載:

1. issue を作って Project に入れて Status=In Progress にする
2. issue 一覧から Priority フィールドだけ bulk 更新する
3. Iteration を現在スプリントに設定する

## ポリシー

**禁止 / 必ず承認をとる**:

- 破壊的操作（`gh issue close` / `gh project item-delete` / `item-archive`、
  MCP の `update_issue` で state を closed にする等）は **ユーザー承認後のみ**
- secret / token を stdout に echo しない（`gh auth status` の token 部分も含む）
- MCP がカバーしている操作を `gh issue` の書込系で代替しない（権限粒度を粗くする）

**推奨**:

- 書込前に dry-run: `--format json` で取得 → ユーザーに提示 → 承認 → 実行
- 同じ field を複数 issue に適用する bulk 操作は GraphQL の `mutation` を
  1 リクエストにまとめる（API レート節約）
- `gh auth refresh -s project` が必要なエラーが出たら、**自動実行はせず**
  ユーザーに案内する（対話を要するため）

**前提が崩れていたら停止**:

- github MCP 未接続（Claude 側で `mcp__github__*` ツールが見えない）→ セットアップ後に再実行を依頼
- `gh auth status` で project scope 不足 → `gh auth refresh -s project` を案内

## 検証チェック（skill 開発者向け）

- `uv run pre-commit run --all-files`
- `mise exec shellcheck -- home/dot_claude/skills/github-issue/scripts/*.sh`
- 実環境テスト: 個人 sandbox repo + Project で resolve → add → set を一連実行
