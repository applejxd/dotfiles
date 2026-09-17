# 開発者向けドキュメント

## 開発環境のセットアップ

### pre-commitの設定（新規環境）

このリポジトリを新しい環境でクローンした後、以下の手順でpre-commit環境を構築できます。

#### 1. miseによるツールのインストール

```bash
# miseがインストール済みの場合
mise trust
mise install

# miseが未インストールの場合（chezmoi適用で自動インストール）
chezmoi apply
```

#### 2. Python環境の構築

```bash
# miseがuvを提供し、uvがpyproject.tomlに従ってPython 3.13以上を選択・取得
uv sync                    # 依存関係のインストール
uv run pre-commit install  # pre-commitフックの設定
```

Windows native と WSL で同じ worktree を共有する場合、mise が
`UV_PROJECT_ENVIRONMENT` を切り替え、Windows は `.venv-windows`、
Unix は `.venv` を使用します。OS の異なる Python 仮想環境を上書きしません。

#### 3. 手動実行とテスト

```bash
# 全ファイルに対してpre-commitチェック実行
uv run pre-commit run --all-files

# 個別ツールの実行例
mise exec gitleaks -- detect --source .
git ls-files '*.sh' | xargs mise exec shellcheck -- shellcheck

# chezmoi テンプレートを描画して検査
mise exec -- python3 scripts/lint_templates.py

# agent設定・hook
uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q
```

##### テンプレートの検査

`identify` は `*.tmpl` に一切タグを付けないため、`check-toml` / ruff /
shellcheck はテンプレートを素通りする（この穴は sh 14 / py 8 / toml 4 の
ファイルに空いていた）。`scripts/lint_templates.py` は
`chezmoi execute-template` で描画し、**描画後の拡張子**で既存の linter へ
振り分ける。

分岐の両側を通すため、ファイルごとに描画コンテキストを変える。

| 軸 | 決め方 |
| --- | --- |
| OS | `home/.chezmoiscripts/` のディレクトリ規約（`100_linux/` なら linux だけ） |
| username | `.chezmoi.username` を参照するファイルだけ `applejxd` と別ユーザの 2 通り |

`--skip-secrets` を付けるので Bitwarden は呼ばれない。秘密を使うテンプレートは
chezmoi が `skip template` を返し、検査対象から外れる。

対象外:

- `.ps1.tmpl` — PSScriptAnalyzer（pwsh 本体）が要る
- `.zsh.tmpl` — shellcheck が zsh をサポートしない
- `home/.chezmoitemplates/**` — 単体では描画できない（`test_modifier_wrappers.py` が担保）
- `.chezmoi.toml.tmpl` — `execute-template --init` が要る

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
- **新規環境での簡単セットアップ**: `mise trust && mise install && uv sync && uv run pre-commit install`
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

一時的に全スクリプトを除外する場合：

```bash
chezmoi apply --exclude=scripts
```

恒久的に無効化する場合は、対象ファイルの `run_` 属性を外すか削除します。
`.tmpl` は実行属性ではないため、拡張子だけを外しても無効化されません。

## テンプレート変数

利用可能な chezmoi テンプレート変数：

- `{{ .chezmoi.os }}` - OS名 (`windows` / `linux` / `darwin`)
- `{{ .chezmoi.homeDir }}` - ホームディレクトリパス
- `{{ .chezmoi.sourceDir }}` - ソースディレクトリパス

sudoパスワードはテンプレート変数へ保存せず、`SUDO_PASSWORD` または
`get_sudo_password.sh.tmpl` を介して取得します。

## 新しいスクリプトの追加

1. `home/.chezmoiscripts/` にスクリプトを追加
2. 実行順序を考慮してファイル名の番号を設定
3. 必要に応じて `.tmpl` 拡張子を付けてテンプレート機能を使用
