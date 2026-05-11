# Requirements: `.claude` → `.copilot` 移植

> 全体要件を EARS（Easy Approach to Requirements Syntax）で記述する。
> 個別資産の要件は [`skills.md`](./skills.md) / [`hooks.md`](./hooks.md) に記述。
> ID 規約: `REQ-NNN`。

## EARS パターン凡例

- **Ubiquitous**: `THE <system> SHALL <action>`（常時成り立つ要件）
- **Event-driven**: `WHEN <trigger> THE <system> SHALL <action>`
- **State-driven**: `WHILE <state> THE <system> SHALL <action>`
- **Optional**: `WHERE <feature> THE <system> SHALL <action>`
- **Unwanted behavior**: `IF <unwanted condition> THEN THE <system> SHALL <action>`

## 1. スコープ要件

### REQ-001 (Ubiquitous)

THE migration SHALL target only GitHub Copilot CLI (`@github/copilot`); Copilot Coding Agent (cloud) and Copilot Chat in IDE are out of scope.

### REQ-002a (Ubiquitous)

THE migration SHALL cover all 12 assets currently in `home/dot_claude/` (6 skills, 1 command, 5 hooks).

### REQ-002b (Ubiquitous)

THE migration SHALL assign each migrated asset exactly one of the four statuses: `migrated`, `partial`, `deferred`, `dropped` (定義は ADR-0001 参照).

### REQ-003 (Ubiquitous)

THE present phase SHALL produce only specification documents under `docs/spec/`; implementation under `home/dot_copilot/` is out of scope and tracked in [`tasks.md`](./tasks.md).

## 2. 配置・命名要件

### REQ-010 (Ubiquitous)

THE Copilot artifacts SHALL be placed under personal scope (`~/.copilot/skills/`, `~/.copilot/hooks/`) so that they do not depend on a specific repository being open.

### REQ-011 (Ubiquitous)

THE skill name SHALL match its directory name and the `name` frontmatter value, all lowercase with hyphens only.

### REQ-012 (Ubiquitous)

THE single-file Claude command (`criticalthink.md`) SHALL be migrated as a Skill directory (`<name>/SKILL.md`) since Copilot CLI has no independent custom-slash-command concept.

## 3. Skill 起動要件

### REQ-020 (Ubiquitous)

THE migration SHALL guarantee that every migrated skill is invocable via `/<skill-name>` from the Copilot CLI prompt.

### REQ-021 (Ubiquitous)

WHERE a Claude skill is declared with `context: fork`, THE migrated SKILL.md body SHALL instruct the user (or Copilot itself) to spawn a subagent via the `Task` tool when running the skill (詳細は ADR-0003).

### REQ-022 (Ubiquitous)

THE migrated skill body SHALL resolve every reference to `${CLAUDE_SKILL_DIR}` to the absolute path of its install location at chezmoi template render time (詳細は ADR-0006).

### REQ-023 (Unwanted)

IF Copilot CLI does not provide a documented mechanism to substitute `$ARGUMENTS` in skill bodies, THEN every migrated skill that uses `$ARGUMENTS` (currently `adr` and `onboarding`) SHALL be marked `partial` and SHALL contain an interactive fallback prompt for the missing input. The runtime behaviour SHALL be verified in the implementation phase per [`tasks.md`](./tasks.md).

## 4. Hook 要件

### REQ-030 (Ubiquitous)

THE migrated hooks SHALL communicate with Copilot CLI exclusively via JSON written to stdout (with exit code 0) for blocking / context decisions, instead of relying on `exit 2` + stderr (詳細は ADR-0004).

### REQ-031 (Event-driven)

WHEN a hook fails to parse its stdin JSON or raises any unexpected exception, THE hook SHALL exit 0 (fail-open) so that the failure does not block the agent.

### REQ-032 (Event-driven)

WHEN a hook needs to block a tool call, THE hook SHALL emit `{"permissionDecision": "deny", "permissionDecisionReason": "<message>"}` to stdout and exit 0.

### REQ-033 (Ubiquitous)

THE migrated hook event names SHALL use camelCase (`preToolUse`, `postToolUse`, `sessionEnd` 等) for consistency, even though Copilot CLI accepts both PascalCase and camelCase.

### REQ-034 (Unwanted)

IF a Claude hook depends on the `TaskCompleted` event for mid-session feedback, THEN the migration SHALL document that this behavior cannot be reproduced and SHALL fall back to `sessionEnd` with a `partial` status.

### REQ-035 (Unwanted)

IF a Claude hook depends on `PostToolUse` stderr feedback being relayed to the LLM, THEN the migration SHALL document the loss and SHALL retain only the side effects (auto-fix, lint apply 等) with a `partial` status.

## 5. Permission 要件

### REQ-040 (Ubiquitous)

THE migrated **shell-tool** deny rules SHALL preserve every Claude `Bash(*)` deny entry whose intent maps to a Copilot-supported pattern (`shell(cmd:*)` 等).

### REQ-041 (Unwanted)

IF a Claude `deny` rule targets a file path (e.g. `Read(**/*token*)`, `Write(./.env)`) and Copilot has no equivalent path-deny construct, THEN the migration SHALL extend `redirect-tmp` (or add a sibling `preToolUse` hook) so that the Read / Write / Edit / MultiEdit tools also reject paths matching `SENSITIVE_PATH_PATTERNS`. The original `check_bash` hook only inspects Bash invocations and is NOT sufficient on its own.

### REQ-042 (Ubiquitous)

THE Claude `ask` permissions SHALL be omitted from the Copilot configuration so that Copilot's default per-call confirmation behaviour applies.

### REQ-043 (Ubiquitous)

THE migrated **URL** allow / deny rules (translated from Claude `WebFetch(domain:...)`) SHALL be written to the `allowedUrls` / `deniedUrls` keys of `~/.copilot/config.json` (or `settings.json` after Copilot's auto-rename).

### REQ-044 (Unwanted)

IF the Copilot CLI documentation does not confirm the persistence target of shell-tool allow / deny rules (e.g. `permissions-config.json` vs inline in `settings.json`), THEN the migration SHALL flag the relevant requirement as `TODO: 要確認` and SHALL plan a runtime verification task before declaring the deny rules `migrated`.

## 6. chezmoi / 配布要件

### REQ-050 (Ubiquitous)

THE migration SHALL extend the existing `home/dot_copilot/modify_config.json` to merge in URL allow / deny lists.

### REQ-051 (Unwanted)

IF the Copilot CLI documentation does not confirm that hook bindings (`hooks.preToolUse`, `hooks.postToolUse`, `hooks.sessionEnd`) can be inlined in `~/.copilot/config.json` / `settings.json`, THEN the migration SHALL flag this binding mechanism as `TODO: 要確認` and SHALL prepare a fallback design (e.g. individual files under `~/.copilot/hooks/`) before declaring hook installation `migrated`.

### REQ-052 (Ubiquitous)

THE chezmoi templates SHALL produce stable JSON output that is idempotent across `chezmoi apply` runs (no random ordering; lists merged via `concat | uniq`).

### REQ-053 (Ubiquitous)

THE skill bodies that contain `${CLAUDE_SKILL_DIR}` SHALL be expressed as `.tmpl` files.

### REQ-054 (Ubiquitous)

THE skill bodies that do NOT contain template variables SHALL be installed as plain `.md` files (no `.tmpl` extension).

## 7. ドキュメント要件

### REQ-060 (Ubiquitous)

THE asset inventory tables in `README.md`, `skills.md`, `hooks.md` SHALL stay in sync regarding status, related ADR IDs, and related REQ IDs.

### REQ-061 (Ubiquitous)

WHERE a Copilot CLI behaviour is unverified by official docs, THE spec SHALL flag the relevant requirement as `TODO: 要確認` and SHALL not silently assume the behaviour holds.

## 8. 実装フェーズへの引き渡し要件

### REQ-070 (Ubiquitous)

THE [`tasks.md`](./tasks.md) SHALL list every implementation step with explicit dependencies, so that the implementation phase can pick them up without re-deriving the breakdown.

### REQ-071 (Ubiquitous)

WHERE a requirement here defers verification to runtime (REQ-031, REQ-061 等), THE [`tasks.md`](./tasks.md) SHALL include an explicit verification task.

## 受け入れ基準（全体）

本仕様フェーズの完了基準は次の通り:

1. `docs/spec/` 配下に以下が揃っている: `README.md`, `requirements.md`, `design.md`, `adr/0001-0007-*.md`, `skills.md`, `hooks.md`, `tasks.md`
2. 全 12 資産が `skills.md` / `hooks.md` のインベントリ表に登場し、ステータス値（4 値）が割り当てられている
3. 各 EARS 文に対し、対応する受け入れ基準（実装フェーズで検証する手順）が `tasks.md` に存在する
4. ADR 同士・REQ ↔ ADR の参照に矛盾がない（`spec-final-review` タスクで確認）
