# ADR-0002: Skill / Custom Slash Command の配置と命名規約

- Status: Accepted
- Date: 2026-04-29
- Deciders: maintainer
- Related: ADR-0001, ADR-0003, REQ-010, REQ-011, REQ-012

## Context

Claude Code には skill (`SKILL.md` ベース) と custom slash command (`.md` 単一ファイル) の 2 系統があり、両者は統合済み（同フロントマターを共有）。

Copilot CLI には:

- 公式の `Skills` 機構（`SKILL.md` ベース、`agentskills` 標準）が存在し、`.claude/skills/` も project skills として公式サポート
- 独立した「custom slash command」概念は **存在しない**（slash 起動も Skill 経由）

→ 両者を Copilot 側でどう配置・命名するかを統一する必要がある。

## Decision

### 配置

- **すべて Skill として配置する**:
  - personal: `~/.copilot/skills/<name>/SKILL.md`
  - chezmoi 上のソースは `home/dot_copilot/skills/<name>/SKILL.md`
- **`home/dot_claude/commands/criticalthink.md` も同等に Skill 化** する（`~/.copilot/skills/criticalthink/SKILL.md`）。Copilot に単一 `.md` のスラッシュコマンド概念がないため。
- 同梱補助ファイル（references/, scripts/）は **同一ディレクトリ配下** に維持（Skill ディレクトリ全ファイルが auto-discover される）。

### 命名規約

- skill 名は `[a-z0-9-]+`、ハイフン区切り（既存 `adr`, `commit`, `explain`, `fix`, `learn`, `onboarding`, `criticalthink` をそのまま採用）
- ディレクトリ名 == skill 名 == `/<skill 名>` での invocation 名
- `name` フロントマターはディレクトリ名と一致させ、明示する

### 起動方法の保証

- 全 skill は **手動 invocation `/<name>`** が動作することを最低限保証する
- 自動 invocation は description の質に依存するため努力目標とする

### `.claude/skills/` 共有読み取りに依存しない

- Copilot CLI が `.claude/skills/` を project skills としてサポートするのは事実だが、**personal skills 側 `~/.copilot/skills/`** に配置することを優先する。理由:
  - personal scope のため特定リポジトリに依存しない
  - 将来 chezmoi 管理のディレクトリが変わった場合の影響範囲を狭められる
  - リポジトリ root を切り替えても全環境で同一動作

## Consequences

### 肯定的

- 配置先が一意に決まり、chezmoi テンプレート設計がシンプルになる（ADR-0007 で詳述）
- `criticalthink` を含めた全 7 件が同じ Skill 抽象に統一され、ドキュメント・運用が簡素化
- `.claude/skills/` 互換読み取りは**保険としての位置付け**になり、本系統の動作には影響しない

### 否定的

- 単一 `.md` で十分だった `criticalthink` も `SKILL.md` ディレクトリ化が必要（軽微）
- Copilot の Skills `description` は自動 invocation の判断材料となるため、skill ごとに記述品質を担保する必要がある

## Options Considered

1. **採用**: 全 skill を `~/.copilot/skills/<name>/SKILL.md` に配置、`criticalthink` も Skill 化
2. 却下: `.claude/skills/` 互換読み取りに依存して `home/dot_claude/skills/` をそのまま流用
   - 却下理由: Claude/Copilot 両方が enabled な環境でディレクトリの解釈が二重化し、管理が複雑になる
3. 却下: `criticalthink` は単一 `.md` のまま `~/.copilot/commands/` に配置
   - 却下理由: Copilot CLI 公式 docs に該当ディレクトリ仕様がない

## References

- `docs/research/copilot-spec.md` §1「Skills」
- `docs/research/copilot-spec.md` §3「Custom Slash Commands」
- `docs/research/claude-spec.md` §3「Custom Slash Commands」
