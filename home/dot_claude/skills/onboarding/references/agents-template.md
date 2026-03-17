# AGENTS.md テンプレート（一本化・最適化版）

## NG / OK 対比（生成前に確認）

**NG — README の転載（エージェントに不要）**

```markdown
## プロジェクトとは

本プロジェクトは〇〇を解決するためのツールです。詳しくは README を参照してください。

## インストール

1. リポジトリをクローンする
2. `npm install` を実行する
```

**OK — エージェントが実行・判断できる情報**

```markdown
## 最重要コマンド

- Install: `npm ci`
- Test: `npm test`
- Lint: `npm run lint`

## 変更時の必須チェック

- `npm test` を実行し全テストが通ること
- `npm run lint` でエラーがないこと
```

---

```markdown
# AGENTS.md

## このファイルの目的

- 本ファイルは AI エージェント向けの実務ルールを定義する。
- README.md の補助ではなく、作業手順と安全境界を明文化する。

## プロジェクト概要（1〜3行）

- プロジェクト名: <name>
- 概要: <summary>

## 技術スタック

- Language: <...>
- Framework: <...>
- Package Manager: <...>

## 最重要コマンド（実在のみ）

- Install: `<command>`
- Build: `<command>`
- Test: `<command>`
- Lint: `<command>`
- Typecheck: `<command>`

## 変更時の必須チェック

- `<test command>` を実行し成功させる
- `<lint command>` を実行し成功させる
- `<typecheck command>` を実行し成功させる

## ディレクトリ責務

- `src/`: 実装
- `tests/`: テスト
- `docs/`: ドキュメント
- 既存レイヤを越える変更は事前相談

## コード規約

- 既存の formatter / linter 設定に従う
- 不要な大規模リファクタを避ける
- 挙動変更時はテストを追加・更新する

## 安全境界（Always / Ask first / Never）

- Always:
  - 変更理由と検証結果を簡潔に示す
- Ask first:
  - 新規ランタイム依存追加
  - DBスキーマ変更
  - CI/CD設定変更
- Never:
  - 秘密情報（APIキー、.env、トークン）をコミットしない
  - 本番設定・認証設定を無断変更しない
  - 破壊的操作（大量削除、履歴改変、force push）を無断実行しない

## PRルール

- 必須チェックを全通過させる
- 変更概要・影響範囲・テスト結果を記載する

## 不明点があるとき

- 推測で進めず確認する
- `TODO: 要確認` を明示して報告する
```
