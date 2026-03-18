# JavaScript / TypeScript — Lint & Format ガイド

## 検出ファイル

| ファイル | 判定内容 |
|---|---|
| `package.json` | JS/TS プロジェクトの基本判定 |
| `tsconfig.json` | TypeScript プロジェクト |
| `.eslintrc*`, `eslint.config.*` | ESLint 設定 |
| `.prettierrc*`, `prettier.config.*` | Prettier 設定 |

## 実行手順

```bash
# 1. ESLint 自動修正
npx eslint --fix .
# または (package.json に scripts があれば)
npm run lint -- --fix

# 2. Prettier フォーマット（設定がある場合）
npx prettier --write .

# 3. TypeScript 型チェック（tsconfig.json がある場合）
npx tsc --noEmit

# 4. 残存エラー確認
npx eslint .
```

## よく使うオプション

```bash
# 特定ファイルのみ
npx eslint --fix src/foo.ts

# ルールを指定
npx eslint --rule 'no-unused-vars: error' --fix .

# 差分確認（修正しない）
npx prettier --check .
```

## 自動修正の安全性

| 操作 | 安全度 | 備考 |
|---|---|---|
| `eslint --fix` | ✅ 安全 | 整形・明確な構文修正 |
| `prettier --write` | ✅ 安全 | コードの意味を変えない |
| `tsc --noEmit` | ✅ 読み取り専用 | 型エラーの確認のみ |

## 修正可能 vs 判断が必要な例

**自動修正してよい:**
- `no-extra-semi` — 余分なセミコロン
- `no-var` — `var` → `let`/`const`
- `prefer-const` — `let` → `const`
- Prettier によるインデント・クォート整形

**判断が必要（レポートのみ）:**
- `@typescript-eslint/no-explicit-any` — `any` 型（設計判断）
- `no-unused-vars` — 削除すると影響範囲が広い場合
- `complexity` — 関数の複雑度
