# Claude Code permission リストの既知バグ（2026-05 時点）

`docs/spec/guard/agent-command-policy.md#claude-code-permission-リストの既知バグ` から移した記録。移設時点で再測定していない（issue の現在の状態は未確認）。

## 記録 E1 — 2026-05

- **対象バージョン**: Claude Code（版は元の文に無い）
- **環境**: 元の文は「2026-05 時点」。観測日は月までしか分からない

### 問い

Claude Code の permission リスト（`Bash(...)` の ask / deny）は、複合コマンドや `git -C` の形で迂回されないか。

### 事前の予想

元の文には書かれていない。

### 方法・条件

既知の issue を集めた（元の文の表）。

### 結果

元の文: 「下記は 2026-05 時点で open。hook 側の normalize で必ず防ぐべき理由。」

| Issue | 概要 |
| --- | --- |
| [#59498](https://github.com/anthropics/claude-code/issues/59498) | `cd /elsewhere && git push` が `Bash(git push:*)` ask/deny を bypass |
| [#59006](https://github.com/anthropics/claude-code/issues/59006) | `git -C /path commit` が `Bash(git commit *)` deny を bypass |
| [#20085](https://github.com/anthropics/claude-code/issues/20085) | compound 命令 (`a && b`) が個別評価されない |
| [#52419](https://github.com/anthropics/claude-code/issues/52419) | VS Code 拡張の auto-attach が `.claudeignore` / deny を bypass |

`test/agents/test_command_policy.py` の `test_real_bug_*` ケースで、これらの
bypass パターンを hook が確実に block することを保証している。

### 考察

これらが open だったことが、hook 側の normalize で迂回を防ぐ設計の理由だった。現在の open / closed は未確認。

### 次の問い

各 issue の現在の状態の確認。現行の仕様は [agent-command-policy.md](../../spec/guard/agent-command-policy.md#claude-code-permission-リストの既知バグ)。

### 参照

- [#59498](https://github.com/anthropics/claude-code/issues/59498)、[#59006](https://github.com/anthropics/claude-code/issues/59006)、[#20085](https://github.com/anthropics/claude-code/issues/20085)、[#52419](https://github.com/anthropics/claude-code/issues/52419)
