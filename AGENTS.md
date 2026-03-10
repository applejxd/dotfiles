# Chezmoi Dotfiles

chezmoi を使った個人用 dotfiles 管理リポジトリ。Windows / Ubuntu / WSL / macOS に対応。

## Tech Stack

- **dotfiles 管理**: chezmoi
- **ツールバージョン管理**: mise
- **Python パッケージ管理**: uv
- **コード品質**: pre-commit（gitleaks, yamllint, shellcheck）
- **秘密管理**: Bitwarden + age 暗号化

## セットアップ

```bash
mise install && uv sync && uv run pre-commit install
```

## コード品質チェック

```bash
uv run pre-commit run --all-files          # 全チェック
mise exec shellcheck -- installer/**/*.sh  # Shell 構文チェック
mise exec gitleaks -- detect --source .    # シークレット検出
```

## プロジェクト構造

```
home/
  .chezmoiscripts/   # 自動実行スクリプト（chezmoi apply 時）
  dot_config/        # ~/.config/ 配下の設定ファイル
installer/
  osx/               # macOS 用インストールスクリプト
  ubuntu/            # Ubuntu 用インストールスクリプト
config/              # アプリケーション設定ファイル
docs/                # ドキュメント
```

## スクリプト命名規則

| プレフィックス | 実行タイミング |
|---|---|
| `run_once_XXX_name.sh(.tmpl)` | 一度だけ実行 |
| `run_onchange_XXX_name.sh(.tmpl)` | ファイル変更時に実行 |

番号順序: `010_os_setup` → `020_mise` → `030_git` → `800_vscode` → `900_shell`

## テンプレート規則

- `.tmpl` は OS 判定・パスワード管理が必要な場合のみ使用
- 変数存在確認: `{{- if and (hasKey . "var") .var }}`
- パス参照: `{{ .chezmoi.workingTree }}/installer/`

## エラーハンドリング

- 全スクリプトの先頭に `set -eu`
- ファイル存在確認後に実行
- 重要でないコマンドは `|| true` でエラーを抑制

## パスワード管理

- 環境変数 `SUDO_PASSWORD` を優先使用
- 空パスワードでも動作するよう実装
- パスワードはログ・出力に含めない

## Git ワークフロー

- ブランチ: `main` に直接コミット
- コミット規約: Conventional Commits（`feat:`, `fix:`, `docs:`, `chore:` 等）

## 禁止事項

- パスワード・シークレットのハードコーディング
- エラーハンドリングなしのスクリプト
- 対話的入力が必須のスクリプト
- 長時間実行するスクリプト
- 実行順序を無視した番号付け

## デバッグ

```bash
chezmoi apply --verbose          # 詳細ログ付きで適用
chezmoi status                   # 状態確認
chezmoi diff                     # 変更確認
chezmoi execute-template <file>  # テンプレートのテスト
```
