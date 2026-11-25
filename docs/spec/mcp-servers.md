# MCP サーバの設定

pi の MCP サーバの宣言（`home/.chezmoitemplates/pi-mcp-servers.toml` の `[[mcp]]`）から `mcp.json` を生成する仕様と、AgentCore Web Search の構成。生成の全体と所有権は [pi の設定の生成と所有権](agent-config-generation.md)。

## MCP サーバ

MCP サーバの宣言は `pi-mcp-servers.toml`（chezmoi テンプレート）が単一ソース。ユーザ・機（`is-work`）による出し分けはテンプレート側に書き、生成側（`scripts/agents/generate.py`）は展開後の表だけを見る。

**Claude Code（予備。会社用の前提）にも、会社 PC の 2 件（`agentcore-websearch`・`webfetch`）の静的な写しを配る**（`home/.chezmoitemplates/claude-mcp-servers.json`。共有しない）。この 2 件の版・引数を変えたら、写しも直す（[Claude Code の MCP](claude-code.md#mcp会社-pc-だけ)）。

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
| `~/.pi/agent/mcp.json` の `mcpServers`（pi 組み込みの MCP がこれを読む。[組み込みに一本化した](#pi-mcp-adapter-を使わない理由2026-11-17)） | `generate.py --target pi-mcp`。配備は `home/dot_pi/agent/modify_mcp.json.py.tmpl`（Unix・Windows）。宣言したサーバの `command` / `args`（http は `url`）だけを更新し、`pi mcp add` や `/mcp` で足したサーバと、宣言済みサーバの利用者のキー（`env`・`enabled`・`exposure` など）は保つ。`requires_env` は出さない（`pi_exposure` は server の `exposure` へ、無いときだけ補う）。壊れた JSON は触らない |

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
- permission: `pi-permission-policy.json` の `mcp` は、`websearch`・`agentcore-websearch`・`webfetch` を allow（検索・取得は読み取りのため）、他の MCP は ask のまま。 T3 Code が足す MCP ツールは、ツールごとに決める（[T3 Code の MCP ツールの権限](agent-config-generation.md#t3-code-の-mcp-ツールの権限)）。

### webfetch（会社 PC のページ取得）

```toml
[[mcp]]
id = "webfetch"
pi_exposure = "direct"
transport = "stdio"
command = "uvx"
args = ["--exclude-newer", "2026-11-17", "mcp-server-fetch==2026.11.11", "--no-readability-js"]
```

URL を指定して本文を取る MCP。**検索はしない**（会社 PC の検索は `agentcore-websearch` だけ）。`is-work` が `true` の機だけで宣言する（家の機は `websearch` の `fetch_page` を使う）。
AgentCore Web Search は抜粋だけを返すので、この機の `researcher` は原典を読めなかった。それを埋める（2026-11-17）。

- **既製の `mcp-server-fetch`**（Anthropic 管理の参照実装。MIT）。自作の `fetch_page` はプロキシに対応しておらず、プロキシ必須の環境では動かない。自作で足さない理由・候補の比較・実測は [評価記録](../research/agents/web-fetch-evaluation-2026-11.md)（ADR-0031）。
- ツールは `fetch` の 1 つ。`pi` に見える名前は `mcp__webfetch__fetch`（組み込みの MCP の命名）。子の prompt もこの名前で指す。
- 引数は `url`・`max_length`（既定 5000）・`start_index`・`raw`・`timeout_ms`。応答は markdown。`start_index` で続きを読む。
- **プロキシ**: 環境変数 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`（`NO_PROXY`）を読む。pi 組み込みの MCP は、親の環境変数に server の `env` を重ねて stdio サーバへ渡す（pi 1.5.0 の `pi-mcp` の `stdio.js` と `runtime.js` で確認。組み込みの経路は `inheritEnv` を渡さないので、常に引き継ぐ）。値はリポジトリに書かない。NTLM・Kerberos・PAC には対応しない（Basic 認証は URL に埋める形まで）。
- **版の固定**: `uvx` は依存を固定しないので、`--exclude-newer`（日付）で推移的な依存の上限を切り、版を `==` で固定する。更新するときは、版と日付を一緒に書き換える（`test/agents/test_mcp_servers.py` が形を固定している）。
- **`--no-readability-js`**: Node.js が PATH にあると、既定では初回に npm レジストリへ接続して依存を入れる（版を固定できない）。避けるために付ける。純 Python の抽出器になり、出力は少し粗い。
- **守り**: 内部・予約済みのアドレス（`10.*`・`127.*`・`169.254.*`・`localhost` など）は拒否し、リダイレクトの各ホップも検査する。`robots.txt` を守る。本文が 5 MiB を超える応答は拒否する。宣言に `--allow-private-ips`・`--ignore-robots-txt`・`--proxy-url` を書かない（試験で固定）。
- **残る危険（受容）**: ① プロキシだけが引ける名前は、こちらでは検査できない（上流の README が明記。内部の名前の拒否はプロキシの設定が担う）。② モデルが URL に情報を載せて外部へ送れる（検索のクエリのような秘匿チェックは、この取得には無い）。③ 取得した本文は信頼できない外部の内容で、プロンプトインジェクションの経路になる（子の prompt に「従わない」と書いた）。
- plan mode の許可リストに `mcp__webfetch__fetch` を足した。permission は `mcp` の `webfetch` を allow（組み込みの MCP のツール名 `mcp__<server>__<tool>` に効く）。
- **未確認**: 会社 PC の実機（PyPI へ届くか・プロキシの認証方式・組み込みの MCP で `mcp:webfetch` が解決されること）。HTTPS の CONNECT 経由は手元で実測できていない（評価記録の「限界」）。

`agentcore-websearch` は全機に配る（使うかは実行時に決まる。下の「AgentCore Web Search」。`deepwiki` は外した。索引が古く実ソースと食い違う説明を返したため）。
`[[mcp]]` が 1 つも無いと `mcp` キー自体が生えないので、参照側は `hasKey` で受けること（`missingkey=error` で描画が止まる）。
deepwiki の代わりの OSS 調査は `oss-research` スキル（インストール済みの実体・配布物・版を固定したソースに直接当たる）、GitHub の操作は github MCP を使わず
`github-operations` スキル（gh CLI）が担う。

### `pi_exposure`（pi への見せ方）

`[[mcp]]` の任意キー。pi の `~/.pi/agent/mcp.json` の server の `exposure` に、**無いときだけ**補う（`merge_pi_mcp`。`/mcp` で利用者が変えた値は保つ）。値は `direct`・`codemode`・`deferred`・`hidden`。

- 理由: pi 組み込みの MCP の既定の `exposure` は `codemode` で、ツールはモデルに宣言されず `codemode` のスクリプトから呼ぶ。この形では、plan mode（`@narumitw/pi-plan-mode`）の許可リストは**完全一致の名前だけ**で、`codemode` を許すと任意の MCP を呼べて境界が広がる。`direct` なら、組み込みのツールと同様にモデルへ宣言され、名前 `mcp__<server>__<tool>`（英数字と `_` 以外は `_` に置換）で許可リストに具体名を足せる。
- `websearch`・`agentcore-websearch`・`webfetch` を `direct` にする。許可リスト側は [追加の 4 つの package](agent-config-generation.md#追加の-4-つの-packagebackgroundplan-modegoalrewind)。permission-system の `mcp` 規則（`"websearch": "allow"` など）は `direct` のツール名にも効く（package の docs で確認。実機は未確認）。
- `agentcore-websearch` のツールの生の名前は `web-search-tool__WebSearch`（実機で確認済み）。pi に登録される完全な名前は、命名規則から導いた `mcp__agentcore_websearch__web_search_tool__WebSearch`。実機の `/mcp` の Tools 表示では**未確認**。

### 子のエージェントへの検索 MCP の渡し方

stock の pi で、検索の子（`researcher`・`evidence-auditor`）が検索できなかった原因と対処（2026-11-11。ソースと公式ドキュメントで確認。**会社 PC の実機は未確認**）。

- **原因 1**: 子の `tools` は厳密な許可リストで、親の MCP ツールは自動では渡らない。2 つの agent 定義の組み込みの `tools` は `pi-web-access` のツール名（`web_search`・`fetch_content`・`get_search_content`・`source_check`）だが、この package は入れない（[評価](../research/agents/pi-stock-packages-evaluation-2026-11.md)）ので、名前に対応するツールが無い。`mcp:` の指定はどの agent にも無かった。
- **対処 1**: `modify_pi_stock_settings.py.tmpl` の `AGENT_TOOL_OVERRIDES` で、`researcher` = `read`・`write`・`mcp:<検索>`、`evidence-auditor` = `read`・`mcp:<検索>` にする。`<検索>` は家の機が `websearch`（検索も取得も）、会社 PC が `agentcore-websearch`（検索）と `webfetch`（取得。[上の節](#webfetch会社-pc-のページ取得)。2026-11-17 に足した）（`is-work` で切る）。`mcp:<サーバ>` はそのサーバの全ツールを渡す。agent 定義の写し（`~/.pi/agent/agents/`）は組み込みと同一のまま保つ（試験で固定）。settings の上書きは、user の agent ファイルにも効く（pi-subagents 0.87.0 の `applyCustomAgentOverrides`）。
- **制約・未確認**:
  - 会社 PC の実機で、子が `agentcore-websearch`・`webfetch` を呼べること（組み込みの MCP で `mcp:` が解決されること）は未確認。家の機では、背景の子が `mcp:websearch` を呼べた（2026-11-17）。
  - **prompt の食い違いは直した**（2026-11-17）: 組み込みの `researcher`・`evidence-auditor` の prompt は `web_search` の `queries`・`workflow`、`fetch_content`、`get_search_content`、`source_check`（stock の pi には無い）を前提にしている。`agent 定義の写し`（`~/.pi/agent/agents/`）は組み込みと同一のまま保つ（試験で固定）ので、settings の `subagents.agentOverrides.<役>.systemPrompt` で、機のツールに合わせた文面へ置き換える。文面は `home/.chezmoitemplates/pi-agent-prompt-researcher`・`pi-agent-prompt-evidence-auditor`（組み込みの本文の派生。ツールの節だけを機で出し分け、`source_check` の代わりに「原文を自分で読み、該当の一節を引用し、手作業の確認と書く」とした。取得に失敗したら `Missing evidence` に書き、抜粋を原典として扱わない）。`systemPrompt` は**この repo が管理するキー**で、`chezmoi apply` のたびにこの文面へ揃える（利用者が書き換えても戻る。`tools`・`model` など他のキーは保つ）。
  - **維持費と撤去**: `pi-subagents` を上げたら、組み込みの本文（`~/.pi/agent/npm/node_modules/pi-subagents/agents/`）と見比べて追随する。`pi-web-access` のように、組み込みの prompt が前提とするツールを入れたら、この上書きを外す。
  - 会社 PC の prompt は、組み込みの MCP の登録名（`mcp__webfetch__fetch`・`mcp__agentcore_websearch__web_search_tool__WebSearch`）で指す。

### pi-mcp-adapter を使わない理由（2026-11-17）

会社 PC も、家の機と同じ **pi 組み込みの MCP** に一本化した（`pi-mcp-adapter` を `pi-stock-packages` から外した）。`pi-mcp-adapter` が入ると `/mcp` を登録し、pi は組み込みの MCP を読み込まない（pi の `mcp.md`。起動時の通知「registers command `/mcp`, so built-in extension `mcp` was not loaded」はこの結果）。両方は使えず、選ぶ必要があった。

| 観点 | 組み込み | adapter（外した） |
| --- | --- | --- |
| 設定 | `mcp.json` の 1 つ | `mcp.json` に加えて `mcp-adapter.json`（子の `mcp:` の解決用）が要った |
| ツール名と権限 | `mcp__<server>__<tool>`。permission-system が MCP として扱い、方針の `mcp` の allow が効く。plan mode の名前も確定 | direct の登録名は `<server>_<tool>`。permission-system は拡張のツール（既定は ask）として扱い、`mcp` の規則が効かない（deferred 用の `mcp__…` 登録は別）。`mcp.json` の `exposure` は adapter が `directTools` などへ変換する |
| 子の起動 | 前景・背景のどちらも（文書上。前景は未実測） | 背景の子だけ。ツール情報の cache が要り、初回は再起動が要ることがあった |
| 利点 | 構成が単純。保守者が増えない | サーバの遅延起動・MCP の管理画面・OAuth の keychain・他の CLI の設定の取り込み |

- 外した理由: 会社 PC の MCP は 2 つの stdio サーバ（`agentcore-websearch`・`webfetch`）で、adapter の利点（多数のサーバ・OAuth）が要らない。一方で、権限・名前・設定の二重管理の費用が実際に出た（`webfetch_fetch` の権限、`-builtin:mcp` を `chezmoi apply` が消して通知が出続ける問題）。出典: adapter 7.0.1 の `CHANGELOG.md`・`index.ts`・`types.ts`・`pi-builtin-mcp.ts`、pi 1.5.0 の `mcp.md`・`resource-loader.js`、permission-system 42.0.0 の `tool-kind.ts`。
- **再び入れる条件**: MCP のサーバが増える（遅延起動が要る）、OAuth の keychain が要る、組み込みで足りない機能が出たとき。そのときは、ツール名の権限（`<server>_<tool>` の厳密名の allow）と `-builtin:mcp`（`modify_pi_stock_settings.py.tmpl` は `-builtin:` の項目を取り除く）の扱いを先に設計する。
- **移行**: `chezmoi apply` で `packages` から adapter が外れ、adapter が `settings.json` の `extensions` に足した `-builtin:mcp` も取り除かれる（組み込みの MCP が戻る）。すでに配った `~/.pi/agent/mcp-adapter.json` と、adapter の npm 実体は残る。どちらも読まれない。不要なら利用者が消す。
- 会社 PC の実機での動作（組み込みの MCP で、子が検索・取得を呼べること）は**未確認**。

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
2. `chezmoi apply` で pi の `mcp.json` を生成する
3. 確認: pi の `/mcp` で `agentcore-websearch` が connected になり、検索のツールが 1 つ見えること

URL が未設定だとラッパーは、理由を stderr に出して、ツールの無い空のサーバとして待機する（上の「使えない機」。MCP クライアント側では接続できて、ツールが 0 件に見える）。

#### 料金と制約

- 検索 1,000 回あたり $7。Gateway の呼び出しなどは別に課金される
  （[料金](https://aws.amazon.com/bedrock/agentcore/pricing)）
- `query` は 200 文字以内、`maxResults` は 1〜25（既定 10）
- 返るのは関連部分の抜粋・URL・タイトル・公開日。本文が要るときは、URL を指定して取る [`webfetch`](#webfetch会社-pc-のページ取得) と組み合わせる
- 利用条件として、結果を表示するときは出典リンクを残す
- Target 単位でドメインの許可・除外リストを強制できる（エージェント側から解除できない）

#### MCP のプロトコルの版（2026-07-28 への対応。2026-11-25 に確認）

MCP の仕様 **2026-07-28**（2026-07-28 公開）は、`initialize` の握手とプロトコルのセッションを廃止し、リクエストごとに版・クライアントの情報・能力を `_meta` で運ぶ（`server/discover` は任意の事前の問い合わせ。stdio では旧式のサーバを見分ける探りにも使う）。
**旧式（2025-11-25 以前）との共存が仕様にある**ので、更新は区間ごとに独立して進められる。

| 区間 | 今の版 | 2026-07-28 |
| --- | --- | --- |
| pi ⇔ ラッパー（stdio） | pi 1.6.0 の組み込みの MCP クライアントは**最大 2025-11-25**（実体の `LATEST_PROTOCOL_VERSION` で確認。`server/discover` を送らず、`initialize` で始める） | **pi 側が未対応**。Issue [#10416](https://github.com/earendil-works/pi/issues/10416)・PR [#12479](https://github.com/earendil-works/pi/pull/12479)（2026-11-24 に open。未マージ）。対応した pi は、まず `server/discover` で探り、旧式なら `initialize` へ戻る |
| ラッパーの空のサーバ | 旧式（`initialize`）と新式の**両方に答える**（2026-11-25 に追加） | 対応済み。`server/discover`・`_meta` に版を持つ `tools/list` などに、握手なしで答える（`resultType`・`ttlMs`・`cacheScope` を付ける）。知らない版は `-32022` で、対応する版の一覧を返す |
| proxy ⇔ AgentCore Gateway（HTTPS） | `mcp-proxy-for-aws-cli==1.7.0`（fastmcp 3 系）。Gateway へは 2025 系で話す | proxy **2.0.0**（2026-11-18）が MCP Python SDK v2（2026-07-28 対応。旧式にも同じ実装で答える）へ移った。**据え置き**（下の「上げる条件」） |
| AgentCore Gateway | 既定は 2025 系（版ヘッダが無いリクエストは 2025-03-26） | アカウント側の設定。`UpdateGateway` の `supportedVersions` に `2026-07-28` を足すと、その版を要求したクライアントだけが新式になる。旧式のクライアントは、そのまま使える |

**proxy を 2.0.0 に上げる条件**（会社 PC の実機が要る。この repo の機では確かめられない）:

1. 2.0.0 は大きな版の更新（fastmcp 4・MCP Python SDK v2。Python 3.11 以上）。コマンドの引数（`--service`・`--region`・`--disable-telemetry`）は 2.0.0 の `--help` で残っていることを確かめた。**Gateway との通信（Gateway が 2025 系だけのとき・2026-07-28 も足したとき）と、pi の旧式の stdio への応答は未確認**。
2. 会社 PC で `PROXY` を 2.0.0 にして、pi の `/mcp` で検索が通ることを、Gateway の 2 つの状態（2025 系だけ・2026-07-28 を足した）で確かめる。
3. 通ったら、ラッパーの `PROXY` と試験（`test_wrapper_with_a_gateway_runs_the_pinned_proxy`）の版を上げる。Claude Code の写し（`claude-mcp-servers.json`）はラッパーを呼ぶだけで、版を持たない。

**得るもの（推測）**: 検索 1 本を stdio のラッパー越しに呼ぶ使い方では、2026-07-28 の利点（水平に増やせる・キャッシュ・ヘッダでの振り分け）はほぼ効かない。上げる理由は、1.7.0 → 2.0.0 の間の依存の脆弱性の修正（proxy の CHANGELOG の 1.8.0 の記載）が主になる。

出典（2026-11-25 に取得）: [MCP 仕様 2026-07-28 の変更点](https://modelcontextprotocol.io/specification/2026-07-28/changelog)・[版の互換](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)・[stdio](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)・[server/discover](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)、
[AWS: AgentCore Gateway と MCP 2026-07-28](https://aws.amazon.com/blogs/machine-learning/how-agentcore-gateway-supports-the-mcp-2026-07-28-spec/)（2026-07-28）、
[mcp-proxy-for-aws の CHANGELOG](https://github.com/aws/mcp-proxy-for-aws/blob/main/CHANGELOG.md)（v2.0.0 は 2026-11-18）、
[MCP Python SDK v2.0.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0)（2026-07-28）。

#### コネクタの版（確認と更新）

出典は AWS 公式の [Web Search Tool](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html) と
[Connector versions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-versions.html)（2026-11-16 に本文を取得して確認）。

**target は作成時の版に固定され、自動では新しくならない。**
版を指定せずに作ると、そのときの既定の版が入る。**その後に既定の版が上がっても、既存の target は上がらない。**
新しい版にするには `source.version` を指定して target を更新する（指定せずに更新すると、今の版のまま）。
minor・patch は後方互換（追加だけ）。major は破壊的変更で、移行ガイドが付く。
この repo は版を指定しない（サンプルの CloudFormation で作る）ので、**会社の target の版は、作った時点の既定のまま**である（版は未確認）。

| 版（`web-search`） | 公開日 | 変更 |
| --- | --- | --- |
| 1.3.0（現在の既定） | 2026-10-19 | `tools/list` にツールの注釈（`readOnlyHint: true`・`openWorldHint: true`）が付く。読み取り専用のツールを絞り込む MCP クライアントが、検索ツールを見つけて呼べる |
| 1.2.0 | 2026-07-20 | 呼び出しごとの絞り込み `filters`（ドメインの許可・除外 各 100 まで、公開日の範囲 ISO-8601 UTC） |
| 1.1.0 | 2026-06-15 | `structuredContent`、`publishedDate`、スニペットの改善 |

- **版の確認**: `GetGatewayTarget` の応答の `source.version`。または、`tools/list` のスキーマで、`filters` があれば 1.2.0 以上、注釈があれば 1.3.0 以上。AWS の権限が要るので、リポジトリからは確かめられない
- **更新の効果**: 1.2.0 以上で、モデルが公式サイトのドメイン（`domainFilter.include`。ルートドメインはサブドメインにも一致）や期間（`publishedDateFilter`）で絞れる。1.3.0 の注釈が、pi の plan mode や MCP の扱いにどう効くかは**未確認**
- **絞り込みの合成**: target 単位のリスト（管理者が設定。エージェントには見えない）と呼び出しごとのフィルタは、除外が**和**、許可が**積**になる。許可リストが両方にあって共通のドメインが無ければ、結果は 0 件。呼び出し側は、target の除外を解けず、許可を広げられない
- **公式サンプルの README は古い**: 「Web Search は us-east-1 のみ」と書くが、公式 docs 本体は 7 つのリージョン（`us-east-1`・`us-east-2`・`us-west-2`・`eu-west-1`・`ap-southeast-2`・`ap-northeast-1`・`us-gov-west-1`）を挙げる。docs 本体を正とする
- **検索だけでは足りないとき**（本文・原文の確認が要るとき）: URL を指定して取る [`webfetch`](#webfetch会社-pc-のページ取得)（2026-11-17）を使う。同じ Gateway に別の built-in connector を足すこともできる。**Web Answer**（`web-answer`。質問に対し、検索とページの読み込みをして、引用つきの回答を返す。**原文は返さない**。`us-east-1` のみ。版 1.1.0 は 2026-11-04）は、原文の取得の代わりにならない。足すかは、引用つきの回答が要る場面の頻度で決める
