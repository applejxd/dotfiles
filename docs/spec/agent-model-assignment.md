# モデルの割り当て

AI CLI（OpenCode・pi・Copilot CLI）が使うモデルの割り当て: プロバイダと会社 PC の判定、階層（`[opencode.model.tier.*]` と pi の上書き）、生成されるもの。見直しの手順は [モデルの割り当ての見直し](model-lineup-review.md)。生成の全体は [設定の生成と所有権](agent-config-generation.md)。

## モデルの割り当て

PC ごとにモデルのプロバイダを 1 つに決め、既定モデル・エージェントごとのモデル・
接続設定・他のプロバイダの禁止を `opencode.json` へ出す。
新しいモデルが出たときなどに割り当てを見直す手順は
[モデルの割り当ての見直し](model-lineup-review.md)にある。

### 会社 PC の判定

`.chezmoitemplates/is-work` が `apply` のたびに決める（`"true"` / `"false"`）。**LLM のプロバイダ（`llm-provider`）とは別の軸**で、
「検索語などを AWS の外へ出してよい個人用の機か」を表す。会社 PC で Copilot を使うようになっても、個人専用の配布が会社の機へ入らないようにするため。

| 条件（上から順に評価） | `is-work` |
| --- | --- |
| `chezmoi.toml` の `[data]` に `work` がある | その値（`true` / `false`） |
| ユーザー名が `applejxd`（`DOMAIN\applejxd` も含む、大小無視） | `false`（個人用） |
| それ以外 | `true`（会社 PC） |

- **`is-work` で切るもの**: `web-search` と `imozuru` のスキルの配布と許可規則（検索語を外へ出さない）、GitHub の認証の出どころ（個人は `gh auth token`、会社 PC は権限を絞った PAT のファイル）、`agentcore-websearch` を入れる CLI の一覧
- **`llm-provider` で切るもの**: Copilot ブローカー、Envoy の取得、OpenCode のプロバイダ、`[pis.network]` の既定
- **AgentCore 自体は、どちらでも切らない。** 使うかは実行時（URL の有無）で決まる。判定を誤っても、認証が無ければ何も起きない
- 勤務先の具体はリポジトリに書かない。判定の根拠は個人のユーザー名だけで、自動の判定が合わない機は `[data] work` で上書きする（`chezmoi update` は `init` を呼ばないので、`[data]` は `init` 時にしか変わらない。上書きが要るのは例外）

### プロバイダの判定

`.chezmoitemplates/llm-provider` が `apply` のたびに決める。

| 条件（上から順に評価） | プロバイダ |
| --- | --- |
| `chezmoi.toml` の `[data]` に `llm_provider` がある | その値 |
| ユーザー名が `applejxd`（`DOMAIN\applejxd` も含む、大小無視） | `github-copilot`（個人用） |
| それ以外 | `amazon-bedrock`（制約のある環境用） |

判定の前提は「個人機のユーザーは `applejxd`、制約のある環境の機は別名で AWS CLI にログイン
している」こと。どちらでもない PC では OpenCode を使わない。

- **gh のログイン状態は見ない。** 制約のある環境の機でも `gh auth login` していることがあり、
  見分けに使えない。OpenCode の Copilot 接続も `gh` とは別で、`/connect` が要る
- **`~/.aws` の有無も見ない。** 個人機にも `~/.aws` ディレクトリだけ存在する
  ことがある（この PC で確認）
- `[data]` ではなくテンプレートで判定するのは、`chezmoi update` が `init` を
  呼ばないため（[CHG-0008](../change/closed/0008-raspi-branching.md)）。
  `[data]` の `llm_provider` は判定を覆したいときの逃げ道

### 階層

`[opencode.model.tier.<プロバイダ>]` に**階層名 → モデル ID** を書き、エージェントは
階層名で指す。PC が変わってもエージェントの割り当てを書き直さずに済む。
**階層名はモデルの大小ではなく用途で付ける。** どのモデルを当てるかは計測で変わるが、
エージェントがどの用途かは変わらないので、当てるモデルを変えても名前と割り当てはそのまま使える。

| 階層 | 用途 | Copilot | Bedrock |
| --- | --- | --- | --- |
| `default` | 主エージェントの既定 | `claude-sonnet-5.5` | `us.anthropic.claude-sonnet-5-5` |
| `routine` | 決まった形の短い作業 | `claude-sonnet-5.5#medium` | `us.anthropic.claude-sonnet-5-5#low` |
| `worker` | 実装などを任せる作業役 | `claude-sonnet-5.5#medium` | `us.anthropic.claude-sonnet-5-5#medium` |
| `deep` | 難しい判断・設計 | `claude-sonnet-5.5#high` | `us.anthropic.claude-opus-5-5#high` |
| `second_opinion` | 別系統のモデルでの確かめ | `gpt-6-astra` | `us.openai.gpt-6-sol` |

Copilot の `default`・`deep` は Sonnet 5.5、`second_opinion` は OpenCode の階層では Astra のままで、
pi の Copilot は `[pi.model.tier.github-copilot]` で `gpt-6.1-terra` に上書きしている（Opus と Astra が制限されたため。以前は Sol。Terra は pi の Copilot の一覧には無く、custom model id の警告つきで動く。[pi の子エージェント](guard/pi-subagents.md)）。
**`worker` も、pi の Copilot は `gpt-6.1-sol#medium`、pi の Bedrock は `us.openai.gpt-6.1-sol`（推論の強さは付けない）に上書きしている**
（2026-10-27、利用者の決定:「できるだけ最新のモデルで揃える」。OpenCode の階層は Sonnet 5.5 `#medium` のまま）。
計測済みの既定（Sonnet 5.5 `#medium`）とは、まだ比べていない（[調査の記録](../research/agents/subagent-model-assignment.md)）。
**Haiku は使わない**（利用者の方針。`explore`・`commit` の小型の候補にもしない）。
pi の Bedrock の `second_opinion` は `us.openai.gpt-6.1-terra`（AWS の公式モデルカードで GA を確認、2026-10-26）。`deep` の `xhigh` は Sonnet で通る確認が取れていないので `high` にした。Bedrock の階層は全部 `us.`
（`global.` は使わない）。`us.` 無しの ID は `ask_description` の候補の最後のフォールバック
（`amazon-bedrock/anthropic.claude-haiku-5-5`）だけで、推論プロファイルが無い環境で取りこぼさないための意図的なもの。

割り当て（`[opencode.model.agents]`）は `commit = "routine"`・`review = "second_opinion"`・
`fleet-worker = "worker"`。

- **`routine` と `worker` は今は同じモデルだが、分けておく。** 名前は用途なので、
  どちらかの計測結果が変わったときに片方だけ差し替えられる
- **`routine`（`commit`）は Sonnet 5.5。** haiku ではコミットメッセージの書式が崩れ、Sonnet 5.5 でそろう。effort では差が出なかった
- **`worker`（`fleet-worker`）も Sonnet 5.5。** 実装課題で Opus 5.5 と合格率に差が無く、速い。haiku は難しめの課題で不合格が多く、担当外にファイルを残す。
  Bedrock の値は Copilot で近似した判断で、Bedrock 上では未確認
- 比較の数値と根拠は[経緯](../research/agents/agent-config-generation-notes.md)と[階層のモデルの計測](../research/opencode/tier-models.md)
- **effort はプロバイダの予算で分ける。** Copilot（使い放題）は質と待ち時間で選び、`routine` も
  `worker` も `medium`。Bedrock（予算が有限）は、effort で差が出なかった `routine` を `low` にして
  費用を削り、`worker` は `medium`。公開のベンチマークでも、effort の差は難しいコーディングの課題で
  1 段あたり 1〜3 ポイント程度（[階層のモデルの計測](../research/opencode/tier-models.md)の追記）。
  Bedrock の Sonnet 5.5 に effort を付けられることは、利用者が確かめた
- **`deep` は計測していない**（機械的に採点できる課題が作れないため、opus の上位の effort のまま）
- **Bedrock の `default` は Sonnet 5.5 のまま。** Opus 5.5 の `low` が候補だが未比較（[経緯](../research/agents/agent-config-generation-notes.md)）
- `default` を割り当てに使わないのは、Copilot の `default` はバリアントが付けられず
  （下記）ほかの階層と推論の強さが変わるのと、既定モデルを変えたときに子エージェントまで
  変わらないようにするため。Bedrock では今は `routine` / `worker` と同じモデルで、effort だけが違う

```toml
[opencode.model.agents]
explore = "worker"      # 例
```

- **どのプロバイダにも同じ階層名をそろえる**（`test_every_provider_defines_the_same_tiers`）
- ID は [models.dev](https://models.dev) の一覧か TUI の `/models` で実在を確かめてから
  書く。Bedrock の `us.` はクロスリージョン推論プロファイル (米国のリージョン内。以前の `global.` は使わない)
- **`default` に `#variant` は付けられない。** 既定の `model` はバリアントを
  保持しない（公式）。付けると `apply` を止める
  - Copilot の `default` に推論の強さを持たせる手段は無かった（2 回目以降の呼び出しで送られない。
    [実測 記録 E2](../research/opencode/agent-models.md#記録-e2--2026-09-28-既定モデルに推論の強さを持たせられるか)）
  - そのため Copilot の `default` はバリアントなし（強さは Copilot 側の既定。
    どの強さかは未確認）。high で動かしたいセッションは TUI でバリアントを選ぶ
- 未知の階層・プロバイダ、`[opencode.agent]`（V1 形式）にあるエージェントへの
  割り当ても `apply` を止める。後者は V1 の `agent` と V2 の `agents` に同じ ID が
  並んだときの結合順を確かめていないため
  - 改名前の階層名（`light` / `standard` / `heavy`）で割り当てても、未知の階層として止まる。
    エラーには定義済みの階層名が並ぶ
- 宣言も組み込みでもない ID への割り当ても止める（[所有の規則](opencode-config-generation.md#配置済みの設定の所有)）
