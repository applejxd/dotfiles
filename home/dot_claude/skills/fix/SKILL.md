---
name: fix
description: "linter を実行し、解決法が明確な指摘を自動修正する。「fix して」「lint エラーを直して」と言われたときに使う。"
context: fork
agent: general-purpose
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Lint & Format 自動修正スキル

## タスク

プロジェクトの linter を実行し、**解決法が明確な指摘のみ**自動修正する。

## 手順

### 1. 言語の特定

プロジェクトルートの設定ファイルから言語を判定し、言語ごとのガイドを読み込む:

| 言語 | 判定ファイル | 参照ガイド |
|------|-------------|-----------|
| Python | `pyproject.toml`, `setup.py`, `setup.cfg` | `${CLAUDE_SKILL_DIR}/references/python.md` |
| JS/TS | `package.json`, `tsconfig.json` | `${CLAUDE_SKILL_DIR}/references/js-ts.md` |
| Go | `go.mod` | `${CLAUDE_SKILL_DIR}/references/go-rust.md` |
| Rust | `Cargo.toml` | `${CLAUDE_SKILL_DIR}/references/go-rust.md` |
| C++ | `CMakeLists.txt`, `compile_commands.json` | `${CLAUDE_SKILL_DIR}/references/cpp.md` |

複数の言語が該当する場合はすべてのガイドを読み込み、順に実行する。

### 2. linter の実行

各言語ガイドに従い、自動修正オプション付きで linter・formatter を実行する。

### 3. 残存指摘の分類

自動修正後に再度 linter を実行し、残った指摘を分類する:

- **修正可能**: 修正方法が一意に定まるもの → 手動で修正
- **判断が必要**: 設計に関わる・複数の修正方法があるもの → レポートに含めるのみ

### 4. レポート出力

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
- **テスト実行しない**: linter の修正に限定する
