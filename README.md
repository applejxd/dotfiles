# Dotfiles

chezmoi を使用した個人用 dotfiles 管理リポジトリ。Windows/Ubuntu/WSL/macOS に対応。

## 特徴

- **クロスプラットフォーム対応**: Windows/Ubuntu/WSL/macOS で動作
- **自動セットアップ**: OS固有の依存関係を自動インストール
- **セキュアな設定管理**: Bitwarden 連携と sops (age) による機密情報保護

## クイックスタート

### インストール

```bash
# Ubuntu
sudo snap install chezmoi --classic

# macOS
brew install chezmoi
```

> Bitwarden CLI (`bw`) は **事前インストール不要**。`chezmoi apply` 中に mise 経由 (`npm:@bitwarden/cli`) で自動投入される。
> bw が必要なテンプレート展開 (sops の age 鍵取得・gitconfig の user セクション等) は、bw 取得後に `chezmoi init` / `chezmoi apply` を再実行することでフェーズ 2 として反映される。

### 初期化と適用（2 フェーズ bootstrap）

```bash
# フェーズ 1: bw 不在のまま初期化・適用
chezmoi init applejxd     # bw 不在ガードにより bitwarden 関連はスキップされる
chezmoi apply             # mise 本体 + npm:@bitwarden/cli を含む全ツールがここで入る

# フェーズ 2: bw が使えるようになったので Bitwarden 連携を有効化
bw login
export BW_SESSION="$(bw unlock --raw)"
chezmoi init applejxd     # .chezmoi.toml を bw 有り状態で再生成 (bitwarden.unlock="auto")
chezmoi apply             # sops の age 鍵取得・gitconfig user セクション展開などが反映される
```

依存関係スクリプトをスキップしたい場合は `chezmoi apply --exclude=scripts`。

### Herdr と agent integration

Windows native、Linux、WSL では、`chezmoi apply` 時に公式インストーラーから Herdr を
ユーザースコープへ導入します。Windows のバイナリは
`%LOCALAPPDATA%\Programs\Herdr\bin`、Linux / WSL では `~/.local/bin` に配置されます。
macOS は現在の自動導入対象外です。

agent integration は設定ファイルの配備後に毎回冪等に再適用されます。

| chezmoi username | integration | 前提となる agent CLI |
| --- | --- | --- |
| `applejxd` | GitHub Copilot CLI | Windows は Winget、Linux / WSL は公式 installer で導入 |
| その他 | Claude Code | Windows / Linux / WSL は公式 installer で導入 |

Herdr は `~/.copilot/settings.json` または `~/.claude/settings.json` の既存設定を保持し、
Herdr 管理の hook entry だけを追加・更新します。現在の状態は次で確認できます。

```bash
herdr integration status
```

初回適用後に `herdr` が見つからない場合は、新しいターミナルを開いてください。
以後の Herdr 本体の更新は `herdr update` で行います。

Windows ARM64 では、Herdr 公式の x86_64 ビルドが Windows のエミュレーション上で動作します。

### 更新

```bash
# 最新版に更新
chezmoi update

# または段階的に
chezmoi pull && chezmoi diff && chezmoi apply
```

`chezmoi update` 後に zinit 管理プラグイン (zeno.zsh など) も最新化したい場合は次のタスクを実行する。
chezmoi 自体はプラグインキャッシュに干渉しないため、手元の `~/.zinit/plugins/...` を refresh するための明示コマンド。zeno の deno モジュールキャッシュ再生成と zinit completions の宙ぶらりんリンク掃除も同時に行う。

```bash
mise run dotfiles-update
```

## 基本的な使用方法

### 設定ファイルの編集

```bash
# chezmoi経由での編集 (推奨)
chezmoi edit ~/.bashrc

# 実ファイルを直接編集した場合の反映
chezmoi add ~/.bashrc

# 管理対象ファイルのうち、実ファイル側で変更があったものをすべて更新 (re-add)
chezmoi re-add

# 変更の確認
chezmoi diff

# 適用
chezmoi apply
```

## ドキュメント

詳細な情報は以下のドキュメントを参照してください：

- [プロジェクト構造](docs/STRUCTURE.md) - ディレクトリ構造と自動実行スクリプト
- [セキュリティ機能](docs/SECURITY.md) - Bitwarden と sops (age) の設定
- [トラブルシューティング](docs/TROUBLESHOOTING.md) - よくある問題と解決方法
- [開発者向け](docs/DEVELOPMENT.md) - 開発環境のセットアップとカスタマイズ
- [Bitwarden + sops セットアップ](docs/SETUP_SOPS_AGE.md) - 詳細なセットアップ手順

## ライセンス

MIT License
