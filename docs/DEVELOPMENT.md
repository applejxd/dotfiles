# 開発者向けドキュメント

## 開発環境のセットアップ

### pre-commitの設定（新規環境）

このリポジトリを新しい環境でクローンした後、以下の手順でpre-commit環境を構築できます。

#### 1. miseによるツールのインストール

```bash
# miseがインストール済みの場合
mise install

# miseが未インストールの場合（chezmoi適用で自動インストール）
chezmoi apply
```

#### 2. Python環境の構築

```bash
# uvとPythonがmiseで管理されているため自動で利用可能
uv sync                    # 依存関係のインストール
uv run pre-commit install  # pre-commitフックの設定
```

#### 3. 手動実行とテスト

```bash
# 全ファイルに対してpre-commitチェック実行
uv run pre-commit run --all-files

# 個別ツールの実行例
mise exec gitleaks -- detect --source .
uv run shellcheck installer/**/*.sh
```

#### 4. 継続的な使用

```bash
# 通常のgit操作でpre-commitが自動実行
git add .
git commit -m "commit message"  # pre-commitが自動実行される

# 手動でのチェック
uv run pre-commit run --all-files
```

#### 環境管理のメリット

- **統一された環境管理**: mise → uv → pre-commitの一貫したツールチェーン
- **新規環境での簡単セットアップ**: `mise install && uv sync && uv run pre-commit install`
- **バージョン固定**: mise.tomlとuv.lockによる再現可能な環境
- **段階的導入**: 既存環境に影響せず新規環境から適用可能

## カスタマイズ

### パスワード管理

パスワードは以下の方法で設定できます：

1. **環境変数**: `export SUDO_PASSWORD="your_password"`
2. **対話的入力**: 初回実行時にプロンプトで入力
3. **スキップ**: Enter キーでスキップ（手動入力が必要な場合あり）

### 設定ファイルの編集

```bash
# 設定ファイルを編集
chezmoi edit ~/.bashrc

# 変更を確認
chezmoi diff

# 変更を適用
chezmoi apply
```

### スクリプトの無効化

特定のスクリプトを実行したくない場合：

```bash
# ファイル名を変更して無効化
chezmoi edit home/.chezmoiscripts/run_once_800_vscode_extensions.sh.tmpl
# ファイル名から .tmpl を削除するか、ファイルを削除
```

## テンプレート変数

利用可能な chezmoi テンプレート変数：

- `{{ .chezmoi.os }}` - OS名 (linux/darwin)
- `{{ .chezmoi.homeDir }}` - ホームディレクトリパス
- `{{ .chezmoi.sourceDir }}` - ソースディレクトリパス
- `{{ .sudo_password }}` - sudo パスワード

## 新しいスクリプトの追加

1. `home/.chezmoiscripts/` にスクリプトを追加
2. 実行順序を考慮してファイル名の番号を設定
3. 必要に応じて `.tmpl` 拡張子を付けてテンプレート機能を使用
