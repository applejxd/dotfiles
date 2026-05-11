# Skills / Commands 個別仕様

> 旧 `home/dot_claude/skills/` 6 件 + `home/dot_claude/commands/` 1 件 = 計 7 件の個別仕様。
> 全体方針は [`requirements.md`](./requirements.md) と [`design.md`](./design.md) を参照。
> ID 規約: `SKILL-<name>-NNN`（命名は ADR-0002 に従い、旧 `commands/` も `SKILL-` 接頭辞）。

## インベントリ表

| 名称 | 旧パス | Claude 機能 | Copilot 移植先 | ステータス | 関連 ADR | 関連 REQ |
| --- | --- | --- | --- | --- | --- | --- |
| `adr` | `home/dot_claude/skills/adr/` | `context:fork` + `general-purpose` + `${CLAUDE_SKILL_DIR}` 参照 | `~/.copilot/skills/adr/SKILL.md.tmpl` + references/ | `partial` | 0002, 0003, 0006 | SKILL-adr-* |
| `commit` | `home/dot_claude/skills/commit/` | `context:fork` + `${CLAUDE_SKILL_DIR}` + 同梱 script | `~/.copilot/skills/commit/SKILL.md.tmpl` + references/ + scripts/ | `migrated` | 0002, 0003, 0006 | SKILL-commit-* |
| `criticalthink` | `home/dot_claude/commands/criticalthink.md` | 単一 `.md`、引数なし | `~/.copilot/skills/criticalthink/SKILL.md` | `migrated` | 0002 | SKILL-criticalthink-* |
| `explain` | `home/dot_claude/skills/explain/` | `context:fork` + `agent: Explore`、参照ファイル無し | `~/.copilot/skills/explain/SKILL.md` | `migrated` | 0002, 0003 | SKILL-explain-* |
| `fix` | `home/dot_claude/skills/fix/` | `context:fork` + `${CLAUDE_SKILL_DIR}` + 言語別 references | `~/.copilot/skills/fix/SKILL.md.tmpl` + references/ | `migrated` | 0002, 0003, 0006 | SKILL-fix-* |
| `learn` | `home/dot_claude/skills/learn/` | `context:fork`、`AGENTS.md`/`CLAUDE.md` 編集 | `~/.copilot/skills/learn/SKILL.md` | `migrated` | 0002, 0003 | SKILL-learn-* |
| `onboarding` | `home/dot_claude/skills/onboarding/` | `context:fork` + `${CLAUDE_SKILL_DIR}` + 同梱 script | `~/.copilot/skills/onboarding/SKILL.md.tmpl` + references/ + scripts/ | `partial` | 0002, 0003, 0006 | SKILL-onboarding-* |

ステータス補足:

- `partial` の `adr` / `onboarding` は `$ARGUMENTS` 受け渡しが Copilot で未確認 (ADR-0006) のため
- `migrated` 判定は ADR-0003 の subagent 誘導文を本文に追加することで、振る舞いの再現を達成する想定

---

## SKILL-adr

### 現状（Claude 側）

- フロントマター: `name=adr`, `description=...`, `context=fork`, `agent=general-purpose`, `allowed-tools=Read, Write(docs/adr/*), Edit(docs/adr/*), Glob`
- 参照ファイル: `references/adr-template.md`
- 環境変数: `${CLAUDE_SKILL_DIR}/references/adr-template.md`
- 引数: `$ARGUMENTS` を「決定内容・タイトル・ADR 番号」として受け取る

### Copilot 移植方針

- 配置: `home/dot_copilot/skills/adr/SKILL.md.tmpl`（テンプレ化）
- 同梱: `references/adr-template.md`
- フロントマター: `name=adr`, `description=...`, `allowed-tools=` は省略（Copilot 側で個別承認、ADR-0005）
- `context: fork` の代替: 本文冒頭に「`Task` ツールで `general-purpose` subagent を起動して以下を実行」を追記（ADR-0003）
- `${CLAUDE_SKILL_DIR}` → chezmoi テンプレで `{{ .chezmoi.homeDir }}/.copilot/skills/adr` に静的置換（ADR-0006）
- 引数受け渡し: `$ARGUMENTS` 表記をそのまま残す（ADR-0006、未検証）

### EARS 受け入れ基準

#### SKILL-adr-001 (Ubiquitous)

THE migrated `adr` skill SHALL be invocable via `/adr` and SHALL produce an ADR draft based on `references/adr-template.md` without writing the file before user approval.

#### SKILL-adr-002 (Event-driven)

WHEN the user invokes `/adr` in a directory that has no `docs/adr/`, THE skill SHALL ask for confirmation before creating the directory.

#### SKILL-adr-003 (Unwanted)

IF Copilot CLI does not substitute `$ARGUMENTS` automatically, THEN the skill body SHALL still operate by asking the user for the decision content interactively.

### 保留事項

- `$ARGUMENTS` 自動置換の動作確認（実装フェーズの検証タスク）
- Copilot の Custom Agent 定義 (`adr.agent.md`) を併設するかは将来検討

---

## SKILL-commit

### 現状

- フロントマター: `name=commit`, `description=...`, `context=fork`, `agent=general-purpose`, `allowed-tools=Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(*get-git-context.sh*)`
- 参照ファイル: `references/conventional-commits-spec.md`, `scripts/executable_get-git-context.sh`
- 環境変数: `${CLAUDE_SKILL_DIR}/scripts/get-git-context.sh`, `${CLAUDE_SKILL_DIR}/references/conventional-commits-spec.md`

### Copilot 移植方針 (commit)

- 配置: `home/dot_copilot/skills/commit/SKILL.md.tmpl`
- 同梱: `references/conventional-commits-spec.md`, `scripts/executable_get-git-context.sh`
- `${CLAUDE_SKILL_DIR}` 静的置換
- 本文冒頭に Task ツール経由 subagent 起動指示を追加
- `git commit` / `git add` の実行禁止ポリシーは本文内のスタイル規範として維持（permission ではなく行動規範）

### EARS 受け入れ基準 (commit)

#### SKILL-commit-001 (Ubiquitous)

THE migrated `commit` skill SHALL be invocable via `/commit` and SHALL run `scripts/get-git-context.sh` (resolved to its absolute install path) to gather git status/diff/branch/log.

#### SKILL-commit-002 (Ubiquitous)

THE skill output SHALL conform to Conventional Commits format described in `references/conventional-commits-spec.md`.

#### SKILL-commit-003 (Unwanted)

IF the user has not explicitly approved, THEN the skill SHALL NOT execute `git commit` or `git add`.

### 保留事項 (commit)

- なし（`migrated` 判定）

---

## SKILL-criticalthink

### 現状 (criticalthink)

- 旧パス: `home/dot_claude/commands/criticalthink.md`（単一ファイル、`.md`）
- フロントマター: `description=...` のみ
- 引数なし、`${CLAUDE_SKILL_DIR}` 等の変数なし

### Copilot 移植方針 (criticalthink)

- 配置: `home/dot_copilot/skills/criticalthink/SKILL.md`（テンプレ化不要）
- フロントマター: `name=criticalthink`, `description=` を Claude 版から流用
- 本文はほぼそのまま転載
- ADR-0003 の subagent 誘導は **本 skill には不要**（メインの直前応答を分析する性質上、subagent 化するとコンテキストを失う）

### EARS 受け入れ基準 (criticalthink)

#### SKILL-criticalthink-001 (Ubiquitous)

THE migrated `criticalthink` skill SHALL be invocable via `/criticalthink` and SHALL operate within the main conversation context (without forking to a subagent) so that it can analyse the assistant's preceding response.

#### SKILL-criticalthink-002 (Ubiquitous)

THE output SHALL follow the same six-section template (Core Thesis / Foundational Analysis / Logical Integrity / AI-Specific Pitfall / Risk & Mitigation / Synthesis) as the Claude version.

### 保留事項 (criticalthink)

- なし（`migrated` 判定）

---

## SKILL-explain

### 現状 (explain)

- フロントマター: `name=explain`, `description=...`, `context=fork`, `agent=Explore`
- 参照ファイル: なし
- 引数: なし

### Copilot 移植方針 (explain)

- 配置: `home/dot_copilot/skills/explain/SKILL.md`（テンプレ化不要）
- `agent: Explore` → 本文冒頭に「`Task` ツールで `explore` subagent を起動して以下を実行」（ADR-0003）
- 読み取り専用性を本文の制約セクションで明示（既に「**読み取り専用**: ファイルの変更は行わない」と記載されているのを維持）

### EARS 受け入れ基準 (explain)

#### SKILL-explain-001 (Ubiquitous)

THE migrated `explain` skill SHALL be invocable via `/explain` and SHALL only perform read-only operations (no `Edit`, `Write`).

#### SKILL-explain-002 (Ubiquitous)

THE skill SHALL recommend invoking it via the `explore` subagent (Copilot built-in) rather than `general-purpose`, matching the `agent: Explore` setting in the Claude version.

### 保留事項 (explain)

- なし（`migrated` 判定）

---

## SKILL-fix

### 現状 (fix)

- フロントマター: `name=fix`, `description=...`, `context=fork`, `agent=general-purpose`, `allowed-tools=Read, Edit, Write, Bash, Grep, Glob`
- 参照ファイル: `references/{cpp,go-rust,js-ts,python}.md`
- 環境変数: `${CLAUDE_SKILL_DIR}/references/<lang>.md`

### Copilot 移植方針 (fix)

- 配置: `home/dot_copilot/skills/fix/SKILL.md.tmpl`
- 同梱: `references/{cpp.md, go-rust.md, js-ts.md, python.md}` をそのまま転載
- `${CLAUDE_SKILL_DIR}` 静的置換
- 本文冒頭に Task ツール経由 subagent 起動指示

### EARS 受け入れ基準 (fix)

#### SKILL-fix-001 (Ubiquitous)

THE migrated `fix` skill SHALL be invocable via `/fix` and SHALL detect the project language from configuration files: Python (`pyproject.toml`, `setup.py`, `setup.cfg`), JS/TS (`package.json`, `tsconfig.json`), Go (`go.mod`), Rust (`Cargo.toml`), C++ (`CMakeLists.txt`, `compile_commands.json`).

#### SKILL-fix-002 (Event-driven)

WHEN the project contains multiple language indicators, THE skill SHALL load the corresponding reference files in sequence and SHALL run each linter / formatter accordingly.

#### SKILL-fix-003 (Unwanted)

IF a remaining lint finding is design-sensitive (multiple valid fixes), THEN the skill SHALL include it in the report but SHALL NOT auto-fix it.

### 保留事項 (fix)

- なし（`migrated` 判定）

---

## SKILL-learn

### 現状 (learn)

- フロントマター: `name=learn`, `description=...`, `context=fork`, `agent=general-purpose`, `allowed-tools=Read, Edit, Write, Grep, Glob`
- 参照ファイル: なし
- 編集対象: `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`

### Copilot 移植方針 (learn)

- 配置: `home/dot_copilot/skills/learn/SKILL.md`（テンプレ化不要）
- 本文冒頭に Task ツール経由 subagent 起動指示
- **書き込み先は `AGENTS.md` 主体**: 既存の `AGENTS.md` / `CLAUDE.md` / `.claude/CLAUDE.md` を読み込んで知見を抽出するが、**書き込みは AGENTS.md のみ**（既存 skill 本文の運用方針を維持）
- 詳細が長くなる場合の分離先は `.claude/rules/` または `docs/` 配下（既存方針を維持）
- 肥大化防止チェック（重複排除・統合整理・詳細の分離・陳腐化チェック）は本文の制約として維持

### EARS 受け入れ基準 (learn)

#### SKILL-learn-001 (Ubiquitous)

THE migrated `learn` skill SHALL be invocable via `/learn` and SHALL extract knowledge from the conversation history into `AGENTS.md` only (reads from `AGENTS.md`, `CLAUDE.md`, and `.claude/CLAUDE.md` are allowed for context, but writes target only `AGENTS.md`).

#### SKILL-learn-002 (Unwanted)

IF a candidate addition duplicates existing AGENTS.md content semantically, THEN the skill SHALL update the existing entry instead of appending a new one.

#### SKILL-learn-003 (Event-driven)

WHEN an addition would exceed 3 lines of detail, THE skill SHALL extract the detail to a separate file under `.claude/rules/` or `docs/` and SHALL replace the inline content with a reference link in `AGENTS.md`.

### 保留事項 (learn)

- なし（`migrated` 判定）

---

## SKILL-onboarding

### 現状 (onboarding)

- フロントマター: `name=onboarding`, `description=...`, `context=fork`, `agent=general-purpose`, `allowed-tools=Write(AGENTS.md), Edit(AGENTS.md), Bash(*check-agents.sh*)`
- 参照ファイル: `references/agents-template.md`, `references/review-checklist.md`, `scripts/executable_check-agents.sh`
- 環境変数: `${CLAUDE_SKILL_DIR}/scripts/check-agents.sh`, `${CLAUDE_SKILL_DIR}/references/...`
- 引数: `$ARGUMENTS` で対象を受け取る（mode: `full` / `partial` / `minimal`）

### Copilot 移植方針 (onboarding)

- 配置: `home/dot_copilot/skills/onboarding/SKILL.md.tmpl`
- 同梱: `references/{agents-template,review-checklist}.md`, `scripts/executable_check-agents.sh`
- `${CLAUDE_SKILL_DIR}` 静的置換
- 本文冒頭に Task ツール経由 subagent 起動指示
- `$ARGUMENTS` はそのまま残す

### EARS 受け入れ基準 (onboarding)

#### SKILL-onboarding-001 (Ubiquitous)

THE migrated `onboarding` skill SHALL be invocable via `/onboarding` and SHALL run `scripts/check-agents.sh` to gather existing AGENTS.md content.

#### SKILL-onboarding-002 (Ubiquitous)

THE produced AGENTS.md draft SHALL be 60-150 lines and SHALL contain `Always` / `Ask first` / `Never` sections explicitly.

#### SKILL-onboarding-003 (Ubiquitous)

THE skill SHALL write only to `AGENTS.md` and SHALL NOT propose creating `CLAUDE.md` or other tool-specific instruction files.

#### SKILL-onboarding-004 (Unwanted)

IF the user has not explicitly approved, THEN the skill SHALL NOT write to `AGENTS.md`.

#### SKILL-onboarding-005 (Unwanted)

IF Copilot CLI does not substitute `$ARGUMENTS` automatically, THEN the skill SHALL fall back to asking the user for the mode (`full` / `partial` / `minimal`) interactively.

### 保留事項 (onboarding)

- `$ARGUMENTS` 自動置換の動作確認（実装フェーズの検証タスク）
