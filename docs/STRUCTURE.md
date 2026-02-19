# プロジェクト構造

## ディレクトリ構造

```txt
.
├── .chezmoi.toml.tmpl          # chezmoi 設定ファイル（パスワード管理）
├── .chezmoiroot                # ルートディレクトリ指定
├── config/                     # アプリケーション設定ファイル
├── home/                       # ホームディレクトリ配下のファイル
│   ├── .chezmoiscripts/        # 自動実行スクリプト
│   └── dot_config/             # ~/.config/ 配下の設定ファイル
├── installer/                  # OS固有のインストールスクリプト
│   ├── osx/                    # macOS用スクリプト
│   └── ubuntu/                 # Ubuntu用スクリプト
└── init.sh                     # 従来の初期化スクリプト（参考用）
```

## 自動実行スクリプト

chezmoi apply 実行時に以下の順序でスクリプトが自動実行されます：

1. **`run_once_010_os_setup.sh.tmpl`** - OS固有の基本セットアップ
   - Ubuntu: 基本パッケージ、mise、Python/Ruby環境、VS Code等
   - macOS: Homebrew、GUI アプリ、開発環境等

2. **`run_once_020_mise.sh`** - mise（開発ツール管理）のインストール

3. **`run_onchange_030_git_globals.sh`** - Git グローバル設定のアップデート

4. **`run_once_800_vscode_extensions.sh.tmpl`** - VS Code 拡張機能のインストール
   - Iceberg テーマ
   - GitLens
   - Git Graph
   - Shell Format

5. **`run_once_900_shell.sh`** - デフォルトシェルを zsh に変更

6. **`run_onchange_after_fetch_spacemacs.tmpl`** - Spacemacs設定の取得と更新

## 対応環境

### Ubuntu

- Ubuntu 18.04 LTS 以降
- 必要な権限: sudo

### macOS

- macOS 10.15 (Catalina) 以降
- Homebrew が自動インストールされます
