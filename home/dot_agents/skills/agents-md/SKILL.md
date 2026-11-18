---
name: agents-md
description: "AGENTS.md を新規作成・整理する、または会話で分かった知見を AGENTS.md へ追記する（差分の提案まで。反映は明示的に頼まれたときだけ）。「AGENTS.md を作って」「AGENTS.md を整理して／見直して」「この会話の知見を AGENTS.md に反映して」で使う。docs/ の仕様・調査記録・ADR は sdd-docs の領分なので使わない。"
disable-model-invocation: true
allowed-tools: Read, Edit, Write, Grep, Glob
---

# agents-md

> **この skill は fork しない（`context: fork` を付けない）。**
>
> 会話の知見の追記は入力が親の会話そのものなので、独立したサブエージェントでは成立しない
> （fork すると**会話が見えないまま知見を捏造する**）。新規作成・整理も、質問と承認でユーザーとやり取りするため fork しない。

AGENTS.md 一本化運用を前提に、プロジェクトの指示ファイルを作る・整える・育てる。

## モードの選び方

- **会話で分かった知見を AGENTS.md へ追記する**（「この会話の知見を AGENTS.md に反映して」など）:
  `references/append-from-conversation.md` を読んで従う。差分の提案までが既定で、書き込みは明示的に頼まれたときだけ。
- **AGENTS.md を新規作成・整理する**（「AGENTS.md を作って」「AGENTS.md を整理して／見直して」など）:
  `references/rebuild.md` を読んで従う。リポジトリを調査し、質問を通してドラフトを作る。

## 共通の規則

- 出力先は `AGENTS.md` だけ。`CLAUDE.md` や他ツール固有ファイルの新規作成を提案しない。
- ユーザー承認前にファイルへ書き込まない。
- 言語はユーザーの使用言語に合わせる。
- `docs/` の仕様・調査記録・ADR は書かない（`sdd-docs` スキルの領分）。移管候補として報告に挙げる。
