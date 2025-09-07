---
description: "git commit をクリーンになるまで反復"
allowed-tools: Bash(git add:*), Bash(git status:*), Bash(git diff:*), Bash(git branch:*), Bash(git log:*), Bash(git commit:*), Bash(git restore:*), Bash(git rev-parse:*), Bash(git check-ignore:*), Bash(git ls-files:*)
argument-hint: "[scope-prefix?] [--include-ignored]"
---

## コンテキスト
- branch: !`git branch --show-current`
- status: !`git status --porcelain=v1 -b --ignored`
- root:   !`git rev-parse --show-toplevel`

## 役割
未ステージの変更を**上位ディレクトリ単位**でグルーピング（例: `src/`, `tests/`, `docs/`, `ui/`, `core/`）。`$ARGUMENTS` があれば**接頭辞一致**を優先。大きい場合はサブディレクトリで細分化。

## ループ
1) 候補 C を抽出  
2) Ignore Guard: `I = !\`printf "%s\n" <C> | git check-ignore --stdin\``  
   - 既定: `C_non = C \ I` のみ add  
   - `--include-ignored` 指定時のみ `!git add -f <I>`  
3) ステージ: `!git add <C_non>`（誤追加は `!git restore --staged <paths>`）  
4) メッセージ生成（Conventional Commits）：
```
<type>(<scope>): <日本語の簡潔な説明>

- <差分の要約1>
- <差分の要約2>
```
- type ∈ {feat, fix, docs, style, refactor, test, chore}  
- scope はパス/モジュールから推定（例: core, ui, db, cli, build）  
- 破壊的変更は `!` または `BREAKING CHANGE:` を本文に明記
5) commit: `!git commit -m "<ヘッダ>\n\n<本文>"`  
6) `!git status --porcelain` が空になるまで 1)〜5) 反復。最後に `!git log --oneline -10`
