# GitHub Copilot CLI: skills / hooks / custom agents 仕様サマリ

> 対象は `@github/copilot` パッケージで提供される対話型 CLI（`copilot` コマンド）。
> Copilot Coding Agent (cloud) や Copilot Chat in IDE とは **別物** として扱う。
> 一次ソースは `fetch_copilot_cli_documentation` の出力と `docs.github.com` の公式ドキュメント。
> 末尾に Claude Code → Copilot CLI の **概念マッピング章** を置く。

## 0. 全体像（カスタマイズ手段の整理）

公式の "Comparing CLI features" によれば、Copilot CLI のカスタマイズ手段は次のとおり。**「Custom Slash Commands」という独立第一級概念は公式 docs には存在しない**（Skills が同等の役割を担う）。

| 機能 | 役割 | 配置例 |
| --- | --- | --- |
| Custom Instructions | 振る舞いの常時ガイダンス | `AGENTS.md`, `.github/copilot-instructions.md`, `~/.copilot/copilot-instructions.md` |
| **Skills** | 特定タスク向けの just-in-time な手順（≒ 動的に発火する slash command） | `.github/skills/`, `.claude/skills/`, `.agents/skills/`, `~/.copilot/skills/`, `~/.agents/skills/` |
| Tools | 個々の能力（read/edit/shell 等）。基本ユーザは直接呼ばない | 内蔵 + MCP 由来 |
| MCP servers | 外部ツール群を一括追加 | `~/.copilot/mcp-config.json`, `.mcp.json`, `.github/mcp.json` |
| **Hooks** | ライフサイクル時点で任意コマンド実行 | `~/.copilot/hooks/`, `.github/hooks/`, `settings.json` の `hooks` |
| Subagents（内蔵） | `explore` / `task` / `general-purpose` | 不要（メインエージェントが選択） |
| Custom Agents | 特化サブエージェントの定義 | `.github/agents/*.agent.md`, `~/.copilot/agents/*.agent.md` |
| Plugins | 上記を束ねた配布パッケージ | `installed-plugins/`, marketplace |

## 1. Skills

公式名称: **Agent Skills**。Anthropic の `agentskills` オープン標準に準拠し、Copilot CLI / Copilot cloud agent / VS Code agent mode で共通に使える。

### 1.1 配置ディレクトリ

| 種別 | パス |
| --- | --- |
| Project skills | `.github/skills/`, `.claude/skills/`, `.agents/skills/`（リポジトリ直下） |
| Personal skills | `~/.copilot/skills/`, `~/.agents/skills/` |
| 追加検索パス | 環境変数 `COPILOT_SKILLS_DIRS`（カンマ区切り） |

precedence: **同名は project が personal を上書き**。

### 1.2 ファイル構造

各 skill は **サブディレクトリ** + 内部の **`SKILL.md`**（ファイル名固定）。任意で同梱スクリプトや参考 Markdown を同居可能。

```markdown
---
name: github-actions-failure-debugging   # 必須・lowercase + hyphen
description: ...                         # 必須（発火判定に使われる）
license: MIT                             # 任意
allowed-tools: shell                     # 任意・事前承認するツール
---

# 任意の Markdown 本文（手順、例、ガイドライン）
```

- `name` / `description` は **必須**。`description` が Copilot のスキル選択における最重要メタ情報
- `allowed-tools` を指定すると、その skill 実行中だけ確認なしでツールを使える。`shell`/`bash` 事前承認は警告ベースで非推奨
- スクリプト同梱の場合、Copilot は skill ディレクトリの全ファイルを自動 discover する

### 1.3 発火・呼び出し

- **手動**: `/SKILL-NAME [args]`（例: `/Markdown-Checker check README.md`）
- **自動**: Copilot が prompt と skill description を見て関連性を判定し自動 invoke
- 管理: `/skills [list|info|add|remove|reload]`
- 無効化: `settings.json` の `disabledSkills`

### 1.4 Claude / 標準互換

- **`.claude/skills` を project skill のひとつとして公式にサポート**
- `agentskills` という独立 OSS 仕様に準拠しており、`anthropics/skills` や `github/awesome-copilot` のスキルがそのまま利用できる
- `gh skill` GitHub CLI 拡張で marketplace 的 install も可能

## 2. Hooks

**Copilot CLI には公式の hooks 機構があり、Claude Code との互換性が意図的に保たれている**（PascalCase / camelCase イベント名どちらも受理、Claude のネスト構造 `matcher` / `hooks` も受理）。

- リファレンス: "Hooks configuration" および "Using hooks with GitHub Copilot CLI"
- Cloud agent と CLI で同じ仕様を共有
- SDK (`@github/copilot-sdk`) からプログラム的にも登録可能（`onPreToolUse` 等のコールバック）

### 2.1 イベント一覧

| イベント名 | タイミング | output 解釈 |
| --- | --- | --- |
| `sessionStart` | セッション開始 / resume / startup | `additionalContext` のみ会話に注入 |
| `sessionEnd` | セッション完了・エラー・abort・timeout・user_exit | 無視 |
| `userPromptSubmitted` | ユーザープロンプト送信時 | **prompt の改変は不可**、`additionalContext` 等の注入は可 |
| `preToolUse` | ツール実行直前 | `permissionDecision`（allow/deny/ask）、`modifiedArgs`、`additionalContext`、`suppressOutput` |
| `postToolUse` | ツール正常終了後 | 無視（result 改変は不可） |
| `postToolUseFailure` | ツール失敗時（changelog） | — |
| `errorOccurred` | エージェント実行中のエラー | 無視 |
| `notification` | shell 完了 / permission prompt / elicitation / agent 完了（非同期） | — |
| `PermissionRequest` | ツール権限要求の許可/拒否を script で制御（changelog） | allow / deny |
| `subagentStart` | subagent spawn 時 | `additionalContext` |
| `preCompact` | コンテキスト compaction 開始前（changelog） | — |

> イベント名は VS Code / Claude Code 互換のため PascalCase / camelCase 両方を受理。ペイロードは `hook_event_name` / `session_id` / ISO 8601 timestamp を含む snake_case 版に変換される。

### 2.2 入出力 IF

- **入力**: stdin に JSON。共通フィールド `timestamp` (ms)、`cwd`。イベント固有フィールド（例: `preToolUse` なら `toolName`, `toolArgs`）
- **環境変数**: `PLUGIN_ROOT`, `COPILOT_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_DATA`（plugin hook 用）。テンプレート変数 `{{project_dir}}`, `{{plugin_data_dir}}` も使える
- **出力**: stdout に **コンパクトな単一行 JSON**（`jq -c` / `ConvertTo-Json -Compress` 推奨）
- **exit code**: `0` 推奨。`set -e` してエラー時は非 0
- **stderr**: ログ用途（debug 時 `set -x` で stderr 出力）。LLM への直接フィードバックは output JSON 経由が基本
- **タイムアウト**: 既定 30 秒。`timeoutSec`（または alias `timeout`）で延長可
- **matcher**: `preToolUse.matcher` は **ツール名にフルマッチする正規表現**（途中マッチではない）

### 2.3 設定スキーマ

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "matcher": "^bash$",
        "bash": "./scripts/pre-tool-policy.sh",
        "powershell": "./scripts/pre-tool-policy.ps1",
        "command": "./scripts/pre-tool-policy.sh",
        "cwd": ".github/hooks",
        "timeoutSec": 30,
        "env": { "LOG_LEVEL": "INFO" }
      }
    ]
  }
}
```

- `version: 1` 必須（changelog で omit も許容に変更されたが明記推奨）
- `disableAllHooks: true` で当該設定ファイルの全 hook を無効化可
- HTTP hook もサポート: ローカルコマンドの代わりに configured URL に JSON を POST 可能

### 2.4 配置場所（時系列で順に拡張された）

1. リポジトリ単位: `.github/hooks/*.json`（CLI ではカレントディレクトリ起点）
2. プラグイン単位: plugin 内の `hooks.json`
3. ユーザー単位: `~/.copilot/hooks/`（personal hooks）
4. **`~/.copilot/config.json` / `~/.copilot/settings.json` / `settings.local.json` 内の `hooks` セクション** に直接記述可能

### 2.5 blocking / non-blocking

- **blocking**: `preToolUse`, `userPromptSubmitted`, `sessionStart` 等は同期実行
  - `preToolUse` は `permissionDecision: "deny"` で実行を完全ブロック、`"ask"` でユーザー承認プロンプト、`"allow"` で承認プロンプト自体を抑止
- **non-blocking**: `notification` は非同期発火。`postToolUse`, `errorOccurred`, `sessionEnd` は output が無視される（≒ fire-and-forget）

### 2.6 LLM へのフィードバック手段

- `additionalContext`（`sessionStart` / `subagentStart` / `userPromptSubmitted` / `preToolUse` 等で会話に注入）
- `permissionDecisionReason`（deny/ask の理由文字列をユーザーに表示）
- `modifiedArgs`（preToolUse のみ、ツール引数を上書き）
- `suppressOutput`（preToolUse のみ、ツール出力を会話から除外）

## 3. Custom Slash Commands

**Copilot CLI に独立した「カスタムスラッシュコマンド」概念は存在しない**。同等の役割は **Skills が担う**。

- 公式の Comparing features ページにも「You can manually invoke a skill by using a slash command. For example, `/Markdown-Checker check README.md`」と明示
- 「Copilot CLI が `~/.claude/commands/*.md` を slash command として直接読む」という記述は公式 docs では確認できない
- ただし `.claude/skills/` は project skills として公式サポートされるため、Claude の **Skill** はそのまま流用できる

## 4. Custom Agents

### 4.1 配置と形式

- ファイル名: `*.agent.md`（または `*.md` も可、`.agent.md` 推奨）
- パス:
  - Project: `.github/agents/CUSTOM-AGENT-NAME.agent.md`
  - Personal: `~/.copilot/agents/CUSTOM-AGENT-NAME.agent.md`
  - 組織 / Enterprise: `.github-private` リポジトリの `/agents/`
- precedence: **personal > project**（公式 create-custom-agents-for-cli の Note。Skills とは方向が逆なので注意）
- YAML frontmatter:
  - `name`（任意・display 名。省略時はファイル名）
  - `description`（発火判定に使用）
  - `tools`（任意。省略 or `["*"]` で全ツール、`[]` で全禁止、`some-mcp-server/*` で MCP 全許可、`some-mcp-server/some-tool` で個別許可）
  - `mcp-servers`（任意。当エージェント専用の MCP 設定）
  - `argument-hint` / `handoffs` は VS Code 由来で **CLI / cloud では無視**（互換のため許容）
- 本文（プロンプト）は Markdown、最大 30,000 文字

### 4.2 ツール alias

| Primary | Compatible |
| --- | --- |
| `execute` | `shell`, `Bash`, `powershell` |
| `read` | `Read`, `NotebookRead` |
| `edit` | `Edit`, `MultiEdit`, `Write`, `NotebookEdit` |
| `search` | `Grep`, `Glob` |
| `agent` | `custom-agent`, `Task` |
| `web` | `WebSearch`, `WebFetch` |
| `todo` | `TodoWrite` |

未知のツール名は無視（プロダクト間互換のため）。

### 4.3 呼び出し方法

- `/agent`：一覧から選択（**内蔵 explore / task / general-purpose は表示されない**）
- 推論: prompt と description から自動選択
- 明示: `Use the security-auditor agent on ...` または `@security-auditor ...`
- プログラム実行: `copilot --agent security-auditor --prompt "..."`

### 4.4 内蔵 subagent

- `explore` — 読み取り専用の高速コードベース探索（並列呼び出し可）
- `task` — テスト / ビルド / lint 等の実行と要約
- `general-purpose` — メインと同等の完全権限

## 5. Fleet / 並列実行

- スラッシュコマンド: `/fleet [PROMPT]`
- 動作: メインエージェントが prompt をサブタスクに分割し、依存関係を見て **オーケストレータとして並列実行**。各 subagent は独立した context window を持つ
- Custom agent との連携: 並列 subagent が状況に応じて custom agent を選択。`@custom-agent` で指名可
- 並列度の制御:
  - 環境変数 `COPILOT_SUBAGENT_MAX_CONCURRENT` (default 32, range 1–256)
  - 環境変数 `COPILOT_SUBAGENT_MAX_DEPTH` (default 6, range 1–256)
- Plan モード連携: `Shift+Tab` で plan / autopilot を切り替えた上で、計画作成 → "Accept plan and build on autopilot + /fleet" で実行が定石

## 6. MCP 連携

### 6.1 設定ファイル

- User: `~/.copilot/mcp-config.json`
- Repository: `.mcp.json` / `.github/mcp.json`
- セッション限定追加: `--additional-mcp-config=JSON | @path/to/file`

precedence: project > user（同名サーバ）。

### 6.2 スキーマ

```jsonc
{
  "mcpServers": {
    "<name>": {
      "type": "local" | "stdio" | "http" | "sse",  // local と stdio は同義
      // local/stdio:
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": { "API_KEY": "..." },
      // http/sse:
      "url": "https://...",
      "headers": { "...": "..." },
      // 共通:
      "tools": ["*"]
    }
  }
}
```

- 内蔵 `github-mcp-server` は最初から有効。`--disable-builtin-mcps` で無効化、`--add-github-mcp-tool=*` / `--add-github-mcp-toolset=all` で公開範囲を拡張
- `/mcp [show|add|edit|delete|disable|enable|auth|reload]` で対話管理
- `tools` は `*` で全公開、配列指定で限定

## 7. settings.json スキーマ

### 7.1 場所と階層

`config.json` は **`settings.json` にリネーム済み**で、起動時に自動マイグレートされる。

| Scope | Path | 用途 |
| --- | --- | --- |
| User | `~/.copilot/settings.json`（`COPILOT_HOME` で変更可） | 全セッション既定 |
| Repository | `.github/copilot/settings.json` | チーム共有設定 |
| Local | `.github/copilot/settings.local.json` | 個人差分（gitignore 推奨） |

CLI オプション > 環境変数 > local > repository > user の順で precedence。JSONC（コメント可）。

### 7.2 主な user settings キー（抜粋）

| キー | 型 | 既定 | 概要 |
| --- | --- | --- | --- |
| `banner` | `"always"` / `"once"` / `"never"` | `"once"` | 起動バナー |
| `effortLevel` | `"low"` / `"medium"` / `"high"` / `"xhigh"` | `"medium"` | 推論努力 |
| `allowedUrls` | `string[]` | `[]` | ワイルドカード可（例 `*.github.com`） |
| `deniedUrls` | `string[]` | `[]` | 常に拒否（allow より優先） |
| `askUser` | `boolean` | `true` | 質問を許可（`false` で無人運転） |
| `autoUpdate` / `autoUpdatesChannel` | bool / `"stable"` / `"prerelease"` | — | 自動更新と channel |
| `bashEnv` | `boolean` | `false` | bash の `BASH_ENV` 読み込み |
| `colorMode` | `"default"` / `"dim"` / `"high-contrast"` / `"colorblind"` | `"default"` | `/theme` 管理 |
| `companyAnnouncements` | `string[]` | `[]` | 起動時ランダム表示メッセージ |
| `compactPaste` | `boolean` | `true` | 大量ペーストを折り畳む |
| `continueOnAutoMode` | `boolean` | `false` | レート制限時に自動で auto モードへ |
| `customAgents.defaultLocalOnly` | `boolean` | `false` | 組織 / Enterprise の custom agent を使わない |
| `disableAllHooks` | `boolean` | `false` | hooks 全停止 |
| `disabledMcpServers` | `string[]` | `[]` | MCP サーバを名前で無効化 |
| `disabledSkills` | `string[]` | `[]` | skill を名前で無効化 |
| `enabledMcpServers` | `string[]` | `[]` | デフォルト無効な内蔵 MCP の有効化 |
| `enabledPlugins` | `Record<string, boolean>` | `{}` | 宣言的 plugin auto-install |
| `experimental` | `boolean` | `false` | 実験機能 |
| `extraKnownMarketplaces` | object | `{}` | 追加 plugin marketplace |
| `hooks` | object | — | inline hook 定義 |

`model` キーは公開表抜粋には未掲載だが、`/model` および `COPILOT_MODEL` 環境変数経由で settings.json にも保存される実態あり。

### 7.3 Permission モデル

- 段階: 都度確認 → セッション内承認 → `permissions-config.json` への永続化（プロジェクト単位）
- 全許可:
  - 対話: `/allow-all` / `/yolo`
  - 起動オプション: `--allow-all`, `--allow-all-tools`, `--allow-all-paths`, `--allow-all-urls`, `--yolo`
  - 環境変数: `COPILOT_ALLOW_ALL=true`
- 個別:
  - `--allow-tool='shell(git:*)'` / `--deny-tool='shell(git push)'`（**deny は allow に常に優先**）
  - `--allow-tool='MyMCP(create_issue)'` / `--allow-tool='MyMCP'`
  - `:*` サフィックスは「コマンド + スペース」マッチ（`gitea` が誤マッチしない）
- ディレクトリ: `--add-dir`, `/add-dir`, `/list-dirs`, `/cwd`
- URL: `--allow-url`, `--deny-url`, `settings.json` の `allowedUrls` / `deniedUrls`
- 永続化先: 自動管理ファイル `~/.copilot/permissions-config.json`

### 7.4 シークレット / 環境変数

- 認証: `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN`。Classic PAT (`ghp_`) は不可。fine-grained PAT は "Copilot Requests" 権限が必要
- 出力からの redaction: `--secret-env-vars=VAR ...`（`GITHUB_TOKEN` / `COPILOT_GITHUB_TOKEN` は既定で redact）
- 主な env: `COPILOT_HOME`, `COPILOT_CACHE_HOME`, `COPILOT_SKILLS_DIRS`, `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`, `COPILOT_SUBAGENT_MAX_CONCURRENT`, `COPILOT_SUBAGENT_MAX_DEPTH`, `COPILOT_MODEL`, `COPILOT_ALLOW_ALL`, `COPILOT_AUTO_UPDATE`, `COPILOT_GH_HOST`, `COPILOT_EDITOR`, `PLAIN_DIFF`, `USE_BUILTIN_RIPGREP`

## 出典

- `fetch_copilot_cli_documentation` の出力（README + `/help`）
- <https://docs.github.com/en/copilot/reference/cli-command-reference>
- <https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference>
- <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-custom-agents>
- <https://docs.github.com/en/copilot/reference/custom-agents-configuration>
- <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli>
- <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-skills>
- <https://docs.github.com/en/copilot/concepts/agents/about-agent-skills>
- <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/comparing-cli-features>
- <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/fleet>
- <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers>
- <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks>
- <https://docs.github.com/en/copilot/reference/hooks-configuration>
- <https://docs.github.com/en/copilot/tutorials/copilot-cli-hooks>
- <https://github.com/github/copilot-cli> （`changelog.md` の hook 関連エントリ）

## TODO: 要確認

- リポジトリ `home/dot_copilot/README.md` 記載「カスタムスラッシュコマンドは claude のものを読み取れる」の正確な根拠
  - 仮説: 実態は **Skills の `.claude/skills` 互換読み取り** であり、"スラッシュコマンド" という表現は不正確
- `config.json` → `settings.json` リネーム後の正式キー名総覧（`model` 等が公開表に未掲載）
- `customAgents` precedence: skills は project > personal、custom agents は **personal > project** と方向が逆。実装上の整合性
- Copilot CLI Plugin reference の詳細スキーマ
- `~/.copilot/hooks/` の正確なディレクトリ構造（ファイル名規約、サブディレクトリの扱い）
- `config.json` / `settings.json` 直書き hooks の **トップレベルキー**（`hooks` で良いか、`version` の要否）
- `notification` / `PermissionRequest` / `preCompact` / `subagentStart` / `postToolUseFailure` の **入力 JSON スキーマ**（reference ページに未掲載）
- HTTP hook の **POST 先 URL 指定キー名・ペイロード仕様**
- `permissionDecision: "ask"` が **CLI 非対話モード（`-p`）で動作するか**
- `matcher` が `preToolUse` 以外のイベント（例: `postToolUse`）でも有効か

---

## 8. Claude Code → Copilot CLI 概念マッピング

### 8.1 機能対応一覧

| 観点 | Claude Code | Copilot CLI | 対応度 |
| --- | --- | --- | --- |
| Skill 概念 | `SKILL.md` ベース、`agentskills` 標準 | `SKILL.md` ベース、`agentskills` 標準 | **★★★ ほぼ 1:1**（同じオープン標準） |
| Skill 配置 | `.claude/skills/` (project) / `~/.claude/skills/` (user) | `.claude/skills/` を含む複数 path / `~/.copilot/skills/` (user) | **★★★** Copilot 側が `.claude/skills` を公式サポート |
| Skill precedence（同一スコープ同士） | Personal > Project の上書き関係（Personal が勝つ） | Project > Personal の上書き関係（Project が勝つ） | **★★ ずれあり**（user / project の優先順が逆） |
| Skill precedence（org / enterprise 領域） | Enterprise が最優先（managed-settings 経由） | 公開ドキュメント上は personal / project が中心、enterprise 配布は plugin / marketplace 経由が主 | **★ Copilot CLI は org / enterprise 単位の skill 配布が未成熟** |
| Skill 自動 invocation | `description` + `when_to_use`（1,536 char 上限） | `description`（必須） | **★★★** ロジックはほぼ同じ |
| Skill フロントマター（共通） | `name`, `description`, `allowed-tools` | `name`, `description`, `allowed-tools` | **★★★ 共通** |
| Skill フロントマター（Claude 固有） | `disable-model-invocation`, `user-invocable`, `argument-hint`, `arguments`, `model`, `effort`, `context: fork`, `agent`, `paths`, `hooks`, `shell` | — | **★ Copilot 側に対応物なし**（未知フィールドのハンドリングは公式 docs 未記載 / TODO） |
| Skill 引数 | `$ARGUMENTS` / `$N` / `$name` 等の文字列置換 | （公式仕様に同等記述なし。手動 invocation 時に args 渡せる程度） | **★★ ずれあり**：複雑な引数バインディングは未確認 |
| Skill 環境変数 | `${CLAUDE_SKILL_DIR}`, `${CLAUDE_SESSION_ID}` 等 | （未確認） | **TODO: 要確認** |
| Custom Slash Command | `~/.claude/commands/*.md` (Skill に統合済) | **独立概念なし**。Skill が代替 | **★★ ずれあり**：単一 `.md` での軽量 command は不可 → Skill ディレクトリ化が必要 |
| Hook 概念 | あり（命令的・JSON I/O） | あり（**Claude 互換を意図した命名・スキーマ**） | **★★ 命名互換はあるが、サポートされる event 範囲・output 解釈の網羅性は Claude より狭い** |
| Hook イベント網羅 | `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `SessionEnd`, `Stop`, `StopFailure`, `TaskCreated`, `TaskCompleted`, `TeammateIdle`, `PermissionRequest`, `PermissionDenied`, `Notification`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `FileChanged`, `WorktreeCreate/Remove`, `PreCompact`, `PostCompact`, `Elicitation`, `ElicitationResult`, `SubagentStart`, `SubagentStop` | `sessionStart`, `sessionEnd`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `postToolUseFailure`, `errorOccurred`, `notification`, `subagentStart`, `preCompact`, `PermissionRequest`（PascalCase / camelCase 両受理） | **★ Copilot は event 数が大幅に少ない**：`Stop` / `TaskCompleted` / `UserPromptExpansion` / `PermissionDenied` / `FileChanged` / worktree 系 等は対応物が未確認 |
| Hook 入力 IF | stdin に JSON、`tool_name` / `tool_input` / `cwd` / `session_id` / `hook_event_name` 等 | stdin に JSON、`toolName` / `toolArgs` / `cwd` / `session_id` / `hook_event_name` / `timestamp` 等 | **★★ ずれあり**：camelCase / snake_case の混在、フィールド名差 |
| Hook 出力 IF | exit 0/2 + stderr（feedback）、stdout JSON で細粒度制御 | stdout に compact JSON、exit 0 推奨、stderr はログ用途 | **★★ ずれあり**：feedback 主経路が exit code + stderr (Claude) vs stdout JSON (Copilot) |
| Hook ブロッキング | `PreToolUse` で exit 2 → ブロック、`PreToolUse` JSON で `permissionDecision` | `preToolUse` で `permissionDecision: "deny"` で完全ブロック、`"ask"` でユーザ確認（**非対話モードでの ask 動作は未確認 / TODO**） | **★★** 概念は近いが、`ask` の挙動は Copilot 非対話モードで未保証 |
| Hook handler 種別 | `command` / `http` / `mcp_tool` / `prompt` / `agent` | `command`（bash / powershell）/ HTTP POST | **★ ずれ大**：Copilot は `mcp_tool` / `prompt` / `agent` 型を持たない |
| Hook matcher | tool 名の文字列 / 正規表現、`if:` で permission rule 構文の絞り込み | tool 名にフルマッチする正規表現（`preToolUse` 以外での matcher 動作は未確認） | **★★ ずれあり**：`if:` の permission rule 絞り込み相当なし |
| Hook 設定階層 | user / project / local / managed / plugin / skill frontmatter | user / repository / local / plugin（skill frontmatter は未確認） | **★★** ほぼ同様、ただし skill 内 hook の有無は要確認 |
| Hook の skill 内定義 | skill frontmatter に `hooks:` 記述可（`once: true` も） | （未確認） | **TODO: 要確認** |
| Custom Agent | サブエージェント (`general-purpose` / `Task` 等) を Skill から `agent: ...` で fork | `*.agent.md` をユーザ定義可（`tools`, `mcp-servers`） | **★★ ずれあり**：Claude は skill が agent を引っ張る、Copilot は agent が独立第一級 |
| Permission モデル | `allow` / `ask` / `deny` の 3 段階、`Tool(pattern)` 構文 | `--allow-tool` / `--deny-tool` の 2 段階（`shell(git:*)` 構文）、`/yolo` で全許可 | **★★ ずれあり**：`ask` 段階が CLI フラグでは表現できない |
| URL allowlist | `WebFetch(domain:...)` を permissions に書く | `allowedUrls` / `deniedUrls` を settings.json に書く（ワイルドカード可） | **★★ ずれあり**：構文は別 |
| 設定ファイル名 | `~/.claude/settings.json` | `~/.copilot/settings.json`（旧 `config.json`） | **★** ファイル名・スキーマとも別 |
| MCP 設定 | `~/.claude.json` 内 / project `.mcp.json` | `~/.copilot/mcp-config.json` / `.mcp.json` / `.github/mcp.json` | **★★** project 側 (`.mcp.json`) は同名で互換性あり |
| Plugin 機構 | あり（`hooks/`, `commands/`, `skills/` を束ねる） | あり（marketplace + `installed-plugins/`） | **★★** 概念は同じ、配布形式は別 |

凡例: ★★★ ほぼ 1:1 / ★★ ずれあり（概念は対応するがスキーマ・挙動に差） / ★ 対応物なし（or 大きく異なる）

### 8.2 マッピング上の重要な注意点

#### 8.2.1 Claude の Custom Slash Command は Copilot 側に直接の受け皿がない

公式 docs 上、Copilot CLI が `~/.claude/commands/*.md`（単一 Markdown のスラッシュコマンド）を直接ロードする記述は確認できない。Copilot CLI が公式に互換読み取りするのは **Skills（`.claude/skills/<name>/SKILL.md`）** のみ。

→ **単一 `.md` で書かれた Claude の custom command を Copilot 側に持ち込むには、Skill ディレクトリ（`<name>/SKILL.md`）化が原則必要**。

#### 8.2.2 Skill フロントマターの非互換フィールド

Claude 独自の `disable-model-invocation`, `context: fork`, `agent`, `paths`, `hooks`, `model`, `effort`, `arguments` などは Copilot CLI 公式 docs に記載がなく、解釈・無視・警告のいずれかは **公式仕様未確定**（TODO）。挙動に依存している Skill は、Copilot では別の手段（custom agent / hooks / manual invocation）で代替する設計が必要となる可能性が高い。

特に:

- `context: fork` + `agent: general-purpose` で **「サブエージェントで実行する skill」** を表現していたものは、Copilot では「skill から custom agent を `@agent-name` で呼ぶ」あるいは「最初から custom agent として定義する」形に再設計する必要がある。
- `disable-model-invocation: true`（Claude が自動起動しないユーティリティ）は Copilot の `disabledSkills` で個別無効化はできるが、**「`/` で手動だけ呼べる」状態** は表現できない。

#### 8.2.3 Hook の出力 IF と「移植可能性」の境界

Claude Code の hook は **exit 0 / 2 + stderr** で feedback / blocking を表現するのが慣用句。Copilot CLI は **stdout の JSON** が主経路で、exit 0 推奨・stderr はデバッグログ用途。

書き換えで移植できる範囲には **明確な境界** があるので注意：

- **公開 reference で保証されている範囲**: `preToolUse` の `permissionDecision: "deny"` による完全ブロック、`sessionStart` での `additionalContext` 注入。これらは「stdout JSON 形式に書き換えれば概ね移植可能」と言える
- **changelog / 観測ベースで動くと推測される範囲**: `preToolUse` の `permissionDecision: "ask"` / `modifiedArgs` / `suppressOutput`、`userPromptSubmitted` の `additionalContext`、`subagentStart` の `additionalContext`。移植しても期待通り動かない可能性があり、移植時に検証が必要
- **明示的にサポートされない範囲**: `userPromptSubmitted` での **prompt 改変**、`postToolUse` での結果改変、`sessionEnd` の output 利用。これらに依存していた Claude hook は **Copilot ではロジック側を再設計するしかない**

Copilot は **PascalCase / camelCase 両方のイベント名を受理** し、ネスト構造（`matcher` + `hooks`）も受理するため、`settings.json` 側のキー命名は最小変更で済むが、上記の「実際に有効な output 解釈」の差を踏まえないと「設定は通るのに hook が効かない」状態に陥る。

#### 8.2.4 Hook handler 型の差

Claude の `mcp_tool` / `prompt` / `agent` 型は Copilot では使えない。`command` 型（外部スクリプト）と HTTP POST のみ。LLM 呼び出しが必要な hook は、外部スクリプト経由で別途 LLM を叩くか、`additionalContext` の注入で代替するしかない。

#### 8.2.5 Permission モデルの粒度差

| 観点 | Claude | Copilot |
| --- | --- | --- |
| 段階 | `allow` / `ask` / `deny` の 3 段 | `allow` / `deny` の 2 段（`ask` は対話 UI 側） |
| 表現 | `Bash(git push:*)` | `shell(git push)` / `shell(git:*)` |
| 並び順 | deny → ask → allow（先勝ち） | deny が常に allow より優先 |
| URL | `WebFetch(domain:...)` を permissions に | `allowedUrls` / `deniedUrls` を settings に |

`ask` ルールに依存して「都度確認」していた挙動は、Copilot では **インタラクティブセッションのデフォルト挙動** に任せるしかない（非対話モードでは事実上 deny 相当になる）。

#### 8.2.6 Skill / Custom Agent の使い分け

- Claude: Skill 中に `context: fork` + `agent` を書けば、skill ≒ subagent invocation という単一抽象
- Copilot: Skill と Custom Agent は **別の第一級概念**
  - Skill = 「手順書 + 既定ツール群」
  - Custom Agent = 「特化した独立した呼び出し可能 persona」
- Claude の「fork する skill」は Copilot では **Custom Agent として定義** するのが意図に近い場合が多い
- precedence の方向（Skills は project > personal、Custom Agents は personal > project）が **逆**な点にも要注意

### 8.3 総括

- **Skill** は両者ともに `agentskills` オープン標準ベースで概念がほぼ一致し、Copilot 側が `.claude/skills/` を公式サポートするため **互換性は高い**。ただし Claude 固有のフロントマター拡張（`context: fork` / `agent` / `disable-model-invocation` / `model` / `effort` / `paths` / `hooks` 等）に依存する skill は移植時に再設計が必要
- **Hook** は名前空間（PascalCase / camelCase 両受理）と設定スキーマ形状（`matcher` + `hooks` の入れ子）こそ **意図的に Claude 互換** に揃えられているが、**サポートされる event 種類は Claude の半数以下** で、`Stop` / `TaskCompleted` / `UserPromptExpansion` / `PermissionDenied` / `FileChanged` / worktree 系 など対応物が未確認のものが多い。**「命名互換 ≠ 機能互換」** の理解が必須
- **Hook の I/O** は表面上の「exit code + stderr → stdout JSON」への変換だけでは不十分で、Copilot で実際に解釈される output フィールド（公開 reference で保証されるもの・changelog ベースのもの・サポートされないもの）の境界を踏まえた再設計が必要
- **Custom Slash Commands** は Copilot に独立概念がなく、Skill 化が必要（最大の構造差）
- **Permission モデル** は Claude が `allow` / `ask` / `deny` の 3 段階、Copilot が `allow` / `deny` の 2 段階という根本差があり、`ask` ルールに依存していた挙動は Copilot 側で完全には再現できない
- **サブエージェント抽象** が異なる（Claude は skill から fork、Copilot は custom agent が独立第一級）ため、「fork する skill」の意図は Copilot では custom agent 定義へ翻訳するのが自然
- 公式 docs に未記載の細部は **TODO** として残しており、具体的な移植作業時に都度補完が必要
