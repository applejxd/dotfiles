# Design: `.claude` → `.copilot` 移植 技術設計サマリ

> 本書は ADR 群への索引と、移植の全体アーキテクチャを 1 ページで掴むための要約。
> 個別の判断根拠は各 ADR を参照。個別資産の仕様は [`skills.md`](./skills.md) / [`hooks.md`](./hooks.md)。

## ADR 索引

| ID | タイトル | 概要 |
| --- | --- | --- |
| [ADR-0001](./adr/0001-target-runtime-and-scope.md) | Target Runtime と移植スコープ | Copilot CLI のみ対象、12 資産、4 値ステータス |
| [ADR-0002](./adr/0002-skill-placement-and-naming.md) | Skill / Custom Slash Command の配置と命名規約 | `~/.copilot/skills/<name>/SKILL.md`、`criticalthink` も Skill 化 |
| [ADR-0003](./adr/0003-context-fork-to-custom-agent.md) | `context: fork` の翻訳方針 | skill 本文に Task ツール経由の subagent 起動指示を埋め込む |
| [ADR-0004](./adr/0004-hook-io-stdout-json.md) | Hook I/O は stdout JSON ベース | exit 2 + stderr → stdout JSON、fail-open |
| [ADR-0005](./adr/0005-permission-translation.md) | Permission モデルの翻訳則 | shell 系のみ翻訳、path 単位は hook 代替、`ask` は省略 |
| [ADR-0006](./adr/0006-environment-variable-translation.md) | `${CLAUDE_SKILL_DIR}` 等の翻訳 | chezmoi テンプレートで絶対パス静的置換 |
| [ADR-0007](./adr/0007-chezmoi-template-strategy.md) | chezmoi テンプレート戦略 | 既存 `modify_config.json` 拡張、変数を含む skill のみ `.tmpl` |

## 全体アーキテクチャ

```text
┌───────────────────────────────────────────────────────────────┐
│ chezmoi source: home/dot_copilot/                              │
│                                                                │
│ ├── modify_config.json (modify-template)                       │
│ │     ├─ allowed_urls (ADR-0005)                               │
│ │     └─ hooks.{preToolUse, postToolUse, sessionEnd} (ADR-0004)│
│ ├── mcp-config.json (既存)                                     │
│ ├── skills/<name>/                                             │
│ │     ├─ SKILL.md(.tmpl) (ADR-0002, ADR-0003, ADR-0006)        │
│ │     ├─ references/                                           │
│ │     └─ scripts/executable_*.sh                               │
│ └── hooks/executable_*.{py,sh} (ADR-0004)                      │
└───────────────┬───────────────────────────────────────────────┘
                │ chezmoi apply
                ▼
┌───────────────────────────────────────────────────────────────┐
│ ~/.copilot/                                                    │
│ ├── config.json   (Copilot CLI が起動時に settings.json へ rename)│
│ ├── mcp-config.json                                            │
│ ├── skills/<name>/SKILL.md ← Skill auto-discovery              │
│ └── hooks/executable_*.{py,sh} ← settings 内 hooks bind から呼出│
└───────────────────────────────────────────────────────────────┘
```

## 主要設計判断のサマリ

### 1. Skill 配置（ADR-0002）

- 全資産（旧 skill 6 + 旧 command 1）を **personal skill** として `~/.copilot/skills/<name>/SKILL.md` に配置
- 単一 `.md` だった `criticalthink` も Skill ディレクトリ化
- `.claude/skills/` 互換読み取りには依存しない（保険のみ）

### 2. サブエージェント実行（ADR-0003）

- Claude の `context: fork` は Copilot 側に対応物がない
- 代替: skill 本文の冒頭で「`Task` ツールで subagent を起動して以下を実行してください」と誘導
- 自動的な subagent 化は努力目標とし、必要に応じて Custom Agent (`*.agent.md`) を `tasks.md` で追加

### 3. Hook I/O（ADR-0004）

- 全 hook を **stdout JSON ベース** に書き換え
- ブロック: `{"permissionDecision":"deny","permissionDecisionReason":"..."}` を stdout、exit 0
- fail-open: JSON パース失敗・例外時は exit 0
- camelCase イベント名で統一
- `TaskCompleted` の代替なし → `update-adr-on-stop` は `partial`、`sessionEnd` で発火
- `PostToolUse` 経由の LLM フィードバックなし → `markdownlint` は `partial`、自動修正のみ。`format-file` は元 Claude 設定でも未 bind のため `dropped`

### 4. Permission 翻訳（ADR-0005）

| 元 | 先 | 備考 |
| --- | --- | --- |
| `Bash(cmd:*)` | `shell(cmd:*)` | ツール名のみ変換、永続化先は **TODO**（`permissions-config.json` 想定、REQ-044） |
| `Read(path)` / `Write(path)` | （直接対応物なし） | path 単位 deny は **`redirect-tmp` 拡張または同種の `preToolUse` hook 新設** で代替（REQ-041） |
| `WebFetch(domain:X)` | `allowedUrls: ["X"]` | settings.json |
| `mcp__server__tool` | `shell(server(tool))` 形式 | MCP ツール名構文 |

`ask` リスト 9 件は **何も書かない**（Copilot のデフォルト対話確認に委ねる）。
詳細は ADR-0005 / REQ-040〜044 を参照。

### 5. 環境変数置換（ADR-0006）

- `${CLAUDE_SKILL_DIR}` → chezmoi テンプレートで絶対パスへ静的置換
- `$ARGUMENTS` はそのまま残す（動作未確認・実装フェーズで検証）
- 静的置換が必要な skill: `adr`, `commit`, `fix`, `onboarding`

### 6. chezmoi 戦略（ADR-0007）

- 既存 `modify_config.json` を拡張（rename しない）
- 新規追加: `home/dot_copilot/skills/`, `home/dot_copilot/hooks/`
- chezmoi の `executable_` 接頭辞を維持
- `hooks` 配列は `concat + uniq` で merge する（既存 `allowed_urls` と同パターン）

## 失われる機能とその許容

| 失われる機能 | 影響資産 | 許容理由 |
| --- | --- | --- |
| `PostToolUse` stderr の LLM 再投入 | `markdownlint` | 自動修正効果は残る |
| `format-file` の機能（自動整形）全般 | `format-file` | 元 Claude 設定でも未 bind のため `dropped` |
| `TaskCompleted` の任意ターン発火 | `update-adr-on-stop` | `sessionEnd` で代替、起動頻度は減るが目的は達成 |
| `Read(path)` 単位の deny | （permission 翻訳時） | `redirect-tmp` hook の path 検査拡張で代替（REQ-041） |
| Claude の 3 段階 `ask` permission | （permission 翻訳時） | Copilot デフォルトの対話確認に委ねる |
| skill 本文の Claude 固有変数（`${CLAUDE_SKILL_DIR}`） | テンプレ化対象 4 skill | chezmoi の静的置換で代替 |

## クロスリファレンス

- 個別 skill / command 仕様: [`skills.md`](./skills.md)
- 個別 hook 仕様: [`hooks.md`](./hooks.md)
- 全体要件 EARS 文: [`requirements.md`](./requirements.md)
- 実装タスク: [`tasks.md`](./tasks.md)
- 移植ステータス索引: [`README.md`](./README.md)
