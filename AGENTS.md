# Chezmoi Dotfiles

chezmoi で Windows / Ubuntu / WSL / macOS の dotfiles を管理する個人用リポジトリ。
`home/` 配下が source state で、それ以外は導入・生成・検証用。詳細は [docs/index.md](docs/index.md)。

## 検証

- `mise run verify`（日常。変更に応じた選択実行）
- `mise run verify:all`（コミット前に 1 回。全件。`main` への統合前にも回す）
- `uv run pre-commit run --all-files`（lint / secret scan）

対象別のコマンドと選択規則は [docs/spec/development.md](docs/spec/development.md)。`*.tmpl` は pre-commit が素通りするので `lint_templates.py` も要る。

## 常に守ること

- 公開リポジトリ。私物の環境以外の具体（勤務先・組織の情報）と秘密は、コード・docs・コミットのどこにも書かない。
- `develop` / `main` に直接コミットしない。実装は feature の worktree（`.tmp/worktrees/<名前>/`）で行う。
- 保護ブランチへの統合（`git flow feature finish`・`git flow integrate`）は、AI は原則実行しない。**利用者が自分から明示的に指示したときだけ**実行する。AI が「統合してよいですか」と聞いて得た返事は数えない（許可を求める質問はせず、「準備ができた」という報告だけにする）。`git push` は方針で deny（利用者が行う）。
- 生成先（`~/.pi/agent/mcp.json` 等）を直接編集しない。MCP の宣言は `home/.chezmoitemplates/pi-mcp-servers.toml` が単一ソース。
- docs・コメント・コミットメッセージは日本語で書く。
- `.ps1` / `.ps1.tmpl` は UTF-8 BOM 付きで保存する。
- コミットメッセージは Conventional Commits。本文は件名 + 1〜3 行の要約だけ。
- 仕組みや機能を足す前に、既存の拡張・標準機能・設定で足りるかを先に探して評価する。自作は最後の手段で、理由・維持費・撤去条件を記録し、利用者の承認を得る（[ADR-0031](docs/adr/0031-evaluate-existing-extensions-first.md)）。

## スキル（編集・運用の場面で読む）

- `dotfiles-conventions`: このリポジトリのファイルを編集・検証するときの規則（検証の限界・Windows 実機・chezmoi の作法・docs・試験の登録・`pk`）。
- `chezmoi-usage`: chezmoi 本体の知識と落とし穴（属性・特殊ファイル・scripts の実行条件と適用順序・テンプレート・`update` / `diff` の限界・`inconsistent state`）。
- `feature-orchestration`: feature 起票・worker への委譲・並列実装・取り込み・統合。
- `pi-extension-dev`: pi の機能を足す・直すときの進め方（既存の拡張・設定の評価が先。自作は最後の手段）。
