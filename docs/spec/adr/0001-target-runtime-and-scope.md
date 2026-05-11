# ADR-0001: Target Runtime と移植スコープ

- Status: Accepted
- Date: 2026-04-29
- Deciders: maintainer
- Related: REQ-001, REQ-002a, REQ-002b, REQ-003

## Context

`home/dot_claude/` に整備された Claude Code 向け資産を `home/dot_copilot/`（GitHub Copilot CLI）側へ移植する。研究フェーズ（`docs/research/`）の結果、両 CLI は Skill / Hook の概念を共有するが、サポート範囲・I/O・permission モデルに差異があると判明した。

仕様駆動で進めるにあたり、まず **何を対象とし、何を達成すれば「移植完了」と見なすか** を確定する必要がある。

## Decision

1. **対象 CLI**: GitHub Copilot CLI (`@github/copilot`、`copilot` コマンド) のみ。Copilot Coding Agent (cloud) や Copilot Chat in IDE は対象外。
2. **対象資産**: `home/dot_claude/` 配下の以下 12 件（2026-04 時点）
   - skills 6: `adr`, `commit`, `explain`, `fix`, `learn`, `onboarding`
   - commands 1: `criticalthink`
   - hooks 5: `check_bash`, `redirect-tmp`, `update-adr-on-stop`, `format-file`, `markdownlint`
3. **移植可否ステータス**: 以下 4 値のいずれかを各資産に付与する。

   | 値 | 意味 |
   | --- | --- |
   | `migrated` | Copilot 上で同等の振る舞いが実現できた |
   | `partial` | 主要機能は移植できたが Claude 固有機能の一部が失われた |
   | `deferred` | 仕様未確定や Copilot 公式 docs の TODO により判断保留 |
   | `dropped` | Copilot 上では実現不可能、または重複機能のため移植しない |

4. **「移植完了」の判定基準**: 全 12 資産がいずれかのステータスに分類され、`migrated` / `partial` の各資産について個別 EARS の受け入れ基準を満たすこと。
5. **本フェーズの責務範囲**: 仕様ドキュメント（`docs/spec/`）の作成のみ。実装（`home/dot_copilot/` 配下のファイル追加・chezmoi テンプレート編集）は別フェーズ（`tasks.md` で計画）。

## Consequences

### 肯定的

- スコープが明確化され、12 資産という有限集合に対して網羅的に進捗を追える
- 4 値ステータスにより「諦めた」資産も明示的に記録され、後で再検討可能
- 仕様と実装を分離することで、仕様レビューと実装作業を別タイミングで進められる

### 否定的

- Copilot CLI の仕様は活発に変化しており（changelog 追跡が必要）、`deferred` 判定が増える可能性がある
- VS Code agent mode 等への横展開を行う場合、本 ADR の前提が再検討対象となる

## Options Considered

1. **採用**: Copilot CLI のみを対象、12 資産を 4 値ステータスで管理
2. 却下: VS Code agent mode / Copilot Coding Agent も同時対象に含める
   - 却下理由: I/O 仕様や hook サポート範囲がさらに分岐し、仕様量が膨大になる
3. 却下: 「動くもの」だけ移植し、未対応資産は仕様化しない
   - 却下理由: 後で再検討するときに判断履歴が失われる

## References

- `docs/research/copilot-spec.md` §0「全体像」
- `docs/research/copilot-spec.md` §8「Claude Code → Copilot CLI 概念マッピング」
