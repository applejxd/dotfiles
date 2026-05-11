# ADR-0003: `context: fork` の Copilot Custom Agent 化方針

- Status: Accepted
- Date: 2026-04-29
- Deciders: maintainer
- Related: ADR-0002, REQ-020, REQ-021

## Context

Claude Code の skill には `context: fork` + `agent: <type>` を指定することで、メイン会話を汚染せず **サブエージェント上で skill を実行** する仕組みがある。

`home/dot_claude/` 全 6 skill がこの設定を使用している:

| Skill | `context` | `agent` |
| --- | --- | --- |
| `adr` | `fork` | `general-purpose` |
| `commit` | `fork` | `general-purpose` |
| `explain` | `fork` | `Explore` |
| `fix` | `fork` | `general-purpose` |
| `learn` | `fork` | `general-purpose` |
| `onboarding` | `fork` | `general-purpose` |

Copilot CLI には:

- `context: fork` 相当のフロントマターは存在しない
- 代わりに **Custom Agent**（`*.agent.md`）が独立第一級の概念として存在
- 内蔵 subagent: `explore` / `task` / `general-purpose` (Claude の `Explore` / `general-purpose` に概ね対応)

## Decision

### 翻訳則

各 skill は **2 つの呼び出しモード** を Copilot 上で実装する:

1. **手動 invocation（必須・全 skill 対象）**:
   - `/<skill 名>` で **メイン会話** から起動
   - Skill 本文の冒頭で **「この作業はサブエージェントで実行してください」** と明示する手順を入れる
   - 具体的には Skill 本文に「`Task` ツールを使い、`general-purpose`（または `explore`）サブエージェントを起動して以下の手順を実行してください」のような誘導文を含める
2. **自動的なサブエージェント実行（努力目標）**:
   - メインエージェントが skill description を読み、Custom Agent として呼び出すかは Copilot 側のヒューリスティクスに委ねる
   - 必要なら同名の Custom Agent (`~/.copilot/agents/<skill>.agent.md`) を併設し、`@<skill>` での明示呼び出しを可能にする（本フェーズでは保留・`tasks.md` で扱う）

### Claude → Copilot agent 名のマッピング

| Claude `agent:` 値 | Copilot 対応 | 根拠 |
| --- | --- | --- |
| `general-purpose` | 内蔵 `general-purpose` (`Task` ツール経由) | 名称・役割が一致 |
| `Explore` | 内蔵 `explore` (`Task` ツール経由) | Claude の Explore は読み取り専用調査用、Copilot の `explore` も同等 |

### 本フェーズの実装範囲

- 移植対象は **手動 invocation の動作確認まで**。内訳:
  - 全 skill が `/<skill 名>` で起動できる
  - 起動された skill 本文がサブエージェント実行を誘導する
- Custom Agent ファイル (`*.agent.md`) の作成は **`tasks.md` の Phase 2 以降に保留** する

### Skill 本文 vs テンプレ化の責務分離

- **「Task ツール経由 subagent 起動を誘導」する追記は `context: fork` を持つ全 6 skill に必要**（`adr`, `commit`, `explain`, `fix`, `learn`, `onboarding`）
- **chezmoi `.tmpl` 化は `${CLAUDE_SKILL_DIR}` を含む 4 skill のみ**（`adr`, `commit`, `fix`, `onboarding`）。残る `explain` / `learn` は誘導文の追加だけで `.md` のままにできる
- 両者は独立した変換であり、`.tmpl` 化したかどうかと subagent 誘導は無関係（ADR-0006/0007 と本 ADR で責務が分かれる）

## Consequences

### 肯定的

- `context: fork` を「skill 本文の中で `Task` ツールを呼ぶ手順」に翻訳することで、Copilot の標準機構だけで意図を再現できる
- Custom Agent 作成は段階的に追加可能で、初期移植のスコープが小さくなる

### 否定的

- メイン会話と完全に分離するわけではなく、skill 起動時の最初のターンはメイン会話で消費される
- skill 本文に「Task ツールで実行してください」という Copilot 固有の誘導文を入れるため、Claude 側との完全互換は失われる（ADR-0006 で扱うテンプレート化で吸収する余地あり）

## Options Considered

1. **採用**: 手動 invocation 必須 + skill 本文で Task ツール経由のサブエージェント実行を誘導
2. 却下: 全 skill を Custom Agent (`*.agent.md`) として実装する
   - 却下理由: Skill としての `/<name>` invocation が主用途であり、Custom Agent は `@<name>` メンション or `--agent` 起動が主用途のため、ユーザー体験が変わる
3. 却下: `context: fork` を無視してメイン会話で実行
   - 却下理由: skill 内容（特に `adr`, `onboarding`, `learn`）はメイン会話を汚染しないことが前提

## References

- `docs/research/copilot-spec.md` §4「Custom Agents」
- `docs/research/copilot-spec.md` §8.2.6「Skill / Custom Agent の使い分け」
- `docs/research/claude-spec.md` §1.6「実行コンテキストとサブエージェント」
