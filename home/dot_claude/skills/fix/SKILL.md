---
name: fix
description: "プロジェクトの linter / formatter を実行し、解決法が明確な指摘だけを自動修正する。「lint を直して」「lint エラーを直して」「フォーマットして」「/fix」と言われたときに使う。バグ修正・テストの失敗・型エラー・ビルドエラーには使わない（「fix して」がそれらを指すときも使わない）。"
context: fork
agent: general-purpose
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Lint & Format 自動修正スキル

## タスク

プロジェクトの linter を実行し、**解決法が明確な指摘のみ**自動修正する。

## 手順

### 0. 範囲の確定

依頼から次の 2 つを決める。決まらなければリポジトリ全体・lint 修正と整形の両方とする。

- **対象パス**: 指定があればそこだけ。プロジェクトの除外設定（`.gitignore`・linter の exclude）を守る
- **種類**: 整形だけ（「フォーマットして」）/ lint 修正だけ / 両方。整形だけの依頼では lint の自動修正を走らせない

### 1. 実行方法の特定

優先順は **リポジトリの規約 → 既存のタスクと設定 → 言語別ガイド**。

1. `AGENTS.md` / `CONTRIBUTING.md` に lint の手順があればそれに従う
2. `.pre-commit-config.yaml`・`package.json` の scripts・`Makefile` / `mise.toml` のタスクに
   lint / format があればそれを使う（固定されたバージョンと除外設定がそのまま効く）
3. どちらも無ければ、設定ファイルから言語を判定して言語ごとのガイドを読む:

| 言語 | 判定ファイル | 参照ガイド |
| ------ | ------------- | ----------- |
| Python | `pyproject.toml`, `setup.py`, `setup.cfg` | `${CLAUDE_SKILL_DIR}/references/python.md` |
| JS/TS | `package.json`, `tsconfig.json` | `${CLAUDE_SKILL_DIR}/references/js-ts.md` |
| Go | `go.mod` | `${CLAUDE_SKILL_DIR}/references/go-rust.md` |
| Rust | `Cargo.toml` | `${CLAUDE_SKILL_DIR}/references/go-rust.md` |
| C++ | `CMakeLists.txt`, `compile_commands.json` | `${CLAUDE_SKILL_DIR}/references/cpp.md` |

複数の言語が該当する場合はすべてのガイドを読み込み、順に実行する。
ガイドのコマンドは例であり、手順 0 の範囲に合わせて対象パスを絞る。
プロジェクトに設定の無い linter / formatter を新たに導入・適用しない（報告に留める）。

### 2. linter の実行

手順 1 で決めた方法で、自動修正オプション付きで実行する。

### 3. 残存指摘の分類

自動修正後に再度 linter を実行し、残った指摘を分類する:

- **修正可能**: 修正方法が一意に定まる lint 指摘 → 手動で修正し、対象の lint / format の検査を再実行する
- **判断が必要**: 設計に関わる・複数の修正方法があるもの → レポートに含めるのみ
- **対象外**: 型チェック・ビルドの診断 → 直さずにレポートに含めるのみ

### 4. レポート出力

```text
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
