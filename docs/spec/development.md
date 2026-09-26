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

##### gitleaks はプレビルドを使う

pre-commit の gitleaks フックは、公式リポジトリ（`language: golang`）ではなく
`mise exec -- gitleaks` を呼ぶローカルフックにしています。版は `mise.toml` の
`gitleaks = "8.28.0"` が正本です。

公式フックは、初回にフック環境を作るとき Go のツールチェーンを落として
gitleaks を**ソースからビルド**します。Raspberry Pi 4（RAM 3.7GB、swap 0）では
このビルドでメモリが尽き、SSH も応答しなくなって電源の抜き差しが要りました
（2026-09-26）。mise なら GitHub Releases のバイナリを落とすだけで済みます。
フックの id は `gitleaks` のままなので、`SKIP=gitleaks` はそのまま使えます。

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

##### Windows 実機での検証

次を変更したら **Windows の PowerShell で**検証する。WSL / Linux では実行できない。

- `home/**/*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`
- `home/.chezmoiscripts/300_windows/`
- Windows 向けの hook 起動コマンド生成（`scripts/agents/generate.py`）

```powershell
chezmoi apply
uv run --with pytest --with pywinpty --no-project pytest test\test_windows_assets.py test\test_powershell_interactive.py -q
```

`test_powershell_interactive.py` は**配備済みの実プロファイル**を PowerShell 7 と
Windows PowerShell 5.1 の ConPTY セッションで読み込み、プロンプト到達後の状態を
検査する。だから先に `chezmoi apply` が要る。`pywinpty` はその ConPTY を Python から
扱うための依存で、Rust ビルドの Windows 専用パッケージ。WSL / Linux では
**依存解決の時点でビルドに失敗する**。

| 環境 | 実行できる範囲 |
| --- | --- |
| Windows (pwsh) | 静的 + 対話 |
| WSL / Linux | 静的のみ（`uv run --with pytest --no-project pytest test/test_windows_assets.py -q`） |

対話テストは `os.name != "nt"` で全件 skip するため、WSL で
「27 passed / 4 skipped」を見ても Windows 側は未検証である。静的テストが拾えるのは
UTF-8 BOM、winget の記法、プロファイルの字面までで、次は拾えない。

- 起動エラーと OnIdle ジョブのエラー（どちらもコンソールに出ない）
- 対話時だけ実行するブロック（PSReadLine / oh-my-posh / PSFzf / ZLocation、
  `pbcopy` などの補助関数）
- oh-my-posh の init をキャッシュすると pure テーマが既定の powerline へ戻る問題、
  `mise activate` の PATH 重複、`Ctrl+d` の既定バインドが端末を閉じる問題

実機で回せない場合は「Windows 未検証」と明記する。

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
