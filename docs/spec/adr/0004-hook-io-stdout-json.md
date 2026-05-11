# ADR-0004: Hook の I/O は stdout JSON ベースに統一する

- Status: Accepted
- Date: 2026-04-29
- Deciders: maintainer
- Related: ADR-0001, REQ-030, REQ-031, REQ-032, REQ-033

## Context

`home/dot_claude/hooks/` の全 5 hook は **Claude Code の慣用的な I/O** で書かれている:

- 入力: `json.load(sys.stdin)`（`tool_name`, `tool_input.command`, `cwd` 等を読む）
- 出力: `exit 0` (許可) / `exit 2` (ブロック) + `print(message, file=sys.stderr)`（Claude へのフィードバック）

一方 Copilot CLI の hook 仕様は:

- 入力: stdin に JSON（`toolName`, `toolArgs`, `cwd` 等の **camelCase**）
- 出力: **stdout に compact JSON** が主経路（`{"permissionDecision": "deny", "permissionDecisionReason": "..."}`）
- exit code: `0` 推奨。stderr はログ用途
- 各イベントで実際に解釈される output フィールドが異なる（公開 reference 保証 / changelog ベース / サポート外 の 3 段階）

## Decision

### 共通変換則

すべての hook を以下の方針で書き直す:

1. **入力フィールド名の対応**:

   | Claude (snake_case) | Copilot (camelCase) | 変換戦略 |
   | --- | --- | --- |
   | `tool_name` | `toolName` | 両キーを試みる helper を導入 |
   | `tool_input` | `toolArgs` | 同上 |
   | `tool_input.command` | `toolArgs.command` | dict 検索の階層は同一 |
   | `tool_input.file_path` | `toolArgs.file_path` または `toolArgs.path` | tool 名で分岐（既存挙動踏襲） |
   | `cwd` | `cwd` | 同名 |
   | `session_id` | `session_id` | 同名（snake_case 統一済との changelog 記述） |
   | `hook_event_name` | `hook_event_name` | 同名 |

2. **出力**:
   - `preToolUse` でブロックする場合: stdout に `{"permissionDecision":"deny","permissionDecisionReason":"<message>"}` を出力。**exit 0** で終了
   - `preToolUse` で context を注入する場合: stdout に `{"additionalContext":"<text>"}` を出力。exit 0
   - `postToolUse` 系で警告/フィードバックを出したい場合: **stdout JSON では効かない**ため `additionalContext` 経路を諦め、**stderr にログ出力 + exit 0** にとどめる（外部ログとして残るのみ）
3. **エラーハンドリング**:
   - JSON パース失敗時は exit 0（hook を fail-open）
   - 例外時も exit 0 で fail-open（hook が壊れても本体実行をブロックしない）
4. **shebang・ランタイム**:
   - Python hook は `#!/usr/bin/env python3` を維持
   - Bash hook は `#!/usr/bin/env bash` + `set -eu` を維持
5. **JSON 出力ヘルパー**:
   - 共通の Python ユーティリティ（`hooks/_lib.py` 等）を導入しない。各 hook は標準ライブラリのみで完結させ、依存を最小化する

### イベント名の翻訳

| Claude イベント名 | Copilot 対応 | 備考 |
| --- | --- | --- |
| `PreToolUse` | `preToolUse` | PascalCase / camelCase 両受理だが camelCase で統一 |
| `PostToolUse` | `postToolUse` | 同上。**output は無視されるため副作用のみ** |
| `TaskCompleted` | **対応物なし** → `sessionEnd` で代替 | TaskCompleted の任意ターン内発火は再現できない。セッション終了時のみ |

### 失われる機能の明示

- **Claude の exit 2 + stderr による「メッセージ付きブロック」のうち、`postToolUse` 系のフィードバックは Copilot では LLM に届かない**
  → `markdownlint` hook の「残存違反を Claude に再修正させる」挙動は Copilot では再現できない（lint 自動修正のみが残る）
- **`update-adr-on-stop` の TaskCompleted 起動は再現できない**
  → セッション終了時 (`sessionEnd`) のみで発火させ、ADR 更新を促すログを stderr に出すのみとなる

## Consequences

### 肯定的

- 全 hook が同じ I/O 規約に統一され、レビュー・デバッグが容易
- fail-open 方針により hook 不具合がエージェント本体を壊さない
- camelCase / snake_case の差を helper で吸収することで Claude 側の hook も流用しやすくなる

### 否定的

- `postToolUse` 系の LLM フィードバックが失われる（markdownlint, format-file の自動修正後の通知）
- `TaskCompleted` 系の挙動が再現できず、`update-adr-on-stop` が `partial` 扱いになる

## Options Considered

1. **採用**: stdout JSON ベースに統一、fail-open
2. 却下: HTTP hook (POST) を採用
   - 却下理由: ローカル スクリプトで十分なケースに対しオーバースペック。永続化サーバーが必要
3. 却下: Claude 用 hook をそのまま `command:` で呼び、出力は無視
   - 却下理由: Copilot は exit 2 を blocking として解釈しないため、ブロック動作が成立しない

## References

- `docs/research/copilot-spec.md` §2「Hooks」
- `docs/research/copilot-spec.md` §8.2.3「Hook の出力 IF と移植可能性の境界」
- `docs/research/claude-spec.md` §2.7「出力 IF」
