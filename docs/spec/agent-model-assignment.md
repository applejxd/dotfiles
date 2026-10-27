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

### 子エージェントのモデルのカタログ

[CHG-0043](../change/0043-model-catalog.md)。`guarded_task` で、ユーザの指示により、子のモデルと effort を選べる範囲。**最新のモデルだけ**を載せる。
`[pi.model.catalog.<プロバイダ>]` に、`reviewed_on`（最新かを見直した日）・`enforce_verified`・`families`（系統の分類）と、`[[...models]]`
（`id`・`family`・`generation`・`verified`・`cost`・`note`）を書く。

- **`generation` は整数の列**（`6.1` は `[6, 1]`。辞書順に比べる。小数で書くと `6.9` と `6.10` が比べられない）。`family` は `families` にある名前だけ（typo を検査で拒否）
- **階層の既定は、カタログの中の、同じ系統の最新**でなければならない（生成時の検査 `check_pi_tiers_against_catalog`。新しい世代をカタログに足すと、古い世代を使う階層が落ちる）。
  **`enforce_verified = true` のプロバイダでは `verified = true`** も要る。Bedrock は、使える環境で probe するまで `false`（未確認の環境の生成が止まらないように）
- **保証の範囲は「確認済みカタログ内で最新」**。外部（プロバイダ）の最新との一致は、`mise run models:check`（`pi --list-models` と比べ、新しい世代・一覧に無い項目・`reviewed_on` が古いことを警告。**一覧の取得に失敗した・空のときは「問題なし」にせず終了コード 2**）と、定期的な見直しで補う。一覧に無いことは廃止の証明ではない（Copilot の Terra は、一覧に無いが動く）
- `mise run models:probe`: 固定のファイルを読ませ、応答にその固定の文字列が含まれること（ツール呼び出しの成功）を確かめる。**`verified` は自動では書き換えない**（手で直す）
- 初期のカタログ: Copilot は `claude-sonnet-5.5`・`gpt-6.1-sol`・`gpt-6.1-terra`（すべて `verified`。2026-10-27 に probe）。Bedrock は `us.anthropic.claude-sonnet-5-5`・`us.anthropic.claude-opus-5-5`（`cost = "high"`）・`us.openai.gpt-6.1-sol`・`us.openai.gpt-6.1-terra`。Haiku・古い世代（`gpt-6-*`・`claude-sonnet-5`）は載せない
- 選べる範囲・effort の仕様と、ユーザの指示なしに選ぶ危険の扱いは [pi の子エージェント](guard/pi-subagents.md)

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
pi の Copilot は `[pi.model.tier.github-copilot]` で、`second_opinion` を `gpt-6.1-sol`、`deep` を `claude-sonnet-5.5#xhigh` に上書きしている（2026-10-27、利用者の決定。Astra は pi の Copilot 経由で動かない。GPT は Sol に揃えた。`gpt-6.1-terra` はカタログに残し、明示の指示のときだけ使う。Copilot の Sonnet 5.5 の `xhigh` は動く実測。[pi の子エージェント](guard/pi-subagents.md)）。OpenCode の `deep` は `#high` のまま。
**`worker` は上書きしない**（Sonnet 5.5 `#medium`。Bedrock も `us.anthropic.claude-sonnet-5-5#medium`）。`review`（GPT）と系統を分け、
レビューの独立性を保つため（2026-10-27、利用者の決定。いったん GPT-6.1 Sol にしたが、worker と review が同じ系統になる点を見直した）。
GPT-6.1 Sol は、比較の実験で試す（[調査の記録](../research/agents/subagent-model-assignment.md)）。
**Haiku は使わない**（利用者の方針。`explore`・`commit` の小型の候補にもしない）。
**`plan` 役（pi の子。[CHG-0044](../change/0044-plan-agent.md)）は `deep` 階層**（Copilot は Sonnet 5.5 の `xhigh`、Bedrock は Opus 5.5 の `high`）。Opus は費用が高く、これまで「明示の指示のときだけ」としてきたが、`plan` の既定だけは例外にした（利用者の決定、2026-10-27）。計測（同じ課題で `medium`・`xhigh`・`max`・Sol を比べ、別系統の採点者が採点）では、`medium` は 15.0 点・事実の誤り 6 件、`xhigh` は 20.5 点、`max` は 21.5 点（25 点満点）で、`max` は `xhigh` の約 3 倍の時間のため、既定は `xhigh`。
pi の Bedrock の `second_opinion` は `us.openai.gpt-6.1-sol`（AWS の公式モデルカードで GA を確認、Sol は 2026-09-29。`gpt-6.1-terra` はカタログに残す）。`deep` の `xhigh` は Sonnet で通る確認が取れていないので `high` にした。Bedrock の階層は全部 `us.`
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
