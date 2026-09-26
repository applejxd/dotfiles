# chezmoi リポジトリ検証（Docker 実行メモ）

このメモは、コンテナ内のクリーンな `$HOME` に対して **chezmoi リポジトリを安全に検証**するための手順です。
`docker compose run` により毎回新規環境で `diff` →（必要に応じて）`apply` を実行できます。

> すべてのコマンドは **リポジトリ直下**で実行してください。

## Windows / PowerShell の検証

```powershell
uv run --with pytest --with pyyaml --no-project pytest test\agents\ -q
uv run --with pytest --with pywinpty --no-project pytest test\test_windows_assets.py test\test_powershell_interactive.py -q
uv run pre-commit run --all-files
```

対話テストは **配備済みの実プロファイル**を PowerShell 7 と Windows PowerShell 5.1
の ConPTY セッションで読み込み、プロンプト到達後の起動エラー、OnIdle ジョブのエラー、
PSReadLine / PSFzf / ZLocation と基本コマンドを確認する。
`chezmoi update` / `chezmoi apply` はテスト内で実行しないため、変更した設定は事前に適用する。
Windows 以外、または `pywinpty` 未指定の場合は対話テストをスキップする。

プロファイル本体は `~/.config/powershell/profile.ps1` で、`$PROFILE`
（`Documents/PowerShell` と `Documents/WindowsPowerShell`）は1行のローダーである。
起動時間の切り分けには `-NoProfile` との差を見る。`mise` / `oh-my-posh` の init は
`%LOCALAPPDATA%\PowerShellProfileCache` にキャッシュされるため、
再生成の挙動を試すときはこのディレクトリを削除する。

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

---

## 1. Docker での cold start 検証

**新しい機械で `chezmoi apply` が人手を介さず完走するか**を、実機を汚さずに試す。
頻度は低くてよい。回すきっかけは AGENTS.md と下の「いつ回すか」を参照。

### 要件

- Docker Engine v24 以上 / Docker Compose V2
- コンテナから外部への接続（外部 CLI を取りに行くため）
- arm64 サービスを使うなら QEMU（`docker buildx ls` で `linux/arm64` が出ること）

### 使い方

```bash
bash test/test.sh [service] [mode]
```

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
| `shell` | コンテナへ入る | — |

```bash
bash test/test.sh                            # 既定で dry-run
bash test/test.sh ubuntu2204 place           # 22.04 で配置だけ
bash test/test.sh raspi2204 apply            # 実機 Pi に近い構成で cold start
IS_RASPI=1 bash test/test.sh ubuntu2204 place  # 22.04 を Pi 扱いで
```

### 環境変数

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `APPLY` | `0` | `1` で apply まで実行 |
| `IS_RASPI` | `0`（`raspi2204` のみ `1`） | `1` で Raspberry Pi 扱いを注入 |
| `SOURCE_MODE` | `clone` | `mount` にすると未コミットの変更ごと検証 |
| `CHEZMOI_TEST_ARGS` | 空 | `diff` / `apply` への追加引数 |

> `CHEZMOI_ARGS` は**使えない**。chezmoi 自身が予約しており、`chezmoi cd` の
> サブシェルでは `CHEZMOI_ARGS="chezmoi cd"` が export されている。

## 2. 設計上の約束（崩さないこと）

### ソースは既定で clone する

`/repo` は読み取り専用でマウントするが、**既定ではそこから `git clone` して
追跡ファイルだけを使う**（`SOURCE_MODE=clone`）。理由は 3 つ。

- 新 PC が実際に受け取るものと同じになる
- ローカルの汚れ（`.venv`、壊れた symlink）を持ち込まない
- **`git add` し忘れ**を検出できる

未コミットの変更を試したいときだけ `SOURCE_MODE=mount` にする。

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

## 3. 既知の未達（2026-09-26 時点）

E2E はまだ完走しない。`update` モードまでは組み上がっている。

### 解決済み: tmpfs の `noexec`

`$HOME` の tmpfs に既定で `noexec` が付き、**そこへ入れた実行ファイルが一切
起動できなかった**。uv / mise / AI CLI はすべて `$HOME` 配下に入るので、
cold start は必ず失敗する。しかも症状が紛らわしい。

```text
installing to /home/tester/.local/bin
everything's installed!
⚠️  uv を導入できませんでした          ← ファイルは -rwxr-xr-x で存在する
```

`test -x` は `access(2)` を使うため、`noexec` の上では権限ビットがあっても
false を返す。`compose.yaml` の `tmpfs: - /home/tester:exec,...` で解消した。
**これはハーネスの欠陥であってリポジトリの不具合ではなかった。**

### 解決済み: `modify_` スクリプトが `python3` を解決できない

素の Ubuntu で apply すると `modify_` が全滅していた（残差分 16 件）。

```text
chezmoi: .claude/settings.json: exec: "python3": executable file not found in $PATH
```

順序の問題だった。`chezmoi init` が `[interpreters.py]` を焼く時点では
3.11 以上どころか `python3` すら無く、後から `run_before_005_python.sh.tmpl` が
uv で入れる Python は PATH に出ない。

固定パスの shim（`~/.local/bin/chezmoi-python3`）を挟んで解決した。
init 時に PATH 上で 3.11 以上が見つからなければ設定はこの shim を指し、
005 が毎 apply その実体へ張り直す（`run_before_` なので modify より先に走る）。
`python3` が 3.10 の Ubuntu 22.04 も同じ経路で救われる。

**実測で残差分 16 件 → 1 件**（残りはスクリプト 6 件で、これは diff に出るのが正常）。

### 環境都合と切り分けるもの

次は**リポジトリの不具合ではない**。合否ではなく「未判定」として扱う。

| 症状 | 実体 |
| --- | --- |
| `no space left on device` | tmpfs の上限。`$HOME` 使用率 95% 以上なら UNDETERMINED にする |
| apply が 15 分で打ち切り | 回線速度。実測で mise の取得が 145 kB/s まで落ちた |
| `導入できなかった CLI:claude` | ネットワークか GitHub のレート制限 |

### 未着手

- `apply` のフル実行を成功させること
- 2 フェーズ bootstrap（`bw login` は対話が要るので、無認証で通る範囲までしか見ていない）

## 4. いつ回すか

頻度ではなく、きっかけで決める。

- `.chezmoiscripts/` にファイルを足した / 番号順を変えた
- `.chezmoi.toml.tmpl`・`.chezmoitemplates/`・`mise/config.toml.tmpl` を触った
- 新しいマシンを組む直前
- 半年以上回していないと気づいたとき（腐敗の検知そのもの）

## 5. 結果の読み方

`run_chezmoi` は各段の成否を記録し、最後にサマリーを出す。

```text
[19:16:01] clone: SUCCESS (ef7d476)
[19:16:01] config-template: SUCCESS
[19:16:02] diff: FAILED (exit code: 1)
OVERALL STATUS: FAILED
```

**失敗を「環境都合」と「リポジトリの不具合」に即断で二分しない。**
タイムアウト（既定 900 秒）や tmpfs の上限（4GB）に当たった場合は、
合否ではなく「未判定」として扱う。ruby は単独で 956 秒かかった実績がある。

## 6. hook の配備と判定の検証

```bash
docker compose -f test/compose.yaml run --rm ubuntu2404 bash /repo/test/verify_hooks.sh
```

配備されたファイル、`settings.json` に登録された hook の数、代表的なコマンドに
対する判定を検査し、期待と違えば非ゼロで終了する。

## 7. クリーンアップ

`docker compose run --rm` でコンテナは都度破棄される。残るのはイメージのみ。

```bash
docker image prune -f
```
