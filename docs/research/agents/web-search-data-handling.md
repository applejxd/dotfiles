# 検索・モデルのデータの扱いの裏取り（会社の AWS と、家の Copilot・検索 API）

<!-- 現在の総合判断は docs/change/ の候補比較表が正本（CHG-0037）。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 D1 — 2026-10-24

- **対象**: 会社（モデルは Amazon Bedrock、検索は AgentCore の Web Search。`llm-provider` が `amazon-bedrock`）と、家（モデルは GitHub Copilot、検索は `web-search` スキルの Brave → Exa → Tavily → DuckDuckGo）
- **方法の限界**: 公式の文書と、AWS・GitHub・各社の公開ページを、`explore` の子が読んだ。**契約・社内の設定は見ていない**。取得日は、ページ内に日付があるもの以外は不明。親が確かめた行は「確認済み」（保存先 `.tmp/research/openshell-vs-pis-sandbox/sources/aws-*.md`）

### 問い

利用者の前提（2026-10-24）: 会社は、Bedrock の opt-out 設定で、社外秘までの入力を許可されており、AgentCore の検索を使うのでクエリの漏洩は気にしない（認証キーは気にする）。家は、認証以外の漏洩を気にしない。この前提は、公式の文書と食い違わないか。

### 事前の予想

会社の前提は、AWS の公式文書と整合する（学習に使わない・モデルプロバイダーと共有しない）。家は、検索 API のクエリが保存されうるが、認証以外は気にしないので許容できる。

### 結果

**会社（AWS）**:

- Bedrock は、プロンプトと応答を**モデルプロバイダーと共有せず、学習にも使わない**（確認済み: 「Amazon Bedrock doesn't share your prompts or model outputs with model providers. AWS and third-party model providers don't use inputs to or outputs from Amazon Bedrock to train …」。`aws-bedrock-model-data-use.md:15`。re:Post、ページ内の更新 2026-09-23）。「zero operator access」で、ゼロ保持にも対応（同 `:23`）
- **ただし、不正利用検知のために、一部のモデルで入出力が最大 30 日保持される**（確認済み: 同 `:27`「retains classifier-flagged traffic or all traffic for up to 30 days, for certain models」）。**Claude Fable 5 / 5.1 は全トラフィックが保持され、AWS による人の確認の対象になりうる**（確認済み: `aws-bedrock-abuse-detection.md:31`〜`:33`）。保持した入出力は、AWS が処理し、第三者のモデルプロバイダーとは共有しない。ゼロ保持が要るなら、`data_retention_mode` を `none` にする（アカウント単位またはプロジェクト単位）と、保持が要るモデルへの要求は拒否される（確認済み: `:33`）
- **「opt-out 設定」という名前の Bedrock の公式設定は、見つからなかった**。AWS Organizations の「AI services opt-out policy」の対応サービス一覧に、Bedrock も AgentCore も**載っていない**（子が一覧を目視で確認）。この opt-out が何を指すか（`data_retention_mode`、社内の契約・設定、別のサービスの設定のどれか）は、公式文書からは判別できない
- AgentCore の **Web Search Tool** は、Amazon が自前で運用する Web のインデックスを使い、**クエリは AWS の外へ出ない**（確認済み: 「Customer queries are not sent to a third-party search engine or routed outside AWS」。`aws-agentcore-web-search-tool.md:91`、`:67`）。クエリは 200 字以内（子の抜き書き）
- AgentCore Gateway の顧客データとメタデータは DynamoDB と S3 に暗号化して保存し、メトリクスとログは CloudWatch に保存する。「顧客のコンテンツは、サービスの提供と保守には使わない」（子の抜き書き。`bedrock-agentcore/…/data-protection.html`）
- クロスリージョン推論のデータは、AWS のネットワークの中にとどまり、リージョン間は暗号化される。保持が要るモデルでは、処理したリージョンに入出力が保存される（子の抜き書き）
- **未確認**: Service Terms の AI の節（50.x）、Data Privacy FAQ、モデル呼び出しログの保存仕様、AgentCore の Runtime・Browser・Identity・Memory の扱い、Gateway の target（Lambda など）経由のデータの流れ

**会社の実装**（リポジトリのファイルで確認）: `agentcore-websearch` の MCP は、`uvx mcp-proxy-for-aws-cli==1.7.0` を起動する薄いラッパーで、環境変数 `AGENTCORE_GATEWAY_URL` の Gateway（us-east-1）へ、**手元の AWS 認証情報（`AWS_PROFILE` / `~/.aws`）で SigV4 署名**して接続する（`agent-config-generation.md:279`〜`:290`）。クエリ以外を足す処理は、ラッパーには無い（proxy 本体は未読）。**`pis` の境界の中では、`~/.aws` が読み取り拒否、`AWS_*` の環境変数は子へ渡さず、許可リストに AgentCore のドメインが無い**ので、動かない可能性が高い（`pi-extension-under-harness.md` も「実機の `pis` では未確認」）

**家（GitHub Copilot、個人プラン）**:

- Free・Pro・Pro+ は、対話のデータ（プロンプト、コード片、接続したツールの内容）を、**学習に使う設定があり、いつでも opt-out できる**（2026-04-24 に有効。GitHub の Community の FAQ）。**既定値は、取得した範囲の原文に明記が無い**（「設定が有効な場合」の書き方）。モデルプロバイダーは、このデータを自社の学習に使わない
- モデルプロバイダー側の保持: OpenAI と Anthropic はゼロ保持の契約があるが、**Claude Fable 5 / 5.1 は、既定で保持される**（子の抜き書き。GitHub Docs の model-hosting）。プロンプト・応答の GitHub での保存期間は、公式で確認できなかった（第三者の記事に「28 日」とあるが、プランの区別は未確認）。`pi` の github-copilot プロバイダー経由の扱いの記述は、見つからなかった

**家（検索 API）**（子の抜き書き）:

- Brave Search API: クエリの記録を、**最大 90 日**、課金とトラブルシュートのために保持する。ゼロ保持は Enterprise のみ。クエリを個人や端末に結びつける識別子は集めない（Brave の privacy policy、更新 2026-08-25）。学習への利用の明示は無い
- Exa: ゼロ保持は Enterprise のみ（チーム単位）。既定の保存期間と学習への利用は、取得した文書に無い
- Tavily: クエリの保存・学習への利用の記述は、取得した範囲に無い（プライバシーポリシー本文は未取得）
- DuckDuckGo: 検索履歴を保存・共有しない。匿名化したクエリだけを、索引の改善のために保存する

### 考察

言える:

- 会社の前提「学習に使われない・モデルプロバイダーに共有されない」は、**公式の文書と整合する**。**AgentCore の検索は、クエリが AWS の外へ出ない**ので、会社のクエリの漏洩を気にしない方針とも整合する
- **注意点（前提の修正）**: (1) 一部のモデル（Claude Fable 5 / 5.1 など）は、入出力が最大 30 日保持され、人の確認の対象になりうる。使うモデルが該当するかを確認し、該当するなら `data_retention_mode` の設定を、社内の AWS 管理者に確認する。(2) 「opt-out 設定」が何を指すかは、公式文書からは特定できない。「AI services opt-out policy」は Bedrock・AgentCore を対象にしていない。社内の設定の正体は、AWS 管理者に確認が要る
- 家の前提「認証以外は気にしない」は、**検索 API のクエリが最大 90 日保持される（Brave）**程度で、許容できる。**ただし、Copilot の学習への利用の設定（個人プラン）の既定値は不明**なので、アカウントの設定を確認する。コードや、認証キーがプロンプトに入ると、学習に使われうる点に注意（認証キーを内側に置かない設計の意味が、ここでも強まる）

言えない: 会社の契約・社内の設定の中身、各社の最新の規約、Tavily・Exa の既定の保持。

### 次の問い

- 会社: 使っているモデル、`data_retention_mode`、「opt-out」の正体を、AWS 管理者に確認する
- 会社: `agentcore-websearch` が、境界の中で動くか（資格情報の渡し方。[CHG-0037](../../change/0037-pis-usability-and-telemetry.md)）
- 家: Copilot の「データの利用を許可する」設定を、アカウントで確認する

### 参照

- <https://repost.aws/knowledge-center/amazon-bedrock-model-data-use>、<https://docs.aws.amazon.com/bedrock/latest/userguide/abuse-detection.html>、<https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html>
- <https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_ai-opt-out_all.html>
- <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html>、`…/data-protection.html`
- <https://github.com/orgs/community/discussions/188488>、<https://docs.github.com/en/copilot/reference/ai-models/model-hosting>
- <https://api-dashboard.search.brave.com/privacy-policy>、<https://exa.ai/docs/admin/security/zero-data-retention>、<https://duckduckgo.com/privacy>
