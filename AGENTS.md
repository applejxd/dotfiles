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
| シェルスクリプト | `git ls-files '*.sh' \| xargs mise exec shellcheck -- shellcheck` |
| テンプレート（描画して検査） | `mise exec -- python3 scripts/lint_templates.py` |
| 展開結果 | `chezmoi diff`（sandbox 内では不可。下記） |

`*.tmpl` は `identify` がタグを付けないため、`check-toml` / ruff / shellcheck が
素通りする。`scripts/lint_templates.py` が描画してから振り分けるので、
テンプレートを編集したらこれを実行する（pre-commit にも入っている）。

初回のみ `mise install && uv sync && uv run pre-commit install` が要る。

`chezmoi diff` は **AI CLI の sandbox 内では意味のある結果を返さない**。
`~/` が deny-by-default で不可視のため、展開先が空に見えて全て「new file」
になる。sandbox 外のシェルで実行すること。

### Windows 実機での検証

次を触ったら、**Windows の PowerShell で**以下を実行する。WSL / Linux では実行できない。

- `home/**/*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`
- `home/.chezmoiscripts/300_windows/`
- Windows 向けの hook 起動コマンド生成（`scripts/agents/generate.py`）

```powershell
chezmoi apply
uv run --with pytest --with pywinpty --no-project pytest test\test_windows_assets.py test\test_powershell_interactive.py -q
```

- 対話テストは**配備済みの実プロファイル**を ConPTY で読むため、先に `chezmoi apply` が要る
- `pywinpty` は Windows 専用（Rust ビルド）。WSL / Linux では依存解決の時点で失敗する
- 対話テストは `os.name != "nt"` で全件 skip する。WSL で「27 passed / 4 skipped」を
  見ても **Windows 側は未検証**。実機で回せない場合はそう明記する
- 何が拾えて何が拾えないかは
  [開発ガイド](docs/spec/development.md#windows-実機での検証)

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
- `common.toml.tmpl` のコメントは「その行を編集するときに要る注記」だけにする。
  仕組み・判断基準・既知の不具合・実測値は `docs/spec/agent-permissions.md` が正本
- 秘密情報はソースに書かず `SUDO_PASSWORD` / Bitwarden / sops + age を使う
- 対話入力が必須なスクリプトや長時間実行スクリプトは追加しない
- コミットメッセージは Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:`）
- 運用手順やコマンドを追加したら `README.md` と `docs/` の該当ファイル・`index.md` を
  更新する
- ユーザーへの説明とドキュメントは日本語で書く
