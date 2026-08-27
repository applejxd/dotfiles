---
name: commit
description: "Conventional Commits 形式のメッセージ作成と Git コミットを行う。「コミットして」「commit メッセージを作って」「変更をコミット」と言われたら必ず使う。"
context: fork
agent: general-purpose
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git add:*), Bash(git commit:*)
---

# Git コミットスキル

## コンテキスト収集

補助スクリプトは使わず、以下のコマンドを直接実行する:

- `git status --short --branch` — 変更ファイルとブランチ
- `git diff HEAD` — ステージ済み・未ステージの差分
- `git branch --show-current` — 現在のブランチ
- `git log --oneline -10` — 直近コミット履歴

差分を論理単位に分け、ユーザーの変更や無関係な変更を混ぜない。

## 実行

1. 上記コンテキストから **Conventional Commits** 形式のメッセージを作成する。
   詳細は `references/conventional-commits-spec.md` を参照する。
2. メッセージ作成だけを依頼された場合は、対象ファイルとメッセージを提示して終了する。
3. コミットを依頼された場合は、対象ファイルを列挙した次の形を**1回の Bash 呼び出し**
   で実行する:

   ```bash
   git add -- <対象ファイル...> && git commit -m '<件名>' -m '<本文>'
   ```

   `git commit` は共通 PreToolUse hook の ask 対象で、compound command 全体が
   ステージング前に止まる。**Claude Code ではこの hook 確認が唯一の確認点**
   なので、スキル独自の確認は挟まない。
4. **Copilot CLI で実行している場合に限り**、上記コマンドを出す前に対象ファイルと
   コミットメッセージを提示し、ユーザーの承認を得てから実行する。
   Copilot CLI 1.0.53 以降には hook の `ask` を TUI が数十 ms で自動承認する
   既知バグ (github/copilot-cli#3590) があり、hook 確認が機能しないため。
   このバグが修正されたら、この手順を削除して hook 一本へ戻す。
5. コミット後に `git status --short` と `git log -1 --oneline` を実行し、
   コミットと作業ツリーを確認する。

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
- `git add .` / `git add -A` による無関係な変更の追加
- `git commit -a` / `git commit --all` による無関係な変更の追加
- 明示依頼のない `git commit --amend`
- 共同著者タグ・Claude リンクの追加
- 未測定の数値主張

**要求**:

- 対象ファイルをパスで明示してステージする
- hook の確認が拒否された場合はコミットせず停止する
- Copilot CLI で承認が得られない場合はコミットせず停止する
