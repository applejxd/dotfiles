# 会社 PC のページ取得（URL 指定）の評価（2026-11-17）

観測日: 2026-11-17。対象: `mcp-server-fetch` 2026.11.11（PyPI）・`pi-subagents` 0.87.0・pi 1.5.0。
目的: AgentCore Web Search だけを持つ機（`is-work`）の `researcher` は、抜粋しか得られず、ページ本文を取れない。URL を指定して本文を取る手段を足す。
前提: 外部へはプロキシ経由でしか出られない制約のある環境を対象にする。取得は URL 指定だけ（検索は AgentCore に一本化したまま）。方針は [ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md)（既存を先に評価し、自作は最後の手段）。

## 問い

1. 既製の取得 MCP で、プロキシ必須の環境の要件を満たせるか。
2. 満たせなければ、自作の `fetch_page`（家の機の `websearch`）にプロキシ対応を足す価値はあるか。

## 候補

| 候補 | プロキシ | 私的アドレスの拒否 | 保守・出所 | 判断 |
| --- | --- | --- | --- | --- |
| 家の機の `fetch_page`（自作。`core.py`）をそのまま配る | **非対応**。名前を手元で解決し、検証した IP へ直接つなぐ。プロキシ必須の環境では「名前を解決できない」で止まる | あり（接続先 IP を固定） | 自作（標準ライブラリだけ） | 不可 |
| 自作の `fetch_page` にプロキシ対応を足す | 自作する（CONNECT・`NO_PROXY`・認証・OS の設定の読み取り）。通信なしの試験では確かめきれない | プロキシ越しは IP を固定できない（既製品と同じ限界） | 自作を維持する | 不採用（既製品で足りるため） |
| **`mcp-server-fetch`（採用）** | 環境変数 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` と `--proxy-url`（httpx）。socks も可 | あり（名前を解決できる場合。各リダイレクトも検査）。プロキシだけが引ける名前は検査されない（README に明記） | Anthropic 管理の参照実装（`modelcontextprotocol/servers`）。MIT。版 2026.11.11 | 採用 |

## 確かめたこと

- **出典**（2026-11-17 に取得）: [README](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md)・[`server.py`](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/src/mcp_server_fetch/server.py)・[`pyproject.toml`](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/pyproject.toml)・[PyPI](https://pypi.org/project/mcp-server-fetch/)（版 2026.11.11）。
- **ツール**: `fetch` の 1 つだけ（引数 `url`・`max_length`・`start_index`・`raw`・`timeout_ms`）。検索はしない。応答は markdown。本文が 5 MiB を超える応答は拒否し（途中までは返さない）、圧縮爆弾にも備える。`robots.txt` を守る。
- **実測**（`uvx --exclude-newer 2026-11-17 mcp-server-fetch==2026.11.11 --no-readability-js`。Linux・stdio の JSON-RPC）:
  - `tools/list` は `fetch` だけ。`https://example.com/` を取得できた。
  - `http://169.254.169.254/…` と `http://localhost:8080/` は、「公開アドレスではない」として拒否された。
  - 偽のプロキシ（HTTP の絶対 URI 要求だけに答える）を `HTTP_PROXY` に指定し、`http://only-the-proxy-can-resolve.invalid/page`（手元では解決できない名前）を取得できた。プロキシは `robots.txt` と本文の 2 件の要求を受けた。**プロキシ越しの取得と、手元で解決できない名前の通過を確かめた**。
- **pi 側**: 組み込みの MCP も、`pi-mcp-adapter` 7.0.1 も、stdio サーバの環境変数に、親の環境変数を引き継ぐ（組み込み: pi 1.5.0 の同梱ソース、adapter: `server-manager.ts` の `resolveEnv` で確認。どちらも `inheritEnv` が `false` でない限り）。したがってプロキシの環境変数は、子のサーバに届く。
- **adapter が入る機の名前と権限**（`reviewer` の監査で判明）: adapter は pi 組み込みの MCP を切り（`pi-builtin-mcp.ts` が `-builtin:mcp` を設定へ足す）、ツールを `<server>_<tool>`（既定の `toolPrefix`＝`server`）の名前で登録する。この機では `fetch` は `webfetch_fetch` になる。permission-system は `mcp__<server>__<tool>` 形と `mcp` だけを MCP として扱い、`webfetch_fetch` は拡張のツール（方針の既定は ask）になる。方針の `mcp` の `webfetch` 規則はこの名前に効かないため、トップレベルに `webfetch_fetch` の allow を足した。**実機では未確認**。

## 採用の条件と選んだ設定

- `uvx --exclude-newer <日付> mcp-server-fetch==<版>` で、版と、推移的な依存が解決される日付の上限を固定する（`uvx` は依存を固定しない。日付で上限を切る）。日付は取得した日。
- `--no-readability-js`: Node.js が PATH にあると、既定で Readability.js を使い、初回に npm レジストリへ接続して JavaScript の依存を入れる（版を固定できない）。これを避ける。純 Python の抽出器になるので、出力は少し粗い（実測: `<p>Example Domain</p>` のように、タグが一部残る）。
- 既定のまま使うもの: 私的アドレスの拒否・`robots.txt`。`--allow-private-ips`・`--ignore-robots-txt`・`--proxy-url` は宣言に書かない（プロキシの値は環境変数で渡し、リポジトリに載せない）。

## 限界（未確認を含む）

- **adapter が入る機の実機は未確認**: PyPI へ届くか（AgentCore のラッパーが同じ `uvx` を使うので届く見込みはあるが、確認していない）、プロキシの認証方式、`pi-mcp-adapter` 7.0.1 での `mcp:webfetch` の解決とツールの登録名。
- **HTTPS の CONNECT は未実測**: 手元で作った CONNECT 中継が上流へ届かず（原因は未調査）、確かめられなかった。httpx は標準で CONNECT を使う（`server.py` のコメントと README の記述）。
- **認証**: httpx が扱えるのは URL に埋めた Basic 認証まで。NTLM・Kerberos・PAC（自動設定スクリプト）には対応しない。
- **SSRF の限界**: プロキシだけが引ける名前は検査されず、DNS rebinding も防げない（README に明記）。プロキシ越しでは、接続先 IP の固定ができない（自作でも同じ）。内部の名前の拒否は、プロキシの設定が担う。
- **URL による情報の持ち出し**: モデルが URL のクエリ文字列などに情報を載せて、外部へ送れる。検索のクエリのような秘匿チェックは、この取得には無い。
- **robots.txt**: 拒否されるページがある。取れない場合は、子が「未確認」と報告する（prompt に書いた）。

## 関連

- 仕様: [webfetch（会社 PC のページ取得）](../../spec/mcp-servers.md#webfetch会社-pc-のページ取得)
- 家の機の取得: [Web 検索](../../spec/web-search.md)（自作の `fetch_page`。変更しない）
