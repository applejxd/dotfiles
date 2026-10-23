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
