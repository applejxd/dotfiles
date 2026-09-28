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

### スクリプトの無効化

一時的に全スクリプトを除外する場合：

```bash
chezmoi apply --exclude=scripts
```

恒久的に無効化する場合は、対象ファイルの `run_` 属性を外すか削除する。
`.tmpl` は実行属性ではないため、拡張子だけを外しても無効化されない。
