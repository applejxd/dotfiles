# MCP サーバの設定

MCP サーバの定義（`common.toml` の `[[mcp]]`）を、各 AI CLI の形式へ生成する仕様と、AgentCore Web Search の構成。生成の全体と所有権は [設定の生成と所有権](agent-config-generation.md)。

## MCP サーバ

MCP サーバの定義も `common.toml` の `[[mcp]]` が単一ソース。同じサーバを
CLI ごとに書くと、URL を変えたときに片方だけ古いまま残る。

```toml
[[mcp]]
id = "agentcore-websearch"
purpose = "AgentCore Web Search で web 検索する (Gateway の URL がある機だけ)"
clis = [{{ if eq (includeTemplate "is-work" .) "true" }}"claude", "opencode", "pi"{{ else }}"pi"{{ end }}]
requires_env = "AGENTCORE_GATEWAY_URL"
transport = "stdio"
command = "uv"
args = [
  "run", "--no-project", "--quiet",
  '{{ .chezmoi.homeDir }}/.config/agents/agentcore_websearch_mcp.py',
  "--service", "bedrock-agentcore", "--region", "us-east-1", "--disable-telemetry",
]
```

| CLI | 生成先 | 生成する仕組み |
| --- | --- | --- |
| Copilot CLI | `~/.copilot/mcp-config.json` | `generate.py --target copilot-mcp` |
| OpenCode V2 | `~/.config/opencode/opencode.json` の `mcp.servers` | `generate.py --target opencode-config` |
| Codex CLI | `~/.codex/config.toml` の `mcp_servers` | `modify_config.toml` が `fromToml` で描画 |
| Claude Code | `~/.claude.json` | `400_unix/410` (Unix) と `300_windows/346` (Windows) が `claude mcp add-json` で登録 |
| pi（Unix・Windows） | `~/.config/pi/harness/rules.json` の `mcp` | `generate.py --target pi-harness`。フルガードが起動のたびに `registerMcpServer` で登録する（[pi のガード](guard/pi-guard.md#mcp)。`mcp.json` へ書く経路は無い。[経緯](../research/agents/agent-config-generation-notes.md)） |

Gemini CLI と Antigravity は使わないため対象外。既存の定義はそのまま残す。

**`[[mcp]]` の任意のキー `exposure`（pi だけに効く）**: モデルへのツールの見せ方で、`direct` / `codemode` / `deferred` / `hidden`（不正な値は生成が止まる）。
**省略すると pi には `direct` を出す。** pi 本体の既定は `codemode` だが、`pis` は `-ne` で組み込みの `codemode` / `tool_search` を外すので、
既定のままだとツールがモデルから呼べない（[実測 E6](../research/agents/pi-extension-under-harness.md#記録-e6--2026-10-11)）。
`direct` はツール定義が常駐する（1 ツールで数十トークン）ので、大きいサーバを足すときは、そのサーバだけ `deferred` などに変えて試す。
他の CLI の定義には `exposure` を混ぜない。`pis` では MCP のツールは役割の既定（実装役は確認）になる。

`agentcore-websearch` は全機に配る（使うかは実行時に決まる。下の「AgentCore Web Search」。`deepwiki` は外した。[経緯](../research/agents/agent-config-generation-notes.md)）。
`[[mcp]]` が 1 つも無いと `mcp` キー自体が生えないので、参照側は `hasKey` で受けること（`missingkey=error` で描画が止まる）。
deepwiki の代わりの OSS 調査は `oss-research` スキル（インストール済みの実体・配布物・
版を固定したソースに直接当たる）、GitHub の操作は github MCP を使わず
`github-operations` スキル（gh CLI）が担う。

**入れる CLI を絞るには `clis` を書く。** 省略すると 5 つ全部に入る。
`agentcore-websearch` は、会社 PC（`is-work`）では `clis = ["claude", "opencode", "pi"]`、個人の機では `["pi"]` にしてある
（家で、動かない MCP を Claude Code・OpenCode に登録しないため。Copilot は内蔵の web 検索があり、Codex は使わない）。書ける値は `claude` /
`copilot` / `opencode` / `codex` / `pi` で、それ以外を書くと apply が止まる。

その結果、**Copilot / Codex 向けのサーバは現在 0 件**である。
Codex の重複宣言ガードは `[[mcp]]` が 1 つ以上ないと発火しないので、試験だけ
合成したソースで確かめている。

**宣言を消しても Copilot / OpenCode / Claude の生成先からは消えない。**
`merge_copilot_mcp` / `merge_opencode_mcp` は宣言されたサーバを足す・更新するだけで、
消えたサーバを刈らない (Claude も未登録のものを追加するだけ)。既に生成された
設定から取り除くには各 CLI の削除コマンドを使う。例外は Codex で、
`modify_config.toml` が管理ブロックごと描き直すので宣言から消せば消える。

**transport 名の違い**: OpenCode は `http` を `remote`、`stdio` を `local` と呼び、
`command` は実行ファイルと引数を **1 本の配列**で書く (Copilot は `command` と
`args` に分かれる)。`generate.py` が `[[mcp]]` から各形式へ変換する。

**Claude だけ生成ではない理由**: user scope の定義先である `~/.claude.json` は
MCP の `headers` / `env` に秘密が入りうるため chezmoi 管理外にしている
([ADR-0005](../adr/0005-agent-runtime-config-as-secret.md))。
そのためファイルを書かず、`[[mcp]]` のうち **未登録のものだけ** を CLI 経由で
追加する。既に同名のサーバがあれば触らないので、手元で差し替えた定義は残る。
`run_onchange_` なので `[[mcp]]` を増やすと次の `chezmoi apply` で登録される。
`add-json` を使うのは、http と stdio を同じ経路で登録できるため。

**適用範囲の非対称性**: この仕組みが揃えるのは「配布する既定値」であって、
全 CLI の状態の完全同期ではない。宣言から消したサーバは Copilot / OpenCode / Claude の
手元設定からは消えない (Codex は管理ブロックごと再生成するので消える)。
`chezmoi apply --exclude=scripts` や `chezmoi diff` では Claude の登録だけが
走らない点も同じ理由による。

**Codex の衝突**: 管理ブロックの外に同名の `[mcp_servers.<id>]` があると
TOML の重複宣言になり、Codex が設定ファイル全体を読めなくなる。黙って壊さない
よう、`modify_config.toml` が衝突を検出して `apply` を止める。

**ユーザ・OS による出し分け**: `common.toml` 側のテンプレートに書く。生成側
3 つは展開後の表だけを見るので、条件の解釈は 1 か所で済む。上の例では
`.chezmoitemplates/is-work` で、`agentcore-websearch` を入れる CLI の一覧を切り替える
（[会社 PC の判定](agent-model-assignment.md#会社-pc-の判定)）。

**transport**: `http` は `url`、`stdio` は `command` / `args` を書く。
`stdio` のサーバは `uvx` から起動する形にしておくと、本体を別途入れずに済み、
`mise reshim` の要否やバックエンドの破損に左右されない。MCP サーバは sandbox
内で動く (Copilot は `sandboxMcpServers: true`) が、`uvx` が使う `~/.cache/uv`
と `~/.local/share/uv/tools` は書き込み許可済みで、`pypi.org` /
`files.pythonhosted.org` も許可済みなので追加設定は要らない。

**生成側が触らないもの**: Copilot の `headers` / `env` / `tools`、OpenCode の
`headers` / `environment` / `oauth`、および common.toml に無いサーバは既存値の
まま残す。前者は秘密、最後は公開範囲の設定で、どれも `common.toml` が持たない
情報だから。

未対応の transport・重複 id・不正な id・transport に無いキー (typo) は
`generate.py` が `apply` を止める。トークンは `common.toml` に書かず、
環境変数参照として各 CLI 側で設定する。

### AgentCore Web Search

Bedrock の PC で web 検索を提供する MCP サーバ。Claude Code の内蔵 `WebSearch` は
Anthropic 側のサーバ機能で、Bedrock 経由では使えない
（[Claude Code on Amazon Bedrock](https://code.claude.com/docs/en/amazon-bedrock)）。
OpenCode V2 の内蔵 `websearch` は Exa / Tavily などの別契約が要る。
そこで、AWS 内で完結する AgentCore Web Search を両方に入れる
（[公式ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html)）。

```text
Claude Code / OpenCode
  └─ stdio ─ ~/.config/agents/agentcore_websearch_mcp.py
               └─ uvx mcp-proxy-for-aws-cli (手元の AWS 認証情報で SigV4 署名)
                    └─ HTTPS ─ AgentCore Gateway ─ Web Search コネクタ
```

| 項目 | 決めたこと |
| --- | --- |
| 対象 | **全機に配る**（会社 PC で Copilot を使うので、`llm-provider` では切らない）。使うかは実行時に決まる（下の「使えない機」）。`clis` は会社 PC が `claude` / `opencode` / `pi`、個人の機が `pi` |
| リージョン | `us-east-1`（`[provider.amazon-bedrock]` と揃える） |
| Gateway の URL | アカウント固有なのでソースに書かず、環境変数 `AGENTCORE_GATEWAY_URL` から読む |
| 認証 | AWS の既定の認証情報（`AWS_PROFILE` / `~/.aws`）。API キーは無い |
| proxy の版 | `mcp-proxy-for-aws-cli` をラッパーの `PROXY` で固定。依存まで固定した CLI 用の配布物 |
| OpenCode 内蔵の検索 | `[opencode] websearch = false` で消す（v2.0.14 で、設定するとツール一覧から消えることを確認） |

**使えない機（家など、URL も AWS の認証も無い機）**: 失敗させず、**ツールの無い空の MCP サーバ**になる（ラッパーが stdio で `initialize` / `tools/list` などに空で答える）。
起動の失敗が毎回の通知になるのを避け、「家で設定されても、認証しなければ何も起きない」を実現する。空になるのは、`AGENTCORE_GATEWAY_URL` が無い・`https://` でないとき、
pi のサンドボックスの内側（`PI_HARNESS_BOUNDARY=1`。内側では AWS の認証情報を使えない）のとき。
Unix の pi のフルガードは、`[[mcp]]` の `requires_env`（`AGENTCORE_GATEWAY_URL`）が空の機では、そもそも登録しない（プロセスも起動しない）。
**`pis` の内側で AgentCore を使うには、ブローカーでの中継が要る**（Bedrock のブローカー（段 U7b）の後。[CHG-0037](../change/0037-pis-usability-and-telemetry.md)）。
それまで、会社 PC の `pis` の内側では使えない（境界なしの `pi` か、Windows の素の `pi` では使える）。**未確認**: 起動失敗時の pi の挙動、Windows の `uvx`、内側の環境変数に `PI_HARNESS_BOUNDARY` が伝わるか。

**ラッパーを挟む理由**: proxy は Gateway の URL を位置引数でしか受け取らない。
MCP の定義に URL を書かずに済ませるには、環境変数から読んで渡す層が要る。
ラッパーは Python で書き、`uv run` から起動する（Windows に `python3` が無いため）。
MCP クライアントは `~` を展開しないので、ラッパーのパスは `.chezmoi.homeDir` から絶対パスにする。

**`ocs`（隔離版 OpenCode）では使えない。** Bedrock 自体が `ocs` から届かないのと同じ理由で、
境界が `~/.aws` も Gateway のドメインも開けていない。

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
2. `chezmoi apply` で Claude Code へ登録し、OpenCode の設定を生成する
3. 以前の `ddgs` は宣言から消しても登録が残るので、1 回だけ `claude mcp remove ddgs -s user` を実行する
4. 確認: Claude Code の `/mcp` で `agentcore-websearch` が connected になり、`WebSearch` ツールが 1 つ見えること

URL が未設定だとラッパーは理由を stderr に出して終了する（MCP クライアント側では接続失敗として見える）。

#### 料金と制約

- 検索 1,000 回あたり $7。Gateway の呼び出しなどは別に課金される
  （[料金](https://aws.amazon.com/bedrock/agentcore/pricing)）
- `query` は 200 文字以内、`maxResults` は 1〜25（既定 10）
- 返るのは関連部分の抜粋・URL・タイトル・公開日。本文が要るときは `webfetch` と組み合わせる
- 利用条件として、結果を表示するときは出典リンクを残す
- Target 単位でドメインの許可・除外リストを強制できる（エージェント側から解除できない）
