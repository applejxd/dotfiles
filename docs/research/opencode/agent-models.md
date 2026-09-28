# OpenCode V2 のエージェントごとのモデル指定

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

> **現行の仕様**: [モデルの割り当て](../../spec/agent-config-generation.md#モデルの割り当て)

## 結論

| 指定の仕方 | 子エージェント（`explore`） | 主エージェント（`--agent plan`） |
| --- | --- | --- |
| V1 の `agent.<id>.model`（バリアントなし） | **効く** | 効かない |
| V1 の `agent.<id>.model`（`#high` 付き） | **黙って無視**。親のモデルで動く | 効かない |
| V2 の `agents.<id>.model`（`#high` 付き） | **効く**。バリアントも付く | 効かない |

- バリアントを使うなら **V2 の `agents` キーに書く**
- 主エージェントを選んでも、セッションのモデルは変わらない（公式の記述どおり）
- V1 の `agent` と V2 の `agents` は 1 つのファイルに併存できた
  （`agent.bypass` と `agents.explore` を同時に置いて、両方効いた）
- **既定の `model` に推論の強さを持たせる設定上の手段は無い**（記録 E2）。
  Copilot の Claude は 2 回目以降の呼び出しで、明示したバリアントしか送らない

## 記録 E1 — 2026-09-28

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `51930d4`

### 問い

エージェントごとの `model`（`#variant` 付き）は効くか。V1 の `agent` キーと V2 の
`agents` キーで違うか。

### 事前の予想

V1 の設定はメモリ上で V2 へ正規化されるので、どちらのキーでも同じに効く。

### 方法・条件

- `mise run opencode:probe` の種 DB（資格情報だけ引き継いだもの）を使い、
  `OPENCODE_CONFIG_DIR` へ生成した `opencode.json` を置いた
- 既定の `model` は `github-copilot/claude-sonnet-5`
- 子エージェントは次のプロンプトで起動し、試験用 DB の `session_v2.model` と
  `session_message.data` の `model` を読んだ

```console
$ OPENCODE_DB=.tmp/opencode/probe/seed.db OPENCODE_CONFIG_DIR=.tmp/opencode/probe-cfg \
    opencode run --standalone --log-level error \
    'Use the explore subagent to list the files in the current directory, then reply DONE.'
```

- 主エージェントは `opencode run --standalone --agent plan 'Reply with exactly: OK'`
  の表示行（`> plan · <モデル>`）を見た

### 結果

| 設定 | 子セッションの `session_v2.model` | メッセージの `model` |
| --- | --- | --- |
| `agents.explore.model = github-copilot/claude-haiku-4.5` | `claude-haiku-4.5` | — |
| `agent.explore.model = github-copilot/claude-haiku-4.5` | `claude-haiku-4.5` | — |
| `agent.explore.model = github-copilot/claude-opus-5.5#high` | `None` | `claude-sonnet-5`（親） |
| `agents.explore.model = github-copilot/claude-opus-5.5#high` | `claude-opus-5.5`, `variant: high` | 同左 |

主エージェント:

```console
$ opencode run --standalone --agent plan 'Reply with exactly: OK'   # agent.plan.model = ...opus-5.5#high
> plan · claude-sonnet-5
$ opencode run --standalone --agent plan 'Reply with exactly: OK'   # agents.plan.model = ...opus-5.5#high
> plan · claude-sonnet-5
```

### 考察

- 予想は外れた。V1 の `agent` キーは `#variant` 付きの値を解決できず、エラーも
  出さずに親のモデルへ落ちる。**誤った指定が「安いモデルで動く」形でしか現れない**
- 主エージェントの `model` は、`--agent` で選んだだけでは使われない。公式の
  「A session stores its selected model separately. Selecting a primary agent by
  ID does not change that model.」と一致する
- 主エージェントの `model` が効くと公式が書いているのはコマンド経由
  （コマンドの `agent` で選んだエージェントの `model` が、呼び出し時のモデルに勝つ）

### 次の問い

- 主エージェントの `model` を TUI で使う経路（Tab での切り替え、コマンドの
  `agent:` 指定）で実際に切り替わるか。未実施
- V1 の `agent` と V2 の `agents` に**同じ ID** を書いたときの結合順。未実施
  （生成側はこの組み合わせを禁止した）

### 参照

> A subagent uses its configured model, or inherits the parent session's model when none is configured.
> A session stores its selected model separately. Selecting a primary agent by ID does not change that model.

出典: <https://opencode.ai/v2/docs/agents/>

> Otherwise, the selected command agent's configured model overrides the model active at invocation.

出典: <https://opencode.ai/v2/docs/commands/>

## 記録 E2 — 2026-09-28: 既定モデルに推論の強さを持たせられるか

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `2df5da7`

### 問い

既定の `model` はバリアントを保持しない（公式）。Copilot の `claude-opus-5.5` を
既定にしたまま、推論の強さを `high` にできるか。

### 事前の予想

カタログのバリアント `high` の中身は `settings.reasoningEffort: "high"` なので、
同じ設定をモデル単位に書けばバリアントなしの呼び出しでも `high` になる。

### 方法・条件

- 記録 E1 と同じ試験環境。試験用の設定ディレクトリに、送信直前のリクエスト本文を
  記録する plugin（`http.request` hook）を置いた
- 依頼はツールを 1 回使わせるもの（`Use the glob tool to find *.md files in docs/adr,
  then reply DONE.`）。モデル呼び出しが 2 回起きる
- カタログのバリアント定義は、plugin から `ctx.model.list()` で読んだ

### 結果

**Copilot の Claude は、1 回目と 2 回目で送信先と形が変わる。**

| 呼び出し | 送信先 | 推論の強さの載り方 |
| --- | --- | --- |
| 1 回目 | `api.githubcopilot.com/chat/completions` | `reasoning_effort` |
| 2 回目以降 | `api.enterprise.githubcopilot.com/v1/messages` | `output_config.effort` |

カタログのバリアント定義（`ctx.model.list()`）:

```text
claude-opus-5.5  package: aisdk:@ai-sdk/github-copilot
   {"id": "high", "settings": {"reasoningEffort": "high"}}   (low / medium / xhigh / max も同形)
```

指定の仕方ごとの送信内容:

| 指定 | 1 回目 `reasoning_effort` | 2 回目 `output_config` |
| --- | --- | --- |
| 何もしない | なし | なし |
| `--model ...claude-opus-5.5#high` | `high` | `{"effort": "high"}` |
| 子エージェントの `model` に `#medium` | —（`/v1/messages` のみ） | `{"effort": "medium"}` |
| モデル単位の `settings.reasoningEffort = "high"` | `high` | **なし** |
| 別名モデル（`modelID = claude-opus-5.5`、`settings.reasoningEffort = "high"`） | `high` | **なし** |
| モデルに `id = "default"` のバリアントを定義 | なし | なし |
| `context` hook で `options.reasoningEffort = "high"` | `high` | **なし** |
| 既定の `model` を消し、`agents.build.model` に `#high` | 使われず最新の `gpt-6-luna` へ落ちた | — |

バリアントを付けない呼び出しは、hook の中で `variant: "default"` として見える。

### 考察

- 予想は外れた。**2 回目以降の経路は、バリアントを明示したときにしか推論の強さを
  送らない。** 設定値・別名・hook のどれで入れても 1 回目にしか効かない
- したがって v2.0.14 では、既定の `model` を「Opus 5.5 の high」にする設定上の手段は
  見つからなかった。推論の強さを確実に指定できるのは、バリアントを付けて選んだ
  セッション・子エージェント・コマンドだけ
- モデル単位の設定で入れると「最初の 1 回だけ high、あとは指定なし」になる。
  気づけない劣化なので採らない

### 次の問い

- plugin からセッションのモデルをバリアント付きに切り替える
  （`ctx.session.switchModel`）と、2 回目以降にも効くか。未実施
- 指定なしのとき、Copilot 側がどの強さで動くか。未確認
- `/v1/messages` へ切り替わる条件。未確認
