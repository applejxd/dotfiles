# サンドボックス内のエージェントへの認証の渡し方（AWS・LiteLLM・ブローカー・サプライチェーン）

<!-- 現在の総合判断は docs/change/ の候補比較表が正本（CHG-0037）。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 D2 — 2026-10-24

- **対象**: 会社（Bedrock・AgentCore Gateway）と家（GitHub）で、境界（Fence）の中のエージェントが、`aws`・`gh`・`git`・MCP を、**強い認証情報を内側に置かずに**使う手段
- **方法の限界**: 公式の文書・README・各社の記事を、`explore` の子 5 件が Web 検索で調べた。**動かして試したものは無い**。記事の日付は 2026 年。親が確かめた行は「確認済み」（保存先 `.tmp/research/openshell-vs-pis-sandbox/sources/`）。本文を取得していない（検索の抜粋だけの）ものは「抜粋のみ」と書く

### 問い

[CHG-0037](../../change/0037-pis-usability-and-telemetry.md) の候補 G「認証情報を、狭い権限で内側へ渡す」を実現する手段は何か。以前は、LiteLLM で「漏れてもよいキー」を渡す方法を使った（起動が 1 回だけの `hermes` の場合）。起動・終了が頻発する `pi` で、常駐のデーモンが要るか。LiteLLM はサプライチェーン攻撃の対策が要る。

### 事前の予想

LiteLLM のような常駐のゲートウェイが要る。代替は少ない。

### 結果

#### A. Bedrock・AgentCore 固有

- **Bedrock API key**: 短期は**最大 12 時間**（またはコンソールのセッションの時間のうち短い方）で、**生成した IAM プリンシパルの権限を継承**する。「本番では短期キー」と AWS が推奨（確認済み: `aws-bedrock-api-keys.md:15`、`:17`）。長期は IAM ユーザーが作られ、「探索用のみ」。使い方は環境変数 `AWS_BEARER_TOKEN_BEDROCK` か `Authorization: Bearer`。短期キーは、クライアント側で SigV4 の事前署名として生成され、CloudTrail に作成が記録されない（子の抜き書き。2025-10-17 のブログ）。**pi は `AWS_BEARER_TOKEN_BEDROCK` に対応している**（`docs/providers.md:176`〜`:199`。子の抜き書き）。AgentCore Gateway がこのキーを受け付けるという記載は、**見つからなかった**
- **ローカルの SigV4 署名プロキシ**: `awslabs/aws-sigv4-proxy`（AWS 公式 OSS、Apache-2.0、Go）は、受けた HTTP 要求に署名して、Host ヘッダーの宛先へ転送する。`-s Authorization` のように、受けたヘッダーを除去できる（確認済み: `awslabs-aws-sigv4-proxy.md:185`、`:187`）。プロキシ側の認証情報は、SDK の既定の探索順で解決し、`--role-arn` で AssumeRole もできる。**呼び出し側は認証情報なしで呼べる**。README の例は S3・SQS・API Gateway で、**Bedrock・AgentCore の例は見つからなかった**
- **エンドポイントの上書き**: `AWS_ENDPOINT_URL` とサービス別の `AWS_ENDPOINT_URL_<SERVICE>` で、SDK の宛先を `http://` のローカルへ向けられる（AWS 公式の SDK リファレンス）。ただし SDK ごとの対応差があり、aws-sdk-rust では `AWS_ENDPOINT_URL_BEDROCK_AGENT(_RUNTIME)` が無視された報告がある（Closed）。**pi の使う SDK が `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` に対応するかは未確認**。pi の docs に、Bedrock のエンドポイントの上書きの記述は**無い**
- **「ダミーの鍵を内側に渡し、プロキシが再署名する」構成**: 個人のリポジトリ（`cjohnstoniv/wardyn`）の Open の提案（2026-10-18）があるだけで、**実装済みの実例は見つからなかった**
- **AgentCore Gateway の受け付け認証**: JWT・IAM・認証なし。1 つのゲートウェイにつき方式は 1 つ（AWS re:Post の回答）。**JWT（`CUSTOM_JWT`。IdP の `discoveryUrl` と `allowedClients`）にすれば、AWS の認証情報なしで呼べる**（公式の文書）。`aws/mcp-proxy-for-aws` は SigV4 専用。AWS のサンプル（`aws-samples/sample-mcp-identity-proxy-for-aws`、MIT-0、★0）が、OAuth のベアラートークンや API キーを注入する
- **IAM で絞る**: AssumeRole は 900 秒以上、セッションポリシーは「権限を絞る方向にだけ」働く。`aws configure export-credentials` は `credential_process` 用の形式で出せる。IAM Roles Anywhere の `serve` は、ローカルのエンドポイントで、IMDSv2 互換の一時的な認証情報を配る（抜粋のみ）

#### B. LiteLLM と代替のゲートウェイ

- **仮想キー**: **Postgres が必須**（「Need a postgres database」。DB なしでは仮想キーを解決できない）。`max_budget`・`budget_duration`・`duration`・`models`・レート制限などで絞れる。Bedrock の認証情報は、config か環境変数で LiteLLM 側に置く（長期の認証情報がゲートウェイに残る）。OpenAI 互換と Anthropic 互換の両方を出す
- **常駐**: 公式の本番の推奨は常駐の運用（1 worker あたり 1 vCPU・4Gi、起動の probe は最大 300 秒）。**起動ごとに起動・終了する運用を扱った公式の文書は見つからなかった**。メモリリークの報告がある
- **サプライチェーンの事件が 2 件**（公式のブログ）:
  - **2026-03-24**: `litellm==1.82.7`・`1.82.8` が約 40 分、PyPI に出た。環境変数・SSH 鍵・クラウドの認証情報を窃取（`models.litellm.cloud` へ送信）。公式の Docker イメージは影響なし
  - **2026-10-21（3 日前）**: `litellm==1.107.0` が **PyPI に約 2 時間（11:39〜13:23 UTC）、Docker の `latest` なども 11:46〜14:20 UTC**（確認済み: `litellm-incident-oct-21-2026.md:24`、`:61`）。**Trusted Publisher・不変タグ・Docker の署名は、既に導入済みだったが突破された**（開発者の GitHub CLI の認証情報の窃取から）。Python の起動のたびに `cook.pth`・`sitecustomize.py` が動く（pip を実行しても再実行される。確認済み: `:89`）。影響は「固定していない版を入れた場合」。**プロキシ DB 内のプロバイダーのキーと、環境にあるすべての秘密が、回転の対象**（公式の記述）。Wiz は、盗まれた AWS の認証情報が、約 4.5 時間後に、Bedrock へのアクセスの確認に使われたと報告（抜粋のみ）
- **CVE-2026-42208**: キー検証の経路の SQL インジェクション。「プロキシに到達できる攻撃者が、認証なしで SELECT を発行できる」。開示から 36 時間後に標的型の攻撃（Sysdig。抜粋のみ）。修正は 1.83.7
- **代替**（出典どおり。Star・ライセンスは第三者の記述を含む）: Bifrost（`maximhq`。Go とみられる。仮想キー・予算。Apache-2.0。9.1k Star）、Envoy AI Gateway（Kubernetes 前提。SigV4 署名）、Portkey（TypeScript。MIT。Gateway 2.0 はプレリリース）、Helicone（Rust）、`claude-code-router`（Node）、`bedrock-access-gateway`（**2026-09-04 にアーカイブ**。Bedrock 自体が OpenAI 互換・Anthropic 互換の API を提供するようになった、と README が述べる）。Kong と OpenRouter は未調査

#### C. 認証情報ブローカー・シークレット注入プロキシ（全般）

- **Infisical Agent Vault**（MIT、`ee/` を除く。単一バイナリ。MITM 方式）: 「エージェントが付けた認証情報を除去し、暗号化したストアから正しい認証情報を注入する」（抜粋のみ）
- **nono**: ローカルのリバースプロキシと phantom token（エージェントは `localhost` へ平文の HTTP）。**WSL2 では既定で使えない**（[記録 C1](sandbox-alternatives-comparison.md)）。`--env-credential` は値が子の環境に出る
- **srt の `credentials` の `mask`**: サンドボックス内には sentinel だけを置き、プロキシが外向きで置換する（要 `tlsTerminate`。実験）。AWS の署名の再署名への言及もある（確認済み: `srt-readme-official.md:816`、`:676`）
- **OpenShell の provider**: 不透明な placeholder を環境変数に置き、承認済みのホストへの要求にだけ実値を付ける。**Docker sbx**: `sbx secret`。「認証情報はサンドボックスのファイルシステムに入らない」
- **Envoy の credential injector**（OSS）、**agentgateway**（第三者の記事）、**Aembit**（商用）、個人の mitmproxy 自作（`credkeeper`、`agent-sandbox`、`desbma/agent-sandbox` など）。**`bw`（Bitwarden の個人保管庫）を注入元にする既製品は、見つからなかった**
- 共通の限界: プロキシが許可した API 操作の悪用は防げない（第三者の比較記事）

#### D. `gh`・`aws`・`git`・`ssh`

- **GitHub**: App の installation token は**1 時間で失効**し、権限とリポジトリを絞れる（公式の文書）。細粒度 PAT の文書は未取得。devcontainers は、ホストの `ssh-agent` の転送と、`/tmp` の IPC ソケット経由の credential helper の転送を行う（転送が壊れる報告もある）。個人のホスト側ラッパー（`honnibal.dev`、sudo 方式）は、著者自身が「多層防御であって、サンドボックスではない」と述べる。`gh` 専用の個人実装は、`GH_TOKEN` にダミーを入れ、プロキシが実トークンに差し替える
- **AWS CLI**: SSO のトークンは `~/.aws/sso/cache/*.json` に平文で保存される（第三者・個人）。**これを内側から読めると、その期間は使われうる**（文面からの推論）。`aws-vault` は SSO の認証情報もキャッシュする。`granted` は未取得
- **SSH**: `ssh-add -h`（宛先の制約。OpenSSH 8.9 以降で、転送先も対応が要る）、`ssh-keygen -s` の証明書（期限つき）。`ssh-add -c` の本文は未確認。デプロイ鍵は未調査
- **実行時の注入**: `op run`（1Password）、`bws run`（Bitwarden **Secrets Manager**。個人保管庫の `bw` とは別製品）。どの方式でも、子プロセスの環境変数に値は出る

#### E. サプライチェーンの対策

- **公開から削除までの時間**（待機期間の根拠）: LiteLLM の 1.107.0 は PyPI に約 **1 時間 44 分**、Docker Hub に約 2 時間 33 分（公式の記事の時刻から計算）。ほかは、約 2 時間（Endor Labs）、約 3 時間（axios、Datadog）、約 4〜5 時間（s1ngularity、Datadog）、3〜12 時間（個人ブログ）。待機期間の標準は 1〜3 日（pnpm 11 の既定は 1 日、Yarn 4.10 は 3 日、第三者の記事の「3 日ルール」）
- **uv**: `exclude-newer` に**相対の期間**（`24 hours`・`1 week`・`P7D`）を指定できる。`exclude-newer-package` で個別に除外できる（公式の文書）。pip 26.0 の `--uploaded-prior-to`、Renovate の `minimumReleaseAge`、Dependabot の `cooldown` がある。「待機期間は、マルウェアのスキャナーではない」（第三者）
- **PyPI の attestation（PEP 740）**: 「公開した Trusted Publisher を検証できる証拠」を提供するが、**クライアントでの検証は定めない**（Trail of Bits）。**今回の事件は、正規の provenance を持つ版でも悪意ある版が出る**例（Tensorlake の件の個人ブログ、LiteLLM 自身が Trusted Publisher を導入済みだった点）
- **`pip-audit`**: 「悪意あるパッケージを防ぐとは考えないこと」（公式の README）。GuardDog（Datadog）、OpenSSF の走査は、新規の版の静的解析
- **`mise`**: `mise.lock` に checksum と provenance を記録し、`mise install --locked` で検証する（公式）。Go: sumdb は検知用の透明性ログで、「侵害の防止ではない」
- **外向き通信の許可リスト**: TrendAI は、LiteLLM の事件で「ドメインの許可リストが、窃取の送信先 `models.litellm.cloud` を止められた」と述べる（抜粋のみ）。**専用ユーザーやサンドボックスでゲートウェイを封じ込める実践の一次資料は、見つからなかった**

#### F. 現行の `pis` の事実（リポジトリのファイルで確認）

- 内側へ渡さない環境変数: `DROP_ENV`（`GH_TOKEN`・`GITHUB_TOKEN`・`SSH_AUTH_SOCK`・`AWS_ACCESS_KEY_ID`・`AWS_SECRET_ACCESS_KEY`・`AWS_SESSION_TOKEN` など。`cli.py:34`〜`:48`）と、名前に `TOKEN`・`SECRET`・`PASSWORD`・`PASSPHRASE` を含むもの（`pi.py:64`）。`AWS_PROFILE`・`AWS_REGION` は除去しないが、`~/.aws` は境界で読めない。`*_API_KEY` は落とさない（`pi-guard.md:411`）。**認証情報用の「渡す」例外は、コードに無い**
- `auth.json` などは、起動ごとの agent 置き場へ写し、OAuth の更新分を終了後に戻す（`pi.py:41`、`:265`）
- **`ocs/relay.py` は、`pis` と同じプロセスの中で、`127.0.0.1` の空きポートに待ち受けるスレッドを起動し、終了時に止める**（`session()` の context manager。`relay.py:~165`、`pi.py` の `with relay.session(...)`）。Fence へは `allowedDomains=[]`・`defaultAction:"proxy"`・`upstreamProxy:"http://127.0.0.1:<port>"` で渡す。**`allowLocalOutbound` と Unix ソケットの設定は、リポジトリに無い**（Fence の仕様では、Linux は `allowLocalOutbound` ＋ `allowLocalOutboundPorts` が要る。[記録 D1](web-search-data-handling.md) の前の調査と、CHG-0037 の「通信の方針」を参照）
- pi の Bedrock: `AWS_PROFILE`・`AWS_ACCESS_KEY_ID` など・`AWS_BEARER_TOKEN_BEDROCK`・ECS/IRSA に対応。カスタムプロバイダー（`models.json`）は `baseUrl`・`apiKey`（`!command` で実行時に解決。キャッシュなし）を持ち、OpenAI 互換のローカルプロキシを指せる

### 考察

言える（原文の範囲）:

- **事前の予想は外れた。常駐のゲートウェイは必須ではない**。選択肢は 3 系統ある: (1) **短命のキーを、内側へ渡す**（Bedrock の短期 API key。最大 12 時間、専用の最小権限のロールで生成）、(2) **ホスト側の署名プロキシが認証情報を持ち、内側にはダミーだけを渡す**（`aws-sigv4-proxy` ＋ エンドポイントの上書き。または、注入プロキシ。`pis` と同じ寿命で起動できる型が `relay.py` にある）、(3) 常駐のゲートウェイ（LiteLLM・Bifrost など）
- **LiteLLM は、この用途では、リスクが大きい**: 事件が 2026-03 と 2026-10（3 日前）に 2 回あり、2 回目は Trusted Publisher・署名・不変タグを導入済みでも突破され、**ゲートウェイの DB に長期のプロバイダーのキーが残る**ことが、被害を拡大した（盗まれた AWS の認証情報が、約 4.5 時間後に Bedrock の確認に使われた）。さらに Postgres が要り、重い（公式の推奨は 4Gi）。(1)(2) は、ゲートウェイを持たないので、この攻撃の面が無い
- **サプライチェーンの対策は、「入れない」「固定する」「待つ」「封じ込める」の組み合わせ**: ハッシュの固定、`exclude-newer` の相対指定（1〜3 日）、署名や attestation は**必要条件だが十分条件ではない**（今回の事件で証明された）。外向き通信の許可リストが、窃取の送信先を止められた、という指摘がある
- `gh`・`aws` の CLI 向けには、**短命・最小権限の認証情報**（GitHub App の 1 時間のトークン、AWS の STS の一時的な認証情報）と、**ホスト側の注入プロキシ**（Agent Vault・mitmproxy など）の両方が成立する。SSO のキャッシュを内側へ見せるのは避ける

言えない:

- pi が使う AWS SDK で、`AWS_ENDPOINT_URL_BEDROCK_RUNTIME` が効くか、`AWS_BEARER_TOKEN_BEDROCK` を AgentCore Gateway に使えるか（見つからなかった）
- `aws-sigv4-proxy` が Bedrock・AgentCore の要求（ストリーミング、ヘッダー）で動くか（README に例が無い）
- Fence の中から、ホスト側のローカルポート・Unix ソケットへ届くかの実機の結果（仕様上は `allowLocalOutbound` ＋ ポートで可能）
- 本文を取得していない抜粋のみの項目（Wiz・Sysdig・Agent Vault の詳細など）

### 次の問い

- 最小の実験: Bedrock の短期 API key を、専用ロールで生成して `pis` に渡す（実装が最小。常駐なし）。pi が動くか、モデルの呼び出しが通るか（会社の機）
- AgentCore の検索: Gateway を JWT に変えるか、ホスト側の署名プロキシ（`mcp-proxy-for-aws` の宛先をローカルへ向ける）か
- `gh`: GitHub App の installation token（1 時間）を、ホスト側で発行して渡す、または注入プロキシ
- Fence の `allowLocalOutbound` ＋ `allowLocalOutboundPorts` で、`pis` の中から `127.0.0.1` のポートへ届くかの実機の確認
- LiteLLM を採用する場合の対策（ハッシュ固定、1〜3 日の待機、専用の封じ込め）と、他のゲートウェイ（Bifrost）の評価は、(1)(2) が不可のときだけ

### 参照

- <https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html>、<https://github.com/awslabs/aws-sigv4-proxy>、<https://docs.aws.amazon.com/sdkref/latest/guide/feature-ss-endpoints.html>、<https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html>、<https://github.com/aws/mcp-proxy-for-aws>
- <https://docs.litellm.ai/blog/security-incident-oct-21-2026>、<https://docs.litellm.ai/blog/security-update-march-2026>、<https://docs.litellm.ai/docs/proxy/virtual_keys>、<https://docs.litellm.ai/docs/proxy/prod>
- <https://github.com/Infisical/agent-vault>、<https://nono.sh/docs/cli/features/credential-injection>、<https://docs.nvidia.com/openshell/how-it-works/providers/overview>、<https://docs.docker.com/reference/cli/sbx/secret/>
- <https://docs.astral.sh/uv/concepts/resolution/>（`exclude-newer` の相対指定）、<https://cooldowns.dev/>、<https://securitylabs.datadoghq.com/articles/dependency-cooldowns/>（第三者）

## 記録 D3 — 2026-10-24（LiteLLM の連携、設計を真似る要点、共有ゲートウェイと個人の GitHub）

- **観測日**: 2026-10-24。`explore` の子 4 件（検索 10 回以上、本文の取得あり）と、親の確認。親が確かめた行は「確認済み」（保存先 `.tmp/research/openshell-vs-pis-sandbox/sources/litellm-mcp-*.md`）。本文を読んでいない抜粋のみの項目は、そう書く

### 問い

(1) LiteLLM は、AgentCore と `gh`（GitHub）と連携できるか。(2) LiteLLM を採用しなくても、**設計を真似る**ために、何を押さえればよいか。(3) 利用者の制約: **`websearch` は、課内の全員で共有するゲートウェイ**で、**GitHub は、メンバーごとにアカウントを指定したい**。

### 結果

#### LiteLLM の MCP Gateway

- **MCP Gateway**: 「すべての MCP ツールに固定のエンドポイントを使い、キー・チームごとにアクセスを制御する」（確認済み: `litellm-mcp-gateway.md:9`）。transport は streamable HTTP・SSE・stdio。**stdio は、環境変数 `LITELLM_ENABLE_MCP_STDIO=true` を付けて起動しない限り無効**（確認済み: `:100`。設定ファイルや DB では有効にできない）。登録は `config.yaml` の `mcp_servers`、UI、`POST /v1/mcp/server`。クライアントは `x-litellm-api-key` に仮想キーを送り、ツール名はサーバー名の接頭辞つき（例 `github_mcp-search_issues`）
- **上流への認証**（`auth_type` の値。子の抜き書き。公式の表）: `none`・`api_key`・`bearer_token`（確認済み: `:223`）・`basic`・`authorization`・`token`（GitHub 形式）・`oauth2`（`authorization_code` と `client_credentials`）・`oauth2_token_exchange`・`oauth_delegate`・`true_passthrough`・**`aws_sigv4`**。ほかに `static_headers`、クライアントのヘッダーを通す許可リスト `extra_headers`
- **AgentCore との連携**: 「AWS Bedrock AgentCore 上のホストした MCP サーバーへ、SigV4 で接続する」（確認済み: `litellm-mcp-aws-sigv4.md:11`）。認証情報を省くと boto3 の既定の連鎖を使い、`aws_role_name` を設定すると AssumeRole（「recommended」と注記。確認済み: `:65`）。署名は、要求ごとに、本文のハッシュを含めて行う（子の抜き書き）。**対象は Runtime にホストした MCP サーバー**と読める。**AgentCore の Gateway（共有ゲートウェイ）を登録できるかは、文書に明記が無く、JWT での登録は見つからなかった**（SigV4 の署名先サービス名は同じ `bedrock-agentcore` なので動く可能性はあるが、推測）。Runtime のエージェントを呼ぶ経路も 2 つある（`bedrock/agentcore/<ARN>` と A2A ゲートウェイ）
- **GitHub との連携**: GitHub の MCP サーバー（`https://api.githubcopilot.com/mcp`）を、`auth_type: bearer_token` ＋ PAT で登録できる（確認済み: `:266`）。OAuth は、GitHub が動的なクライアント登録に対応しないので、事前登録したアプリの `client_id` と `client_secret` を使う（GitHub 側の回答。2026-05）。LiteLLM の UI で認証 URL の未設定エラーが出る報告がある。**`gh` の CLI をプロキシする機能は、見つからなかった**（LiteLLM が扱うのは HTTP・MCP の経路で、CLI は範囲外）
- **ユーザーごとの認証**: `is_byok`（ユーザーが自分のキーを保存。DB に暗号化して、`(user_id, server_id)` をキーに保存）、ユーザーごとの OAuth（トークンを暗号化して保存し、更新して、その利用者の呼び出しに注入）、`env_vars` の `scope: user`、クライアントが `x-mcp-{alias}-{header}` で毎回持ち込む方式（LiteLLM は保存しない）。「キー・チーム単位で、保存した認証情報を上書きする機能は、ネイティブには無い」
- **アクセス制御・監査**: キー・チーム・ユーザーなど 6 階層の積集合。**既定は「どの階層にも一覧が無ければ、すべてのサーバーに到達できる」**で、`require_key_mcp_access_defined: true` が推奨。ツール単位の `allowed_tools`・`disallowed_tools`、ツール定義の固定（pin。ツールの名前・説明・スキーマの差分を検知して、tool poisoning を防ぐ）、`mcp_rpm_limit`、ガードレール
- **セキュリティ上の問題**（第三者の記事・公式ブログ。一部は抜粋のみ）: CVE-2026-59822（MCP の OAuth2 パススルーの fallback で、検証失敗時に空の認証に置き換わり、偽の Bearer で到達。1.84.0 で修正、CISA の KEV に 2026-09-02 登録）、CVE-2026-42271（MCP のテスト用エンドポイントの stdio 経由のコマンド注入。CVSS 8.7）、CVE-2026-30623（Anthropic の MCP SDK の stdio のコマンド注入）。**仮想キーが上流へ漏れる不具合**（`extra_headers` に `Authorization` を設定すると、`auth_type: none` などで仮想キーが上流へ漏れた。PR #46932、2026-10-20 にマージ）

#### 設計を真似る要点（LiteLLM から読み取れるもの）

1. **二層の認証を分ける**: ゲートウェイへの入場用の鍵（仮想キー）と、上流の認証情報を、別のヘッダー・別の保存先にし、**入場用の鍵を上流へ転送しない**（漏れた不具合の教訓）
2. **注入は、上流へ送る直前**: 静的な認証はヘッダーとして、OAuth は期限が切れていれば更新してから、SigV4 は要求ごとに本文のハッシュを含めて署名する。署名の後に、クライアント由来のヘッダーを足す
3. **書き込み専用**: 認証情報の入力は、返さず、伏せ字にする。一覧の API は秘密の値を返さない
4. **保存**: 環境変数の参照（`os.environ/NAME`）を既定にし、DB に置くなら、暗号化に専用の salt key を使う（マスターキーと分ける。後から変えると読めなくなる）。ユーザー別は `(user_id, server_id)` で暗号化
5. **既定を拒否にする**: 到達できるサーバーとツールは、許可を明示した鍵だけにする（LiteLLM の既定は「開いている」ので、真似るときは逆にする）
6. **ツール定義を固定する**: 差分が出たら警告（tool poisoning）。stdio は既定で無効（コマンド注入の教訓）
7. **ユーザー別の認証情報は、「保存する」「毎回持ち込む」の 2 通り**。後者は、ゲートウェイに長期の秘密が残らない

#### AgentCore Gateway 自体の外向き認証（既に使っている仕組みの拡張）

- target の種類ごとに、外向きの認証が選べる（公式の表の要約。子の抜き書き）: **MCP サーバーと OpenAPI の target は、なし・gateway ロール・OAuth 2LO・OAuth 3LO・トークン交換・API キー**。Lambda は gateway ロールのみ。API キーと OAuth の認証情報は、**AgentCore Identity の credential provider**（保存先は Secrets Manager）に置く。**gateway が自分で認証情報を取り（`GetResourceApiKey`・`GetResourceOauth2Token`）、エージェントには渡さない**。Identity の上限は、API キー provider 50 件・OAuth2 provider 50 件（調整可）。Identity は、Runtime か Gateway 経由なら追加料金なし
- **3LO（ユーザーごとの OAuth）**: GitHub の MCP サーバーを target にし、GitHub の OAuth アプリを Identity の組み込みの GitHub provider に登録する公式のブログ（2026-04-06）とサンプルがある。トークンは「workload identity と user identity の下の Token Vault」に入る。初回はユーザーの同意が要る。**3LO はユーザー ID を要するので、受け付け認証が AWS_IAM の Gateway との組み合わせは、文書で未確認**
- **GitHub の API キー（PAT）の target は、現時点で不具合の報告がある**: `aws/agentcore-cli#2550`（2026-10-07、Open）。`tools/list` は通るが、`tools/call` が HTTP 400 で失敗する（Gateway の MCP クライアントが送る `Accept` ヘッダーが、GitHub の要求を満たさないとみられる）。AWS 側の返答は見つからなかった。**GitHub App の installation token を発行する credential provider は無い**
- ツール単位の制御は Cedar のポリシー（呼び出し元の claim・ツール・引数）。ログは、ログ出力先を作ると CloudWatch などに出て、要求・応答の本文も出せる（ログに秘密が残る点に注意）。ユーザー単位のレート制限が 2026-08-06 に追加された。Web Search は 1,000 クエリあたり 7 ドル（公式）

#### 他のゲートウェイの設計

- **agentgateway**（Linux Foundation 配下。Apache-2.0。Rust。★5.5k）: **単一の静的バイナリ**、YAML 1 つで、Kubernetes は不要（第三者・AAIF の記事）。`backendAuth` に、静的キー・パススルー・クラウドの認証情報・署名 JWT・トークン交換。**`backendAuth: aws`（リージョン・サービス名・`assumeRole`）で SigV4**、Bedrock のプロバイダー設定（`auth: aws: {}`）、**AgentCore のバックエンドは IAM（SigV4）と JWT の両方**（ベンダーの docs）。仮想キー・トークン・予算・CEL のポリシー・レート制限。MCP（stdio・SSE・streamable HTTP）と OpenAI 互換の LLM プロキシ。**2026 年に CVE-2026-29791（CVSS 4.9）、GHSA-mvgg-jvj2-4frq（High 8.1、MCP の認可、v1.4.0 で対処）、GHSA-jwm2-83f3-52xc（Moderate）**。インストールは `curl … | sudo bash` が案内されている（採るなら、リリースのバイナリを、checksum で固定する）。DB の要否、署名・SBOM の有無は未確認
- **Bifrost**（Apache-2.0、Go、★9.1k）: `npx -y @maximhq/bifrost` で起動。**CVE-2026-90898（CVSS 9.8）: 管理認証が既定で無効の、2.1.0 より前の版で、認証なしで RCE**（抜粋のみ。本文は 403）。SigV4 の記述は見つからなかった。MCP のツールフィルターと仮想キーはある
- **Docker MCP Gateway**（MIT、Go、★1.6k）: **Docker Desktop 4.59 以上が前提**（Desktop なしは `DOCKER_MCP_IN_CONTAINER=1`）。MCP 専用で LLM のプロキシは無い。秘密は Docker Desktop の secrets 管理。SigV4 の署名は見つからなかった
- **Envoy Gateway / Envoy AI Gateway**: Kubernetes 前提。Secret を `HTTPRoute` のフィルターで注入（Basic・JWT・API キー）。**SigV4 の署名そのものではない**。IBM ContextForge は Python・DB あり
- 起動時間・メモリの実測値は、どの対象でも見つからなかった

#### 現行の `pi` と `pis` の MCP（リポジトリのファイルで確認）

- pi は MCP を**組み込み**でサポートし、stdio と streamable HTTP に対応（`docs/mcp.md:3`。旧式の SSE は非対応）。`registerMcpServer` は `url`・`headers`・`env`・`oauth`・`exposure` を受け、`env` と `headers` は `${VAR}` や `!command` を使える（`mcp.md:81`）
- **ただし、このリポジトリの設定生成は、http のサーバーには `url` しか出さず、`headers` を出さない**（`generate.py:2139`〜`:2153`）。`pis` は `-nbt -ne -e builtin:mcp -e <ハーネス>` で起動し、`-ne` が `codemode` と `tool_search` を外すので、**`exposure` が `codemode` / `deferred` のサーバーはモデルから呼べない**（既定は `direct`）。stdio のサーバーは、pi が子として起動する（pi は Fence の内側なので、内側とみられる。文書の明記は無い）
- ローカルの HTTP の MCP サーバー（`http://127.0.0.1:<port>/mcp`）の登録自体はできると読める（pi の `mcp.md` は `localhost`・`127.0.0.1` を例外として扱う）。**ただし、リポジトリには、Fence の `allowLocalOutbound` と `allowUnixSockets` を出す記述が 1 つも無い**（`allowLocalBinding: False` のみ）。内側から `127.0.0.1` へ届くかは、設定生成の追加と実機の確認が要る
- `agentcore-websearch` の起動は `uv run … agentcore_websearch_mcp.py`（`common.toml.tmpl:2085`〜`:2102`。このスクリプトが `uvx mcp-proxy-for-aws-cli` を実行する）。Bedrock の PC だけに出る

#### GitHub のトークンの種類（利用者の制約: メンバーごとのアカウント）

- **GitHub App の installation token**: 1 時間で失効し、リポジトリと権限を絞れるが、**アプリ自身（ボット）として動く**ので、メンバーごとのアカウントの帰属にはならない
- **GitHub App の user access token**: **ユーザーとして動き**、**8 時間で失効、リフレッシュトークンは 6 か月**（確認済み: GitHub Docs の「Refreshing user access tokens」）。メンバーがアプリを承認する（device flow など）。アプリは 1 つ（課や組織で共有）でよい
- **細粒度の PAT**: ユーザーとして動き、**50 を超える細かい権限**でリポジトリを絞れる。有効期限は選べ、「無期限は許されるが、組織の最大期間のポリシーで禁止されうる」。組織の既定の最大期間は 366 日（確認済み: GitHub Docs の検索結果の抜粋）

### 考察

言える:

- **LiteLLM は、AgentCore の MCP サーバー（SigV4）と GitHub の MCP サーバー（PAT・OAuth）を、MCP Gateway で束ねられる**。ただし、`gh` の CLI は束ねられない。共有のゲートウェイ（Gateway）に対応するかは、文書に明記が無い。**採用しなくても、「二層の認証」「注入は送信の直前」「書き込み専用」「既定は拒否」「ツール定義の固定」は、そのまま真似られる**
- **利用者の制約は、設計を決める**: (a) **`websearch` の共有ゲートウェイは、各メンバーが自分の IAM の認証（SigV4）で呼ぶ**ので、メンバーごとの認証情報は、メンバーのホストに残る。(b) **GitHub をメンバーごとにするなら、中央のゲートウェイに GitHub の認証情報を集約する設計は合わない**。LiteLLM の per-user BYOK や、AgentCore の 3LO は、ユーザーごとに保存できるが、**共有の IAM の Gateway との組み合わせが未確認**で、課の共有物を、個人の都合で変えにくい。したがって、**GitHub の認証は、メンバーごとのホスト側で持つ（ローカルのブローカー、または、起動時に短命のトークンを渡す）**形が自然
- **GitHub の候補**: (G4a) メンバーごとの細粒度 PAT（短い有効期限、必要なリポジトリと権限だけ）を、Bitwarden から起動時に取り出して渡す（最小の実装。漏れても、権限・期間が限られる）、(G4b) 課で共有する GitHub App の user access token（8 時間）を、ホスト側のブローカーが device flow で取得・更新する（短命で、ユーザーとして動く。アプリの登録が要る）、(G4c) 注入プロキシ（Agent Vault など）に PAT を置き、内側には渡さない（MITM と CA の信頼が要る）

言えない:

- LiteLLM が、共有の AgentCore Gateway（IAM 認証）を、MCP サーバーとして登録できるか
- AgentCore Gateway の 3LO が、IAM 受け付けでメンバーごとに働くか。issue #2550 の修正の状況
- agentgateway の DB の要否、署名・SBOM の有無、起動の重さ（実測が無い）
- 本文を読んでいない抜粋のみの項目（CVE の一部、Bifrost の CVE 本文）

### 次の問い

- 課の共有ゲートウェイを触らずに済む、**メンバーごとのホスト側のブローカー**（最小は、`pis` と同じ寿命のローカルプロセス。`relay.py` の型）。`pi` の MCP を、`http://127.0.0.1:<port>/mcp` に向ける場合の、設定生成（`headers`・`allowLocalOutbound`）の追加
- GitHub は、(G4a) の PAT の最小運用から。(G4b) は、課で GitHub App を共有できるかを、GitHub の管理者に確認
- 「設計を真似る」場合の最小のブローカーの仕様書（二層の認証、書き込み専用、既定は拒否、ツール定義の固定）。実装は、`review` を経る

### 参照

- <https://docs.litellm.ai/docs/mcp>、<https://docs.litellm.ai/docs/mcp_aws_sigv4>、<https://docs.litellm.ai/docs/mcp_control>、<https://docs.litellm.ai/docs/mcp_per_user_auth>
- <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html>、<https://aws.amazon.com/blogs/machine-learning/connecting-mcp-servers-to-amazon-bedrock-agentcore-gateway-using-authorization-code-flow/>、<https://github.com/aws/agentcore-cli/issues/2550>
- <https://github.com/agentgateway/agentgateway>、<https://github.com/maximhq/bifrost>、<https://github.com/docker/mcp-gateway>
- <https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens>、<https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization>
