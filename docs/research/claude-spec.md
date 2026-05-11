# Claude Code: skills / hooks / custom slash commands 仕様サマリ

> 対象: Anthropic 公式 CLI コーディングエージェント `claude` (Claude Code)。
> 一次ソースは `docs.claude.com/en/docs/claude-code/...` 配下の公式ドキュメント。
> 本資料は抽象レベルの仕様整理であり、当リポジトリ固有の実装には言及しない。

## 1. Skills

### 1.1 概要

Skill は `SKILL.md` をエントリポイントとする **ディレクトリ単位の拡張機能**。Markdown 本文 + YAML フロントマターで構成し、Anthropic 主導の OSS 標準 [`agentskills`](https://github.com/agentskills/agentskills) に準拠する。Claude Code 独自の拡張として「呼び出し制御」「サブエージェント実行」「動的コンテキスト注入」が用意されている。

`description` で「いつ使うか」を Claude に示し、関連文脈で **自動 invocation** されるか、`/skill-name` で **手動 invocation** される。

### 1.2 配置場所（スコープと優先順位）

| スコープ | パス | 共有範囲 |
| --- | --- | --- |
| Enterprise | managed-settings 経由 | 組織全体 |
| Personal (User) | `~/.claude/skills/<name>/SKILL.md` | 自分の全プロジェクト |
| Project | `.claude/skills/<name>/SKILL.md` | 当該リポジトリ |
| Plugin | `<plugin>/skills/<name>/SKILL.md` | プラグイン有効時 |

- 名前衝突時の優先順: **Enterprise > Personal > Project**。Plugin は `plugin-name:skill-name` の名前空間を持ち衝突しない。
- `.claude/skills/` と `.claude/commands/` で同名がある場合は **Skill 優先**。
- セッション中の追加・編集・削除は **ライブ反映**（top-level ディレクトリの新規作成のみ要再起動）。
- `--add-dir` で追加されたディレクトリ内の `.claude/skills/` も自動ロード（subagents/commands は対象外）。
- モノレポでは作業中ファイルの上位ディレクトリの `.claude/skills/` も自動探索される。

### 1.3 ディレクトリ構成

```text
my-skill/
├── SKILL.md         # 必須エントリポイント
├── reference.md     # 参照ドキュメント（必要時のみ読み込み）
├── examples/...
└── scripts/         # Claude が実行可能な補助スクリプト
```

本文から `[reference.md](reference.md)` のように相対参照させる。

### 1.4 フロントマター主要フィールド

すべて optional（実質 `description` が必須）。

| フィールド | 用途 |
| --- | --- |
| `name` | 表示名 / `/コマンド名`。省略時はディレクトリ名。`[a-z0-9-]`、最大 64 文字 |
| `description` | いつ使うかを Claude に伝える主要根拠。省略時は本文先頭段落を採用。`when_to_use` と合算で **1,536 文字**で truncate |
| `when_to_use` | description の補助。トリガーフレーズ等 |
| `argument-hint` | autocomplete 表示用ヒント（例 `[issue-number]`） |
| `arguments` | `$name` 形式で参照する位置引数の名前（スペース区切り or YAML list） |
| `disable-model-invocation` | `true` で Claude による自動起動を無効化（手動 `/name` のみ） |
| `user-invocable` | `false` で `/` メニューから隠す（Claude のみ起動可） |
| `allowed-tools` | この skill 有効中、許可なしで使用できるツール一覧 |
| `model` | この skill 実行時のモデル上書き（`/model` と同じ値、または `inherit`） |
| `effort` | `low` / `medium` / `high` / `xhigh` / `max` |
| `context` | `fork` を指定するとサブエージェント context で実行 |
| `agent` | `context: fork` 時に使うサブエージェント種別 |
| `hooks` | この skill のライフサイクルにスコープした hooks（`once: true` も使用可） |
| `paths` | glob パターン。マッチするファイルを編集中のときだけ自動 invocation 候補化 |
| `shell` | `bash`（既定）/ `powershell`。`!` インラインシェル実行に影響 |

### 1.5 引数受け渡し（文字列置換）

- `$ARGUMENTS`: 渡された全引数。本文に出現しなければ末尾に `ARGUMENTS: <value>` として追記される
- `$ARGUMENTS[N]` / `$N`: 0-based の位置引数。シェル風 quoting に従う
- `$name`: `arguments:` で宣言した名前の置換
- 環境変数置換: `${CLAUDE_SESSION_ID}` / `${CLAUDE_EFFORT}` / `${CLAUDE_SKILL_DIR}`
- `${CLAUDE_SKILL_DIR}` は `SKILL.md` があるディレクトリを指す。バンドル script 参照に使う（cwd 非依存）

### 1.6 実行コンテキストとサブエージェント

- 既定では **メイン会話の単一メッセージ** として `SKILL.md` 本文が注入され、以後セッション内に常駐（再読み込みなし）
- `context: fork` を指定するとサブエージェント（`agent` で種別指定可）で実行され、メイン会話を汚染しない。副作用やトークン量の大きい task に向く
- 自動 compaction 時は最新 invocation を summary 後に再アタッチ（先頭 5,000 token）

### 1.7 自動 invocation のトリガー

- `description` + `when_to_use`（合計 1,536 char で truncate）が **常時 context に載る** "skill listing"。Claude はこれを見て invocation を決定する
- `disable-model-invocation: true` で listing から外れ、手動のみとなる
- `paths` を設定した skill は対象パターンのファイルを扱うときのみ自動 invocation 候補

## 2. Hooks

### 2.1 概要

Claude Code のライフサイクル特定点で自動実行される、ユーザ定義の **シェルコマンド / HTTP エンドポイント / MCP ツール / LLM プロンプト / サブエージェント**。

### 2.2 主要イベント

| カテゴリ | イベント |
| --- | --- |
| セッション粒度 | `SessionStart`, `SessionEnd` |
| ターン粒度 | `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `StopFailure` |
| ツールループ | `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `PermissionRequest`, `PermissionDenied` |
| サブエージェント / タスク | `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `TeammateIdle` |
| 通知 / ファイル / 環境 | `Notification`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `FileChanged` |
| Worktree | `WorktreeCreate`, `WorktreeRemove` |
| Compaction | `PreCompact`, `PostCompact` |
| MCP elicitation | `Elicitation`, `ElicitationResult` |

### 2.3 設定階層

| 場所 | スコープ |
| --- | --- |
| `~/.claude/settings.json` | User |
| `.claude/settings.json` | Project（コミット可） |
| `.claude/settings.local.json` | Local（gitignored） |
| Managed policy | 組織全体 |
| Plugin `hooks/hooks.json` | プラグイン有効時 |
| Skill / sub-agent frontmatter `hooks:` | コンポーネントが active な間のみ |

`disableAllHooks: true` で一括無効化（managed hooks の無効化は managed 階層からのみ）。`/hooks` で読み取り専用ブラウザを開ける。

### 2.4 設定スキーマ（3 階層）

```json
{
  "hooks": {
    "<EventName>": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "if": "Bash(rm *)", "command": "...", "timeout": 600 }
        ]
      }
    ]
  }
}
```

- 外側の event 名キー → 配列（matcher group）→ 内側の `hooks` 配列（handler）の **3 階層**構造
- `matcher` の評価規則:
  - `"*"` / `""` / 省略 → 全マッチ
  - 英数字 / `_` / `|` のみ → exact 文字列、または `|` 区切りの exact 列挙
  - その他文字を含む → JavaScript 正規表現（例 `^Notebook`, `mcp__memory__.*`）
- 一部イベントは matcher 非対応（`UserPromptSubmit`, `Stop`, `PostToolBatch`, `TeammateIdle`, `TaskCreated`, `TaskCompleted`, `WorktreeCreate/Remove`, `CwdChanged` など）
- ツールイベントでは handler 単位で `if: "Bash(git *)"` のように **permission rule 構文**で更に絞り込める

### 2.5 Handler 種別

| `type` | 主要フィールド |
| --- | --- |
| `command` | `command`, `shell` (`bash`/`powershell`), `async`, `asyncRewake` |
| `http` | `url`, `headers`, `allowedEnvVars`（`$VAR` 補間は allowlist 必須） |
| `mcp_tool` | `server`, `tool`, `input`（`${tool_input.file_path}` 等の補間可） |
| `prompt` | `prompt`（`$ARGUMENTS` 置換）, `model` |
| `agent` | `prompt`, `model`（experimental） |

共通: `if`, `timeout`（command 600s / prompt 30s / agent 60s）, `statusMessage`, `once`（skill frontmatter 限定）

### 2.6 入力 IF（stdin / POST body の JSON 共通フィールド）

| フィールド | 内容 |
| --- | --- |
| `session_id` | セッション ID |
| `transcript_path` | 会話 JSON への絶対パス |
| `cwd` | hook 起動時の作業ディレクトリ |
| `permission_mode` | `default` / `plan` / `acceptEdits` / `auto` / `dontAsk` / `bypassPermissions` |
| `hook_event_name` | イベント名 |
| `tool_name`, `tool_input` | ツール系イベントのみ |
| `agent_id`, `agent_type` | サブエージェント実行中のみ |

参照用環境変数: `$CLAUDE_PROJECT_DIR`, `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `$CLAUDE_CODE_REMOTE`

### 2.7 出力 IF（command hook）

- **exit 0**: 成功。stdout が JSON ならパースされ decision 制御に使われる。`UserPromptSubmit` / `UserPromptExpansion` / `SessionStart` のみ stdout は context に追加されて Claude から見える
- **exit 2**: ブロッキングエラー。stderr が Claude にフィードバック。イベント毎に効果が異なる:
  - `PreToolUse` → ツール呼び出しブロック
  - `UserPromptSubmit` → プロンプト破棄
  - `Stop` / `SubagentStop` → 停止防止
  - `PostToolUse` 系は「すでに実行済み」のため stderr が Claude に表示されるのみ
- **その他 exit code**: 非ブロッキングエラー、transcript に通知のみ
- HTTP hook は status code/body で表現:
  - 2xx + JSON → command hook の JSON output と同等
  - 非 2xx / 接続失敗 → 非ブロッキングエラー（block するには 2xx で `decision: "block"` を返す）

### 2.8 JSON output（細粒度制御）

- 共通: `continue`, `stopReason`, `suppressOutput`, `systemMessage`
- `decision: "block"` + `reason`（`PostToolUse`, `Stop`, `UserPromptSubmit` 等）
- `PreToolUse`: `hookSpecificOutput.permissionDecision`（`allow` / `deny` / `ask` / `defer`） + `permissionDecisionReason`、`updatedInput` で入力上書きや context 注入
- `PermissionRequest`: `hookSpecificOutput.decision.behavior`（`allow` / `deny`）
- `PermissionDenied`: `hookSpecificOutput.retry: true` で再試行を許可
- 出力は 10,000 文字で truncate（超過分は別ファイル化）

### 2.9 Skill / サブエージェント内の hooks

- skill / agent の frontmatter に `hooks:` を書ける（settings と同じスキーマ）
- 当該コンポーネントが active な間だけ動作し、終了時にクリーンアップ
- subagent では `Stop` が `SubagentStop` に自動変換

## 3. Custom Slash Commands

### 3.1 Skills との関係

公式 docs によれば **「Custom commands は Skills に統合された」**。

- `.claude/commands/deploy.md` と `.claude/skills/deploy/SKILL.md` はどちらも `/deploy` を提供し挙動も同じ
- 旧 `.claude/commands/*.md` は引き続き動作し、**Skill と同じフロントマターをサポート** する
- 同名衝突時は Skill が優先

### 3.2 配置場所

| 場所 | スコープ |
| --- | --- |
| `~/.claude/commands/` | User |
| `.claude/commands/` | Project |
| Plugin の `commands/` | プラグイン |

`--add-dir` で追加したディレクトリの `commands/` は **自動ロードされない**（skills とは異なる挙動）。

### 3.3 Skill との実効的な違い

- ディレクトリ + 補助ファイルを持てない（単一 `.md`）
- `${CLAUDE_SKILL_DIR}` のような skill 固有変数は `SKILL.md` 用
- それ以外（フロントマター、`$ARGUMENTS` 置換、`disable-model-invocation`、`allowed-tools`、`argument-hint`、`model` 等）は同様
- 複雑化しそうなら Skill 化が公式推奨

## 4. settings.json スキーマ

### 4.1 ファイル階層と優先順位

1. Managed (server / MDM / `managed-settings.json` / drop-in `managed-settings.d/*.json`)
2. CLI 引数
3. Local: `.claude/settings.local.json`
4. Project: `.claude/settings.json`
5. User: `~/.claude/settings.json`

JSON Schema: `https://json.schemastore.org/claude-code-settings.json`（`$schema` で指定すると IDE 補完が効く）。
他の状態は `~/.claude.json`（OAuth、MCP のユーザー/ローカル設定、プロジェクト固有 trust など）。

### 4.2 主要トップレベルキー

| キー | 概要 |
| --- | --- |
| `permissions` | `allow` / `ask` / `deny` ルール、`defaultMode`、`disableBypassPermissionsMode` 等 |
| `hooks` | 上記 hooks スキーマ |
| `env` | セッション環境変数のマップ |
| `agent` | メインスレッドを名前付き subagent として実行 |
| `includeCoAuthoredBy` | Git コミットの `Co-authored-by: Claude` トレイラー（**deprecated**, 後継 `attribution`） |
| `includeGitInstructions` | Claude のシステムプロンプトに git 指示と status を含めるか |
| `effortLevel`, `alwaysThinkingEnabled` | 思考量の制御 |
| `statusLine` | カスタムステータス行 (`{type, command}`) |
| `editorMode`, `viewMode`, `tui`, `terminalProgressBarEnabled` | UI 設定 |
| `enableAllProjectMcpServers`, `enabledMcpjsonServers`, `disabledMcpjsonServers` | プロジェクト MCP 制御 |
| `companyAnnouncements` | セッション開始時に表示する文言 |
| `forceLoginMethod`, `forceLoginOrgUUID` | ログイン制限 |
| `allowManagedHooksOnly`, `allowManagedPermissionRulesOnly`, `allowedHttpHookUrls`, `httpHookAllowedEnvVars` | ガバナンス系（Managed 中心） |
| `disableAllHooks`, `disableSkillShellExecution` | セキュリティ／無効化 |
| `language`, `voice` | 出力言語・音声 |

### 4.3 permission rule 構文

- 形式: `Tool` または `Tool(specifier)`
- 評価順: **deny → ask → allow**（先勝ち）
- ツール例:
  - `Bash(npm run build)`: 完全一致
  - `Bash(npm run *)`: prefix（`*` は空白を含み得る）
  - `Bash(git * main)`: 中間ワイルドカード
  - `Bash(ls *)` と `Bash(ls*)` は別物（前者は `ls -la` のみ、後者は `lsof` も match）
  - `Bash(ls:*)` は `Bash(ls *)` と等価（`:*` は末尾のみ）
  - `Read(./.env)`, `Read(./secrets/**)`: パスパターン
  - `WebFetch(domain:example.com)`: ドメイン指定
- パターン無し（`Bash`）= 全件マッチ。`Bash(*)` も同義

### 4.4 サンプル

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": ["Bash(npm run lint)", "Bash(npm run test *)", "Read(~/.zshrc)"],
    "deny":  ["Bash(curl *)", "Read(./.env)", "Read(./.env.*)", "Read(./secrets/**)"]
  },
  "env": { "CLAUDE_CODE_ENABLE_TELEMETRY": "1" },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [
          { "type": "command", "if": "Bash(rm *)",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/block-rm.sh" }
        ] }
    ]
  }
}
```

## 出典

- <https://docs.claude.com/en/docs/claude-code/skills>
- <https://docs.claude.com/en/docs/claude-code/slash-commands>（現在は skills ページにリダイレクト相当）
- <https://docs.claude.com/en/docs/claude-code/hooks>
- <https://docs.claude.com/en/docs/claude-code/settings>
- <https://docs.claude.com/en/docs/claude-code/permissions>
- <https://docs.claude.com/en/docs/claude-code/commands>（built-in command 一覧）

## TODO: 要確認

- `code.claude.com/docs/en/skills` などの新ドメイン側 docs の差分確認
- `agent-teams`（teammate / `TeammateIdle`）の詳細スキーマ、および `SubagentStart` の matcher 値の網羅
- `.claude/commands/*.md` でサポートされるフロントマターのうち `model` / `effort` / `context: fork` / `paths` などが完全に同等か
- `hooks` 内 handler の `prompt` / `agent` 型の出力 JSON スキーマ詳細
- `settings.json` の全キー網羅 — `permissions.defaultMode` 周辺や `attribution`（`includeCoAuthoredBy` の後継）の正式スキーマ
