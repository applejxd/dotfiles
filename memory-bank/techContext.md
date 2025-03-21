# 技術コンテキスト

## 使用技術

### シェルスクリプト

- Bash - 主要なスクリプト言語として使用
- Zsh - 対話型シェルとして設定
- Fish - 一部のインストールスクリプトで使用

### パッケージマネージャ

- apt/apt-get - Ubuntu/Debian系システム
- Homebrew - macOS向けパッケージ管理
- mas - macOSアプリストア連携

### 設定管理

- シンボリックリンク - 設定ファイルの配置
- Git - バージョン管理
- Homesick/Homeshick - dotfiles管理の補助ツール（オプション）

## 開発環境

### エディタ/IDE

- Vim/Neovim - 軽量エディタ
- Emacs/Spacemacs - 拡張可能なエディタ
- VSCode - モダンなコードエディタ

### ターミナル

- iTerm2 (macOS)
- tmux - ターミナルマルチプレクサ
- Hyper - JavaScript/Electron ベースのターミナル

### 開発ツール

- GDB - デバッガ
- Git - バージョン管理
- Docker - コンテナ化
- LaTeX - 文書作成
- CUDA - GPU計算（特定環境向け）

## 技術的制約

### クロスプラットフォーム互換性

- シェルスクリプトの互換性（Bash vs Zsh vs Fish）
- macOSとLinuxの違いへの対応
- WSL固有の制約への対応

### 依存関係

- 外部ツールやパッケージの可用性
- バージョンの違いによる互換性問題
- インストール順序の依存関係

### セキュリティ

- SSH設定の適切な管理
- 機密情報の分離（personal.shなど）
- 権限設定の適切な管理

## デプロイメント方法

### 新規インストール

```bash
git clone https://github.com/username/dotfiles.git
cd dotfiles
./install.sh  # 全体インストール
# または
./deploy.sh   # 設定ファイルのみデプロイ
```

### 更新

```bash
cd dotfiles
git pull
./deploy.sh   # 設定ファイルの再デプロイ
```

### カスタマイズ

```bash
# プラットフォーム固有のインストール
./installer/ubuntu/ubuntu.sh
# または
./installer/osx/osx.sh
```

## 依存関係

- Git - リポジトリクローンと管理
- curl/wget - 一部のインストールスクリプトでの使用
- sudo権限 - システムレベルのインストール
- 各種言語ランタイム（必要に応じて）
