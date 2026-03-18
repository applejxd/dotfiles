# Conventional Commits 1.0.0 — Quick Reference

> Source: <https://www.conventionalcommits.org/en/v1.0.0/>

## 構造

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

## type 一覧

| type | 意味 | SemVer |
|------|------|--------|
| `feat` | 新機能 | MINOR |
| `fix` | バグ修正 | PATCH |
| `docs` | ドキュメントのみ | — |
| `style` | コードの意味に影響しないフォーマット変更 | — |
| `refactor` | バグ修正でも機能追加でもないコード変更 | — |
| `perf` | パフォーマンス改善 | — |
| `test` | テスト追加・修正 | — |
| `build` | ビルドシステム・外部依存の変更 | — |
| `ci` | CI 設定変更 | — |
| `chore` | その他の雑務（src/test に影響なし） | — |

> `feat` / `fix` 以外の type は SemVer に影響しない（BREAKING CHANGE を除く）。

## scope

- type の後に括弧で囲んで記述する名詞: `feat(parser):` `fix(api):`
- コードベースのセクションを表す

## Breaking Change の表記

```
# 方法1: ! を使う（推奨）
feat!: drop support for Node 6
feat(api)!: remove deprecated endpoint

# 方法2: footer に BREAKING CHANGE: を書く
feat: allow config to extend other configs

BREAKING CHANGE: `extends` key now extends other config files

# 方法3: ! と footer を併用（最も明示的）
feat!: drop support for Node 6

BREAKING CHANGE: use JavaScript features not available in Node 6.
```

Breaking Change は MAJOR バンプに対応する。

## footer の形式

```
fix: prevent racing of requests

Refs: #123
Reviewed-by: Alice
BREAKING CHANGE: environment variables now take precedence over config files.
```

- トークンと値は `: ` または ` #` で区切る
- トークンの空白は `-` に置換する（例: `Acked-by`）
- `BREAKING CHANGE` と `BREAKING-CHANGE` は同義

## 仕様上の MUST / MUST NOT（抜粋）

1. type **MUST** be a noun followed by `:` and a space
2. `feat` **MUST** be used when adding a new feature
3. `fix` **MUST** be used for bug fixes
4. description **MUST** immediately follow the type/scope prefix
5. body **MUST** begin one blank line after description
6. footer tokens **MUST** use `-` in place of whitespace (except `BREAKING CHANGE`)
7. `BREAKING CHANGE` **MUST** be uppercase in footer
8. type/description are **NOT** case-sensitive (except `BREAKING CHANGE`)

## SemVer との対応

```
feat  → MINOR bump
fix   → PATCH bump
BREAKING CHANGE (any type) → MAJOR bump
```

## 良い例

```
# シンプル
docs: correct spelling of CHANGELOG

# scope あり
feat(lang): add Polish language

# Breaking Change (! スタイル)
feat(api)!: remove v1 endpoints

# Body + footer あり
fix: prevent racing of requests

Introduce a request id and a reference to latest request.
Dismiss incoming responses other than from latest request.

Reviewed-by: Z
Refs: #123
```
