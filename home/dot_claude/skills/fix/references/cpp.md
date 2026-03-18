# C++ — Lint & Format ガイド

## ツール構成

| ツール | 役割 | 自動修正 |
|---|---|---|
| `clang-format` | フォーマッター | ✅ |
| `clang-tidy` | 静的解析（clangd のバックエンド） | ✅ 一部 |
| `cppcheck` | 静的解析（メモリ・UB 検出） | ❌ レポートのみ |
| `cpplint` | Google スタイルチェック | ❌ レポートのみ |

> **clangd との関係**: clangd はエディタ向け LSP サーバー。CLI バッチ lint には
> `clang-tidy` を直接使う。clangd の診断は clang-tidy が提供している。

## 検出ファイル

| ファイル | 用途 |
|---|---|
| `CMakeLists.txt` | CMake プロジェクト |
| `compile_commands.json` | clang-tidy が参照するコンパイル DB |
| `.clang-format` | clang-format 設定 |
| `.clang-tidy` | clang-tidy 有効ルールの設定 |
| `meson.build` | Meson プロジェクト |

## 実行手順

```bash
# 1. フォーマット（最も安全）
clang-format -i **/*.cpp **/*.h
# 再帰的に適用する場合
find . -name '*.cpp' -o -name '*.h' | xargs clang-format -i

# 2. clang-tidy（compile_commands.json が必要）
#    CMake で生成する場合:
cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -B build .

#    lint 実行（自動修正あり）
clang-tidy --fix -p build src/**/*.cpp

#    lint 確認のみ（修正なし）
clang-tidy -p build src/**/*.cpp

# 3. cppcheck（サブ確認、自動修正なし）
cppcheck --enable=all --suppress=missingIncludeSystem src/
```

## compile_commands.json がない場合

```bash
# CMake プロジェクトでない場合の最小構成
clang-tidy --extra-arg="-std=c++17" src/foo.cpp --

# または Bear で生成
bear -- make
```

## よく使うオプション

```bash
# 特定チェックのみ実行
clang-tidy -checks='modernize-*,readability-*' --fix src/foo.cpp -p build

# 差分確認のみ（修正なし）
clang-format --dry-run --Werror src/foo.cpp

# clang-format スタイル確認
clang-format --style=file --dump-config
```

## 自動修正の安全性

| 操作 | 安全度 | 備考 |
|---|---|---|
| `clang-format -i` | ✅ 安全 | 純粋なフォーマット |
| `clang-tidy --fix` | ✅ 概ね安全 | 機械的修正のみ |
| `clang-tidy --fix-errors` | ⚠️ 要確認 | エラー扱いも修正する |
| `cppcheck` | ✅ 読み取り専用 | 診断のみ |

## 修正可能 vs 判断が必要な例

**自動修正してよい:**
- `modernize-use-nullptr` — `NULL` → `nullptr`
- `modernize-use-override` — `override` キーワード追加
- `readability-redundant-*` — 冗長な記述の削除
- `clang-format` によるインデント・スペース整形

**判断が必要（レポートのみ）:**
- `cppcheck` のメモリリーク・UB 警告（設計変更が必要）
- `clang-tidy` の `performance-*` 系（ロジック変更を伴う）
- `bugprone-*` 系（誤検知の可能性あり、文脈判断が必要）
