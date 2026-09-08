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

## 1. 要件

- Docker Engine（推奨: v24 以上）
- Docker Compose V2（`docker compose` コマンドが使えること）
- ネットワークが必要な外部取得のためコンテナから外部へ接続可能であること

---

## 2. 初回セットアップ

```bash
# 実行権限の付与（初回のみ）
chmod +x test.sh run_chezmoi.sh

# イメージのビルド
docker compose build
```

> UID/GID をホストに合わせたい場合は、`compose.yaml` の `build.args` を有効化し
> `docker compose build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g)` を利用してください。

---

## 3. 典型的な実行

### 3.1 ドライラン（差分と doctor の確認のみ）

```bash
./test.sh
```

### 3.2 実適用（コンテナ内の `$HOME` に apply）

```bash
./test.sh apply
```

> `.chezmoiscripts` は外部 CLI をネットワーク経由で入れるため、
> インストーラ側の対話プロンプトやバージョン検証で失敗することがあります。
> ファイルの展開だけを見たい場合は scripts を外してください。
>
> ```bash
> CHEZMOI_TEST_ARGS="--exclude scripts" ./test.sh apply
> ```

### 3.3 hook の配備と判定の検証

`chezmoi` が展開した hook が、新規環境でも実際に deny / pass を返すか確認します。

```bash
docker compose -f test/compose.yaml run --rm chezmoi bash /repo/test/verify_hooks.sh
```

配備されたファイル、`settings.json` に登録された hook の数、
代表的なコマンドに対する判定を検査し、期待と違えば非ゼロで終了します。

### 3.4 デバッグシェル（手動でコマンドを試す）

```bash
./test.sh shell
# 例：コンテナ内で
# run_chezmoi           # 既定動作
# APPLY=1 run_chezmoi   # その場で apply まで実行
```

---

## 4. オプション（環境変数）

`test.sh` 実行時に環境変数を前置して挿入できます。

- `APPLY`：`0`（既定, dry-run）/ `1`（apply 実行）
- `CHEZMOI_TEST_ARGS`：`chezmoi diff/apply` に渡す追加引数

> **注意**: `CHEZMOI_ARGS` は使えません。chezmoi 自身が予約しており、
> `chezmoi cd` のサブシェルでは `CHEZMOI_ARGS="chezmoi cd"` が export されています。
> この名前を使うと、そのまま `chezmoi diff` の引数として渡ってテストが失敗します。

```bash
# 例：タグで Linux のみ含める + apply 実行
CHEZMOI_TEST_ARGS="--include tag=linux" APPLY=1 ./test.sh apply

# 例：macOS を除外し dry-run（diff のみ）
CHEZMOI_TEST_ARGS="--exclude tag=darwin" ./test.sh

# 例：特定ファイル/グループに限定（定義に応じて調整）
CHEZMOI_TEST_ARGS="--include files=.bashrc" ./test.sh
```

---

## 5. 実行の流れ（内部で行っていること）

`run_chezmoi` スクリプト（コンテナ内 `/usr/local/bin/run_chezmoi`）は以下を順に実行し、各ステップの成功/失敗を記録します。

1. **環境情報表示** - ユーザー、HOME、chezmoi/gitバージョン
2. **`chezmoi doctor`** - 環境診断（警告は非致命的として処理）
3. **`chezmoi init --source=/repo`** - ホストリポジトリを読み取り専用でマウントして初期化
4. **source 解決チェック** - `chezmoi source-path` が `/repo` 配下を指すことを確認
   - `chezmoi init` は `.chezmoi.toml.tmpl` から設定を再生成するため、設定ファイルに
     書いた `sourceDir` は失われる。全 chezmoi 呼び出しで `--source=/repo` を明示している
   - ここが壊れると「差分なし」に見えてテストが偽陽性になるので、失敗時は即中断する
5. **`chezmoi diff [${CHEZMOI_TEST_ARGS}]`** - 差分確認
   - Exit code 0: 正常終了（差分の有無は出力の `diff --git` 行数で判定）
   - Exit code != 0: エラー（失敗として中断。stderr も表示する）
6. **`APPLY=1` のとき `chezmoi apply --keep-going -v [${CHEZMOI_TEST_ARGS}]`** - 設定適用 → 再度 `doctor`
7. **実行サマリー表示** - 各ステップの結果と最終的な成功/失敗判定

### 改善された機能

- **事前チェック**: Docker/Docker Compose の動作確認、compose.yaml の存在確認
- **エラーハンドリング**: `|| true` の多用を避け、適切なエラー判定を実装
- **実行結果追跡**: 各ステップの成功/失敗を記録し、最終サマリーで表示
- **変数の安全性**: `CHEZMOI_TEST_ARGS` を配列に展開し、スペースを含む引数に対応
- **偽陽性の防止**: `chezmoi diff` の stderr を捨てずに判定材料とし、source 解決も検証する

> `$HOME` は `tmpfs` マウントで毎回クリーンです（`compose.yaml` 既定）。

---

## 6. よく使うレシピ

- **Linux のみ検証**：

  ```bash
  CHEZMOI_TEST_ARGS="--include tag=linux" ./test.sh
  ```

- **macOS 除外**：

  ```bash
  CHEZMOI_TEST_ARGS="--exclude tag=darwin" ./test.sh
  ```

- **即時適用で挙動確認**：

  ```bash
  APPLY=1 ./test.sh apply
  ```

- **手動で段階確認**：

  ```bash
  ./test.sh shell
  # コンテナ内で
  run_chezmoi
  APPLY=1 run_chezmoi
  ```

---

## 7. トラブルシュート

- **`compose.yaml` が見つからない/ボリュームが空**
  → コマンドを **リポジトリ直下**で実行しているか確認してください（`pwd` を確認）。
  → `docker compose ls` / `docker compose config` で解決に役立つ情報を表示できます。

- **`permission denied: test.sh`**
  → `chmod +x test.sh` を付与してください。

- **`chezmoi` が見つからない**
  → イメージを再ビルドしてください：`docker compose build --no-cache`

- **apply が重く時間がかかる/外部取得が走る**
  → まずは `./test.sh`（dry-run）で差分を把握してから `APPLY=1` を検討してください。
  → タグで範囲を絞る（`CHEZMOI_TEST_ARGS`）と負荷を抑えられます。

- **一時的に `$HOME` を保持して再現性検証したい**
  → `compose.yaml` の `tmpfs` マウントをコメントアウトし、代わりに named volume を設定してください（例：`home_data:/home/tester`）。
  → その際、末尾に `volumes: { home_data: {} }` を追加します。

---

## 8. クリーンアップ

本構成は `docker compose run --rm` でコンテナを都度破棄します。残るのはイメージのみです。
ビルドキャッシュや未使用イメージを削除する場合：

```bash
docker image prune -f
# さらに徹底する場合（注意）
docker system prune -af
```

---

## 9. 補足

- `run_chezmoi.sh` のロジックを編集すれば、`state` のダンプや `apply` 前後の追加チェックなども容易に拡張できます。
- OS やディストリ間差分を見たい場合は、`Dockerfile` のベースイメージを差し替えてビルドしてください（例：`debian:12`, `fedora:40` など；必要に応じてパッケージ名を調整）。

---
