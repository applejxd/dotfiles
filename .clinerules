# Chezmoi Dotfiles Project Rules

## 必須ルール

### スクリプト命名・実行順序
- `run_once_XXX_name.sh(.tmpl)` - 一度だけ実行
- `run_onchange_XXX_name.sh(.tmpl)` - ファイル変更時実行
- 番号順序: 010_os_setup → 020_mise → 030_git → 800_vscode → 900_shell

### テンプレート使用
- OS判定・パスワード管理時のみ .tmpl 使用
- `hasKey` で変数存在確認: `{{- if and (hasKey . "var") .var }}`
- パス参照: `{{ .chezmoi.workingTree }}/installer/`

### エラーハンドリング
- `set -eu` を全スクリプトで使用
- ファイル存在確認後に実行
- 重要でないコマンドは `|| true`

### パスワード管理
- 環境変数 `SUDO_PASSWORD` を優先
- 空パスワードでも動作するよう実装
- ログに出力しない

## 開発環境

### ツールチェーン
- **mise**: ツールバージョン管理
- **uv**: Pythonパッケージ管理
- **pre-commit**: コード品質チェック

### セットアップ
```bash
mise install && uv sync && uv run pre-commit install
```

### コード品質チェック
```bash
uv run pre-commit run --all-files
mise exec shellcheck -- installer/**/*.sh
mise exec gitleaks -- detect --source .
```

## 禁止事項
- パスワードのハードコーディング
- 外部URLへの直接依存
- エラーハンドリングなしのスクリプト
- 実行順序を無視した番号付け
- 長時間実行スクリプト
- 対話的入力必須スクリプト

## クイックリファレンス

### 開発作業
```bash
# 新規環境セットアップ
mise install && uv sync && uv run pre-commit install

# ファイル編集
chezmoi edit <ファイル>
chezmoi diff
chezmoi apply

# 品質チェック
uv run pre-commit run --all-files
```

### デバッグ
- `chezmoi apply --verbose` - 詳細ログ
- `chezmoi status` - 状態確認
- `chezmoi diff` - 変更確認
- `chezmoi execute-template` - テンプレートテスト

### よくある問題
- テンプレート構文エラー → execute-template でテスト
- パスワード認証エラー → SUDO_PASSWORD 環境変数設定
- ファイル参照エラー → パス確認
- スクリプト実行順序問題 → 番号見直し

### テンプレート構文例
```go
{{- if eq .chezmoi.os "linux" }}    # Linux判定
{{- else if eq .chezmoi.os "darwin" }}  # macOS判定
{{- if and (hasKey . "sudo_password") .sudo_password }}  # 安全な変数参照
