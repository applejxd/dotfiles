# プロキシ必須の環境で、境界（Fence / srt）の通信を通すには

- **観測日**: 2026-10-15
- **対象**: Fence v0.1.67（コミット `3e0eefe`）、`@anthropic-ai/sandbox-runtime`（`srt`）0.0.76 / 0.0.79、WSL2（プロキシ無しの個人機）
- **きっかけ**: 制約のある環境の機で `pis --check` が「許可済みドメインへ到達できず」で落ち、180 秒の時間切れになった。
  **制約のある環境の機では実測していない**（下の「未確認」）

現在の運用は [pi のガード](../../spec/guard/pi-guard.md#プロキシ必須の環境での通信) が正本。

## 結論

- Fence は `allowedDomains` に当たる通信を**直接**つなぐ（`internal/proxy/http.go` の `handleConnect`、`net.DialTimeout`）。
  `network.upstreamProxy`（`http://` のみ）は、許可にも拒否にも当たらない通信（グレーゾーン）に、`defaultAction: "proxy"` のときだけ使われる（PR #165。mitmproxy での検査用途）。
  ホストの `HTTPS_PROXY` を読む処理は無い。**プロキシ必須の機械では、許可リストを保ったまま外へ出る手段が Fence に無い**
- `srt` は `network.parentProxy`（未設定ならホストの `HTTP(S)_PROXY` / `NO_PROXY`）で、許可リストの照合後に上流プロキシへ流せる。ただし
  `pis` の境界の形がそのままでは載らない（下の実験）
- 対応は、許可リストの照合を自前の小さな中継へ移し、Fence の上流プロキシにそれを指す形にした（`relay.py`）

## 実験 1: `srt` で `pis` と同じ境界の形を組む（0.0.76 / 0.0.79。結果は同じ）

広く拒否（`denyRead: [$HOME]`）し、作業の親を `allowRead`、親の内側の秘密を `denyRead`、作業領域だけ `allowWrite`、保護を `denyWrite` とした。

| 項目 | 結果 |
| --- | --- |
| 作業領域・親の他ディレクトリを読む | 読めた |
| 親の内側の秘密（`denyRead`）・`allowRead` 外 | 読めなかった |
| **作業領域へ書く（祖先が `allowRead`）** | **書けない（読み込み専用）。R1 が再現** |
| 親の他ディレクトリ・既存の保護へ書く | 書けなかった |
| **存在しない保護対象を `denyWrite` に入れる** | **`srt` が起動に失敗**（`bwrap: Can't create file … Read-only file system`） |
| **`denyRead` に `$HOME` を含めたときの通信** | **許可済みも 000。含めないと 200** |

## 実験 2: `srt` にプロキシ越しを任せる（0.0.79。手元の CONNECT 中継をプロキシの代役にした）

| 通信 | 結果 | 代役のログ |
| --- | --- | --- |
| `github.com`（許可） | 200 | `CONNECT github.com:443` |
| `example.com`（許可外） | 000 | 記録なし（`srt` が先に拒否） |
| `github.com`（代役を停止） | 000 | — |

## 実験 3: 採用した中継（`relay.py`）を実際の Fence で通す

手元の CONNECT 中継をプロキシの代役にし、`HTTPS_PROXY` を設定して `pi.run_sandboxed(["--check"])` を実行した。
境界チェックは合格し、代役のログには `CONNECT github.com:443` だけが残った（許可外の `example.com` は中継が拒否し、代役へ届かなかった）。
変数を外した実行でも合格した（従来の経路）。`test/agents/test_relay.py` の 40 件も通った。

## 採らなかった案

| 案 | 理由 |
| --- | --- |
| 境界を `srt` へ戻す | 実験 1 の 3 点（R1・存在しない保護対象・`$HOME` 拒否での通信停止）。Fence へ移した経緯は CHG-0009 |
| Fence の `upstreamProxy` にプロキシを直接指す | グレーゾーンの全通信が通り、許可リストが無効になる |
| 境界チェックのネットワーク項目を `SKIP` にするだけ | 実際の通信は通らない |
| sandbox 全体を自前で作る | 保守と検証の範囲が大きい。足りないのは「許可済み通信を上流へ流す」1 点だけ（`sandbox-runtime.md` 18 節も同様に棄却） |
| Fence へ PR（許可済みの CONNECT も上流へ流すオプション） | 採用までの時間が読めない。入ったら `relay.py` を外す。**未着手** |

## 未確認

- **プロキシ必須の制約のある環境の機での実測。** 上の実験はすべて、プロキシの無い機械で、代役の中継を立てたもの。
  プロキシの認証（NTLM / Kerberos）、TLS を検査するプロキシの CA、`NO_PROXY` の実際の値は見ていない
- `scripts/diagnose-corp-proxy.sh` を制約のある環境の機で実行して、次を確かめる:
  ホストからプロキシ必須か、Fence が許可済みへ直接つなごうとして失敗するか（`fence -d` の `dial` の失敗）、
  プロキシの URL の形（`http://` か。認証付きか）
- Fence の上流プロキシが `https://` や SOCKS に未対応なのは文書とソースの読みで、制約のある環境の機では未確認
