# Dotfiles

chezmoi を使用した個人用 dotfiles 管理リポジトリ。Windows/Ubuntu/WSL/macOS に対応。

## 特徴

- **クロスプラットフォーム対応**: Windows/Ubuntu/WSL/macOS で動作
- **自動セットアップ**: OS固有の依存関係を自動インストール
- **セキュアな設定管理**: Bitwarden連携とage暗号化による機密情報保護

## クイックスタート

### インストール

```bash
# Ubuntu
sudo snap install chezmoi --classic

# macOS
brew install chezmoi
```

Bitwarden CLI も必要なら

```bash
sudo smap install bw --classic
bw login
```


### 初期化と適用

```bash
# リポジトリから初期化
chezmoi init applejxd

# 設定ファイルを適用 (依存関係インストールあり)
chezmoi apply
# 設定ファイルを適用（依存関係インストールなし）
chezmoi apply --exclude=scripts
```

### 更新

```bash
# 最新版に更新
chezmoi update

# または段階的に
chezmoi pull && chezmoi diff && chezmoi apply
```

## 基本的な使用方法

### 設定ファイルの編集

```bash
# 編集
chezmoi edit ~/.bashrc

# 確認
chezmoi diff

# 適用
chezmoi apply
```

## ドキュメント

詳細な情報は以下のドキュメントを参照してください：

- [プロジェクト構造](docs/STRUCTURE.md) - ディレクトリ構造と自動実行スクリプト
- [セキュリティ機能](docs/SECURITY.md) - Bitwarden と age 暗号化の設定
- [トラブルシューティング](docs/TROUBLESHOOTING.md) - よくある問題と解決方法
- [開発者向け](docs/DEVELOPMENT.md) - 開発環境のセットアップとカスタマイズ
- [Bitwarden + Age セットアップ](docs/SETUP_BITWARDEN_AGE.md) - 詳細なセットアップ手順

## ライセンス

MIT License
