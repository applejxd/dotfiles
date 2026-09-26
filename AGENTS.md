# Chezmoi Dotfiles

chezmoi で Windows / Ubuntu / WSL / macOS の dotfiles を管理する個人用リポジトリ。
`home/` 配下が chezmoi の source state で、それ以外は導入・生成・検証用。
構成やセットアップの詳細は [docs/index.md](docs/index.md) にある。

## 検証

変更したら該当するものを実行し、出力を根拠として示す。

| 対象 | コマンド |
| --- | --- |
| 全体（lint / secret scan） | `uv run pre-commit run --all-files` |
| agent 設定・hook | `uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q` |
| Windows 資産（静的） | `uv run --with pytest --no-project pytest test/test_windows_assets.py -q` |
| chezmoi の展開範囲 | `uv run --with pytest --no-project pytest test/test_chezmoi_templates.py -q` |
| シェルスクリプト | `git ls-files '*.sh' \| xargs mise exec shellcheck -- shellcheck` |
| テンプレート（描画して検査） | `mise exec -- python3 scripts/lint_templates.py` |
| docs の索引整合 | `mise exec -- python3 scripts/lint_docs.py` |
| OpenCode の実機試験 | `mise run opencode:probe -- '<prompt>'`（実 DB を汚さない） |
| 展開結果 | `chezmoi diff`（sandbox 内では不可。下記） |

`*.tmpl` は `identify` がタグを付けず `check-toml` / ruff / shellcheck が素通りする。
`lint_templates.py` が描画してから振り分けるので、テンプレートを編集したら実行する。

`chezmoi diff` は **sandbox 内では無意味**。`~/` が deny-by-default で不可視のため、
展開先が空に見えて全て「new file」になる。sandbox 外のシェルで実行する。

初回のみ `mise install && uv sync && uv run pre-commit install` が要る。

### Windows 実機での検証

次を触ったら **Windows の PowerShell で**検証する。WSL / Linux では実行できない
（`pywinpty` が依存解決の時点で失敗する）。

- `home/**/*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`
- `home/.chezmoiscripts/300_windows/`
- Windows 向けの hook 起動コマンド生成（`scripts/agents/generate.py`）

対話テストは `os.name != "nt"` で全件 skip する。WSL で「27 passed / 4 skipped」を
見ても **Windows 側は未検証**。実機で回せない場合はそう明記する。
手順と拾える範囲は [開発ガイド](docs/spec/development.md#windows-実機での検証)。

## このリポジトリ固有の約束

ここに無いことは一般的な流儀で判断してよい。

- 実ファイルを直接編集したら `chezmoi add` / `chezmoi re-add` で source state へ戻す
- `home/.chezmoiscripts/` は `run_once_` / `run_onchange_` / `run_after_` と 3 桁番号で
  実行順を管理する。既存の番号体系を崩さない
- シェルスクリプトは先頭に `set -eu` を置く
- `.tmpl` は OS 分岐・chezmoi データ・秘密情報が要るときだけ付ける。テンプレート内の
  変数確認は `{{- if and (hasKey . "var") .var }}` の形にする
- `.ps1` / `.ps1.tmpl` は UTF-8 BOM 付きで保存する。BOM が無いと PowerShell 5.1 が
  CP932 として読み、日本語コメントが次行のコードを無警告で飲み込む
- `SKILL.md` の frontmatter は `name` をディレクトリ名と一致させ、`:` や `#` を含む
  `description` は二重引用符で囲む（囲まないと CLI がスキルを黙って読み飛ばす）
- AI CLI の permission / hook / sandbox は `home/dot_config/agents/common.toml.tmpl` が
  単一ソース。生成先（`~/.claude/settings.json` 等）を直接編集しない
- **設定ファイル・スクリプトのコメントは「その行を編集するときに要る注記」だけにする。**
  仕組み・判断基準・既知の不具合・実測値・経緯は `docs/` が正本で、コメントからは
  参照先だけを示す（`# see docs/spec/structure.md#見出し`）。
  同じ説明をコメントと `docs/` の両方に書かない（更新時に必ず片方が古くなる）
  - 正本の対応: `common.toml.tmpl` → `docs/spec/agent-permissions.md`、
    `mise/config.toml.tmpl` と `.chezmoiscripts/` → `docs/spec/structure.md`
  - コメントに残してよい例: 非自明な 1 行の意図、公式ドキュメントの URL、
    消すと壊れる理由の 1 文
  - `docs/` へ移すもの: 背景・比較・代替案・実測値・失敗談・「なぜ他の方法を
    採らなかったか」
- 秘密情報はソースに書かず `SUDO_PASSWORD` / Bitwarden / sops + age を使う
- 対話入力が必須なスクリプトや長時間実行スクリプトは追加しない
- コミットメッセージは Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:`）
- 運用手順やコマンドを追加したら `README.md` と `docs/` の該当ファイル・`index.md` を
  更新する
- ユーザーへの説明とドキュメントは日本語で書く
