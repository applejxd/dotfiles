# `.claude` → `.copilot` 移植仕様 インデックス

> Claude Code の `home/dot_claude/` 配下資産（skills / commands / hooks）を GitHub Copilot CLI へ移植するための仕様ドキュメント群。
> 本フェーズは **仕様作成のみ**。実装は [`tasks.md`](./tasks.md) で計画された次フェーズで実施する。

## ドキュメント構成

| ファイル | 役割 |
| --- | --- |
| [`requirements.md`](./requirements.md) | 全体要件（EARS 形式） |
| [`design.md`](./design.md) | 技術設計サマリ + ADR 索引 |
| [`adr/`](./adr/) | 横断的な技術決定（1 ファイル 1 ADR） |
| [`skills.md`](./skills.md) | skill / command 7 件の個別仕様（インベントリ + 個別 EARS） |
| [`hooks.md`](./hooks.md) | hook 5 件の個別仕様（インベントリ + 個別 EARS） |
| [`tasks.md`](./tasks.md) | 実装フェーズのタスク分解 |

## ADR 索引

| ID | タイトル | Status |
| --- | --- | --- |
| [ADR-0001](./adr/0001-target-runtime-and-scope.md) | Target Runtime と移植スコープ | Accepted |
| [ADR-0002](./adr/0002-skill-placement-and-naming.md) | Skill / Custom Slash Command の配置と命名規約 | Accepted |
| [ADR-0003](./adr/0003-context-fork-to-custom-agent.md) | `context: fork` の Copilot Custom Agent 化方針 | Accepted |
| [ADR-0004](./adr/0004-hook-io-stdout-json.md) | Hook の I/O は stdout JSON ベースに統一 | Accepted |
| [ADR-0005](./adr/0005-permission-translation.md) | Permission モデルの翻訳則 | Accepted |
| [ADR-0006](./adr/0006-environment-variable-translation.md) | Skill 内環境変数の翻訳 | Accepted |
| [ADR-0007](./adr/0007-chezmoi-template-strategy.md) | chezmoi テンプレート戦略 | Accepted（条件付き） |

## 移植ステータス一覧（12 資産）

ステータス値の定義: ADR-0001 §3 を参照（`migrated` / `partial` / `deferred` / `dropped`）。

| 区分 | 名称 | ステータス | 主理由 | 詳細 |
| --- | --- | --- | --- | --- |
| skill | `criticalthink` | `migrated` | 単一 `.md` を Skill 化、変数なし | [skills.md#skill-criticalthink](./skills.md) |
| skill | `explain` | `migrated` | 変数なし、Task 誘導のみ | [skills.md#skill-explain](./skills.md) |
| skill | `learn` | `migrated` | 変数なし、Task 誘導のみ | [skills.md#skill-learn](./skills.md) |
| skill | `commit` | `migrated` | テンプレ化 + 同梱 script | [skills.md#skill-commit](./skills.md) |
| skill | `fix` | `migrated` | テンプレ化 + 言語別 reference | [skills.md#skill-fix](./skills.md) |
| skill | `adr` | `partial` | `$ARGUMENTS` 受け渡し未確認 | [skills.md#skill-adr](./skills.md) |
| skill | `onboarding` | `partial` | `$ARGUMENTS` 受け渡し未確認 | [skills.md#skill-onboarding](./skills.md) |
| hook | `check_bash` | `partial` | bind 方式の検証待ち（REQ-051） | [hooks.md#hook-check-bash](./hooks.md) |
| hook | `redirect-tmp` | `partial` | 責務拡張（path 単位 deny 吸収）+ bind 検証待ち | [hooks.md#hook-redirect-tmp](./hooks.md) |
| hook | `update-adr-on-stop` | `partial` | `TaskCompleted` 相当が Copilot に無く `sessionEnd` で代替 | [hooks.md#hook-update-adr-on-stop](./hooks.md) |
| hook | `markdownlint` | `partial` | `PostToolUse` の LLM フィードバック喪失 + bind 検証待ち | [hooks.md#hook-markdownlint](./hooks.md) |
| hook | `format-file` | `dropped` | Claude 側でも未 bind の孤立スクリプト | [hooks.md#hook-format-file](./hooks.md) |

集計:

- `migrated`: 5 件
- `partial`: 6 件（うち hook は 4 件全件、bind 検証完了で `migrated` に格上げ可能）
- `deferred`: 0 件
- `dropped`: 1 件

## 規範参照

本仕様は以下の研究ドキュメントを一次根拠とする:

- [`../research/claude-spec.md`](../research/claude-spec.md) — Claude Code 側の仕様サマリ
- [`../research/copilot-spec.md`](../research/copilot-spec.md) — Copilot CLI 側の仕様サマリ + 概念マッピング章

## 形式について

本仕様は **ADR + EARS + 資産インベントリ表** の三層構成を採用している:

- **ADR** (Architecture Decision Records): 横断的な設計判断と却下案を記録（`adr/NNNN-*.md`）
- **EARS** (Easy Approach to Requirements Syntax): 検証可能な単一述語で要件を記述（`REQ-NNN`, `SKILL-<name>-NNN`, `HOOK-<name>-NNN`）
- **インベントリ表**: 12 資産のステータス一覧（本ファイル + skills.md / hooks.md）

EARS パターン:

- `Ubiquitous`: `THE <system> SHALL <action>`
- `Event-driven`: `WHEN <trigger> THE <system> SHALL <action>`
- `State-driven`: `WHILE <state> THE <system> SHALL <action>`
- `Optional`: `WHERE <feature> THE <system> SHALL <action>`
- `Unwanted behavior`: `IF <unwanted condition> THEN THE <system> SHALL <action>`

## 次のフェーズ

[`tasks.md`](./tasks.md) の **Phase 0**（bind 方式・shell deny 永続化先・$ARGUMENTS 動作の 3 検証）から実装フェーズを開始する。Phase 0 の結果次第で ADR-0005 / ADR-0007 を更新する場合がある。
