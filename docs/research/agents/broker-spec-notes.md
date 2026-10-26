# ブローカー仕様の実測と経緯

`docs/spec/sandbox/broker.md#実測と経緯` から移した記録。移設時点で再測定していない。

> **現行の仕様**: [ブローカー](../../spec/sandbox/broker.md)

## 記録 E1 — 2026-10-24〜25 の実測

- **観測日**: 2026-10-24〜2026-10-25（元の文の日付）
- **対象**: `pis` の Copilot・GitHub・検索ブローカー（Envoy）。環境は各項に書いたとおり（WSL2・個人の機）

### 問い

ブローカー越しに、内側から Copilot・GitHub・検索が実際に通るか。

### 結果（元の文）

- **2026-10-24**（WSL2、境界あり）: ダミーの `COPILOT_GITHUB_TOKEN` と `models.json` の `baseUrl` だけで、`pis -p` が Copilot の応答を受け取れた。
  ストリーミングは増分で届いた。許可した 3 経路は 200、GET・別パス・`/../models`・`/chat/completionsx` は 403
- **2026-10-24**（WSL2、境界あり、ダミーの PAT）: 内側の `gh issue list` が `gh.sock` 経由で Envoy に届き、GitHub が `HTTP 401: Bad credentials` を返した
  （差し替え値がダミーのため。経路の成立の証明）。偽装した Host は 403。PAT が無いときは通知を出して `gh` は無認証
- **2026-10-24**（個人の機、境界あり）: `github_token_command = ["gh", "auth", "token"]` で、内側の `gh issue list -R cli/cli -L 2` が実際の issue を返した
- **2026-10-25**: 鍵ファイルは、内側から読むと「許可がありません」（`test -r` は真）
- **2026-10-25**（個人の機、境界あり）: `pis -p` の内側から `websearch.py search` が通った（`provider=brave`、8 件）。内側に鍵は渡っていない。
  独立の `review` の指摘（身元確認を GET に限定、`Proxy-Authorization` の削除、不正なパス・エンコードの実 Envoy の試験）を反映した
- **2026-10-25**: 共通化の前後で `build_config` の出力が同値であることを、HEAD の旧コード（断片 YAML と旧 `broker.py`）を `git show` で取り出して書き出した構造と、正解データ `golden/broker_config.json` のバイト一致で確かめた
- 詳しい経緯は [CHG-0037](../../change/0037-pis-usability-and-telemetry.md)、方式の調査は
  [調査 D2〜D6](agent-auth-delegation.md)
