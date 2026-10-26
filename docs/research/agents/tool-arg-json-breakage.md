# ツール引数の JSON が壊れる問題の調査（細粒度ツールストリーミング・strict・Bedrock）

> `docs/spec/guard/pi-guard.md#ツール引数の-json-を壊さない設定` から移した記録。移設時点で再測定していない。

## 記録 — 観測日は各文に記載（移設 2026-10-26）

- **対象バージョン**: 各文に記載（pi 1.3.0 前後）
- **環境**: 各文に記載

### 問い

モデルのツール引数の JSON が壊れる原因は何か。`supportsEagerToolInputStreaming:false` で減るか。`strict` や Bedrock では。

### 根拠

Anthropic の公式文書 <https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming>・<https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use>、pi の issue（#9643・#10502・#9953）、`before_provider_request` での送信ペイロードの記録（下の元の文のとおり）。

### 結果（元の文）

モデルが出すツール引数の JSON が壊れる問題（`Invalid arguments for tool … Expected ',' or ']' … in JSON`。`friction-review` の集計で、`guarded_edit` 16 件・`ask` 6 件）への対処。pi 本体が引数の JSON を解析できないと、ツール側では救えない（`toolCall.argumentsError`）。

- **原因の候補（公式文書で確認）**: Anthropic の細粒度ツールストリーミング（`eager_input_streaming`）は、サーバー側でバッファリングも JSON の検証もせず、不完全・不正な JSON が届き得る（<https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming>）。pi の Anthropic 経路は、既定で全ツールにこれを付ける（`supportsEagerToolInputStreaming ?? true`）。**実測**（pi の `before_provider_request` で送信直前のペイロードを記録。Copilot 経由の Sonnet 5）: 既定では全ツールに付く（20/20）。
- **設定**: `models.json` の `providers.github-copilot.compat.supportsEagerToolInputStreaming: false`（プロバイダー単位。モデルの一覧を持たない）。配るファイルは `home/dot_pi/agent/models.json`。実測: 設定すると送られなくなり（Sonnet 5・Haiku 5.5 で確認）、呼び出しは正常。戻すときは、設定を外す。副作用は、ツール引数が完成するまで画面に出ないこと。
- **`pis` の内側**: agent ディレクトリは本物の `models.json` を写さず、**`providers.*.compat` だけ**を写す（`ocs/pi.py` の `_copy_provider_compat`。`apiKey`・`baseUrl`・`headers`・`models` は写さない許可リスト）。ブローカーの `baseUrl` とは合成される。
- **採用しなかった（今は）: `strict`（厳密な JSON スキーマ）**。実測: pi は既定で Copilot の Claude に `strict` を送らない（`supportsStrictTools` が `github-copilot` のモデルに無い）。`compat.supportsStrictTools: true` で送ると、Copilot は受け付けた（40/40）が、**強制するかは未確認**（公式文書・報告が見つからない）。さらに、Anthropic の strict が対応しないキーワード（`maxItems`、`minItems`（0・1 以外）、`minLength`/`maxLength` など。公式文書による）がスキーマにあると、pi は黙って通常の呼び出しにフォールバックする（`ask` のスキーマが該当）。必要になれば、`ask` のスキーマからそれらを外し（個数などは自前の検証に任せる）、再検討する。
- **効果の測定**: 実験室では、壊れた JSON を再現できなかった（現状の設定で 0/40（通常のプロンプト）、0/20（引用符・バックスラッシュ・複数行を多用するプロンプト））。実使用の発生率は約 1.7%（`guarded_edit` の 940 回中 16 回）で、数百回の比較は費用に見合わない。**数日使った後に、`friction-review` の集計で `Invalid arguments` の件数を比べる**。
- **Bedrock 経由の環境**（pi のソースと AWS の公式文書で確認。2026-10-25）: **同じ対処は要らず、効きもしない**。pi の Bedrock 実装は ConverseStream だけを使い、`eager_input_streaming` も `fine-grained-tool-streaming` のベータ指定も送らない（`anthropic_beta` に入るのは interleaved-thinking と thinking-binding だけ）ので、既定で検証つきのバッファ済みになる。`compat` の項目は `supportsStrictMode`（既定は偽。`toolSpec.strict` を付ける）だけで、`supportsEagerToolInputStreaming` は効かない。Bedrock で JSON が壊れるなら、原因は別（`max_tokens` 到達による途中切れ、`additionalModelRequestFields` へ fine-grained のヘッダーを足す拡張・ゲートウェイ、確定時の `parseToolCallArguments` の失敗）。**まず、送信ペイロードを `before_provider_request` で見て、`anthropic_beta` に fine-grained が入っていないか確かめる**。実機（Bedrock 経由の環境）での発生率は未測定（`friction-review` の集計を、その環境で実行して比べる）。strict の AWS 側の対応とスキーマの制約は未確認。
- **未確認**: Copilot が `eager_input_streaming` を実際に尊重しているか（送らなくなったことは確認したが、サーバー側の挙動は未確認）。他のモデル（GPT・Gemini）。
- **調べた範囲**（2026-10-25）: Anthropic の strict tool use の公式文書（<https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use>）、pi の issue（#9643 旧版の壊れた JSON、#10502・#9953 strict の 400）、他のエージェントの報告（Claude Code は `StructuredOutput` に `strict` を付けず `eager_input_streaming` を付ける、OpenRouter で不正な JSON の報告）。反例: Bedrock などで `strict` を送ると 400 になった報告。

### 考察

現在の仕様は ../../spec/guard/pi-guard.md の該当節。ここの数値・日付は観測時点のもので、再測定していない。
