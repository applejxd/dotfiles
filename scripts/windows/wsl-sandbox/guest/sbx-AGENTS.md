# @HOST@ 利用ガイド(agent 向け)

AI OSS の動作確認用に隔離した環境(Windows 上の専用 WSL2 / Ubuntu 24.04、Docker Engine + NVIDIA GPU)。
GPU の種類は `nvidia-smi` で確認する。コンテナのメモリ上限は @MEMORY@。Windows のファイルは見えない。

## 基本ルール

- コンテナは必ず `sbx-run` で起動する。`docker run` を直接叩かない。
- `sbx-run [--net=none|bridge] [--root] <image> [command...]`
  - 既定は `--network none`(外部通信なし)。通信が必要な作業だけ `--net=bridge`。
  - 既定はコンテナ内でも一般ユーザー(@USER@ の uid/gid)。root が要る場合のみ `--root`。
  - 付与される制限: `--gpus all --cap-drop ALL --no-new-privileges --pids-limit 512 --memory @MEMORY@`。
  - docker オプションは渡せない(`-p`、`--privileged`、`--network host`、`-v` など)。
- ホスト側 `/home/@USER@/work` がコンテナの `/work`(作業ディレクトリ)に常にマウントされる。成果物は `/work` に書く。

## 典型的な流れ

1. 通信が要る準備(イメージ取得、モデル・依存の取得)を `--net=bridge` で実行し、`/work` に保存する。
   - イメージ取得: `docker pull <image>`(取得だけなら直接 docker で可)。
2. 本実行は既定の `--network none` で行う(外部に出さない)。
3. 結果は `scp @USER@@@HOST@:/home/@USER@/work/<file> .` で取得する。

## web サービスの確認

- ポート公開はできない(`-p` は渡せない)。web UI / API の確認は、同じコンテナ内で行う。
  - 例: `sbx-run <image> bash -c '<サービス起動> & sleep 10; curl -s http://127.0.0.1:<port>/'`
  - 起動したままにせず、1 回のコマンド内で起動・確認・終了させる。
- 画面確認はコンテナ内で Playwright 等によりスクリーンショットを `/work` に保存し、`scp` で取得する。

## 状態確認と掃除

- `docker ps -a`、`docker images`、`docker system df`、`nvidia-smi`
- 不要物: `docker image prune -a`、`docker system prune`、`/home/@USER@/work` の整理。

## 禁止・注意

- 特権コンテナ、`--network host`、ポート公開、ホスト(Windows)側への操作はしない。
- 実行にはほぼ root 権限は不要。sudo は使えない。
- 判断に迷う操作(長時間の GPU 占有、大量のディスク使用)は、実行前にユーザーへ確認する。
