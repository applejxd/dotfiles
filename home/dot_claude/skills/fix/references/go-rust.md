# Go / Rust — Lint & Format ガイド

## Go

### 検出ファイル: `go.mod`

### 実行手順

```bash
# 1. フォーマット（標準ツール）
gofmt -w .

# 2. vet（標準の静的解析）
go vet ./...

# 3. golangci-lint（設定がある場合）
# .golangci.yml / .golangci.toml / .golangci.yaml が存在する場合
golangci-lint run --fix ./...
```

### 自動修正の安全性

| 操作 | 安全度 | 備考 |
|---|---|---|
| `gofmt -w` | ✅ 安全 | 純粋なフォーマット |
| `go vet` | ✅ 読み取り専用 | 診断のみ、修正なし |
| `golangci-lint --fix` | ✅ 安全 | 整形系ルールのみ自動修正 |

---

## Rust

### 検出ファイル: `Cargo.toml`

### 実行手順

```bash
# 1. フォーマット
cargo fmt

# 2. Clippy（lint + 自動修正）
cargo clippy --fix --allow-dirty

# 3. 残存 warning 確認
cargo clippy
```

### よく使うオプション

```bash
# ステージ済み変更のみ対象
cargo clippy --fix

# 特定の lint を指定
cargo clippy -- -D warnings

# フォーマット確認のみ（修正しない）
cargo fmt -- --check
```

### 自動修正の安全性

| 操作 | 安全度 | 備考 |
|---|---|---|
| `cargo fmt` | ✅ 安全 | 純粋なフォーマット |
| `cargo clippy --fix` | ✅ 安全 | 明確な機械的修正 |
| `--allow-dirty` | ⚠️ 注意 | 未コミット変更に適用するため git diff で確認 |

### 修正可能 vs 判断が必要な例

**自動修正してよい:**
- `clippy::needless_return` — 不要な `return`
- `clippy::clone_on_copy` — Copy 型の不要な `.clone()`
- `clippy::unused_imports` — 未使用 import

**判断が必要（レポートのみ）:**
- `clippy::complexity` 系 — ロジックの書き換えが必要
- `clippy::pedantic` 系 — スタイル変更を伴う
