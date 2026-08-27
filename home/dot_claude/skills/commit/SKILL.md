---
name: commit
description: "Conventional Commits 形式でコミットメッセージを生成する。「コミットして」「commit メッセージを作って」と言われたときに使う。"
context: fork
agent: general-purpose
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git add:*), Bash(git commit:*), Bash(*get-git-context.sh*)
---

# コミットメッセージ生成スキル

## コンテキスト収集

`${CLAUDE_SKILL_DIR}/scripts/get-git-context.sh` を実行して以下を取得する:

- `git status` — 変更ファイル一覧
- `git diff HEAD` — ステージ済み＋未ステージ差分
- `git branch --show-current` — 現在のブランチ
- `git log --oneline -10` — 直近コミット履歴

## タスク

上記コンテキストを基に **Conventional Commits** 形式でコミットメッセージを作成する。
仕様の詳細は `${CLAUDE_SKILL_DIR}/references/conventional-commits-spec.md` を参照。

コミットメッセージの作成だけを依頼された場合はメッセージを提示する。
コミットを依頼された場合は対象ファイルだけを `git add` し、そのメッセージで
`git commit` を実行する。`git commit` は permission の ask で確認される。

## スタイル規範

- **出力言語**: 既定は **英語**。ユーザーが日本語で問いかけた場合は日本語で出力
- **必要十分・非誇張**: 事実のみ（何を・なぜ・影響）。誇張・曖昧語を避ける
- 件名は命令形・**72文字以内**・文末ピリオドなし
- **定量主張の条件**:
  - 数値（例: `+30% speedup`）は**測定済みであること**が条件
  - 未測定の見込み・推定（例: `~30% expected`）は**禁止**

## 出力フォーマット

```text
<type>(<scope>): <subject>

- Motivation: <why>
- Change: <what>
- Impact: <effect>  # 数値を書くのは測定済みのときのみ
```

## ポリシー

**禁止**:

- `--no-verify` などによる hook の回避
- 共同著者タグ・Claude リンクの追加
- 未測定の数値主張

**要求**:

- コミット対象に含めるファイルだけを `git add` する
- コミット後に `git status` と直近コミットを確認する
