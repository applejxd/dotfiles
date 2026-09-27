# テストと検証の仕組み

テストの種類と実行の入口は [test/README.md](../../test/README.md)、
変更ごとに回すコマンドは [開発ガイド](development.md#3-手動実行とテスト) にある。
ここには、Docker ハーネスのモード・環境変数・判定の契約と、
GitHub Actions で見ている範囲を書く。

解決済みの障害の経緯は
[Docker の cold start 検証で直した障害](../research/testing/docker-cold-start-fixes.md) にある。

## Windows / PowerShell のテスト

実行するコマンド、対話テストが実プロファイルを読み込む仕組み、実機でしか拾えない
範囲は [Windows 実機での検証](development.md#windows-実機での検証) を参照。

対話テストがプロンプト到達後に確認するのは、起動エラー、OnIdle ジョブのエラー、
PSReadLine / PSFzf / ZLocation と基本コマンドである。
`chezmoi update` / `chezmoi apply` はテスト内で実行しないため、変更した設定は事前に適用する。
Windows 以外、または `pywinpty` 未指定の場合は対話テストをスキップする。

プロファイル本体は `~/.config/powershell/profile.ps1` で、`$PROFILE`
（`Documents/PowerShell` と `Documents/WindowsPowerShell`）は dot-source するだけのローダーである。
起動時間の切り分けには `-NoProfile` との差を見る。`mise` の init は
`%LOCALAPPDATA%\PowerShellProfileCache` にキャッシュされるため、
再生成の挙動を試すときはこのディレクトリを削除する。`oh-my-posh` の init は
テーマ設定がセッションごとに登録されるためキャッシュせず、毎起動で実行する。

agent テストの `--no-project` 実行では、スキル frontmatter 検証用の `pyyaml` も必要。
長大入力のテストには短い ID を付け、Windows の `PYTEST_CURRENT_TEST` 環境変数の
32,767 文字制限を超えないようにする。

pre-commit が実際には変更していないのに `files were modified by this hook` と報告し、
Git が `missing config value GIT_CONFIG_VALUE_N` で失敗する場合は、
`chezmoi apply` 後に PowerShell 7 を開き直す。
Python の Windows 環境変数復元処理は空文字列を削除してしまうため、プロファイルは
空の `core.fsmonitor` だけを同じ無効状態の `false` に置き換える。
その他の有効な Git 設定は保持する。

Windows の Copilot コマンド hook は `powershell` ツール名も照合・正規化する。
agent テストでは生成された matcher と実 hook の判定を両方確認し、
パスの `\` 区切りや大文字小文字によって既存の保護対象が見落とされないことも検証する。

## Windows の GitHub Actions

`.github/workflows/windows.yml` が `windows-2025` の runner で `test/agents/` と
`test/test_windows_assets.py` を回す。Windows 関連のパス（`*.ps1`、PowerShell と
OpenCode の設定、`300_windows/`、共有テンプレート、agent 設定・hook、`scripts/agents/`、
対象のテスト）への push と、手動実行で起動する。

pytest は `PYTHONUTF8=1` で回す。本番の hook は `py -3 -B -X utf8` で起動するので
（`scripts/agents/generate.py`）、テストが起動する hook もそれに揃えるため。
揃えないと hook が日本語の理由を cp1252 で書けずに落ち、JSON が途中で切れる。

**実機（Windows 11）の検証の代わりにはならない。** 見ていないもの:

- 対話テスト（`test_powershell_interactive.py`）。配置済みのプロファイルと
  mise / fzf / oh-my-posh などが要るので回していない
- `.chezmoiscripts` の実行（winget / scoop / choco / レジストリ / 電源設定）。
  runner は管理者で UAC が無効、Chrome・Git・Node などが最初から入っていて導入漏れを
  隠し、Windows Server なので Windows 11 とも違う
- 個人用（applejxd）の分岐。runner のユーザは `runneradmin`

runner は英語版で、Python の既定の文字コードは cp1252 になる。テストの
`subprocess.run(..., text=True)` は `encoding="utf-8"` を必ず明示する
（省くと chezmoi の日本語出力を読めず、終了コード 0 のまま `stdout` が `None` になる）。
`test_windows_assets.py` が構文木で検査している。

runner は checkout 時に改行を CRLF にする（`core.autocrlf`）。modify script の共通ラッパー
（`home/.chezmoitemplates/modify_json.py.tmpl`）は、埋め込んだ common.toml を
`newline=""` で書き出す。既定の改行変換だと `\r\r\n` になり、TOML として読めずに
すべての modify script が落ちる（Windows の runner で発覚。autocrlf を有効にした
Windows の機械でも同じことが起きる）。

## Docker での cold start 検証

**新しい機械で `chezmoi apply` が人手を介さず完走するか**を、実機を汚さずに試す。
頻度は低くてよい。回すきっかけは AGENTS.md と下の「[いつ回すか](#いつ回すか)」を参照。

### 要件

- Docker Engine v24 以上 / Docker Compose V2
- コンテナから外部への接続（外部 CLI を取りに行くため）
- arm64 サービスを使うなら QEMU（`docker buildx ls` で `linux/arm64` が出ること）

### 使い方

```bash
bash test/test.sh [service] [mode]
mise run e2e -- [service] [mode]    # 同じもの
```

実行ごとに `.tmp/e2e/<日時>-<service>-<mode>.log` を残し（先頭に commit・未コミットの
ファイル数・環境変数）、`.tmp/e2e/history.tsv` に所要秒数と判定を 1 行ずつ追記する。
`shell` モードは記録しない。

**リポジトリ直下から実行する。** 引数は順不同。

| service | 中身 | 用途 |
| --- | --- | --- |
| `ubuntu2404`（既定） | Ubuntu 24.04 / amd64 | 最短で「壊れていないか」を見る |
| `ubuntu2204` | Ubuntu 22.04 / amd64 | 実機 Pi と同じディストリ。system python が 3.10 |
| `raspi2204` | Ubuntu 22.04 / **arm64** | 実機 Pi に最も近い。既定で `IS_RASPI=1` |
| `arm2404` | Ubuntu 24.04 / **arm64** | arm64 のバイナリ配布と依存解決だけ見たいとき |

| mode | 中身 | 所要 |
| --- | --- | --- |
| `dryrun`（既定） | doctor と `chezmoi diff` まで | 数十秒 |
| `place` | `--exclude scripts` で apply。配置だけ見る | 数十秒 |
| `apply` | スクリプト込みの cold start | 十数分 |
| `update` | init を省いて apply を 2 回。冪等性と残差分を見る（`chezmoi update` の経路） | 十数分 |
| `bootstrap` | ユーザ applejxd で apply した後、bw のスタブで 2 フェーズ bootstrap を見る（[後述](#bootstrap-モード)） | 20 分前後 |
| `shell` | コンテナへ入る | — |

```bash
bash test/test.sh                            # 既定で dry-run
bash test/test.sh ubuntu2204 place           # 22.04 で配置だけ
APPLY_TIMEOUT=5400 bash test/test.sh raspi2204 apply  # 実機 Pi に近い構成で cold start (arm64 は遅い)
IS_RASPI=1 bash test/test.sh ubuntu2204 place  # 22.04 を Pi 扱いで
```

**`dryrun` / `place` は diff の前に `run_before_005_python` だけを走らせる**
（`PREPARE_PYTHON=1`）。Docker の素のイメージには Python が無く、どちらのモードも
`.chezmoiscripts` を走らせないので、そのままでは modify script 用の Python
（005 が張る shim）が無く `chezmoi diff` の段で必ず失敗する。実際の apply と
同じ順序（`run_before_` が先）を再現する形で、uv が Python を取りに行くので
回線に依存する。取得できなければ `prepare-python: UNDETERMINED` で止まる。

### 環境変数

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `APPLY` | `0` | `1` で apply まで実行 |
| `IS_RASPI` | `0`（`raspi2204` のみ `1`） | `1` で Raspberry Pi 扱いを注入 |
| `SOURCE_MODE` | `clone` | `mount` にすると未コミットの変更ごと検証 |
| `INCLUDE_DIRTY` | `0` | `1` で clone に未コミットの変更（追跡ファイル分）を載せる |
| `PREPARE_PYTHON` | `0`（`dryrun` / `place` は `1`） | `1` で diff の前に 005 だけ走らせる |
| `APPLY_TIMEOUT` | `900` | apply 1 回あたりの上限（秒）。arm64 のエミュレーションでは延ばす |
| `CHEZMOI_TEST_ARGS` | 空 | `diff` / `apply` への追加引数 |

> `CHEZMOI_ARGS` は**使えない**。chezmoi 自身が予約しており、`chezmoi cd` の
> サブシェルでは `CHEZMOI_ARGS="chezmoi cd"` が export されている。

### bootstrap モード

新しい機械の手順（[セキュリティ](security.md) の「2 フェーズ bootstrap」）を
再現する。Bitwarden（`bw`）は `test/bw-stub.sh` で置き換え、本物の Vault には触れない。

| フェーズ | 操作 | 合格条件 |
| --- | --- | --- |
| 1 | `BW_SESSION` 無しで init + apply | `~/.config/git/user` と `~/.config/sops/age/keys.txt` が**作られない** |
| 2 | スタブを PATH の先頭に置き、`BW_SESSION` を設定して init + apply | 2 つのファイルにスタブの値が入る |
| 3 | `BW_SESSION` 無しで apply と diff | 残差分 0 件で、**スタブが呼ばれない**（Bitwarden を引き直さない） |

- Bitwarden を使うファイルは個人用でしか展開しないので、コンテナのユーザを
  `applejxd` にする（`CONTAINER_USER=applejxd`。`bootstrap` モードが自動で設定する）。
  そのため個人用の分岐（Copilot との herdr 連携、MCP の除外など）も通る
- スタブは `bw status` / `unlock` / `lock` / `sync` / `get item <名前>` だけに答え、
  知らない呼び方は失敗させる。呼ばれた引数はログに残す
- 値はすべてダミー。age の鍵も `AGE-SECRET-KEY-` の形にしない（gitleaks の誤検知を避ける）。
  apply 中に sops の復号は走らないので、中身が鍵として無効でも困らない
- 見られるのは「テンプレートと除外条件が 2 フェーズの流れで正しく動くか」まで。
  本物の `bw` の出力形式が変わっても検出できない

### GitHub Actions

`.github/workflows/e2e.yml` が同じ `test/test.sh` を GitHub の runner で回す。
毎 push では回さない。

| きっかけ | 対象 |
| --- | --- |
| 毎月 2 日 03:00 JST（`schedule`） | `ubuntu2204 update` と `raspi2204 update` |
| Actions 画面の **Run workflow**（`workflow_dispatch`） | サービスとモードを選ぶ |

```bash
gh workflow run e2e -f service=raspi2204 -f mode=update   # 手元から起動する場合
```

- arm64 のサービス（`raspi2204` / `arm2404`）は `ubuntu-24.04-arm` の runner で
  **エミュレーション無しに**動く（公開リポジトリは無料）。`raspi2204 update` は
  約 3 分で終わった（手元の QEMU では apply 1 回に約 25 分）。arm64 を見るなら
  こちらが速い
- runner は WSL ではない素の Ubuntu なので、WSL2 ホストの Docker では見られない
  「WSL ではない Linux」の経路もここで見られる
- `APPLY_TIMEOUT` は 2700 秒、ジョブの上限は 120 分
- ログ（`.tmp/e2e/`）は artifact に 30 日残り、判定の一覧はジョブの Summary に出る
- runner は IP を共有するので、認証なしの GitHub API はすぐ上限（1 時間 60 回）に
  当たる。mise には `MISE_GITHUB_TOKEN` にジョブのトークン（読み取りのみ）を渡して
  避けている（compose はホストに変数があるときだけコンテナへ引き継ぐ）。
  mise 以外の導入スクリプトには渡していないので、それらが上限に当たったら再実行する

## Docker ハーネスの設計上の約束（崩さないこと）

### ソースは既定で clone する

`/repo` は読み取り専用でマウントするが、**既定ではそこから `git clone` して
追跡ファイルだけを使う**（`SOURCE_MODE=clone`）。理由は 3 つ。

- 新 PC が実際に受け取るものと同じになる
- ローカルの汚れ（`.venv`、壊れた symlink）を持ち込まない
- **`git add` し忘れ**を検出できる

未コミットの変更を試したいときだけ `SOURCE_MODE=mount` にする。

`/repo` はホストの UID が所有するが、`ubuntu:24.04` は UID 1000 に `ubuntu`
ユーザが既にいるので `tester` は別の UID になり、git が dubious ownership で
拒む。`~/.gitconfig` は検証対象なので `safe.directory` を書かず、`$HOME` 外の
一時ファイルを `GIT_CONFIG_GLOBAL` で `/repo` を読む git にだけ渡す。
`git -c safe.directory=...` は clone の所有者検査まで届かない（git 2.43 で実測）。
`userdel ubuntu` でイメージ側を合わせる案は、ホスト UID との一致に依存するので採らない。

### 失敗を握り潰さない

設定テンプレートの描画に失敗したら、そこで止める。以前は代替 config を書いて
続行していたが、これは**検出したい不具合そのものを隠す**（`*/` でコメントが
壊れた事故が実際にあった）。

### 依存を先入れしない

`Dockerfile` には「素の機械に最初からあるもの」だけを入れる。`zsh` などを
先に入れると、それを導入するはずの `.chezmoiscripts` が no-op になり、
依存漏れを隠す。

### Raspberry Pi の自動判定は再現できない

**コンテナはホストのカーネルを共有する。** `uname -r` はホストの値が出るし、
`/proc/device-tree/model` も無い。arm64 エミュレーションでも同じ。
そのため `raspi2204` は `IS_RASPI=1` で**判定を注入**して、分岐の「帰結」だけを見る。

判定ロジックそのものは `test/test_raspi_detection.py` が検証する（Docker 不要、3 秒）。

### WSL ホストでは素の Linux を再現できない

同じ理由で、WSL2 上の Docker では**どのサービスも WSL 扱い**になる。
`.chezmoiignore.tmpl` はカーネル名に `microsoft` が含まれるかで WSL を見分けるため、
`120_wsl.sh` などが走る。WSL ではない Linux の経路は、素の Linux ホストの Docker か
実機、または GitHub Actions で見る。たとえば `110_native/`（VS Code など）は
WSL と Raspberry Pi では除外されるので、手元の Docker では一度も走らない。

### systemd は無い

コンテナの PID 1 は systemd ではないので、`systemctl` は失敗する。
`121_ubuntu.sh` は `/run/systemd/system` が無ければ、Pi の節（earlyoom / zramswap）と
個人用の節（ClamAV。定義の更新も含む）のサービス操作を飛ばす。
`sysctl -p` も読み取り専用の `/proc/sys` に書けず警告を出すが、止まらない。

## 結果の読み方

`run_chezmoi` は各段の成否を記録し、最後にサマリーを出す。

```text
[19:16:01] clone: SUCCESS (ef7d476)
[19:16:01] config-template: SUCCESS
[19:16:02] diff: FAILED (exit code: 1)
OVERALL STATUS: FAILED
```

**失敗を「環境都合」と「リポジトリの不具合」に即断で二分しない。**
タイムアウト（`APPLY_TIMEOUT`、既定 900 秒）や tmpfs の上限（8GB）に当たった場合は、
合否ではなく「未判定」として扱う。ruby は単独で 956 秒かかった実績がある。

| 段の状態 | 意味 | 総合判定への影響 |
| --- | --- | --- |
| `SUCCESS` / `SKIPPED` / `WARNING` | 問題なし | なし |
| `DEFERRED` | 判定を後段（apply）に委ねた | なし |
| `UNDETERMINED` | 環境の限界で判定できない | `UNDETERMINED`（終了コード 2） |
| `FAILED` | 不具合 | `FAILED`（終了コード 1）。最優先 |

総合判定が `UNDETERMINED` のときは、打ち切りまでのログに出た `chezmoi:` の
エラーを別途確認する。打ち切りが先に来ると、スクリプトの失敗が判定に出ない。

`update` モードの `residual-diff` はファイルだけを見る（`--exclude scripts`）。
毎回走るスクリプト（`run_before_005_python` など）は常に差分に出るためで、
スクリプトの成否は `apply` / `apply-2nd` の終了コードで判定している。

### 環境都合と切り分けるもの

次は**リポジトリの不具合ではない**。合否ではなく「未判定」として扱う。

| 症状 | 実体 |
| --- | --- |
| `no space left on device` | tmpfs の上限。`$HOME` 使用率 95% 以上なら UNDETERMINED にする |
| apply が上限（`APPLY_TIMEOUT`、既定 15 分）で打ち切り | 回線速度か arm64 のエミュレーション。実測で mise の取得が 23〜145 kB/s まで落ちた |
| `導入できなかった CLI:claude` | ネットワークか GitHub のレート制限 |

## いつ回すか

頻度ではなく、きっかけで決める。

- `.chezmoiscripts/` にファイルを足した / 番号順を変えた
- `.chezmoi.toml.tmpl`・`.chezmoitemplates/`・`mise/config.toml.tmpl` を触った
- 新しいマシンを組む直前
- 半年以上回していないと気づいたとき（腐敗の検知そのもの）

## 既知の未達

`ubuntu2204` の `apply` と `update`（2 回の apply と残差分 0 件）は通る
（2026-09-27 時点。そこへ至るまでに直したものは
[記録](../research/testing/docker-cold-start-fixes.md)）。

### 未着手

- 2 フェーズ bootstrap の本物の `bw` での確認（`bootstrap` モードはスタブで流れだけを見る）
- `arm2404`（arm64、Pi 扱いなし）での `apply`

### 未検証のまま残っているもの

- Windows の `346`（Claude の MCP 登録）が `claude` を公式の導入先から探す修正は、
  静的テストのみで実機では未確認
- Codex の `modify_config.toml`: ユーザのトップレベルのキーが 1 つも無い状態で
  Codex 自身が新しいトップレベルのキーを書き込むと、最後のトップレベルのキー
  （管理側）の直後、つまり管理ブロックの内側に入るおそれがある。
  その場合は次の apply で消える（従来と同じ）

[仕様一覧へ戻る](index.md)
