# Chezmoi Dotfiles

chezmoi を使った個人用 dotfiles 管理リポジトリ。
Windows / Ubuntu / WSL / macOS を対象に、設定ファイルと初期化スクリプトを管理する。

## Tech Stack

- Language: Shell, Python, Chezmoi templates
- Core Tools: chezmoi, mise, uv, pre-commit
- Security: Bitwarden, age

## Build & Test

- Setup: `mise install && uv sync && uv run pre-commit install`
- Validation: `uv run pre-commit run --all-files`
- Shell check: `mise exec shellcheck -- installer/**/*.sh`
- Secret scan: `mise exec gitleaks -- detect --source .`

## Project Structure

- `home/`: ホームディレクトリ配下へ展開するファイル
- `home/.chezmoiscripts/`: `chezmoi apply` 時に自動実行されるスクリプト
- `home/dot_config/`: `~/.config/` 配下の設定
- `config/`: アプリケーション設定ファイル
- `docs/`: 運用・構成・セキュリティ関連ドキュメント
- `scripts/`: 補助スクリプト
- `test/`: テスト関連ファイル

## Code Style

- 既存ファイルの流儀を優先し、不要な形式変更は避ける
- Shell スクリプトは先頭に `set -eu` を置く
- chezmoi スクリプト名は `run_once_XXX_name.sh(.tmpl)` / `run_onchange_XXX_name.sh(.tmpl)` に従う
- 実行順は番号で管理し、既存の順序体系を崩さない
- `.tmpl` は OS 分岐や秘密情報・テンプレート変数が必要な場合のみ使う
- テンプレート内の変数確認は `{{- if and (hasKey . "var") .var }}` の形を優先する

## Architecture

- dotfiles は chezmoi の管理下で扱い、実ファイルを直接編集した場合は `chezmoi add` / `chezmoi re-add` で反映する
- OS ごとの差分はテンプレートや OS 別スクリプトで吸収する
- パスワードや秘密情報はハードコードせず、`SUDO_PASSWORD` や Bitwarden/age を使う
- 対話入力が必須になるスクリプトや長時間実行スクリプトは避ける

## Workflow

- ブランチ運用はこのリポジトリの実運用に合わせる
- コミットメッセージは Conventional Commits（`feat:`, `fix:`, `docs:`, `chore:` など）を使う
- 変更前後で `chezmoi diff` や必要な検証コマンドを使って影響を確認する
- 新しいコマンドや運用手順を追加したら、関連する `README.md` や `docs/` を更新する

## Additional Rules

- 日本語で簡潔かつ丁寧に説明する
- 破壊的操作や外部環境の変更は、明示依頼がない限り提案に留める
- 秘密情報をログや出力に含めない
- 作業範囲は基本的にリポジトリ内に限定する
- サブディレクトリに別の `AGENTS.md` がある場合は、より近いものを優先する
