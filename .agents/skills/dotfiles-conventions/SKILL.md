---
name: dotfiles-conventions
description: "chezmoi の dotfiles リポジトリのファイルを編集する・検証するときの規則。*.tmpl・.chezmoiscripts・*.ps1・SKILL.md・docs・README・試験の登録・補助スクリプトの示し方・コミットメッセージを扱う。「このリポジトリのファイルを直して」「スクリプトやテンプレートを足して」「検証して」で使う。他のリポジトリには使わない。"
---

# dotfiles リポジトリの編集・検証の規則

リポジトリ直下 `AGENTS.md` の常時の規則（公開・直接コミット禁止・日本語・BOM など）に加えて、編集・検証の場面で要る規則。

## 検証

変更に応じて該当するものを実行する（選択規則は [検証の方針](../../../docs/spec/development.md#検証の方針と選択実行)）。

| 対象 | コマンド |
| --- | --- |
| agent 設定・hook | `uv run --with pytest --with pytest-xdist --with pyyaml --no-project pytest test/agents/ -q -n 4 --dist worksteal` |
| Windows 資産（静的） | `uv run --with pytest --no-project pytest test/test_windows_assets.py -q` |
| chezmoi の展開範囲 | `uv run --with pytest --no-project pytest test/test_chezmoi_templates.py -q` |
| シェルスクリプト | `git ls-files '*.sh' \| xargs mise exec shellcheck -- shellcheck` |
| テンプレート（描画して検査） | `mise exec -- python3 scripts/lint_templates.py` |
| docs の索引整合 | `mise exec -- python3 home/dot_claude/skills/sdd-docs/scripts/lint_docs.py` |
| OpenCode の実機試験 | `mise run opencode:probe -- '<prompt>'`（実 DB を汚さない） |
| 展開結果 | `chezmoi diff`（sandbox 内では不可） |

初回のみ `mise install && uv sync && uv run pre-commit install`。install 済みでも、pre-push を入れるためにもう一度 `uv run pre-commit install` を実行する。

### 検証結果の限界（判断の不変条件）

- `*.tmpl` は pre-commit の linter が素通りする。描画後の検査（`lint_templates.py`）が別に要る。「pre-commit が通った」だけでは `*.tmpl` を検査したことにならない。テンプレートを編集したら必ず `lint_templates.py` も実行する（[理由と対象](../../../docs/spec/development.md#テンプレートの検査)）。
- `pre-commit run --all-files` は git 未登録の新規ファイルを検査しない。新規ファイルは `uv run pre-commit run --files <パス>` でも回す。ただし秘密検出（gitleaks）は `--staged` なので、新規ファイルは `git add` の後でないと見ない。「pre-commit が通った」は新規ファイルの秘密検出済みを意味しない。
- sandbox 内の `chezmoi diff` は `~/` が不可視のため証拠にならない（全部が「new file」に見える）。sandbox 外のシェルで実行する。worker は実行せず、報告の「次の候補」に書く。
- worker は担当の試験ファイルを優先し、`test/agents/` 全体は必要なときだけ回す。重い検査を同時に回さない（全件 `mise run verify:all` は親が 1 回だけ。並列度は `VERIFY_JOBS`）。

### Windows 実機での検証

`*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`、`home/.chezmoiscripts/300_windows/`、`scripts/agents/hooks.py`（Windows 向けの hook 起動コマンド生成）を触ったら **Windows の PowerShell で**検証する。WSL では対話テストが skip されるだけなので、通っても **Windows 側は未検証**。実機で回せないときはそう明記する（[手順と拾える範囲](../../../docs/spec/development.md#windows-実機での検証)）。

## 公開情報に無いことをするとき

実装の前に「本当に必要か」「この事例に固有の事情か」を検討する。

1. 主流が何をしているかを、出典つきで確かめる（見つからなければ「未確認」と書く）。
2. 違う設計にするなら、その理由が固有の事情（環境・要件）か、一般に必要なのに主流が見落としているものかを、根拠つきで示す。
3. 固有で本当に要るものだけを、最小の例外として理由とともに記録する。既定は主流に合わせる（違う設計は選択肢にとどめ、新しい権限は既定で無効にする）。自作は、標準品・既製品で足りないと確かめた後の最後の手段にする。

## chezmoi の作法

- 実ファイルを直接編集したら `chezmoi add` / `chezmoi re-add` で source state へ戻す。
- `home/.chezmoiscripts/` は `run_once_` / `run_onchange_` / `run_after_` と 3 桁番号で実行順を管理する。既存の番号体系を崩さない。
- シェルスクリプトは先頭に `set -eu` を置く。
- `.tmpl` は OS 分岐・chezmoi データ・秘密情報が要るときだけ付ける。変数確認は `{{- if and (hasKey . "var") .var }}` の形にする。
- `.ps1` / `.ps1.tmpl` は UTF-8 BOM 付きで保存する（BOM が無いと PowerShell 5.1 が CP932 として読み、日本語コメントが次行のコードを無警告で飲み込む）。
- `SKILL.md` の frontmatter は `name` をディレクトリ名と一致させ、`:` や `#` を含む `description` は二重引用符で囲む（囲まないと CLI がスキルを黙って読み飛ばす）。
- AI CLI の permission / hook / sandbox は `home/dot_config/agents/common.toml.tmpl` が単一ソース。生成先を直接編集しない。
- **設定ファイル・スクリプトのコメントは「その行を編集するときに要る注記」だけにする。** 仕組み・判断基準・既知の不具合・実測値・経緯は `docs/` が正本で、コメントからは参照先だけを示す（`# see docs/spec/structure.md#見出し`）。同じ説明をコメントと `docs/` の両方に書かない。正本の対応は [コメントの書き分け](../../../docs/spec/agent-config-generation.md#コメントの書き分け)。
- 秘密情報はソースに書かず Bitwarden / sops + age を使う。sudo のパスワードは保存せず、スクリプトが実行時に端末で尋ねる（[sudo パスワード](../../../docs/spec/development.md#sudo-パスワード)）。
- 対話入力が必須なスクリプトや長時間実行スクリプトは追加しない。
- **`chezmoi init` を前提にした設計にしない。** 普段の運用は `chezmoi update`（`git pull` + `apply`）で `init` を呼ばない。マシン判定などは `.chezmoitemplates/` の共有テンプレートへ置き、`apply` のたびに評価させる。`chezmoi.toml` の `[data]` は `init` 時にしか更新されない（[CHG-0008](../../../docs/change/closed/0008-raspi-branching.md)）。

## docs・README・試験

- 運用手順やコマンドを追加したら `docs/` の該当ファイルと `index.md` を更新する。`README.md` は導入・更新など入口の手順が変わるときだけ更新する。
- **`README.md` は「最短で動かす」ためだけに保つ。** 各項目は数行 + `docs/` へのリンクに留め、背景・一覧表・失敗談・仕組みは `docs/` へ。同じ手順を README と `docs/` の両方に書かない。
- ドキュメントもコメントも日本語。英語のままにするのは、接頭辞（`feat:` など）・識別子・コマンド・ログやエラーの文言・外部の引用だけ。既存の英語のコメントはその箇所を触るときに日本語へ直す。
- 新しい試験ファイルは `scripts/verify.py` の `_PI_TESTS`（または該当の `Rule`）に、取り込み前に feature の中で登録する。漏れは `test/test_verify.py`（2 秒）で先に見つかるので、全件検査の前に回す。worker は依頼文が許したときだけ登録し、許されなければ報告に「登録が必要: <パス>」と書く。
- 公開リポジトリ: 組織・勤務先の環境の具体は書かない。制約が設計に影響するときは「制約のある環境（認証つきプロキシが必須、など）」のような条件つきの一般論で書き、事実として断定しない。迷ったら書かず、リポジトリ外の非公開メモ（`.tmp/` など）に置く。

## 利用者に実行してもらう補助スクリプト

- **`pk <話題> [引数]` の形で示す。** 入口は `.tmp/keep/<話題>/run.sh`（無ければ唯一の `*.sh`）。`sh <長い絶対パス>` は使わない（`pk` は `chezmoi apply` で配備。未配備の機械では絶対パスでよい）。入口の先頭コメントの 1 行目は `pk` の一覧に出る説明として書く。話題名は短く覚えやすく（[詳細](../../../docs/spec/development.md#補助スクリプトの短い入口pk)）。

## コミットメッセージ

- Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:`）。**本文は件名 + 1〜3 行の要約だけにし、箇条書きにしない**（詳細は案件・docs に書く。承認画面で長い本文が読みにくいため）。件名・本文は日本語。

## dotfiles の開発とサンドボックス

- **このリポジトリは、サンドボックスの中（`pis` の既定）で開発しない。`pis --no-sandbox` で行う**（[ADR-0025](../../../docs/adr/0025-dotfiles-dev-without-os-sandbox.md)）。内側では隠した秘密の追跡ファイルが `/dev/null` に見えて `git status` が dirty になり、統合が `stash failed` で失敗する。内側の合図（`git status` が dirty に見える・読めないファイルがある）が出たら、作業を止めて、サンドボックスなしの起動へ切り替えるよう利用者に伝える。

## AGENTS.md 自体の編集

- `AGENTS.md` は印なしの平らな文書（45 行以内）。子向けの抜粋の仕組み（`<!-- child:... -->` の印・`child-context.ts`）は凍結（[ADR-0030](../../../docs/adr/0030-freeze-agent-stack-return-to-stock-pi.md)）で、新しく印を足さない。常時の規則を増やさず、編集の場面でだけ要るものはこのスキルへ書く。
