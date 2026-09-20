# Optional Cost Checkpoint

## When to use

次の場合に、調査と `deck-plan.json` の確定直後に実行する。

- ユーザーが費用見積もりを求めた。
- `deck-plan.json` の `meta.cost_reporting.enabled` が `true`。
- ユーザーがAIクレジットまたは金額上限を指定した。

これは任意機能であり、費用報告を求められていない通常案件では省略できる。

## Runtime priority

1. **Claude Code + Amazon Bedrock** — 標準対応
2. Claude Agent SDK + Amazon Bedrock — 自動化に最も適する
3. Copilot CLI — 明示要求時のみベストエフォート

`CLAUDE_CODE_USE_BEDROCK=1`、AWS region、実際に選択されたmodel IDを確認する。
会社環境ではモデルaliasの自動変更を避け、可能ならモデルIDをpinする。

### Interactive Claude Code

調査・構成の確定時に `/usage`（`/cost` はalias）を表示し、モデル別token、
cache、推定費用を確認する。スキルから同じ対話セッションの `/usage` 結果を
構造化取得できない場合は、ユーザーが実行した結果を入力にする。

### Claude Agent SDK or `claude -p`

調査・構成を1回目のquery、制作を2回目のqueryとして分ける。
1回目のresult messageから次を取得する。

- `total_cost_usd`: top-levelとsubagentを含むクライアント推定
- `modelUsage` / `model_usage`: モデル別input/output/cache/cost
- `usage`: top-level loopのみ。subagentを使う場合の総額には使わない

```bash
claude -p "Research and freeze the deck plan" \
  --output-format json > research-result.json

uv run scripts/extract_claude_code_usage.py research-result.json \
  --output research-usage.json
```

`total_cost_usd` はClaude Code内蔵価格表による推定であり、請求確定値ではない。
価格変更やBedrockの契約条件によりずれる可能性を明記する。

### AWS billing reconciliation

請求上の正値にはAWS Cost and Usage Reportを使う。ユーザー・チーム・案件別に
追跡する場合はApplication Inference Profile、IAM principal、cost allocation tag、
model invocation loggingを組み合わせる。CURは反映に遅延があるため、対話中の
チェックポイントではClaude Code推定、後日の精算ではCURを使う。

## Separate actuals from forecast

必ず次を分ける。

1. **ここまでの実績**
   - 実測 input / output / cache write / cache read tokens
   - 使用モデル、プロバイダー、エンドポイント
   - 公開単価または契約単価
   - 税・割引を含むか
2. **残りの予測**
   - asset preparation
   - slide authoring
   - render / QA
   - independent content review
   - independent visual review
   - expected revision rounds

Claude Codeの`/usage`、Agent SDK result、またはAWSテレメトリーを取得できない場合、
実績金額を推測しない。
`actual_usage_available: false` とし、残額見積もりだけを示す。

## Forecast ranges

残りは単一値ではなく `low / base / high` で示す。

- `low`: 初稿がほぼ合格し、修正1回
- `base`: 独立レビュー2系統、修正2〜3回
- `high`: 原典確認、画像修正、構成変更が発生し、4回以上

画像生成料金、外部検索、ストレージ、データ転送、税、Private Offerは
トークン料金と分ける。

## Pricing

- 価格は実行時にAWS、Anthropic、Googleなどの公式ページで確認する。
- Bedrockのglobal / regional、キャッシュ、thinking、batchの差を区別する。
- Private Offerや組織割引が不明なら `public list price` と明記する。
- 為替換算は換算日とレートを残す。

## User-facing checkpoint

```text
構成が確定しました。
ここまで: $1.30（実測、公開単価、税別）
完遂まで: low $2 / base $5 / high $11
主な変動要因: スクリーンショット再撮影、独立レビュー後の修正回数
```

Autopilotでは報告後も作業を継続する。ユーザーが上限を指定し、high見積もりが
上限を超える場合だけ、リポジトリ標準の承認手順へ従う。

Copilot CLIが定額・無制限契約の場合は金額換算を既定で無効化し、必要なら
token/tool-callの工程指標だけを記録する。
