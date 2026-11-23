# t3-usage-status（ローカル）

T3 Code の中で動く pi に、キャッシュヒット率（CH%）・セッションの費用・コンテキスト使用率を出す。このリポジトリだけが配る自作で、OS を問わず入る。

```text
Pi · CH97.2% $24.480 ctx41.2% · sandbox: on · TPS 62 tok/s · TTFT 1.2s      T3 Code の入力欄のバナー (web・モバイル)
```

- **出すもの（この順）**: 最新の assistant のメッセージの CH%（`cacheRead / (input + cacheRead + cacheWrite)`）、セッションの費用の合計（`$X.XXX`）、コンテキスト使用率（`ctx41.2%`。`ctx.getContextUsage()`。圧縮の直後など不明なときは `ctx--`）。CH% と費用は pi の TUI のフッターと同じ計算。セッションにキャッシュの読み書きが無いときは CH を、費用が 0 のときは費用を省く。コンテキスト使用率の API が無い古い pi では ctx を省く（API があって値が取れないときは `ctx--`）。
- **並び順**: T3 は status を key ごとに、**最初に出した順**に並べ（`Pi · <text> · <text>`）、同じ key の更新は位置を保つ（[T3 の実装](https://github.com/pingdotgg/t3code/pull/23901)）。この拡張の key（`usage`）が先頭になるよう、空のセッションでも ctx を出す。`sandbox`（`pi-sandbox-toggle`。key は `sandbox`）と `TPS/TTFT`（stock の `pi-show-token-rate`。key は `token-rate`）は別の拡張の key で、この順（sandbox → TPS/TTFT）は変えていない。
- **RPC のときだけ出す**: `ctx.mode === "rpc"` のときだけ `ctx.ui.setStatus("usage", …)` を呼ぶ。T3 Code は常に RPC で pi を動かし、`setStatus` を入力欄のバナーにする。pi 自身の TUI では何も出さないので、フッターが唯一の表示のまま（二重にならない）。
- **更新の時点**: `session_start`（再開したセッションの数を出す）・`turn_end`（毎ターンの終わり）・`session_compact`（圧縮で使用率が変わる）・`model_select`（窓の大きさが変わる）。`session_shutdown` で消す（RPC のときだけ）。
- 登録するのは状態の表示だけ。コマンド・ツール・ファイル・ネットワーク・子プロセスは使わない。

方針・理由・撤去の条件は [ADR-0031](../../../../../docs/adr/0031-evaluate-existing-extensions-first.md)（「例外として残す自作の一覧」）。
試験: `uv run --with pytest --no-project pytest test/test_t3_usage_status.py -q`

## 撤去

1. `home/.chezmoitemplates/pi-stock-packages` の `./local-packages/t3-usage-status` の 1 行を消す。
2. このディレクトリ（`home/dot_pi/agent/local-packages/t3-usage-status/`）を消し、`test/test_t3_usage_status.py` と `scripts/verify.py` の対応の行も消す。
3. 配備済みの機を片付けるため、`home/.chezmoiremove` に `.pi/agent/local-packages/t3-usage-status` を足す（全機に行き渡ったら消してよい）。

T3 Code 自身が、セッションごとの費用・CH%・コンテキスト使用率を表示するようになったら、この拡張は要らなくなる。
