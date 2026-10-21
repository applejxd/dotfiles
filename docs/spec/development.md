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
uv run pre-commit install  # pre-commit フックの設定
```

版は `mise.toml` と `uv.lock` で固定している。以後は `git commit` のたびに
pre-commit が走る。

Windows native と WSL で同じ worktree を共有する場合、mise が
`UV_PROJECT_ENVIRONMENT` を切り替え、Windows は `.venv-windows`、
Unix は `.venv` を使う。OS の異なる Python 仮想環境を上書きしない。

### gitleaks はプレビルドを使う

pre-commit の gitleaks フックは、公式リポジトリ（`language: golang`）ではなく
`mise exec -- gitleaks` を呼ぶローカルフックにしている。版は `mise.toml` の
`gitleaks` が正本。

公式フックは、初回にフック環境を作るとき Go のツールチェーンを落として
gitleaks を**ソースからビルド**する。Raspberry Pi 4（RAM 3.7GB、swap 0）では
このビルドでメモリが尽き、SSH も応答しなくなって電源の抜き差しが要った
（2026-09-26）。mise なら GitHub Releases のバイナリを落とすだけで済む。
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
約 9 分かかる（2026-10-22 実測 556 秒）。CI で全件を回す件は
[テストと検証の仕組み](testing.md#いつ回すか) に未着手の候補として書いた。

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

`pre-push` hook に全件は入れない。待ち時間が `--no-verify` を誘い、`AGENTS.md` の
「長時間実行スクリプトは追加しない」とも合わない。選択実行に限れば入れてよい。

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
（実測）。README の `Set-ExecutionPolicy` の行は、`Restricted` のままだと `chezmoi` が `.ps1` の
run スクリプトを実行できないために必要（実測）だが、この検証はその行が無くても通る。

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
- 会社 PC のプロキシや制限は再現しない。WSL の機能有効化は再起動が要るので、警告で終わる想定

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
| Linux | 各スクリプトの先頭の `sudo -v` が端末で尋ねる |

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
