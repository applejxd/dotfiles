# web-search 仕様の実測・経緯

> `docs/spec/web-search.md`（配る範囲・検索の鎖・鍵・実測・`pis` の内側のプロキシ越しの取得）から移した記録。移設時点で再測定していない。
> 現行の仕様は [Web 検索](../../spec/web-search.md)。

## 記録 W1 — 配る範囲の切り替え（2026-10-26）

- **観測日**: 2026-10-26
- **問い**: 検索を配る範囲の条件は何で切っているか。

元の文: 2026-10-26 までは `llm-provider` で切っていたが、会社 PC で Copilot を使うようになったので `is-work` に付け替えた。

## 記録 W2 — 検索プロバイダの順位の根拠と無料枠（2026-10-11 確認）

- **観測日**: 2026-10-11（各社のページで確認）

元の文: 順位の根拠と、各社の無料枠（2026-10-11 に各社のページで確認）は、設計の相談の記録による: Brave は月 $5 の無料クレジット（約 1,000 件）、Exa は月 $10
（約 2,500 件）、Tavily は月 1,000 クレジット。品質・鮮度の優劣は未実測。

DuckDuckGo: HTML 版の検索フォームへ `POST`。`GET` は bot の確認（HTTP 202）になりやすかった（2026-10-12 実測）。

## 記録 W3 — 鍵ファイル作成の実測（2026-10-12）

- **観測日**: 2026-10-12
- **環境**: Windows

元の文: 実測: Windows で、偽の `bw.cmd` で追加・維持・取り直しを確認し、実際の Bitwarden でも 4 件が取れた（2026-10-12）。

## 記録 W4 — 実測（2026-10-12、Windows 11、鍵なしで実行）

- **観測日**: 2026-10-12
- **環境**: Windows 11

### 結果

- `fetch https://example.com` は成功（固定した IP への TLS 接続）。`http://localhost/`・`http://169.254.169.254/` は実際の名前解決で止まった（終了コード 2）
- `search`: 鍵がないので Brave・Exa・Tavily は飛ばされ、DuckDuckGo が答えた（関連する Microsoft Learn のページが出た）。同じクエリの 2 回目はキャッシュ（`(cache)`）
- `papers`: 鍵なしで OpenAlex が答えた
- 試験は 49 件（`uv run --with pytest --no-project pytest test/test_websearch.py`）
- **実際の鍵での確認（2026-10-12）**: `apply` が Bitwarden の 4 項目から鍵ファイルを作り（`added=['brave','exa','tavily','openalex']`）、
  **Brave・Exa・Tavily・DuckDuckGo・OpenAlex の全てが実際の API で結果を返した**（鎖の先頭は Brave）。最初は Exa が HTTP 401（`INVALID_API_KEY`）で、
  Bitwarden の項目の値（25 文字）が違っていた。値を直して取り直したら通った（36 文字）。401 は「auth」として次へ回り、そのプロバイダは 1 時間休止する
- `fetch` は実際の文書サイト（`https://pi.dev/docs/latest/codemode` など）で動き、`search` の結果から公式の URL の形を見つけられた
- **`added=none missing=[…]` になるときは、Vault が未同期**（実機で、アンロック済みでも項目が見えず、`bw sync` のあとに取れた）。`sync-keys` は取りに行く前に `bw sync` する

## 記録 W5 — `pis` の内側のプロキシ越しの取得（2026-10-25）

- **観測日**: 2026-10-25
- **環境**: `pis -p` の内側

### 結果（修正前）

- 内側は DNS を引けない（`getent hosts raw.githubusercontent.com` が終了コード 2）
- 環境変数に `HTTPS_PROXY=http://127.0.0.1:3128`（Fence のプロキシ）がある。`curl -sI https://arxiv.org` は `200 Connection Established` のあと
  HTTP 200、`https://raw.githubusercontent.com` は 301 で通る
- 許可リストの外（`voiceover.manim.community`）は、プロキシが `403 Forbidden` を返す。**ドメインの許可はプロキシが強制している**

### 結果（修正後、2026-10-25、`pis -p` の内側）

`fetch https://arxiv.org/abs/2510.05096` と
`fetch https://raw.githubusercontent.com/…/README.md` は終了コード 0 で本文を取れた。許可外の `https://voiceover.manim.community/` は
`取得を止めた: プロキシが接続を拒否した (Tunnel connection failed: 403 Forbidden)…`（終了コード 2）。

## 記録 W6 — URL 中の長い文字列の誤検知（CHG-0032）

経緯は [CHG-0032](../../change/0032-guard-url-false-positive.md)。仕様側（`docs/spec/web-search.md#安全策`）には、現行の規則と限界だけを残した。
