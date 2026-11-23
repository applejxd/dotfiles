---
name: dotfiles-conventions
description: "chezmoi の dotfiles リポジトリのファイルを編集する・検証するときの規則。*.tmpl・.chezmoiscripts・*.ps1・SKILL.md・docs・README・試験の登録・補助スクリプトの示し方・コミットメッセージを扱う。「このリポジトリのファイルを直して」「スクリプトやテンプレートを足して」「検証して」で使う。pi の権限ポリシー（pi-permission-policy.json）の allow・deny・ask の判断・変更・検証にも使う（「このパスを許可してよい？」「権限ポリシーを見直して」）。他のリポジトリには使わない。"
---

# dotfiles リポジトリの編集・検証の規則

リポジトリ直下 `AGENTS.md` の常時の規則（公開・直接コミット禁止・日本語・BOM など）に加えて、編集・検証の場面で要る規則。

## 検証

変更に応じて該当するものを実行する（選択規則は [検証の方針](../../../docs/spec/development.md#検証の方針と選択実行)）。

| 対象 | コマンド |
| --- | --- |
| pi の設定・agent 関連 | `uv run --with pytest --with pytest-xdist --with pyyaml --no-project pytest test/agents/ -q -n 4 --dist worksteal` |
| Windows 資産（静的） | `uv run --with pytest --no-project pytest test/test_windows_assets.py -q` |
| chezmoi の展開範囲 | `uv run --with pytest --no-project pytest test/test_chezmoi_templates.py -q` |
| シェルスクリプト | `git ls-files '*.sh' \| xargs mise exec shellcheck -- shellcheck` |
| テンプレート（描画して検査） | `mise exec -- python3 scripts/lint_templates.py` |
| docs の索引整合 | `mise exec -- python3 home/dot_agents/skills/sdd-docs/scripts/lint_docs.py` |
| 展開結果 | `chezmoi diff`（sandbox 内では不可） |

初回のみ `mise install && uv sync && uv run pre-commit install`。install 済みでも、pre-push を入れるためにもう一度 `uv run pre-commit install` を実行する。

### 検証結果の限界（判断の不変条件）

- `*.tmpl` は pre-commit の linter が素通りする。描画後の検査（`lint_templates.py`）が別に要る。「pre-commit が通った」だけでは `*.tmpl` を検査したことにならない。テンプレートを編集したら必ず `lint_templates.py` も実行する（[理由と対象](../../../docs/spec/development.md#テンプレートの検査)）。
- `pre-commit run --all-files` は git 未登録の新規ファイルを検査しない。新規ファイルは `uv run pre-commit run --files <パス>` でも回す。ただし秘密検出（gitleaks）は `--staged` なので、新規ファイルは `git add` の後でないと見ない。「pre-commit が通った」は新規ファイルの秘密検出済みを意味しない。
- sandbox 内の `chezmoi diff` は `~/` が不可視のため証拠にならない（全部が「new file」に見える）。sandbox 外のシェルで実行する。worker は実行せず、報告の「次の候補」に書く。
- worker は担当の試験ファイルを優先し、`test/agents/` 全体は必要なときだけ回す。重い検査を同時に回さない（全件 `mise run verify:all` は親が 1 回だけ。並列度は `VERIFY_JOBS`）。

### Windows 実機での検証

`*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`、`home/.chezmoiscripts/300_windows/` を触ったら Windows の PowerShell で検証する。WSL では Windows 側は未検証になる。詳細は `references/windows-verification.md` を読む。

## feature の worktree で作業するとき（本体のパスへ出ない）

一般の指針（worktree の中だけで完結させる・`git rev-parse --show-toplevel`・`git show <基本の枝>:<パス>`）は、全リポジトリへ効くグローバルの指示（`agent-instructions-stock.md` の「確認（ask）」）にある。このリポジトリでの具体は次のとおり。

- cwd が `.tmp/worktrees/<名前>/` のとき、本体（`~/.local/share/chezmoi`）と他の worktree は「作業ツリーの外」で、`cd`・`ls`・`cat` に確認が出る（権限の規則に本体を許可する項目は無い。判定エンジンで確認）。基本の枝は `develop`: `git show develop:<パス>`・`git diff develop...HEAD`・`git log develop`。他の feature の内容は `git show feature/<名前>:<パス>`。
- `cd` は worktree の絶対パスだけにする（`cd ~/…`・`cd $VAR` は使わない。[上流の不具合](../../../docs/spec/temporary-workarounds.md#pi-permission-system-の-cd-先の誤判定)）。
- **`.tmp/` は worktree と一緒に消える**: 再利用するものはコミット、残したい資料は `.tmp/keep/`、使い捨てだけ `.tmp/<話題>/`。置き場所を `TMPDIR` で本体へ向けず、`/tmp` に一本化もしない（子は作業ツリーの外へ書けず、囲いの中の `/tmp` は空の tmpfs）。消す前の確認は [feature-orchestration](../feature-orchestration/SKILL.md) の工程 9。
- 本体へ触るのは、利用者が指示した統合（`git flow feature finish`・`git flow integrate`）と `chezmoi apply` だけ（どちらも確認が出る前提）。この PC の chezmoi のソースは本体（`develop`）なので、worktree の変更は、統合するまで実機へ反映されない。

## 公開情報に無いことをするとき

実装の前に「本当に必要か」「この事例に固有の事情か」を検討する。

1. 主流が何をしているかを、出典つきで確かめる（見つからなければ「未確認」と書く）。
2. 違う設計にするなら、その理由が固有の事情（環境・要件）か、一般に必要なのに主流が見落としているものかを、根拠つきで示す。
3. 固有で本当に要るものだけを、最小の例外として理由とともに記録する。既定は主流に合わせる（違う設計は選択肢にとどめ、新しい権限は既定で無効にする）。自作は、標準品・既製品で足りないと確かめた後の最後の手段にする。

## chezmoi の作法

chezmoi 本体の挙動・落とし穴（属性・特殊ファイル・scripts の実行条件・テンプレート・`diff` の限界）は [chezmoi-usage](../chezmoi-usage/SKILL.md)。以下はこのリポジトリの作法。

- 実ファイルを直接編集したら `chezmoi add` / `chezmoi re-add` で source state へ戻す。
- `home/.chezmoiscripts/` は `run_once_` / `run_onchange_` / `run_after_` と 3 桁番号で実行順を管理する。既存の番号体系を崩さない。
- シェルスクリプトは先頭に `set -eu` を置く。
- `.tmpl` は OS 分岐・chezmoi データ・秘密情報が要るときだけ付ける。変数確認は `{{- if and (hasKey . "var") .var }}` の形にする。
- `.ps1` / `.ps1.tmpl` は UTF-8 BOM 付きで保存する（BOM が無いと PowerShell 5.1 が CP932 として読み、日本語コメントが次行のコードを無警告で飲み込む）。
- `SKILL.md` の frontmatter は `name` をディレクトリ名と一致させ、`:` や `#` を含む `description` は二重引用符で囲む（囲まないと CLI がスキルを黙って読み飛ばす）。
- pi の MCP の宣言は `home/.chezmoitemplates/pi-mcp-servers.toml` が単一ソース。生成先（`~/.pi/agent/mcp.json`）の宣言した項目を直接編集しない。
- **設定ファイル・スクリプトのコメントは「その行を編集するときに要る注記」だけにする。** 仕組み・判断基準・既知の不具合・実測値・経緯は `docs/` が正本で、コメントからは参照先だけを示す（`# see docs/spec/structure.md#見出し`）。同じ説明をコメントと `docs/` の両方に書かない。正本の対応は [コメントの書き分け](../../../docs/spec/agent-config-generation.md#コメントの書き分け)。
- 秘密情報はソースに書かず Bitwarden / sops + age を使う。sudo のパスワードは保存せず、スクリプトが実行時に端末で尋ねる（[sudo パスワード](../../../docs/spec/development.md#sudo-パスワード)）。
- 対話入力が必須なスクリプトや長時間実行スクリプトは追加しない。
- **`chezmoi init` を前提にしてよい（[ADR-0038](../../../docs/adr/0038-allow-chezmoi-init-dependency.md)。CHG-0008 の禁止を撤回）。** 設定（`chezmoi.toml`）でしか実現できないもの（`hooks` など）は `init` 前提でよい。更新手順は `chezmoi update --init`。省いても壊れない形にし、前提にしたことを `docs/spec/` に書く。マシン判定は引き続き `.chezmoitemplates/` の共有テンプレートへ置き、`apply` のたびに評価させる（`[data]` は `init` 時にしか更新されない）。

## 権限ポリシーを変えるとき

対象は `home/.chezmoitemplates/pi-permission-policy.json`。**編集の前に** `references/permission-policy.md` を読む（正本の仕様の節を先に読む手順がある）。

## docs・README・試験

- 運用手順やコマンドを追加したら `docs/` の該当ファイルと `index.md` を更新する。`README.md` は導入・更新など入口の手順が変わるときだけ更新する。
- **`README.md` は「最短で動かす」ためだけに保つ。** 各項目は数行 + `docs/` へのリンクに留め、背景・一覧表・失敗談・仕組みは `docs/` へ。同じ手順を README と `docs/` の両方に書かない。
- ドキュメントもコメントも日本語。英語のままにするのは、接頭辞（`feat:` など）・識別子・コマンド・ログやエラーの文言・外部の引用だけ。既存の英語のコメントはその箇所を触るときに日本語へ直す。
- 新しい試験ファイルは `scripts/verify.py` の `_PI_TESTS`（または該当の `Rule`）に、取り込み前に feature の中で登録する。漏れは `test/test_verify.py`（2 秒）で先に見つかるので、全件検査の前に回す。worker は依頼文が許したときだけ登録し、許されなければ報告に「登録が必要: <パス>」と書く。
- 公開リポジトリ: 組織・勤務先の環境の具体は書かない。制約が設計に影響するときは「制約のある環境（認証つきプロキシが必須、など）」のような条件つきの一般論で書き、事実として断定しない。迷ったら書かず、リポジトリ外の非公開メモ（`.tmp/` など）に置く。

## 利用者に実行してもらう補助スクリプト

利用者に実行させる補助スクリプトは `pk <話題> [引数]` の形で示す。端末で止まらない書き方（pager・行末コメント）の規則と入口の置き方は `references/pk-helper.md` を読む。

## コミットメッセージ

[AGENTS.md](../../../AGENTS.md) と `commit` スキルに従う。

## AGENTS.md 自体の編集

- `AGENTS.md` は印なしの平らな文書（45 行以内）。子向けの抜粋の仕組み（`<!-- child:... -->` の印）は撤去した（ADR-0037）。常時の規則を増やさず、編集の場面でだけ要るものはこのスキルへ書く。
