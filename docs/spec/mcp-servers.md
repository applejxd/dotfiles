# MCP サーバの設定

pi の MCP サーバの宣言（`home/.chezmoitemplates/pi-mcp-servers.toml` の `[[mcp]]`）から `mcp.json` を生成する仕様と、AgentCore Web Search の構成。生成の全体と所有権は [pi の設定の生成と所有権](agent-config-generation.md)。

## MCP サーバ

MCP サーバの宣言は `pi-mcp-servers.toml`（chezmoi テンプレート）が単一ソース。ユーザ・機（`is-work`）による出し分けはテンプレート側に書き、生成側（`scripts/agents/generate.py`）は展開後の表だけを見る。

```toml
[[mcp]]
id = "agentcore-websearch"
purpose = "AgentCore Web Search で web 検索する (Gateway の URL がある機だけ)"
requires_env = "AGENTCORE_GATEWAY_URL"
pi_exposure = "direct"
transport = "stdio"
command = "uv"
args = [
  "run", "--no-project", "--quiet",
  '{{ .chezmoi.homeDir }}/.config/agents/agentcore_websearch_mcp.py',
  "--service", "bedrock-agentcore", "--region", "us-east-1", "--disable-telemetry",
]
```

| 生成先 | 生成する仕組み |
| --- | --- |
| `~/.pi/agent/mcp.json` の `mcpServers`（pi 組み込みの MCP も `pi-mcp-adapter` もこれを読む） | `generate.py --target pi-mcp`。配備は `home/dot_pi/agent/modify_mcp.json.py.tmpl`（Unix・Windows）。宣言したサーバの `command` / `args`（http は `url`）だけを更新し、`pi mcp add` や `/mcp` で足したサーバと、宣言済みサーバの利用者のキー（`env`・`enabled`・`exposure` など）は保つ。`requires_env` は出さない（`pi_exposure` は server の `exposure` へ、無いときだけ補う）。壊れた JSON は触らない |
| `~/.pi/agent/mcp-adapter.json` の `mcpServers`（`mcp.json` と同じサーバ。`exposure` は無し。会社 PC＝`pi-mcp-adapter` を入れる機だけ） | `generate.py --target pi-mcp-adapter`。配備は `home/dot_pi/agent/modify_mcp-adapter.json.py.tmpl`。目的は[子への検索 MCP の渡し方](#子のエージェントへの検索-mcp-の渡し方) |

**宣言を消しても、生成先からは消えない。** 生成は宣言されたサーバを足す・更新するだけで、消えたサーバを刈らない。消すときは `pi mcp remove` か `mcp.json` を直接編集する。

**キーの検査**: 宣言の `id` は英数字・ハイフン・アンダースコアだけ。`transport` は `http`（`url`）か `stdio`（`command`・`args`）で、transport が持てないキーは typo とみなして apply を止める。`requires_env` は大文字の環境変数名、`pi_exposure` は `direct` / `codemode` / `deferred` / `hidden`。
検査は `scripts/agents/validate_mcp.py`（pre-commit）と `test/agents/test_mcp_servers.py` が行う。

### websearch（家の機の検索）

```toml
[[mcp]]
id = "websearch"
pi_exposure = "direct"
transport = "stdio"
command = "uv"
args = ["run", "--no-project", "--quiet", '{{ .chezmoi.homeDir }}/.config/agents/websearch/mcp_server.py']
```

- 自作の stdio サーバ（ツール `web_search`・`fetch_page`・`search_papers`。仕様は [Web 検索](web-search.md#mcp-サーバ)）。この MCP に一本化し、スキル `web-search` は廃止した（2026-11-09）。
- `pi_exposure = "direct"`: pi の `mcp.json` の `exposure` に補う（下の「`pi_exposure`」）。モデルに直接見えるツール名は `mcp__websearch__web_search`・`mcp__websearch__fetch_page`・`mcp__websearch__search_papers`。
- **`is-work` が `true` の機では宣言しない**（`[[mcp]]` のブロックごと条件で囲む）。検索の送り先が限られる環境では登録しない、という一般論による。その機の検索は `agentcore-websearch` だけ。
- 家の機の `mcp.json` には `agentcore-websearch` も出る。認証が無ければツールの無い空のサーバになる。受け入れる。
- permission: `pi-permission-policy.json` の `mcp` は、`websearch`・`agentcore-websearch` を allow（検索は読み取りのため）、他の MCP は ask のまま。

`agentcore-websearch` は全機に配る（使うかは実行時に決まる。下の「AgentCore Web Search」。`deepwiki` は外した。索引が古く実ソースと食い違う説明を返したため）。
`[[mcp]]` が 1 つも無いと `mcp` キー自体が生えないので、参照側は `hasKey` で受けること（`missingkey=error` で描画が止まる）。
deepwiki の代わりの OSS 調査は `oss-research` スキル（インストール済みの実体・配布物・版を固定したソースに直接当たる）、GitHub の操作は github MCP を使わず
`github-operations` スキル（gh CLI）が担う。

### `pi_exposure`（pi への見せ方）

`[[mcp]]` の任意キー。pi の `~/.pi/agent/mcp.json` の server の `exposure` に、**無いときだけ**補う（`merge_pi_mcp`。`/mcp` で利用者が変えた値は保つ）。値は `direct`・`codemode`・`deferred`・`hidden`。

- 理由: pi 組み込みの MCP の既定の `exposure` は `codemode` で、ツールはモデルに宣言されず `codemode` のスクリプトから呼ぶ。この形では、plan mode（`@narumitw/pi-plan-mode`）の許可リストは**完全一致の名前だけ**で、`codemode` を許すと任意の MCP を呼べて境界が広がる。`direct` なら、組み込みのツールと同様にモデルへ宣言され、名前 `mcp__<server>__<tool>`（英数字と `_` 以外は `_` に置換）で許可リストに具体名を足せる。
- `websearch`・`agentcore-websearch` を `direct` にする。許可リスト側は [追加の 4 つの package](agent-config-generation.md#追加の-4-つの-packagebackgroundplan-modegoalrewind)。permission-system の `mcp` 規則（`"websearch": "allow"` など）は `direct` のツール名にも効く（package の docs で確認。実機は未確認）。
- `agentcore-websearch` のツールの生の名前は `web-search-tool__WebSearch`（実機で確認済み）。pi に登録される完全な名前は、命名規則から導いた `mcp__agentcore_websearch__web_search_tool__WebSearch`。実機の `/mcp` の Tools 表示では**未確認**。検索の送り先が限られる環境では `pi-mcp-adapter` も入るので、adapter が別の名前で同じツールを出す可能性も未確認。

### 子のエージェントへの検索 MCP の渡し方

stock の pi で、検索の子（`researcher`・`evidence-auditor`）が検索できなかった原因と対処（2026-11-11。ソースと公式ドキュメントで確認。**会社 PC の実機は未確認**）。

- **原因 1**: 子の `tools` は厳密な許可リストで、親の MCP ツールは自動では渡らない。2 つの agent 定義の組み込みの `tools` は `pi-web-access` のツール名（`web_search`・`fetch_content`・`get_search_content`・`source_check`）だが、この package は入れない（[評価](../research/agents/pi-stock-packages-evaluation-2026-11.md)）ので、名前に対応するツールが無い。`mcp:` の指定はどの agent にも無かった。
- **対処 1**: `modify_pi_stock_settings.py.tmpl` の `AGENT_TOOL_OVERRIDES` で、`researcher` = `read`・`write`・`mcp:<検索>`、`evidence-auditor` = `read`・`mcp:<検索>` にする。`<検索>` は家の機が `websearch`、会社 PC が `agentcore-websearch`（`is-work` で切る）。`mcp:<サーバ>` はそのサーバの全ツールを渡す。agent 定義の写し（`~/.pi/agent/agents/`）は組み込みと同一のまま保つ（試験で固定）。settings の上書きは、user の agent ファイルにも効く（pi-subagents 0.87.0 の `applyCustomAgentOverrides`）。
- **原因 2（会社 PC）**: `pi-mcp-adapter` が入ると、pi-subagents は子の `mcp:` を adapter の設定ファイル（`~/.config/mcp/mcp.json`・`~/.pi/agent/mcp-adapter.json`・`.mcp.json`・`.pi/mcp-adapter.json`）から解決し、`~/.pi/agent/mcp.json` は読まない（0.87.0 の `src/runs/shared/mcp-direct-tool-allowlist.js` の `getConfigPaths`）。adapter 本体は `~/.pi/agent/mcp.json` も読む（7.0.1 の `config.ts`）ので、親では動くのに子では未解決になる食い違いがある。
- **対処 2**: 同じサーバを `~/.pi/agent/mcp-adapter.json` にも置く（`generate.py --target pi-mcp-adapter`。`command` / `args` は `mcp.json` と同一なので、cache の照合に使う項目も同じになるはずだが、adapter 7.0.1 と pi-subagents 0.87.0 の照合が一致することは未確認）。`exposure` は出さない。家の機は pi 組み込みの MCP が `mcp.json` を読むので配らない。
- **制約・未確認**:
  - 会社 PC の実機で、子が `agentcore-websearch` を呼べること（adapter 7.0.1 で `mcp:` が解決されること）は未確認。
  - adapter 経由の `mcp:` は、背景の子（`async: true`）だけで動く。前景の子は起動が失敗する。adapter のツール情報の cache が要るので、サーバへ一度つないだあと（親が一度使ってから pi を再起動したあと）でないと解決しないことがある（pi-subagents の `docs/agents.md`「MCP tools」）。
  - `researcher`・`evidence-auditor` の prompt は組み込みの写しのままで、`web_search`・`fetch_content`・`source_check` を前提にしている（`researcher` は `source_check` の登録を前提とする記述もある）。MCP のツール名への読み替えは、子のモデルに任せる想定で、**未検証**。プロンプトとツールの不整合は残る。`source_check` は無く、AgentCore は検索だけで本文の取得も無い。

### AgentCore Web Search

Bedrock の PC で web 検索を提供する MCP サーバ。Bedrock 経由では、モデル提供元の内蔵の検索は使えない。
そこで、AWS 内で完結する AgentCore Web Search を入れる
（[公式ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html)）。

```text
pi
  └─ stdio ─ ~/.config/agents/agentcore_websearch_mcp.py
               └─ uvx mcp-proxy-for-aws-cli (手元の AWS 認証情報で SigV4 署名)
                    └─ HTTPS ─ AgentCore Gateway ─ Web Search コネクタ
```

| 項目 | 決めたこと |
| --- | --- |
| 対象 | **全機に配る**。使うかは実行時に決まる（下の「使えない機」） |
| リージョン | `us-east-1` |
| Gateway の URL | アカウント固有なのでソースに書かず、環境変数 `AGENTCORE_GATEWAY_URL` から読む |
| 認証 | AWS の既定の認証情報（`AWS_PROFILE` / `~/.aws`）。API キーは無い |
| proxy の版 | `mcp-proxy-for-aws-cli` をラッパーの `PROXY` で固定。依存まで固定した CLI 用の配布物 |

**使えない機（家など、URL も AWS の認証も無い機）**: 失敗させず、**ツールの無い空の MCP サーバ**になる（ラッパーが stdio で `initialize` / `tools/list` などに空で答える）。
起動の失敗が毎回の通知になるのを避け、「家で設定されても、認証しなければ何も起きない」を実現する。空になるのは、`AGENTCORE_GATEWAY_URL` が無い・`https://` でないとき（撤去した `pis` の内側（`PI_HARNESS_BOUNDARY=1`）で空になる処理も撤去した）。
MCP サーバは pi 本体と同じく囲い（`pib`）の外で動く（[pi-sandbox-runner](sandbox/pi-sandbox-runner.md#位置づけ)）ので、`pib` の中の pi でも使える。**未確認**: 起動失敗時の pi の挙動、Windows の `uvx`。

**ラッパーを挟む理由**: proxy は Gateway の URL を位置引数でしか受け取らない。
MCP の定義に URL を書かずに済ませるには、環境変数から読んで渡す層が要る。
ラッパーは Python で書き、`uv run` から起動する（Windows に `python3` が無いため）。
MCP クライアントは `~` を展開しないので、ラッパーのパスは `.chezmoi.homeDir` から絶対パスにする。

#### AWS 側の準備（アカウントごとに 1 回）

リポジトリには CloudFormation を置かない。AWS 公式のサンプル
[aws-samples/sample-agentcore-websearch-agent-skill](https://github.com/aws-samples/sample-agentcore-websearch-agent-skill)
の `cfn/agentcore-websearch.yaml` で、次の 3 つをまとめて作れる。

| リソース | 中身 |
| --- | --- |
| Gateway | 受け付けの認証は `AWS_IAM` |
| Target | `connectorId: "web-search"` のコネクタ |
| サービスロール | Gateway が引き受ける。`bedrock-agentcore:InvokeWebSearch` を持つ |

```bash
aws cloudformation deploy --region us-east-1 --stack-name agentcore-websearch \
  --template-file cfn/agentcore-websearch.yaml --capabilities CAPABILITY_IAM
aws cloudformation describe-stacks --region us-east-1 --stack-name agentcore-websearch \
  --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" --output text
```

サンプルは本番向けではないと明記している。使う前に権限の範囲を見直す。
使う人の IAM には、作った Gateway の ARN に対する
`bedrock-agentcore:InvokeGateway` を付ける。

#### 制約のある環境の機での設定

1. 上で得た URL をシェルの初期化ファイル（リポジトリ管理外）に書く:
   `export AGENTCORE_GATEWAY_URL='https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp'`。
   Windows はユーザー環境変数に設定する
2. `chezmoi apply` で pi の `mcp.json`（と、adapter を入れる機の `mcp-adapter.json`）を生成する
3. 確認: pi の `/mcp` で `agentcore-websearch` が connected になり、検索のツールが 1 つ見えること

URL が未設定だとラッパーは理由を stderr に出して終了する（MCP クライアント側では接続失敗として見える）。

#### 料金と制約

- 検索 1,000 回あたり $7。Gateway の呼び出しなどは別に課金される
  （[料金](https://aws.amazon.com/bedrock/agentcore/pricing)）
- `query` は 200 文字以内、`maxResults` は 1〜25（既定 10）
- 返るのは関連部分の抜粋・URL・タイトル・公開日。本文が要るときは別の取得手段と組み合わせる
- 利用条件として、結果を表示するときは出典リンクを残す
- Target 単位でドメインの許可・除外リストを強制できる（エージェント側から解除できない）
