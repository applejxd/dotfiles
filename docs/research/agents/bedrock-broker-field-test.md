# Bedrock ブローカーの実機確認（段 U7b）

<!-- 現在の総合判断は docs/change/0037-pis-usability-and-telemetry.md の候補比較と段 U7b が正本。
     ここは「手順」と「いつ何を観測したか」を積む場所 -->

> **結論（2026-10-26）**: 実機（制約のある環境の機）で、**スクリプトを 2 回実行して、最後の 1 行を手で打って返す**だけにした（約 10 分）。
> コピー・貼り付けは要らない。AWS の認証情報の値・組織名・プロキシのホスト名は、出力にも返信にも出ない。
> Copilot ブローカーとの機能差のうち、Bedrock で**まだ確かめていないもの**は、下の表に全部ある。スクリプトは、そのうち署名・ストリーミング・鍵の更新・大きい要求・
> プロキシ越し・境界の内側からの到達・内側の環境変数の残りを一度に確かめる（偽の上流で確認できる部分は、この日、ローカルで確認済み）。

## 記録 B1 — 2026-10-26（手順の用意。実機の結果は未取得）

- **対象バージョン**: Envoy 1.40.1、Fence 0.1.67、pi 1.3.0
- **環境**: スクリプトの確認は WSL2（直接接続）。実機（認証つきプロキシが必須で、Bedrock を使う機）は未実施

### 返してほしいもの

打つのは 1〜3 行です（コピーは要りません）。

1. **報告コード**: スクリプトの最後に出る `報告コード: BP1-…` の 1 行（全部で 20 文字ほど）
2. **NG 詳細**: コードに `0` があるときだけ、その下に出る `S2: 403 SignatureDoesNotMatch` のような行（各 40 文字ほど）
3. 実行できなかったときは、出たエラーの**最初の 1 行**

### 手順

準備（初回だけ、5 分）:

1. **リポジトリを最新にする**（`chezmoi update` か、`~/.local/share/chezmoi` で `git pull`）。
2. **Envoy を置く**: `ls ~/.local/bin/envoy` で無ければ、[Envoy の取得](../../spec/cli-management.md#envoy-の取得)の版（v1.40.1）を `~/.local/bin/envoy`（実行権限つき）へ置く。
   この機は `chezmoi apply` では入らない（`llm-provider` が `github-copilot` の機だけが対象）。手で置いてよい（確認だけなので、sha256 は任意）
3. **専用の IAM ユーザーの静的キーを、`~/.aws/credentials` に別のプロファイルとして足す**（`chmod 600`）:

   ```ini
   [bedrock-probe]
   aws_access_key_id = ...
   aws_secret_access_key = ...
   ```

   権限は、使うモデルの `bedrock:InvokeModel` と `bedrock:InvokeModelWithResponseStream` だけに絞る（Converse の権限の名前は、AWS の文書で確認する）。
   **普段の強い認証情報は使わない。** 実験の後は、このキーを無効化する
4. 使う**リージョン**と**モデル ID**を決める（`pi` で使うもの）

実行（リポジトリの根で）:

```bash
cd ~/.local/share/chezmoi
python3 scripts/agents/bedrock_probe.py selftest
python3 scripts/agents/bedrock_probe.py run --region <リージョン> --model <モデル ID> --profile bedrock-probe
```

- `selftest` は AWS へつながない（偽の上流）。**期待は `報告コード: BP1----11111---`**。これが違えば、環境の問題なので、そこで止めて、出た行を返す
- `run` は、実際に Bedrock へ、短い要求を数回送る（応答は数語。費用はごくわずか。要求の本文は表示しない）。
  **S4 は、壊した偽のキーで 1 回だけ要求を送る**（AWS 側に認証失敗の記録が 1 件残る。専用ユーザーなので影響は小さい）

### 報告コードの読み方

`BP1-` の後ろは、固定の順番の 1 文字ずつです。`1`=OK、`0`=NG、`2`=別の形で OK、`-`=実施せず。

| 位置 | 項目 | 何を確かめるか |
| --- | --- | --- |
| 1 | E1 | Envoy が実行できる |
| 2 | E2 | Fence が実行できる |
| 3 | K1 | 静的キーを用意できる（プロファイルが読める） |
| 4 | S1 | Envoy の設定が通り、起動する |
| 5 | S2 | Converse（非ストリーム）が 200（`2` はモデル ID の `:` を生で送ると通る） |
| 6 | S3 | ConverseStream が 200 で、応答が増分で届く |
| 7 | S4 | 鍵ファイルを壊すと 403、戻すと 200（次の要求から反映される） |
| 8 | S5 | 約 1.5MB の要求が 413 にならない |
| 9 | P1 | ホストのプロキシ経由で、Bedrock の宛先に HTTP 応答が返る（プロキシが無い機は `-`） |
| 10 | P2 | Envoy → 橋（`relay`）→ ホストのプロキシで Converse が 200（同上） |
| 11 | F1 | Fence の内側から、Envoy のポートへ届く |

末尾の `-<1 文字><数字>`: 1 文字はホストのプロキシの種類（`n`=なし、`h`=http、`t`=https、`s`=socks、`o`=他）、数字は Fence の内側に残る AWS 系の環境変数の数です。

### NG のときの次の一手（私がすること）

| コード | 意味 | 次の一手 |
| --- | --- | --- |
| E1=0 | Envoy が無い | 準備 2 をやり直す |
| K1=0 | プロファイルから静的キーを読めない | SSO やロールの引き受けのプロファイルは対象外。専用ユーザーの静的キーが要る |
| S1=0 | Envoy の設定が通らない | 出た 1 行を返してもらい、設定を直す（版の差の可能性） |
| S2=0 かつ詳細が `SignatureDoesNotMatch` | 署名が合わない | モデル ID の `:` の扱い（パスの二重エンコード）や、ペイロードのハッシュを調べる |
| S2=0 かつ `AccessDenied…` | IAM の権限 | 権限（モデルの許可・リージョン）を確認してもらう。署名自体は通っている |
| S2=0 かつ 403 以外 | リージョンやモデル ID の違い | 値を確認してもらう |
| S3=0 かつ 200 | 応答がバッファされ、増分で届かない | 時間の値（最初のバイトと全体）を返してもらい、Envoy の設定か、自作のストリーミング対応プロキシかを判断する |
| S4=0 | 鍵ファイルの更新が反映されない | `watched_directory` の挙動を調べる。反映されないなら、Envoy を作り直す運用にする |
| S5=0 | 大きい要求が通らない | 本文の保持の上限を上げる。または、署名のハッシュ方式を変える |
| P1=0 かつ「TLS 検査の CA が無い」 | プロキシが証明書を差し替えている | その CA を、Envoy の上流の CA バンドルへ足す必要がある（設計を決める） |
| P1=0 かつ `curl rc=…` | プロキシ経由で Bedrock に届かない | 宛先が許可されているか、利用者が確認する |
| P2=0 | 橋経由で通らない | 橋が受けた `CONNECT` の宛先の形（`host` か `ip`）と、プロキシの応答を返してもらう |
| F1=0 | Fence の内側から Envoy へ届かない | `allowLocalOutboundPorts` の指定を調べる（WSL2 以外の環境の差の可能性） |
| 末尾の数字が 1 以上 | 内側に AWS 系の環境変数が残る | 名前の一覧が表示されるので、その名前だけ返してもらう（値は出ない） |

### Bedrock で未検証のこと（Copilot ブローカーとの機能差）

Copilot ブローカーは実装・実機確認済み（[broker.md](../../spec/sandbox/broker.md#copilot-ブローカー)）。Bedrock で、同じことを成り立たせるために、**確かめていない・決まっていない**ものを全部書く。
「状態」は、2026-10-26 時点です。

| 機能 | Copilot の現状 | Bedrock で必要なこと | 状態 | 確かめる段 |
| --- | --- | --- | --- | --- |
| 本物の認証の置き場 | ホストの `auth.json` の長期トークン | 専用の最小権限の IAM ユーザーの静的キーを、ホストのファイルに置く（`pis` は AWS 系の環境変数を内側へ渡さず、`~/.aws` も内側から読めない） | **未決**（置き場所の規約が無い） | K1 |
| 認証の更新 | 短命トークンを交換し、SDS ファイルを rename で更新。Envoy が読み直す（**24 時間後の更新は Copilot でも未確認**） | 静的キーなので交換は無い。ローテーションは、鍵ファイルの rename で反映する | 偽の上流で**確認済み**（Envoy が `watched_directory` の rename を読み直す）。実機は未確認 | S4 |
| 署名 | `Authorization: Bearer` を差し替える | リクエストごとの SigV4（日時・Host・ペイロードのハッシュ）を、Envoy の `aws_request_signing` で付ける | 偽の上流で**確認済み**（私の検算の実装で署名が一致。モデル ID の `:` を `%3A` で送る形も一致）。**実際の AWS に通るかは未確認** | S2 |
| ストリーミング | 増分で届く（実測: 最初の 1 バイトが 1.3 秒、全体 4.3 秒） | `ConverseStream` のバイナリのイベントストリームが、壊れず・バッファされずに届く | 偽の上流（チャンク転送）で増分を**確認済み**。実際のイベントストリームは**未確認** | S3 |
| 大きい要求 | 上限なし（Copilot は署名に本文を使わない） | 署名のために Envoy が本文を保持する。上限（32 MiB に設定）を超えると 413 | 偽の上流で 1.5MB が通ることを**確認済み**。実機は未確認 | S5 |
| 通す先の制限 | `POST /v1/messages`・`/responses`・`/chat/completions` の完全一致だけ | Bedrock の API のパス（`pi` が使うのは ConverseStream とみられる。ソース名からの推測）だけに絞る | **未決**（`pi` が実際に呼ぶパスの観測が要る） | 実装前 |
| 身元確認（`/__pis_broker`） | 起動前に、別のサービスがポートを占有していないか確かめる | 同じ仕組みが要る | **未実装** | 実装前 |
| 上流のホスト | トークンの `proxy-ep` から決める | `bedrock-runtime.<リージョン>.amazonaws.com`（リージョンの出どころを決める） | **未決** | 実装前 |
| 上流の TLS 検証 | CA と SAN（`githubcopilot.com` で終わる名前）を検証 | SAN `amazonaws.com`。プロキシが TLS を検査して証明書を差し替える環境では、その CA を足す必要がある | 設定は Envoy が受理（検証済み）。**CA の差し替えは未確認** | P1 |
| 内側へ渡すもの | ダミーの `COPILOT_GITHUB_TOKEN` と、`models.json` の `baseUrl` | `pi` の Bedrock プロバイダー（pi-ai）の `AWS_BEDROCK_SKIP_AUTH=1` と、標準以外の `baseUrl` が使える（ソースで確認）。**`pi` 側の具体的な設定項目の形は未確認** | **未確認** | 次の段 |
| 内側の環境変数 | 名前に `TOKEN` などを含むものを除く | `AWS_BEARER_TOKEN_BEDROCK` は除かれる。`AWS_PROFILE`・`AWS_REGION` などは残る（本物の鍵ではない） | 一覧は**未確認**（`AWS_ACCESS_KEY_ID` などは固定で除外） | 末尾の数字 |
| 認証ファイルの扱い | `auth.json` から `github-copilot` を除いて写す | Bedrock は `auth.json` ではなく、AWS の標準の経路（環境変数・`~/.aws`）。内側から読めないことは確認済み | 確認済み（設計）。実機の通しは未確認 | 次の段 |
| Envoy の導入 | `chezmoi apply` が取得（`llm-provider` が `github-copilot` の機だけ） | Bedrock の機にも入れる（条件を広げる） | **未実装**（今は手で置く） | 実装前 |
| Envoy の上流への出方 | 直接 | 認証つきプロキシが必須の環境では、Envoy は `Proxy-Authorization` を付けられない。**橋（`relay`）に `CONNECT` させる案**。Envoy が送る `CONNECT` の宛先は、ホスト名の形（偽の橋で観測） | 橋への `CONNECT` の形は**確認済み**。プロキシ越しの通しは**未確認** | P1・P2 |
| 境界の内側から Envoy へ | `allowLocalOutboundPorts` で届く | 同じ | 偽の上流の Envoy で**確認済み**（WSL2） | F1 |
| 拒否リスト型の条件 | Copilot ブローカーが条件を満たす（`pi.llm_auth_isolated`） | Bedrock のブローカーと、認証が内側から除かれていることの確認を、条件に足す | **未実装**（足すときは、ブローカーが動くだけでは足りない） | 実装前 |
| 検索（AgentCore の MCP） | 別のブローカー（検索）で、鍵を内側に置かない | AgentCore の MCP（streamable HTTP）を中継する。SigV4 のサービス名が違う | **未検証**（この手順の対象外。次の問い） | — |
| 要求の大きさ・回数の上限 | 無い | 同じ（専用ユーザーの IAM の権限が実質の制限） | 未対応 | — |

### この手順で確かめないこと

- `pi` が実際に Bedrock を呼ぶ通し（`pi` 側の設定の形が未確認のため。この手順で署名・ストリーミング・鍵の更新が通ってから、私が設定を用意して、もう 1 回お願いします）
- AgentCore の検索
- 拒否リスト型との組み合わせ（上流プロキシ経由の拒否リスト型は実装済みだが、Bedrock のブローカーが無いので、条件を満たさず許可リスト型で起動する）

### 事前の予想

- S2 は、モデル ID に `:` を含むときに、署名のパスの扱いで落ちる可能性があると予想していた。**偽の上流では通った**ので、実際の AWS でも通る見込みが高い（未確認）
- S3 は、Envoy が応答をバッファしない設定にしてあるので増分で届くと予想する。実際のイベントストリームでの確認が要る
- プロキシ必須の環境では、P1（TLS 検査）が最も落ちやすいと予想する

### 方法・条件（ローカルでの確認。2026-10-26、WSL2、Envoy 1.40.1）

- `selftest`: 偽の上流（標準ライブラリの HTTP サーバー）に、`aws_request_signing` を通した要求を送り、**SigV4 を私が実装した検算で確かめた**。署名が一致（モデル ID の `:` を `%3A` で送る形を含む）、ストリームは 0.4 秒おきの 6 個のかたまりが増分で届く、鍵ファイルを rename で壊すと 403・戻すと 200、1.5MB の要求は 413 にならない（偽の上流が 400 を返す）
- 本物の TLS の設定（直接・橋）は、`envoy --mode validate` で受理された
- 偽の橋で、Envoy が `CONNECT bedrock-runtime.<リージョン>.amazonaws.com:443` とホスト名で送ることを観測した
- Fence の内側から `allowLocalOutboundPorts` で Envoy のポートへ届くことを確かめた
- **実際の AWS への通信、認証つきプロキシ、TLS 検査は、一切試していない**

### 結果

**未実施**（実機の結果は未取得）。結果が出たら、この節に日付つきで足す。

### 次の問い

- 実機の結果で、Envoy の設定で足りるか、自作のストリーミング対応プロキシが要るかを決める
- `pi` の Bedrock プロバイダーの設定の形を確かめ、`pi.llm_auth_isolated` に Bedrock を足す条件を決める
- Envoy の導入条件を、Bedrock の機へ広げる

### 参照

| 文書 | 内容 |
| --- | --- |
| [認証ブローカー](../../spec/sandbox/broker.md) | Copilot・GitHub・検索の各ブローカーの仕様と、未対応・未検証 |
| [CHG-0037](../../change/0037-pis-usability-and-telemetry.md) | 段 U7b と、これまでの経緯 |
| [記録 D5](agent-auth-delegation.md) | 既製の署名プロキシの実用性（`aws-sigv4-proxy` はストリーミングがバッファされる、Envoy の `aws_request_signing`） |
| [Envoy `aws_request_signing`](https://www.envoyproxy.io/docs/envoy/v1.40.1/configuration/http/http_filters/aws_request_signing_filter) | 2026-10-26 に取得。`credential_provider` の `credentials_file_provider`（`watched_directory` つき）で、鍵ファイルの読み直しができる |
| [Envoy `Http11ProxyUpstreamTransport`](https://www.envoyproxy.io/docs/envoy/v1.40.1/api-v3/extensions/transport_sockets/http_11_proxy/v3/upstream_http_11_connect.proto) | 2026-10-26 に取得。`default_proxy_address` で、上流への接続を、プロキシへの `CONNECT` にする |
