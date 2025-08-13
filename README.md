# Dotfiles

chezmoi を使用した個人用 dotfiles 管理リポジトリです。Ubuntu と macOS に対応しています。

## 特徴

- **クロスプラットフォーム対応**: Ubuntu と macOS で動作
- **自動セットアップ**: OS固有の依存関係を自動インストール
- **テンプレート機能**: OS や環境に応じた設定ファイルの生成
- **段階的実行**: 依存関係を考慮したスクリプト実行順序
- **セキュアな設定管理**: Bitwarden連携とage暗号化による機密情報保護

## クイックスタート

### 1. chezmoi のインストール

#### Ubuntu

```bash
sudo snap install chezmoi --classic
```

#### macOS

```bash
brew install chezmoi
```

### 2. dotfiles の初期化と適用

```bash
# リポジトリから初期化（初回のみ）
chezmoi init applejxd

# 設定ファイルを適用
chezmoi apply
```

初回実行時にパスワードの入力を求められる場合があります（オプション）。

### 3. 手動での更新

```bash
# リポジトリから最新版を取得
chezmoi update

# または段階的に
chezmoi pull    # リポジトリから更新を取得
chezmoi diff    # 変更内容を確認
chezmoi apply   # 変更を適用
```

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

## セキュリティ機能

### Bitwarden連携

個人情報をBitwardenで安全に管理し、dotfilesを公開リポジトリで共有可能にします。

#### 設定方法

1. **Bitwarden CLIのインストール**
   ```bash
   # Ubuntu
   sudo snap install bw

   # macOS
   brew install bitwarden-cli
   ```

2. **Bitwardenアイテムの作成**
   ```bash
   bw login

   # 最新データを同期
   bw sync

   # Login itemを作成（名前: gitconfig）
   # Username: [GitHubユーザー名]
   # Custom Fields:
   #   - email: [GitHubメールアドレス]
   ```

3. **chezmoiでの使用**
   ```bash
   # Bitwardenにログイン
   bw login

   # データを同期（重要！）
   bw sync

   # セッション開始
   export BW_SESSION="$(bw unlock --raw)"

   # 設定ファイル適用
   chezmoi apply
   ```

#### 日常的な使用パターン
```bash
# 一括実行
bw sync && export BW_SESSION="$(bw unlock --raw)" && chezmoi apply
```

### age暗号化

機密性の高い設定ファイルをage暗号化で保護します。

#### 暗号化ファイルの復号化手順

1. **ageキーの準備**
   ```bash
   # 秘密鍵ファイルを安全な場所に配置
   # 例: ~/.config/age/key.txt
   ```

2. **暗号化ファイルの復号化**
   ```bash
   # 手動復号化
   age --decrypt -i ~/.config/age/key.txt home/encrypted_dot_claude.json.age > ~/.claude.json

   # またはchezmoiが自動的に復号化（ageキーが設定済みの場合）
   chezmoi apply
   ```

3. **新しいファイルの暗号化**
   ```bash
   # 公開鍵で暗号化
   age --encrypt -R ~/.config/age/public_key.txt input.json > encrypted_file.age

   # chezmoiに追加
   chezmoi add --encrypt encrypted_file
   ```

#### セキュリティ要件
- Bitwardenマスターパスワードの安全な管理
- ageキーペアの適切な保管（秘密鍵は暗号化ストレージに保存推奨）
- 定期的なパスワード・キーのローテーション

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

## トラブルシューティング

### よくある問題

#### 1. パスワード認証エラー

```bash
# 環境変数でパスワードを設定
export SUDO_PASSWORD="your_password"
chezmoi apply
```

#### 2. スクリプト実行権限エラー

```bash
# chezmoi の状態を確認
chezmoi status

# 強制的に再実行
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

#### 3. VS Code が見つからない

VS Code がインストールされていない場合、拡張機能のインストールはスキップされます。先に VS Code をインストールしてから再実行してください。

#### 4. ネットワークエラー

インストールスクリプトはローカルファイルを参照するため、ネットワーク接続は主に外部パッケージのダウンロード時のみ必要です。

### ログの確認

```bash
# 詳細ログで実行
chezmoi apply --verbose

# 実行状態の確認
chezmoi status
```

### セキュリティ関連のトラブルシューティング

#### 1. Bitwarden認証エラー

```bash
# セッション状態確認
bw status

# データ同期
bw sync

# 再ログイン
bw logout
bw login
bw sync
export BW_SESSION="$(bw unlock --raw)"
```

#### 2. age復号化エラー

```bash
# キーファイルの確認
ls -la ~/.config/age/

# 手動復号化テスト
age --decrypt -i ~/.config/age/key.txt [暗号化ファイル]
```

#### 3. chezmoi設定確認

```bash
# age設定確認
chezmoi data

# Bitwardenテンプレート関数テスト
chezmoi execute-template '{{ (bitwarden "item" "gitconfig").login.username }}'
```

## 開発者向け

### テンプレート変数

利用可能な chezmoi テンプレート変数：

- `{{ .chezmoi.os }}` - OS名 (linux/darwin)
- `{{ .chezmoi.homeDir }}` - ホームディレクトリパス
- `{{ .chezmoi.sourceDir }}` - ソースディレクトリパス
- `{{ .sudo_password }}` - sudo パスワード

### 新しいスクリプトの追加

1. `home/.chezmoiscripts/` にスクリプトを追加
2. 実行順序を考慮してファイル名の番号を設定
3. 必要に応じて `.tmpl` 拡張子を付けてテンプレート機能を使用

## ライセンス

MIT License
