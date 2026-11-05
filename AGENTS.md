<!-- child-context: v1 -->

# Chezmoi Dotfiles

<!-- child:all -->

chezmoi で Windows / Ubuntu / WSL / macOS の dotfiles を管理する個人用リポジトリ。
`home/` 配下が chezmoi の source state で、それ以外は導入・生成・検証用。
構成やセットアップの詳細は [docs/index.md](docs/index.md) にある。

<!-- /child -->

<!-- parent -->

指示の分担: 全リポジトリ共通の作法（応答の言語・判断の仰ぎ方・検証の姿勢・委譲・設計の姿勢）は
グローバルの指示（`home/.chezmoitemplates/agent-instructions.md`）が正本。
このファイルには、**このリポジトリで何を実行し何を守るか**だけを書く。

<!-- /parent -->

## 検証

<!-- child:worker -->

変更したら該当するものを実行する。

<!-- /child -->

<!-- parent -->

| 対象 | コマンド |
| --- | --- |
| 変更に応じた選択実行（日常） | `mise run verify`（`--dry-run` でコマンドを列挙） |
| 全件（コミット前に 1 回） | `mise run verify:all`（安い検査 → 変更に当たる試験 → 残りの順。前の段が落ちたら止まる） |
| 全体（lint / secret scan） | `uv run pre-commit run --all-files` |
| OpenCode の実機試験 | `mise run opencode:probe -- '<prompt>'`（実 DB を汚さない） |

<!-- /parent -->

<!-- child:worker -->

| 対象 | コマンド |
| --- | --- |
| agent 設定・hook | `uv run --with pytest --with pytest-xdist --with pyyaml --no-project pytest test/agents/ -q -n 4 --dist worksteal` |
| Windows 資産（静的） | `uv run --with pytest --no-project pytest test/test_windows_assets.py -q` |
| chezmoi の展開範囲 | `uv run --with pytest --no-project pytest test/test_chezmoi_templates.py -q` |
| シェルスクリプト | `git ls-files '*.sh' \| xargs mise exec shellcheck -- shellcheck` |
| テンプレート（描画して検査） | `mise exec -- python3 scripts/lint_templates.py` |
| docs の索引整合 | `mise exec -- python3 home/dot_claude/skills/sdd-docs/scripts/lint_docs.py` |
| 展開結果 | `chezmoi diff`（sandbox 内では不可。下記） |

<!-- /child -->

<!-- parent -->

日常は `mise run verify`、コミット前に `mise run verify:all` を 1 回回す。回さないと pre-commit が警告する。
選択規則・フォールバック・方針は [検証の方針](docs/spec/development.md#検証の方針と選択実行)。

<!-- /parent -->

<!-- child:worker,review,plan -->

検証結果の限界（判断の不変条件）:

- `*.tmpl` は pre-commit の linter が素通りする。描画後の検査（`lint_templates.py`）が別に要る。「pre-commit が通った」だけでは `*.tmpl` を検査したことにならない。
- `pre-commit run --files` で新規ファイルの lint は検査されるが、秘密検出（gitleaks）は `--staged` なので、新規ファイルは `git add` の後でないと見ない。「pre-commit が通った」は新規ファイルの秘密検出済みを意味しない。
- sandbox 内の `chezmoi diff` は、`~/` が不可視のため展開結果の証拠にならない（全部が「new file」に見える）。

<!-- /child -->

<!-- child:worker -->

担当の試験ファイルを優先し、`test/agents/` 全体は必要なときだけ回す。

`*.tmpl` は pre-commit の linter が素通りするので、テンプレートを編集したら
`lint_templates.py` も実行する（[理由と対象](docs/spec/development.md#テンプレートの検査)）。

`pre-commit run --all-files` は git に未登録の新規ファイルを検査しない。ファイルを
新しく足したら `uv run pre-commit run --files <パス>` でも回す（コミット時に初めて落ちる）。
ただし秘密検出（gitleaks）は `--staged` なので、新規ファイルは `git add` の後でないと見ない（`--files` の対象ではない）。

`chezmoi diff` は **sandbox 内では無意味**。`~/` が deny-by-default で不可視のため、
展開先が空に見えて全て「new file」になる。sandbox 外のシェルで実行する。
worker は実行せず、報告の「次の候補」に書く（worker は sandbox の外に出られない）。

<!-- /child -->

<!-- parent -->

初回のみ `mise install && uv sync && uv run pre-commit install` が要る。
既に install 済みの環境では `uv run pre-commit install` をもう一度実行して pre-push を入れる。

<!-- /parent -->

### Windows 実機での検証

<!-- child:worker,review,plan -->

- Windows 資産（`*.ps1`・`home/dot_config/powershell/`・`300_windows/`・`scripts/agents/hooks.py`）を触った変更は、WSL/Linux の検査が通っても Windows 側は未検証と扱う。実機で回せないときはそう明記する。

<!-- /child -->

<!-- child:worker -->

`*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`、`home/.chezmoiscripts/300_windows/`、
`scripts/agents/hooks.py`（Windows 向けの hook 起動コマンド生成）を触ったら
**Windows の PowerShell で**検証する。WSL では対話テストが skip されるだけなので、
通っても **Windows 側は未検証**。実機で回せない場合はそう明記する
（[手順と拾える範囲](docs/spec/development.md#windows-実機での検証)）。

<!-- /child -->

## このリポジトリ固有の約束

<!-- child:review,plan,worker -->

このリポジトリ固有の約束で定めない事項は、他の適用指示に反しない範囲で一般的な流儀で判断してよい。

<!-- /child -->

<!-- parent -->

- 実ファイルを直接編集したら `chezmoi add` / `chezmoi re-add` で source state へ戻す

<!-- /parent -->

<!-- child:worker,review,plan -->

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
  同じ説明をコメントと `docs/` の両方に書かない（更新時に必ず片方が古くなる）。
  正本の対応・コメントに残してよい例・ docs へ移すものは
  [コメントの書き分け](docs/spec/agent-config-generation.md#コメントの書き分け)
- 秘密情報はソースに書かず Bitwarden / sops + age を使う。sudo のパスワードは保存せず、
  スクリプトが実行時に端末で尋ねる（[sudo パスワード](docs/spec/development.md#sudo-パスワード)）
- 対話入力が必須なスクリプトや長時間実行スクリプトは追加しない

<!-- /child -->

<!-- parent -->

- **利用者に実行してもらう補助スクリプトは、`pk <話題> [引数]` の形で示す。** 入口は `.tmp/keep/<話題>/run.sh`（無ければ唯一の `*.sh`）。
  `sh <長い絶対パス>` は使わない（`pk` は `chezmoi apply` で配備。未配備の機械では絶対パスで示してよい）。
  入口の先頭のコメントの 1 行目は、`pk` の一覧に出る説明として書く。話題名は短く覚えやすく（[詳細](docs/spec/development.md#補助スクリプトの短い入口pk)）
- コミットメッセージは Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:`）。**本文は件名 + 1〜3 行の要約だけにし、箇条書きにしない**（詳細は案件・docs に書く。承認画面、とくにスマホで、長い本文が画面を埋めて読みにくいため）
- **dotfiles のこのリポジトリは、サンドボックスの中（`pis` の既定）で開発しない。`pis --no-sandbox`（フルガードだけ）で行う**（[ADR-0025](docs/adr/0025-dotfiles-dev-without-os-sandbox.md)）。
  内側では隠した秘密の追跡ファイルが `/dev/null` に見えて `git status` が dirty になり、統合（`git merge`）が `stash failed` で失敗する。
  **「`pis`（サンドボックスあり）で dotfiles を開発できる」「内側で統合できる」と言わない・判断しない。** 内側の合図（`git status` が dirty に見える・読めないファイルがある）が出たら、作業を止めて、サンドボックスなしの起動へ切り替えるよう利用者に伝える。
  サンドボックスは、外部のコード・依存・Web アプリ・GPU を実行するほかのリポジトリで使う
- **develop / main に直接コミットしない。** 実装は feature の worktree（`.tmp/worktrees/<名前>/`）で行う。
  feature の起票とクローズ（`git flow feature start` / `finish`）は、機械では止めないので指示で守る。
  AI は、feature の worktree で起動した pi から `guarded_action` の `git_commit` を使う
  （[CHG-0050](docs/change/0050-slim-guarded-action.md)）。**feature の linked worktree（`feature/*`）の `git_commit` は確認なしで実行される**
  （自由区。[CHG-0053](docs/change/0053-worktree-integration-gate.md)）。それ以外のコミットは確認する
- **並列にできる作業は子エージェントに任せる。** 調査・レビュー・独立したファイル範囲の実装を並列にする。
- **1 worktree = 1 feature = 1 worker**。親が `git flow feature start <名前> --worktree --no-fetch` で起票し、
  worker に worktree の絶対パスと担当ファイルを渡す。担当外の worktree や本体を編集させない
- **見込みで並列に実装し、前段が終わり次第、接続して試す（直列に待たない）。** 一般則はグローバルの指示の「子エージェントへの委譲」。このリポジトリでは次のとおり。
  - 前段（設計の返答・独立 review・別 feature の取り込み待ち・承認待ち）を待たず、I/F を**契約書**（`.tmp/keep/<話題>/api-contract-*.md`。API の形・関数の署名・担当ファイルの分担。短く、ずれる前提で書く）で先に固定し、後段（配線・画面・統合・撤去・docs）も別の worker で同時に実装する（例: A4a は J1a・J1b・U を契約だけで並行した）
  - 前段が終わり、配線と試験ができる段になったら、後段の枝へ前段の枝・develop を `git merge` で取り込んで**接続し、実物どうしの試験を回して I/F を調整する**（調整は後段の側で直すのを基本にする）。見込みの実装を直す・捨てる費用は、待つ時間より安いとみなす
  - **見込みで進めないもの**: 承認が要る操作の実行（統合・push）・既定で有効になる権限の拡大・元に戻せない操作。新しい書き込み権限は既定で無効の旗で入れる。上流の設計が根本から変わったら、見込みの部分は捨てる
  - 並列の限界は、子の同時数（`guarded_task` は 6）と全件検査の排他。空きが出たらすぐ次の worker を起動し、全件検査は feature ごとに 1 回（日常は `mise run verify` の選択実行）にする
  - 親は読む量を絞る: 子の返答は先頭の結論と申し送りだけ読み、詳細・全文はファイルに任せて、親のコンテキストを節約する

<!-- /parent -->

<!-- child:worker -->

- worker はコミットしない。親が結果を根拠で確かめ、`git_commit`（`dir` に worktree）→ `guarded_pr_summary` で `mergeMessage` の下書きを出す → 利用者が PR ビューアの「統合する」を押す。worker は `finish`・`merge` を実行しない

<!-- /child -->

<!-- parent -->

- **`git flow feature finish`・`git merge` など、保護ブランチへの統合は、既定では利用者が PR ビューアの「統合する」を押す。利用者がチャットで統合を明示的に指示したときに限り、AI が統合コマンドを実行してよい**（必須確認の承認画面が出て、利用者が TUI で承認する。bypass でも省略できない。指示が無いときは実行しない。実行前に、本体が `develop` で clean・全件検査が合格・`git merge-tree` が衝突なしを確かめる。チャット経由は統合器・2 段確認・リスクパスの警告が無いので、ボタンを既定とする。[運用モード](docs/spec/operation-modes.md#統合)・[CHG-0053](docs/change/0053-worktree-integration-gate.md)）
- 共有されやすいファイル（`common.toml.tmpl`・golden・docs の索引）は、同時に複数の worker に触らせない。衝突するなら、親が順に取り込む

<!-- /parent -->

<!-- child:worker -->

- 重い検査を同時に回さない。worker には対象の試験と `pre-commit --files` だけ回させ、
  全件（`mise run verify:all`）は親が 1 回だけ回す。並列度は `VERIFY_JOBS` で下げられる

<!-- /child -->

<!-- parent -->

- **pi の会話（セッション）を複数並行して使うときは、取り込み（利用者の「統合する」の押下）の窓口を 1 つにする。**
  ほかの会話は feature のコミットまで。全件検査は排他ロックが自動で 1 本ずつにする。
  規則は [複数の会話を並行して使う運用](docs/spec/guard/pi-subagents.md#複数の会話を並行して使う運用)
- 子の結果は、パスと行・コマンドの出力で確かめてから採用する（子は「通った」を実行できないことが多い）
- **並列度を保つ。** 親は、子の完了・利用者の応答のたびに子の一覧（`guarded_task` の list）を見て、**空きをキュー（`.tmp/keep/queue/`）の先頭の依頼文で埋める**。次の依頼文は空きを待つ間に先に書く。子の返答は結論と申し送りだけを読む。手順は スキル `feature-orchestration` の [parallel-ops.md](.agents/skills/feature-orchestration/references/parallel-ops.md)
- **完璧より完了（done is better than perfect）。** 守る境界（権限・秘密・元に戻せない操作）を満たせば、細部の磨き込みで保存を止めない。具体的には: (1) 新しい権限・書き込みは既定で無効の旗で入れ、先に develop へ入れてから実機で確かめる（完璧な確認を待たない。違っていたら別で直す）。(2) 独立 review は**権限の境界を動かす変更だけ**を保存前に行い、それ以外は保存後でよい。(3) 指摘は BLOCKER（境界を破る）だけ保存前に直し、MAJOR 以下は追加の小さな変更に回す。(4) docs のみ・定数 1 つのような小さな変更は、関連の試験だけで保存する（全件検査を回さない）。(5) 磨き込み・未確認・「あとで直す」は todo に起こして続ける（保存の条件にしない）。この原則は守る境界を緩めるものではない
- 手順・依頼文の雛形・踏みやすい落とし穴は、スキル `feature-orchestration`（`.agents/skills/`）と
  [並列実装の運用](docs/spec/guard/pi-subagents.md#並列実装の運用隔離なしの-worktree)。worker への依頼文は、共通の約束をファイルで参照させて短くする

<!-- /parent -->

<!-- child:worker,review,plan -->

- 新しい試験ファイルは `scripts/verify.py` の `_PI_TESTS`（または該当の `Rule`）に、取り込み前に feature の中で登録する。
  漏れは `test/test_verify.py`（2 秒）で先に見つかる。

<!-- /child -->

<!-- child:worker -->

- worker は依頼文が許したときだけ登録し、許されなければ報告に「登録が必要: <パス>」と書く。
- `test/test_verify.py` は全件検査の前に回す

<!-- /child -->

<!-- child:worker,review,plan -->

- 運用手順やコマンドを追加したら `docs/` の該当ファイルと `index.md` を更新する。
  `README.md` は導入・更新など入口の手順が変わるときだけ更新する
- **`README.md` は「最短で動かす」ためだけに保つ。** 各項目は数行 + `docs/` への
  リンクに留め、背景・一覧表・失敗談・仕組みの説明は `docs/` へ逃がす。
  同じ手順を README と `docs/` の両方に書かない
- **`chezmoi init` を前提にした設計にしない。** 普段の運用は `chezmoi update`
  （`git pull` + `apply`）が中心で `init` を呼ばない。マシン判定などは
  `.chezmoitemplates/` の共有テンプレートへ置き、`apply` のたびに評価させる。
  `chezmoi.toml` の `[data]` は `init` 時にしか更新されない
  （[CHG-0008](docs/change/closed/0008-raspi-branching.md)）

<!-- /child -->

<!-- child:all -->

- **このリポジトリは公開。私物の環境以外の具体を書かない。** 勤務先・所属組織の環境、契約、利用ポリシー、
  認証・権限・ネットワークの構成、組織名・部署名・社内の URL やホスト名・ドメインは、コード・コメント・docs・
  コミットメッセージ・案件・調査記録のどこにも残さない（公開後は履歴から消せない）。そうした制約が設計に影響する
  ときは、「制約のある環境（認証つきプロキシが必須、fine-grained PAT が使えない、など）」のように
  **条件つきの一般論**で書き、確認した事実のように断定しない。個人の機（私物）の事実は書いてよい。

<!-- /child -->

<!-- parent -->

  迷ったら書かず、リポジトリ外の非公開メモ（`.tmp/` など）に置く

<!-- /parent -->

<!-- child:worker,review,plan -->

- ドキュメントは日本語で書く
- **コメントも日本語で書く。** コード・設定・スクリプト・試験のコメントと docstring、レビューや PR のコメント・サマリー、コミットメッセージの件名と本文は日本語にする。英語のままにするのは、接頭辞（`feat:` など）・識別子・コマンド・ログやエラーの文言・外部の引用だけ。新しく書く・直すコメントは日本語で、既存の英語のコメントはその箇所を触るときに日本語へ直す

<!-- /child -->

<!-- parent -->

- **このファイルの編集の注意（導入済み: 先頭に `<!-- child-context: v1 -->`）**: 新しい節・段落・表・コードブロックは、子向け（`<!-- child:<役割> -->`〜`<!-- /child -->`）か親だけ（`<!-- parent -->`〜`<!-- /parent -->`）のブロックの中に入れる。
  見出し以外がブロックの外にあると、`extract` の子の起動が失敗する（未分類）。`learn`・`onboarding` スキルが書き足すときも同じ
- 直したら `test/agents/test_child_context_sources.py` を回す。子向けのブロックに規則を足したら、同じ試験の `RULES` に役割別の期待を足す（足さないと `test_extract_has_only_listed_rules` が落ちる）。
  親だけのブロックに足した行は子の抜粋に入らないので、`RULES` への追記は必須ではない（分類を残すなら `NONE` で足す）
- 印の記法を使う文章では、`<!--` の直後の語が `child` / `parent` の行を、印以外では書かない（印に似た行として破損扱いになる）。記法の詳細は [子の文脈の抜粋](docs/spec/guard/pi-subagents.md#子の文脈-agentsmd-の抜粋-chg-0059)

<!-- /parent -->
