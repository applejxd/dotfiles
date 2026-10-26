# 専用 WSL2 の時刻同期の実測

`docs/spec/sandbox/wsl-sandbox.md#時刻同期` と `docs/spec/sandbox/wsl-sandbox.md#検証の状況` から移した記録。移設時点で再測定していない。

> **現行の仕様**: [隔離 GPU サンドボックス（WSL2）](../../spec/sandbox/wsl-sandbox.md)。一般的な時刻同期の運用は [構成](../../spec/platform-wsl.md#wsl-の時刻同期)。

## 記録 E1 — 2026-10-18〜19 の時刻同期の実測

- **観測日**: 2026-10-18、2026-10-19（元の文の日付）
- **環境**: WSL2（mirrored）、Ubuntu と専用ディストロ `sandbox`

### 問い

専用ディストロだけで `systemd-timesyncd` を止めれば、`tick` の偏りは防げるか。

### 結果（元の文）

> **これだけでは不十分**（2026-10-19 の実測）。この環境では `timesyncd` が**1 つだけ**動いていても `tick` が偏った。
> 安定したのは「**すべてのディストロで `timesyncd` を止めた**」ときだけ。メインのディストロ側は `120_wsl` が同じ設定を入れる
> （[WSL の時刻同期](../../spec/platform-wsl.md#wsl-の時刻同期)）。

- 理由: WSL2 の全ディストロは同じ VM・同じカーネルの時計を共有する。`timesyncd` が動いていると、`adjtimex` の `tick` が偏る。
  2 つのディストロで動かすと持続的に約 2% 偏り（標準 10000 に対して 9800 前後）、1 つだけでも数分後に 9629〜10076 へ揺れた。
  `tick` が偏ると `CLOCK_MONOTONIC` と `CLOCK_BOOTTIME` が遅れる（調整を受けない `CLOCK_MONOTONIC_RAW` と Windows の時刻は一致していた）。
  `timesyncd` は壁時計を約 0.6 秒ずつステップ補正するので、「壁時計 − 単調時計」が増え続け、
  psutil の `create_time` が時間とともにずれる。これにより、プロセスの生死を `create_time` の厳密一致で判定する
  アプリで、生きているプロセスが「死んだ」と誤判定される。観測した例は、dockers リポジトリの FreeVideo（常駐サービス経由の動画生成が
  起動の数十秒後に失敗する）。ホスト側の時刻同期（`hv_utils`）と `timesyncd` が同じ時計を制御していることが原因、と**推測**している（未確認）
- 根拠（dockers リポジトリ（別リポジトリ）の freevideo-install-and-generation の記録 E2〜E5）: 2026-10-18、
  Ubuntu と sandbox の両方で `timesyncd` を止めて `tick` を 10000 へ戻すと、`tick` は維持され、`create_time` が一致し、
  サーバー経由の生成が成功した。Ubuntu 側だけを止めても、約 60 秒後に `tick` が戻った。
  2026-10-19、sandbox を mask して Ubuntu 側だけ動かすと、約 5 分後に `tick` が偏り始め、405 秒で `CLOCK_MONOTONIC` が RAW より 1.075 秒遅れた
- 時刻はホスト側の同期（`hv_utils`）に任せる。**すべてのディストロで止めた状態で、壁時計が長時間正確に保たれるかは未確認**
  （区間の経過時間の比較はしたが、絶対的なずれの長期測定はしていない）

### 考察

結論（全ディストロで止める）は spec 側にある。ホスト側の同期（`hv_utils`）と `timesyncd` が同じ時計を制御していることが原因というのは推測で、未確認。

## 記録 E2 — 構築の記録

- **観測日**: 2026-10-17（元の文の日付）

### 結果（元の文）

- 手順は 2026-10-17 に手作業で構築して確かめた（RTX 3070、ドライバ 610.88、Docker 29.9.1、nvidia-container-toolkit 1.20.1、Tailscale 1.104.1。
  Raspberry Pi からの `ssh sbx@sandbox-gpu docker info` を含む）。
