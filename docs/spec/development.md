# 開発ガイド

このリポジトリを変更するときの準備と検証の手順。
各検証のコマンドは [AGENTS.md の検証表](../../AGENTS.md#検証)、テストの種類と入口は
[test/README.md](../../test/README.md)、Docker ハーネスと GitHub Actions の仕組みは
[テストと検証の仕組み](testing.md) にある。dotfiles の編集・反映の手順は
[README の「設定ファイルの編集」](../../README.md#設定ファイルの編集)。

## 環境の準備

クローンした直後に一度だけ行う。

```bash
# mise がインストール済みの場合
mise trust
mise install

# mise が未インストールの場合（chezmoi apply が導入する）
chezmoi apply

# mise が uv を提供し、uv が pyproject.toml に従って Python 3.13 以上を選ぶ
uv sync                    # 依存関係のインストール
uv run pre-commit install  # commit / push の hook の設定 (default_install_hook_types で両方入る)
```

版は `mise.toml` と `uv.lock` で固定している。以後は `git commit` のたびに速い hook が、
`git push` のたびに重い hook と検証の印の警告が走る
([hook の stage の分け方](#hook-の-stage-の分け方))。
すでに install 済みの環境では `uv run pre-commit install` をもう一度実行して pre-push を入れる。

Windows native と WSL で同じ worktree を共有する場合、mise が
`UV_PROJECT_ENVIRONMENT` を切り替え、Windows は `.venv-windows`、
Unix は `.venv` を使う。OS の異なる Python 仮想環境を上書きしない。

### gitleaks はプレビルドを使う

pre-commit の gitleaks フックは、公式リポジトリ（`language: golang`）ではなく
`mise exec -- gitleaks` を呼ぶローカルフックにしている。版は `mise.toml` の
`gitleaks` が正本。

公式フックは、初回にフック環境を作るとき gitleaks を**ソースからビルド**するので、RAM の小さい
Raspberry Pi 4 ではメモリが尽きて SSH も応答しなくなる
（[記録](../research/testing/raspi-oom-ssh-freeze.md)）。mise なら GitHub Releases のバイナリを落とすだけで済む。
フックの id は `gitleaks` のままなので、`SKIP=gitleaks` はそのまま使える。

## 変更の種類ごとの検証

「検証表の行」は [AGENTS.md の検証表](../../AGENTS.md#検証) の行で、
コマンドはそちらにある。

| 変更したもの | 検証表の行 | 補足 |
| --- | --- | --- |
| すべて | 全体（lint / secret scan） | コミット時にも自動で走る |
| `*.tmpl` | テンプレート（描画して検査） | [テンプレートの検査](#テンプレートの検査) |
| `.chezmoiignore.tmpl` / `.chezmoi.toml.tmpl` / `.chezmoiexternal.toml.tmpl` | chezmoi の展開範囲 | apply の最初に読まれ、壊れると apply 全体が止まる |
| `home/dot_config/agents/`、`scripts/agents/`、hook、スキル | agent 設定・hook | |
| `*.sh` | シェルスクリプト | `*.sh.tmpl` はテンプレートの検査が拾う |
| `*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`、`300_windows/` | Windows 資産（静的） | 加えて [Windows 実機での検証](#windows-実機での検証) |
| `docs/` | docs の索引整合 | |
| OpenCode の起動・権限 | OpenCode の実機試験 | 実 DB を汚さない |
| `home/` 全般 | 展開結果（`chezmoi diff`） | エージェントの sandbox の外で実行する |
| `.chezmoiscripts/`、`.chezmoi.toml.tmpl`、`.chezmoitemplates/` | — | [Docker での初回導入の検証](#新しい機械での初回導入を-docker-で検証する) |

### 検証の方針と選択実行

方針: 日常は変更に応じた選択実行、全件はコミット前に 1 回。全件の pytest は約 3,700 件で
約 9 分かかる（実測値は [開発ガイドの実測メモ](../research/testing/development-timing-notes.md)）。
CI の範囲は [テストと検証の仕組み](testing.md#いつ回すか)。
**「いつ・何を回すか」の選択規則の正本はこの節**で、Docker ハーネスの契約は testing.md が正本。

```text
python3 scripts/verify.py [--changed | --all] [--dry-run] [--list]
```

- `--changed`（既定。`mise run verify`）: git の変更（ステージ済み・未ステージ・未追跡）を見て、
  上の表に当たる試験・検査だけを実行する。この表を自動化したもの
- `--all`（`mise run verify:all`）: 全件
- `--dry-run`: 実行せずコマンドを列挙する
- `--list`: 変更パスごとの対応を表示する

次の変更は**全件にフォールバック**する。影響範囲を規則で絞れず、絞ると見逃すため。

- どの規則にも当たらない変更
- 横断的に効く設定（`common.toml.tmpl`、`scripts/agents/generate.py`、`pyproject.toml` など）

`pre-push` hook に**全件検証は入れない**。待ち時間が `--no-verify` を誘い、`AGENTS.md` の
「長時間実行スクリプトは追加しない」とも合わない。入れるのは下記の速い hook と印の警告だけ。

#### hook の stage の分け方

速いものは commit、重いものと検証の印の警告は push に置く。`.pre-commit-config.yaml` は
`default_stages: [pre-commit]` を既定にし、push に回す hook だけ `stages: [pre-push]` を付ける
(`stages` を省くと全 stage で走り、push でも二重に走るため)。
`default_install_hook_types` で `pre-commit install` だけで両方の hook が入る。

| stage | hook |
| --- | --- |
| commit | gitleaks・YAML・ruff・frontmatter・`common-toml-local`・docs の索引・`verify-stamp`・空白・Markdown lint など（速いもの） |
| push | `lint-templates-local` (テンプレートの描画 lint)、`raspi-regression-local` (Raspberry Pi の回帰テスト)、`verify-stamp-push` (印の警告) |

hook ごとの所要時間は [開発ガイドの実測メモ](../research/testing/development-timing-notes.md)。

- 理由: commit のたびに 10 秒以上待たせると `--no-verify` を誘う。push は回数が少なく、
  まとめて検査する場所に向く（利用者の判断）
- 選択実行 (`verify.py --changed`) は `pre-commit run --files` を使うため commit の stage だけを走らせる。
  push 側の `lint-templates-local` は `LINT_TEMPLATES` として別に走り、回帰テストは
  `test_raspi_detection` の選択で走る。全件 (`--all`) は `--hook-stage pre-push` の呼び出しで push の hook も走らせる
- 構造は `test/test_verify.py` の `test_pre_commit_config_splits_stages` が守る

#### 部分コミットで pre-commit が落ちるとき

コミットを複数に分けるとき、pre-commit は未ステージの変更を一時的に退避するが、
**未追跡ファイルは退避されない**。たとえば索引を変更したが、索引に載る新規の docs を
このコミットに含めないときは、「索引に載っていない」と `lint-docs-local` が落とす。
その docs を `.tmp/` へ一時的に退避してからコミットし、後で戻す（`--no-verify` は使わない）。
同じ理由で、`pre-commit run --all-files` は未追跡の新規ファイルを検査しない。
新規ファイルは `--files <パス>` でも回す。

#### コミット前の検証の印

`verify.py --all`（`--changed` が全件に落ちた場合を含む）が成功すると、そのときの作業ツリーの内容
（HEAD + 変更 + 未追跡。`.gitignore` は効く）を印として残す。コミット時に `verify-stamp` hook
（`scripts/verify_stamp.py check`）がステージ済みの内容と照合し、一致しなければ**警告を出すだけで
コミットは通す**（終了コードは常に 0）。push 時には `verify-stamp-push` hook
（`check-push`）が、pre-commit が渡す `PRE_COMMIT_FROM_REF` と `PRE_COMMIT_TO_REF`（push する範囲）の
変更 (`git diff --raw` の追加・変更。削除は除く) を同じ仕組みで照合し、「push するコミット」として警告する
（常に 0）。FROM が無い・全ゼロ（新しいブランチ）のときは、`origin/develop`（あれば。gitflow の feature の親）、無ければ `origin/main` との merge-base から見る。
それも無ければ何も言わない。

- 残すもの: `{version, head, created, entries: {パス: [mode, blob]}}` の JSON。実 index・refs・作業ツリーは
  変えず、一時 index に `add -A` して作る
- 置き場: `git rev-parse --git-path` が指す `.git/` 配下（worktree ごと）。`verify-stamp.json`（印）、
  `verify-stamp.log`（警告の記録）
- 照合: ステージ済みの追加・変更の各パスで (mode, blob) を印と比べる。削除は見ない。部分コミットでは、
  ステージしたパスだけが一致すればよい。印が無いときも警告する
- 警告しない場合: 不一致のパスを `verify.py` の `plan()` に通し、全件にならない（選択実行で足りる。
  docs だけの変更など）とき。`plan()` を読み込めなかったときは全件扱いで警告する
- 強制しない理由: 約 9 分の待ち時間が `--no-verify` を誘う（`pre-push` に全件を入れない判断と同じ。
  [0028](../change/closed/0028-verification-speed-and-delegation.md)）
- 記録の見方: `verify-stamp.log` は 1 行 1 件の JSONL（`{"at", "result": "no-stamp" | "mismatch",
  "count"}`）。`wc -l` で警告の回数、`result` で印が無かったのか内容が違ったのかが分かる
- 強制に進める条件: 記録で「全件検証を回し忘れたコミット」が頻発したとき。そのときは hook を
  失敗させる（終了コード 1）形に変える案件で決める（push 側の警告は実装済み）

### テンプレートの検査

`identify` は `*.tmpl` に一切タグを付けないため、`check-toml` / ruff /
shellcheck はテンプレートを素通りする（導入時点で sh 14 / py 8 / toml 4 の
ファイルが素通りしていた）。`scripts/lint_templates.py` は
`chezmoi execute-template` で描画し、**描画後の拡張子**で既存の linter へ
振り分ける。

分岐の両側を通すため、ファイルごとに描画コンテキストを変える。

| 軸 | 決め方 |
| --- | --- |
| OS | `home/.chezmoiscripts/` のディレクトリ規約（`100_linux/` なら linux だけ） |
| username | `.chezmoi.username` を参照するファイルだけ `applejxd` と別ユーザの 2 通り |
| Raspberry Pi | `is-raspi` / `is_raspi` を参照するファイルだけ、判定なしと Pi 扱いの 2 通り |

`--skip-secrets` を付けるので Bitwarden は呼ばれない。秘密を使うテンプレートは
chezmoi が `skip template` を返し、検査対象から外れる。

対象外:

- `.ps1.tmpl` — PSScriptAnalyzer（pwsh 本体）が要る
- `.zsh.tmpl` — shellcheck が zsh をサポートしない
- `home/.chezmoitemplates/**` — 単体では描画できない（modify script の共通ラッパーは
  `test/agents/test_modifier_wrappers.py` が呼び出し側ごと検査する）
- `.chezmoi.toml.tmpl` — `execute-template --init` が要る（`test_chezmoi_templates.py` が検査する）
- `.chezmoiignore.tmpl` — 描画結果に対応する linter が無い（同上）

### 新しい機械での初回導入を Docker で検証する

素の Ubuntu コンテナで `chezmoi init` / `apply` が人手なしで通るかを
`mise run e2e` で試す。毎回は回さず、上の表の最終行のようなきっかけで回す。
サービス・モード・回すきっかけ・判定の読み方は
[テストと検証の仕組み](testing.md#docker-での-cold-start-検証) が正本。

## Windows 実機での検証

次を変更したら **Windows の PowerShell で**検証する。WSL / Linux では実行できない。

- `home/**/*.ps1` / `*.ps1.tmpl`、`home/dot_config/powershell/`
- `home/.chezmoiscripts/300_windows/`
- Windows 向けの hook 起動コマンド生成（`scripts/agents/hooks.py`）

```powershell
chezmoi apply
uv run --with pytest --with pywinpty --no-project pytest test\test_windows_assets.py test\test_powershell_interactive.py -q
```

`test_powershell_interactive.py` は**適用済みの実プロファイル**を PowerShell 7 と
Windows PowerShell 5.1 の ConPTY セッションで読み込み、プロンプト到達後の状態を
検査する。だから先に `chezmoi apply` が要る。`pywinpty` はその ConPTY を Python から
扱うための依存で、Rust ビルドの Windows 専用パッケージ。WSL / Linux では
**依存解決の時点でビルドに失敗する**。

| 環境 | 実行できる範囲 |
| --- | --- |
| Windows (pwsh) | 静的 + 対話 |
| GitHub Actions（`windows.yml`） | 静的と agent 設定のテスト。対話は回さない（[範囲](testing.md#windows-の-github-actions)） |
| WSL / Linux | 静的のみ（`uv run --with pytest --no-project pytest test/test_windows_assets.py -q`） |

対話テストは `os.name != "nt"` で全件 skip するため、WSL で失敗が 0 件でも
Windows 側は未検証である。静的テストが拾えるのは
UTF-8 BOM、winget の記法、プロファイルの字面までで、次は拾えない。

- 起動エラーと OnIdle ジョブのエラー（どちらもコンソールに出ない）
- 対話時だけ実行するブロック（PSReadLine / oh-my-posh / PSFzf / ZLocation、
  `pbcopy` などの補助関数）
- oh-my-posh の init をキャッシュすると pure テーマが既定の powerline へ戻る問題、
  `mise activate` の PATH 重複、`Ctrl+d` の既定バインドが端末を閉じる問題

実機で回せない場合は「Windows 未検証」と明記する。

### Windows Sandbox でのクリーン導入の検証

まっさらな Windows に README の第 1 フェーズ相当（`winget install` → `chezmoi init applejxd --apply`
の 1 回）だけで導入でき、`pi` などが新しいシェルで起動するかを、使い捨ての Windows Sandbox で確かめる
（`scripts/windows/sandbox/guest.ps1` は `init --apply` を 1 回だけ実行する）。
README の第 2 フェーズ（`bw login` → `BW_SESSION` → 再度の `init` / `apply`）で入る
Bitwarden 由来のファイルは検証の対象外。
実機の環境（古い winget 版 node、PATH の残り）に影響されない。

**実行ポリシーの抜けを検出できない**（既知の限界）。`launch.ps1` が `-ExecutionPolicy Bypass` で
`guest.ps1` を起動すると、子の `chezmoi` にも `PSExecutionPolicyPreference=Bypass` が引き継がれる
。README の `Set-ExecutionPolicy` の行は、`Restricted` のままだと `chezmoi` が `.ps1` の
run スクリプトを実行できないために必要だが、この検証はその行が無くても通る。

```powershell
# ホストの PowerShell で（Sandbox の有効化と再起動が済んでいること）
pwsh scripts/windows/sandbox/launch.ps1
```

- 有効化: 管理者の PowerShell で `Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All` を実行して再起動する（Windows 11 Pro / Enterprise）
- 結果: `.tmp/sandbox-result/summary.txt`（コマンドの有無・版・`pi --version`・PASS/FAIL）と `transcript.log`（全出力）
- 取得元は GitHub の `applejxd/dotfiles`（push 済みの内容）。ローカルの未 push の変更は検証されない
- Sandbox のユーザーは `WDAGUtilityAccount` で `applejxd` ではないため、個人用の分岐（Bitwarden など）は通らない。管理者の作業（309）は UAC なしで走る
- 所要時間は約 1 時間。Python 3.12 のインストーラーだけで約 20 分かかる（固まっているわけではない）。途中経過は `chezmoi-apply.log`（UTF-16）と `winget-*.log` に随時出る。検証が終わると Sandbox は自動で終了する（起動中は `launch.ps1` が止める）
- Sandbox では `msstore` ソースが Rest API エラーになるため、`guest.ps1` が外している
- 制約のある環境の機のプロキシや制限は再現しない。WSL の機能有効化は再起動が要るので、警告で終わる想定

## スクリプトを追加するとき

1. `home/.chezmoiscripts/` の OS 別ディレクトリにスクリプトを追加する
2. 既存の番号体系に合わせて、実行順を表す 3 桁の番号をファイル名に付ける
   （規約は [自動実行スクリプト](structure.md#自動実行スクリプト)）
3. OS 分岐・chezmoi データ・秘密情報が要るときだけ `.tmpl` を付ける

### テンプレート変数

よく使う chezmoi の組み込み変数:

- `{{ .chezmoi.os }}` - OS名 (`windows` / `linux` / `darwin`)
- `{{ .chezmoi.homeDir }}` - ホームディレクトリパス
- `{{ .chezmoi.sourceDir }}` - ソースディレクトリパス

### sudo パスワード

sudo のパスワードはどこにも保存せず、スクリプトが実行時に端末で尋ねる。
`.chezmoi.toml.tmpl` には入力を求める処理が無いので、`chezmoi init` では尋ねられない。

| OS | 取り方 |
| --- | --- |
| macOS（`200_mac/` の 205 / 210 / 250） | 共有テンプレート `sudo-keepalive.sh.tmpl` の `start_sudo_keepalive` が `sudo -v` で 1 回尋ね、スクリプトが終わるまで裏で認証を延長する（macOS の既定の期限は 5 分）。205 は Homebrew を入れるときだけ呼ぶ |
| Linux（`111` / `120` / `121` / `123` / `125`） | 同じ `start_sudo_keepalive`。長い `apt-get upgrade` の途中で、既定の期限（約 15 分）が切れて尋ね直さない。`125` は sudo 無しモードでは呼ばない。`130`（短い）は、先頭の `sudo -v` のまま |

どちらも、パスワードは sudo 自身が尋ね、スクリプトの変数には持たない。Homebrew は
公式の無人導入（`NONINTERACTIVE=1`）で入れ、パスワードを送り込まない。

**環境変数からは読まない。** `export SUDO_PASSWORD=...` は効かないうえ、そのシェルから
起動した AI CLI などの子プロセスへパスワードが引き継がれるので使わない。

### sudo 無しモード

root 権限が無い機械（共有サーバなど）でも `chezmoi apply` / `update` を通すためのモード。
Linux / WSL のみ。macOS と Windows は対象外。

```bash
CHEZMOI_NO_SUDO=1 chezmoi apply     # 明示する
```

`sudo` が PATH に無いときも自動で有効になる。判定は `home/.chezmoitemplates/no-sudo` が
単一ソースで、`apply` のたびに評価する（`init` に依存しない）。

| 対象 | 有効時の挙動 |
| --- | --- |
| `100_linux/110_native/`、`120_wsl.sh`、`121_ubuntu.sh`、`130_shell.sh` | `.chezmoiignore.tmpl` で除外（全部 apt / `/etc` / `chsh` が要る） |
| `125_mise.sh` | `sudo -v` と Python ビルド用の apt を飛ばし、mise 本体とツールはユーザ領域へ入れる |

除外したスクリプトは `run_once_` の記録が残らないので、sudo が使えるようになった次の
`apply` で走る。apt 依存のツール（ビルド用パッケージ、bubblewrap など）は自動では入らない。
管理者に入れてもらうか、sudo のある環境で一度 `apply` する。

### スクリプトの無効化

一時的に全スクリプトを除外する場合：

```bash
chezmoi apply --exclude=scripts
```

恒久的に無効化する場合は、対象ファイルの `run_` 属性を外すか削除する。
`.tmpl` は実行属性ではないため、拡張子だけを外しても無効化されない。

## ブランチモデル（gitflow-lite）

このリポジトリは、`main`（リリース。他のマシンの `chezmoi update` が見る）・`develop`（統合。この PC の chezmoi のソースが指す）・`feature/<名前>`（作業。専用の worktree）で運用する（[CHG-0047](../change/0047-gitflow.md)）。`release`・`hotfix` は使わない。

- **feature**: AI は `guarded_action` の `gitflow_feature_start` で起票し（確認なし）、feature の worktree（`.tmp/worktrees/<名前>`）の中で細かくコミットし（確認なし。[`git_commit` の確認の省略](guard/pi-extensions.md#guarded_action承認つきの外部操作)）、`gitflow_feature_finish` でクローズする（確認あり。develop へ squash の 1 コミット）。`finish` は、develop が checked out の本体の作業ツリーで行う
- **main へ**: 検証（`mise run verify:all`）の後、利用者が `git flow integrate develop` で `develop` を `main` に merge し、`push` する。AI は `integrate` と `push` を行わない
- **設定**: 共有の `.gitflow`（`gitflow.worktreePath` を含む）を、`scripts/gitflow-setup.sh` で作る・取り込む。**サンドボックスの外で、利用者が一度だけ**行う（`.git/config` を書くため）。新しい clone や別のマシンでは、同じスクリプトで `git flow config sync` する
- **検査**: スタンプは worktree ごと。push の基準は `origin/develop`（あれば）、無ければ `origin/main`。CI は `main` と `develop` への push と、全ての pull request で動く

## 作業ツリーの一時領域（`.tmp/`）

`.tmp/` は git の管理外の使い捨ての置き場で、**掃除が無いと溜まる**（実測で 1 か月に 31 GB）。
方針は [CHG-0042](../change/0042-tmp-lifecycle.md)。pi のセッションごとの置き場は
[pi の拡張](guard/pi-extensions.md#セッションごとの一時置き場tmpsid)。

- `mise run tmp:clean`: **既定は一覧だけ**（`--apply` で消す）。`home/dot_config/pi/harness/tmp_clean.py`
  - **自動で消してよいのは、自分で作ったと確かめられるものだけ**: 持ち主の死亡を確証できた `.tmp/s/<名前>/` と、
    再生成できる名前（`pytest-of-*`・`tools-ext-*`・`agents-config-*`・`tmp.*` など）の 1 日より古いもの
  - **未知の名前は一覧に出すだけで消さない**（`--all --apply` で、7 日より古いものを消す。手動の確認用）
  - 消さない: `keep/`（取り込み待ち）・`research/`・`review-loop/`・`away-shift/`・`subagents/`・`worktrees/`・`checkpoint-*`・画像
  - `.tmp` やその中の `s` がシンボリックリンクなら拒否し、別のデバイス（マウント）の中へは降りない。`.sweep.lock` で排他
- **試験が残骸を残さない**: `tools_ext_driver.mjs` は終了時に消す。`agents_common.agents_config_dir` は、
  `conftest.py` の `pytest_sessionfinish` でも消す（pytest-xdist のワーカーは `os._exit` で終わり、`atexit` が走らない）。
  `pyproject.toml` の `tmp_path_retention_count = 1`・`tmp_path_retention_policy = "failed"` で、落ちたテストの分だけ残す。
  固定する試験は `test_tmp_hygiene.py`（実測: `test/agents` を実行した後の `.tmp` に残骸 0、`pytest-of-*` は 4 KB）

## 子エージェントのモデルのカタログの道具

[CHG-0043](../change/0043-model-catalog.md)。仕様は[カタログ](agent-model-assignment.md#子エージェントのモデルのカタログ)。

- `mise run models:check`: カタログと `pi --list-models` を比べる（`scripts/models.py check`）。警告 = 終了コード 1、**一覧を取得できない・対象のプロバイダが空 = 2（「問題なし」にしない）**。`--list-file` で、保存した一覧を使える（試験用）
- `mise run models:probe`: 短い応答とツール呼び出しで確かめる（`scripts/models.py probe`）。既定は未確認のもの（無ければ全部）。`--model <id>`・`--effort <段>`・`--all`・`--dry-run`。1 回の上限は 8 件（費用の保護）
- 試験: `test_pi_model_catalog.py`（生成の検査）・`test_pi_model_choice.py`（ハーネスの選択）・`test_models_tool.py`（道具）
