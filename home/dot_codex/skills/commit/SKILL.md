---
name: commit
description: "Conventional Commits 形式のメッセージ作成と Git コミットを行う。「コミットして」「commit メッセージを作って」「変更をコミット」と言われたら必ず使う。"
---

# Git コミットスキル

## コンテキスト収集

補助スクリプトは使わず、次を直接実行する:

- `git status --short --branch`
- `git diff HEAD`
- `git branch --show-current`
- `git log --oneline -10`

差分を論理単位に分け、ユーザーの変更や無関係な変更を混ぜない。

## 実行

1. Conventional Commits に従ってメッセージを作成する。
2. type は `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
   `build`, `ci`, `chore` から選ぶ。
3. 件名は命令形・72文字以内・文末ピリオドなしとする。
4. メッセージ作成だけを依頼された場合は、対象ファイルとメッセージを提示して終了する。
5. コミットを依頼された場合は、対象ファイルをパスで明示してステージする。
   ステージは取り消せるので、この時点では承認を求めない。

   ```bash
   git add -- <対象ファイル...>
   ```

6. **コミット前の承認**: ステージ内容 (`git status --short`) とコミットメッセージ
   全文を提示してユーザーの承認を得る。目的はメッセージの確認で、承認が
   得られなければコミットせず、指摘に沿って直して再提示する。
7. 承認後にコミットする。`git add` と `&&` で連結しない。rules は
   shell compound の内側を解析しないため、連結すると prompt が効かなくなる。

   ```bash
   git commit -m '<件名>' -m '<本文>'
   ```

8. コミット後に `git status --short` と `git log -1 --oneline` で結果を確認する。

## 禁止

- `--no-verify` などによる hook の回避
- `git add .` / `git add -A` による無関係な変更の追加
- `git commit -a` / `git commit --all` による無関係な変更の追加
- 明示依頼のない `git commit --amend`
- 未測定の数値主張
