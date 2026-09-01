# agent 設定生成に Python 3.11 以上を要求する

- **ステータス**: Accepted
- **日付**: 2026-09-01
- **決定者**: applejxd

## コンテキスト

このリポジトリは `home/dot_config/agents/common.toml` を単一ソースとして、
`scripts/agents/generate.py` から各 AI CLI の設定を生成する。導入後の hook も
`home/dot_config/agents/command_policy.py` から同じ TOML を読む。

両 module は Python 3.11+ の `tomllib` を使い、古い Python では外部パッケージ
`tomli` へ fallback していた。しかし chezmoi は project の uv 環境ではなく
system Python で template と modify script を実行するため、Python 3.10 以下の
Windows 環境では利用者による `pip install tomli` が必要になった。

Windows の package setup は Python 3.12 を導入しており、project 自体も
Python 3.13 以上を要求している。古い Python のためだけに runtime dependency を
増やすより、bootstrap の最小バージョンを明示する時期に来ている。

## 検討した選択肢

### 選択肢 1: Python 3.11 以上を明示的な前提にする

`tomli` fallback を削除し、Windows では `py -3` で最新の Python 3 を選択する。
PowerShell quick start で Python 3.12 を chezmoi より先に導入する。

- **利点**: 外部 Python package が不要になり、stdlib only という runtime の境界が
  明確になる。Python 3.10 を誤選択せず、生成時と hook 実行時の前提が一致する
- **欠点**: Python 3.10 以下だけの既存環境では、先に Python 本体を更新する必要がある

### 選択肢 2: Tomli を repository に同梱する

Tomli の pure Python package とライセンスを repository に取り込み、
Python 3.10 以下も継続して対応する。

- **利点**: 古い Python 環境でも追加インストールなしで動く
- **欠点**: upstream の更新・ライセンス・脆弱性を repository 側で管理する必要がある。
  Windows の標準導入が既に Python 3.12 のため、維持コストに対する便益が小さい

### 選択肢 3: `tomli` を自動的に pip install する

不足時に user site-packages へ `tomli` を導入する。

- **利点**: 現在の fallback を維持できる
- **欠点**: 設定生成と hook 実行がネットワークと pip に依存し、副作用を持つ。
  package 導入より前に template 評価が失敗する bootstrap 循環も解消できない

## 決定事項

**選択肢 1 を採用する。**

理由: Windows setup は Python 3.12、開発環境は Python 3.13 以上へ既に移行しており、
Python 3.10 以下の互換性のために dependency を vendoring する合理性が低い。
選択肢 2 は継続的な保守対象を増やし、選択肢 3 は runtime に予期しない
package installation とネットワーク依存を持ち込むため却下する。

具体的な規則は次のとおり。

1. agent 設定生成と policy module は Python 3.11 以上を要求し、TOML は
   標準ライブラリ `tomllib` で読む
2. Windows の chezmoi Python interpreter と Python hook は `py -3` を使い、
   インストール済みの最新 Python 3 を選択する。3.11 未満は `tomllib` import
   failure として明示的に失敗させる
3. Windows quick start は Python 3.12 を chezmoi より先に導入する
4. `tomli` の手動・自動インストール、および repository への vendoringは行わない
5. policy module を import できない hook は既存方針どおり fail-closed とする

## 完了条件

- [x] `generate.py` と `command_policy.py` から `tomli` fallback を削除する
- [x] Windows の chezmoi interpreter と生成済み Python hook が `py -3` を使う
- [x] README に PowerShell bootstrap と Python 3.11+ の前提を記載する
- [x] troubleshooting に `tomli` を導入しない復旧手順を記載する
- [x] agent 関連 test と pre-commit が通過する

## 結果

### ポジティブな結果

- Windows 導入時に `pip install tomli` が不要になる
- generator と runtime hook の Python 前提が一致する
- project の uv 環境と chezmoi runtime の依存境界が明確になる

### ネガティブな結果

- Python 3.10 以下だけの環境では Python 本体の更新が必要になる

### 中立的な結果

- Python 本体は Windows bootstrap の明示的な前提として残る
- ADR-0001 の `common.toml` 単一ソースと外部設定共存の決定は変更しない

## 関連 ADR

- [ADR-0001](0001-external-tool-config-coexistence.md): `common.toml` を単一ソースに
  する設定生成方式。本 ADR はその Python runtime の最小バージョンを定める
