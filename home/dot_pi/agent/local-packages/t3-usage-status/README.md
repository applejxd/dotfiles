# t3-usage-status（ローカル）

T3 Code の中で動く pi に、セッションの費用とキャッシュヒット率（CH%）を出す。このリポジトリだけが配る自作で、OS を問わず入る。

```text
Pi · CH97.2% $24.480      T3 Code の入力欄のバナー (web・モバイル)
```

- **出すもの**: pi の TUI のフッターと同じ計算の、セッションの費用の合計（`$X.XXX`）と、最新の assistant のメッセージの CH%（`cacheRead / (input + cacheRead + cacheWrite)`）。セッションにキャッシュの読み書きが無いときは CH を省く。何も無い空のセッションは何も出さない。
- **RPC のときだけ出す**: `ctx.mode === "rpc"` のときだけ `ctx.ui.setStatus("usage", …)` を呼ぶ。T3 Code は常に RPC で pi を動かし、`setStatus` を入力欄のバナーにする。pi 自身の TUI では何も出さないので、フッターが唯一の表示のまま（二重にならない）。
- **更新の時点**: `session_start`（再開したセッションの数を出す）と `turn_end`（毎ターンの終わり）。`session_shutdown` で消す（RPC のときだけ）。
- 登録するのは状態の表示だけ。コマンド・ツール・ファイル・ネットワーク・子プロセスは使わない。

方針・理由・撤去の条件は [ADR-0031](../../../../../docs/adr/0031-evaluate-existing-extensions-first.md)（「例外として残す自作の一覧」）。
試験: `uv run --with pytest --no-project pytest test/test_t3_usage_status.py -q`

## 撤去

1. `home/.chezmoitemplates/pi-stock-packages` の `./local-packages/t3-usage-status` の 1 行を消す。
2. このディレクトリ（`home/dot_pi/agent/local-packages/t3-usage-status/`）を消し、`test/test_t3_usage_status.py` と `scripts/verify.py` の対応の行も消す。
3. 配備済みの機を片付けるため、`home/.chezmoiremove` に `.pi/agent/local-packages/t3-usage-status` を足す（全機に行き渡ったら消してよい）。

T3 Code 自身が、セッションごとの費用と CH% を表示するようになったら、この拡張は要らなくなる。
