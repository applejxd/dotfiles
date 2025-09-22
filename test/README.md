# chezmoi リポジトリ検証（Docker 実行メモ）

このメモは、コンテナ内のクリーンな `$HOME` に対して **chezmoi リポジトリを安全に検証**するための手順です。  
`docker compose run` により毎回新規環境で `diff` →（必要に応じて）`apply` を実行できます。

> すべてのコマンドは **リポジトリ直下**で実行してください。

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

### 3.3 デバッグシェル（手動でコマンドを試す）
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
- `CHEZMOI_ARGS`：`chezmoi diff/apply` に渡す追加引数

```bash
# 例：タグで Linux のみ含める + apply 実行
CHEZMOI_ARGS="--include tag=linux" APPLY=1 ./test.sh apply

# 例：macOS を除外し dry-run（diff のみ）
CHEZMOI_ARGS="--exclude tag=darwin" ./test.sh

# 例：特定ファイル/グループに限定（定義に応じて調整）
CHEZMOI_ARGS="--include files=.bashrc" ./test.sh
```

---

## 5. 実行の流れ（内部で行っていること）

`run_chezmoi` スクリプト（コンテナ内 `/usr/local/bin/run_chezmoi`）は以下を順に実行し、各ステップの成功/失敗を記録します。

1. **環境情報表示** - ユーザー、HOME、chezmoi/gitバージョン
2. **`chezmoi doctor`** - 環境診断（警告は非致命的として処理）
3. **`chezmoi init --source=/repo`** - ホストリポジトリを読み取り専用でマウントして初期化
4. **`chezmoi diff [${CHEZMOI_ARGS}]`** - 差分確認
   - Exit code 0: 差分なし（成功）
   - Exit code 1: 差分あり（正常、成功として扱う）
   - Exit code > 1: 実際のエラー（失敗）
5. **`APPLY=1` のとき `chezmoi apply --keep-going -v [${CHEZMOI_ARGS}]`** - 設定適用 → 再度 `doctor`
6. **実行サマリー表示** - 各ステップの結果と最終的な成功/失敗判定

### 改善された機能

- **事前チェック**: Docker/Docker Compose の動作確認、compose.yaml の存在確認
- **エラーハンドリング**: `|| true` の多用を避け、適切なエラー判定を実装
- **実行結果追跡**: 各ステップの成功/失敗を記録し、最終サマリーで表示
- **変数の安全性**: `CHEZMOI_ARGS` を引用符で囲み、スペースを含む引数に対応

> `$HOME` は `tmpfs` マウントで毎回クリーンです（`compose.yaml` 既定）。

---

## 6. よく使うレシピ

- **Linux のみ検証**：
  ```bash
  CHEZMOI_ARGS="--include tag=linux" ./test.sh
  ```
- **macOS 除外**：
  ```bash
  CHEZMOI_ARGS="--exclude tag=darwin" ./test.sh
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
  → タグで範囲を絞る（`CHEZMOI_ARGS`）と負荷を抑えられます。

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