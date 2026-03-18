# Python — Lint & Format ガイド

## 実行環境

**必ず `uv run` 経由で実行する。** `uvx` は外部ツールを一時実行するが、
プロジェクトの仮想環境に依存するツールは `uv run` を使う。

```
# プロジェクト環境内で実行（推奨）
uv run ruff check --fix .
uv run ruff format .

# プロジェクト環境外で一時実行（ruff がプロジェクト依存でない場合）
uvx ruff check --fix .
uvx ruff format .
```

> **判断基準**: `pyproject.toml` に ruff が `[tool.ruff]` で設定されているか、
> `[project.optional-dependencies]` / `[dependency-groups]` に含まれる場合は `uv run`。
> それ以外は `uvx` でも可。

## 検出ファイル

| ファイル | 用途 |
|---|---|
| `pyproject.toml` | メイン設定（`[tool.ruff]` セクション） |
| `ruff.toml` | ruff 専用設定ファイル |
| `.ruff.toml` | 同上（隠しファイル） |

## 実行手順

```bash
# 1. 自動修正可能な lint エラーを修正
uv run ruff check --fix .

# 2. フォーマット適用
uv run ruff format .

# 3. 残存 lint エラーを確認（修正不可分を把握）
uv run ruff check .
```

## よく使うオプション

```bash
# 特定ファイルのみ
uv run ruff check --fix src/foo.py

# ルールを指定して修正
uv run ruff check --fix --select E,F .

# 差分のみ確認（修正しない）
uv run ruff check --diff .

# 設定を無視して全ルール対象（調査用）
uv run ruff check --select ALL .
```

## 自動修正の安全性

| 操作 | 安全度 | 備考 |
|---|---|---|
| `ruff check --fix` | ✅ 安全 | 未使用 import 削除、構文系修正 |
| `ruff format` | ✅ 安全 | コードの意味を変えない整形のみ |
| `--unsafe-fixes` | ⚠️ 要判断 | 動作変更の可能性あり → 実行しない |

## 修正可能 vs 判断が必要な例

**自動修正してよい:**
- `F401` — 未使用 import
- `F811` — 再定義
- `E711` — `== None` → `is None`
- `UP` 系 — Python バージョン対応の書き換え

**判断が必要（レポートのみ）:**
- `E501` — 行長超過（ロジックの再構成が必要な場合）
- `C901` — 複雑度が高い（リファクタリング判断）
- `S` 系 — セキュリティ関連
