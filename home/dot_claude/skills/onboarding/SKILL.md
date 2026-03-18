---
name: onboarding
description: AGENTS.md を対話的に作成・最適化する。README.md との差別化、既存ルール探索、実在コマンド抽出、ギャップ質問、ドラフト提示、承認後の更新が必要なときに使う。`/onboarding [path|scope] [mode]` で実行。
argument-hint: "[target-path(optional)] [mode: full|partial|minimal]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Edit, Write
---

# AGENTS.md Onboarding Skill

このスキルは **AGENTS.md 一本化運用** を前提に、既存プロジェクトの指示ファイルを安全に再構築する。

## 既存 AGENTS.md（自動読込）

!`if [ -f AGENTS.md ]; then echo "=== 既存 AGENTS.md ==="; cat AGENTS.md; echo "(既存 AGENTS.md なし)"; fi`

## 実行ルール（必須）

- 出力先は `AGENTS.md` のみ。
- `CLAUDE.md` や他ツール固有ファイルの新規作成を提案しない。
- `README.md` の説明文は転載せず、必要なら短い参照にとどめる。
- 存在しないコマンドを記載しない。
- ユーザー承認前にファイル書き込みしない。

## 引数

- `$ARGUMENTS` で対象を受け取る。
- 指定がなければ現在のリポジトリルートを対象にする。
- mode がある場合は優先順で解釈する：`full` / `partial` / `minimal`。

## 実行フロー

### 1) 調査（事実収集）

以下を確認し、根拠付きで要約する。

- 既存指示: `AGENTS.md`, `AGENTS.override.md`, サブディレクトリ配下の `AGENTS.md`
- スタック情報: `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`
- 実行コマンド根拠: `Makefile`, `Taskfile.yml`, `.justfile`, `.github/workflows/*`
- 規約: `README.md`, `CONTRIBUTING.md`, `.editorconfig`, lint/format 設定

### 2) 更新モード確定（対話）

既存 AGENTS.md がある場合は以下から選ばせる。**引数で mode が指定済みの場合は確認不要。**

- full: 完全再構成
- partial: 構成を維持して不足補完
- minimal: 陳腐化箇所のみ更新

### 3) ギャップ質問（不足分のみ）

未確定項目を **1 メッセージにまとめてリスト形式**で質問する。複数ターンに分けない。

- build/test/lint/typecheck の正式コマンド
- 変更時の必須チェック
- 触ってはいけない領域（secrets, 本番設定, 破壊的操作）
- 任意: Git運用、デプロイ注意点、チーム固有ルール

### 4) AGENTS.md ドラフト作成

`${CLAUDE_SKILL_DIR}/references/agents-template.md` をベースに作成する。

品質基準:

- **60〜150 行**目安（長い場合はネスト AGENTS.md を提案。200 行超は Claude の遵守率が下がる）
- `Always / Ask first / Never` を必ず含める
- 不明項目は `TODO: 要確認` と明示
- コマンドはコピペ実行可能な形で記述
- README.md の内容（概要・背景・導入手順）は転載しない。エージェントが実行・判断できる情報（手順・境界・検証基準）のみ記載する

### 5) レビュー出力（書き込み前）

**必須（3 項目）**:

1. AGENTS.md ドラフト全文
2. 既存との差分要約
3. `TODO: 要確認` 一覧

**任意（内容があれば追記）**:

- 調査結果サマリー
- README との重複解消メモ

### 6) 承認後に反映

ユーザーが明示承認したら、`${CLAUDE_SKILL_DIR}/references/review-checklist.md` を読み全項目を確認してから `AGENTS.md` を更新する。

## 出力フォーマット（会話）

- セクション見出しを付けて簡潔に出す。
- 箇条書き主体で、冗長説明を避ける。
- 変更理由は「なぜ必要か」を 1 行で添える。

## 参照ファイル

- テンプレート: `${CLAUDE_SKILL_DIR}/references/agents-template.md`
- チェックリスト: `${CLAUDE_SKILL_DIR}/references/review-checklist.md`

## 付記（モノレポの場合のみ）

- ルート AGENTS.md は全体方針のみ記載。
- サブパッケージ固有ルールは各パス配下の AGENTS.md に分離提案。
- 近接ルール優先を明記する。
