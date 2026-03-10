---
name: fix
description: linter を実行し、解決法が明確な指摘を自動修正する。Python なら uvx ruff、JS/TS なら npx eslint 等を使用。
context: fork
agent: general-purpose
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

## タスク

プロジェクトの linter を実行し、**解決法が明確な**指摘のみ自動修正する。

## 手順

### 1. 言語・linter の特定

プロジェクトルートの設定ファイルから言語と linter を判定する:

| 言語 | 判定ファイル | linter コマンド |
|---|---|---|
| Python | `pyproject.toml`, `setup.py` | `uvx ruff check --fix .` → `uvx ruff format .` |
| JS/TS | `package.json`, `tsconfig.json` | `npx eslint --fix .` |
| Go | `go.mod` | `gofmt -w .` → `go vet ./...` |
| Rust | `Cargo.toml` | `cargo clippy --fix --allow-dirty` |

設定ファイルが複数該当する場合は全て実行する。

### 2. linter の自動修正を実行

- まず `--fix` 等の自動修正オプション付きで linter を実行する
- formatter があれば続けて実行する（ruff format, prettier 等）

### 3. 残存指摘の確認

自動修正後に再度 linter を実行し、残った指摘を確認する。

残存指摘を以下に分類:
- **修正可能**: 修正方法が一意に定まるもの（未使用 import の削除、型アノテーション追加等）→ 手動で修正
- **判断が必要**: 設計に関わる指摘、複数の修正方法があるもの → 修正せずレポートに含める

### 4. レポート

```
## /fix 実行結果

### 実行した linter
- <linter名> <バージョン>

### 自動修正
- <N> 件の指摘を自動修正

### 手動修正
- <ファイル:行> <ルール>: <修正内容>

### 未対応（要判断）
- <ファイル:行> <ルール>: <指摘内容>（理由: ...）

### 修正ファイル一覧
- <ファイルパス>
```

## 制約

- **安全な修正のみ**: 動作が変わる可能性のある修正は行わない
- **判断が必要なものは触らない**: レポートに含めてユーザーに委ねる
- **テスト実行しない**: linter の修正に限定する（テスト実行は別途ユーザーが判断）
