# モデルの割り当ての見直し

OpenCode の各階層に当てるモデルと effort を、新しいモデルが出たときなどに見直す手順。

見直す対象は `common.toml` の `[opencode.model.tier.<プロバイダ>]` にある 5 つの階層
（`default` / `routine` / `worker` / `deep` / `second_opinion`）。階層は用途の名前で、
エージェントは階層名で指すので、見直しで変わるのは階層に当てるモデル ID と
`#variant`（effort など）だけになる。階層の用途・今の割り当て・その根拠は
[階層](agent-config-generation.md#階層)の表が正本で、ここには写さない。

## いつ見直すか

- Anthropic / OpenAI が新しいモデルを出したとき、値下げしたとき
- Copilot や Bedrock で使えるモデルが増えた・減ったとき
- 使っていて、質（手戻り・書式の崩れ・担当外の編集）や費用に違和感が出たとき
- 見直すたびに、[再考の候補](#再考の候補)（採らずに残した案。今は Bedrock の主エージェントを
  Opus 5.5 の low にする案）も確かめる

## 前提: プロバイダで選ぶ基準が違う

PC ごとのプロバイダは 1 つ（[プロバイダの判定](agent-config-generation.md#プロバイダの判定)）。
予算の形が違うので、同じ階層でも選ぶ基準が変わる。

| プロバイダ | 予算 | 選ぶ基準 |
| --- | --- | --- |
| Copilot（私用） | 使い放題 | 質と待ち時間 |
| Bedrock（業務用） | 有限 | 仕事 1 件を仕上げる費用 |

- **Bedrock はトークンの単価ではなく、1 件を仕上げる費用で比べる。** 単価の安いモデルでも、
  手数が多い・失敗してやり直すと高くつく。haiku 4.5 は単価が sonnet 5.5 の半分だが、
  手数が 3 倍でキャッシュの読み込みが 5 倍になり、試算では sonnet 5.5 の low / medium より高かった
  （[階層のモデルの計測](../research/opencode/tier-models.md)）
- **費用の大半は主エージェント（`default`）が使う。** 子エージェントの階層を削るより、
  `default` の選び方のほうが費用への効き目が大きい
  （[再考の候補の記録](../research/opencode/tier-models.md#再考の候補-bedrock-の主エージェントを-opus-55-の-low-にする)）

## 調べる場所

### ID・単価・effort の段

| 場所 | 分かること | 注意 |
| --- | --- | --- |
| [models.dev](https://models.dev/api.json) | プロバイダごとの ID・単価（USD / 100 万トークン。キャッシュの読み書きも）・effort の段（`reasoning_options`） | OpenCode の variant の名前はこのカタログから来る（[公式](https://opencode.ai/v2/docs/models/)）。載っていない段を付けるとモデルの解決に失敗する |
| `opencode models`、エージェントからは OpenCode の models ツール | OpenCode が知っているモデル。models ツールは variant と単価も返す | **列挙されても使えるとは限らない**（[実測](../research/opencode/test-isolation.md#3-xdg_data_home-を差し替えるとモデルが引けない)）。実際に呼べるかは下の probe で確かめる |
| TUI の `/models` | その PC で選べるモデル | — |
| Bedrock の PC | Bedrock で有効なモデルと、その ID に variant が付けられるか | **この PC から Bedrock は使えない。** 利用者が Bedrock の PC で確かめる |

models.dev から Bedrock の Claude の単価と effort の段を引く例:

```bash
curl -s https://models.dev/api.json |
  jq -c '."amazon-bedrock".models | to_entries[] | select(.key | test("claude"))
         | {id: .key, cost: .value.cost, effort: .value.reasoning_options}'
```

Copilot のモデルが実際に呼べるかは、実 DB を汚さない probe で 1 回呼んで確かめる。

```bash
OPENCODE_PROBE_MODEL='github-copilot/<ID>' mise run opencode:probe -- 'Reply with exactly: OK'
```

### 公式の資料

- Anthropic
  - [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview)・
    [Pricing](https://platform.claude.com/docs/en/about-claude/pricing): ID・単価・世代
  - [Effort](https://platform.claude.com/docs/en/build-with-claude/effort): effort の段と、段ごとの使い分け
  - [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence):
    モデルと effort の組み合わせで 1 件あたりの費用を下げる考え方。「品質が足りなければ上の段の
    モデルを low で試す」「検証できる出力なら low で回して失敗だけ上げる」など
  - [System cards](https://www.anthropic.com/system-cards) と各モデルの発表: 自社のベンチマーク
- OpenAI の [Models](https://developers.openai.com/api/docs/models): `second_opinion` の候補の ID・単価
- 使えるモデルの一覧: [Copilot](https://docs.github.com/en/copilot/reference/ai-models/supported-models)、
  [Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html)
  （単価は [Bedrock の料金](https://aws.amazon.com/bedrock/pricing/)）

### 第三者の比較

| 場所 | 見るもの |
| --- | --- |
| [Artificial Analysis](https://artificialanalysis.ai/models) | 同じモデルの effort ごとの数字、速さ、費用 |
| [LMArena](https://lmarena.ai/leaderboard)（データは Hugging Face の [lmarena-ai/leaderboard-dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)） | 人の好みの投票による順位。テキストと WebDev |
| [Terminal-Bench](https://www.tbench.ai/) | 端末でのエージェント作業。OpenCode の使い方に近い |
| SWE-bench の集計（[llm-stats.com](https://llm-stats.com/benchmarks/swe-bench-verified) など） | 実リポジトリのバグ修正 |
| [BenchLeader](https://benchleader.com/)・[Vals AI](https://www.vals.ai/benchmarks) | 複数のベンチマークの横並び |

### 読むときの注意

- **多くは自己申告か転載で、条件がそろっていない。** ハーネス・試行回数・effort が
  出典ごとに違うので、数ポイントの差は比べられない
- **LMArena の WebDev は見た目の完成度を評価する。** 正しさや手戻りの少なさとは別物
- **effort の差は難しい課題でしか出ない。** 難しいコーディングの課題で 1 段あたり 1〜3 ポイント。
  易しい課題ではどの段も上限に張り付き、差が見えない
  （[公開のベンチマークの追記](../research/opencode/tier-models.md#追記--2026-09-30-公開のベンチマークと割り当ての判断)）

## 自前で評価する

公開の数字で候補を絞ったら、`routine` と `worker` はこのリポジトリの使い方で測る。
方法の詳細は記録の「方法・条件」にある。ここではその要点だけを示す。

- `routine`（`commit`）: [commit / review エージェントの実機確認](../research/opencode/commit-review-agents.md)の
  記録 E3 で作り、記録 E4〜E6 でも使った方法
- `worker`（`fleet-worker`）: [階層のモデルの計測](../research/opencode/tier-models.md#記録-e1--2026-09-30)の方法と、
  それを流用した[作業役への指示の計測](../research/opencode/fleet-worker-instructions.md)

### 隔離

- 実 DB を読み取り専用で複製し、資格情報だけ残したものを `OPENCODE_DB` に渡す
- 実行ごとに一時の `XDG_*` と `TMPDIR`、組ごとに一時の `OPENCODE_CONFIG_DIR`。
  `OPENCODE_CONFIG` / `OPENCODE_CONFIG_CONTENT` は外す
- `opencode run --standalone --auto --format json` で、常駐サービスを使わない
- **`session.synthetic` を使わない。** 外側の serve で既定モデルのエージェントがホストで
  動いた事故がある（[Fence の記録](../research/opencode/permission/fence.md)）
- 設定は評価したい版の `common.toml` から生成し、比べる組ではエージェントの `model` だけを差し替える

### 計装

計装した guide plugin の複製だけを読み込ませ、`permission.evaluate` の前後とツールの実行の
前後を記録する。これで確認（`ask`）・誘導（plugin がコマンドを拒んで道具を案内した回数）・
静的な `deny` を数える。shell の `ask` は承認した扱い、危ない形（`rm` / `git reset` など）は
拒否した扱いにする。shell 以外の `ask` も承認した扱いにしないと、`--auto` の下で答える人が
いないまま時間切れまで止まる（[記録の「止まった 3 回」](../research/opencode/tier-models.md#結果)）。

### 課題

- `routine`: 親の `build` に「差分は自分で読まず `commit` に任せる」と頼む。作業用リポジトリの
  変更は 5 種類（複数の論理単位・範囲外の個人メモ・削除・理由の要る破壊的な変更・未追跡の
  ディレクトリ）。**2026-10-07 に `commit` は計画だけを返す役になり、承認は会話、コミットは親が行う
  （[コミットの確認](agent-config-generation.md#コミットの確認)）。`scripts/model-eval/routine/` の採点は
  子がコミットまで行う旧方式が前提で、そのままでは測れない。次の見直しの前に作り直す**
- `worker`: 親の `build` から、依頼文を一字も変えずに `fleet-worker` へ渡させる（`/fleet` と同じ経路）。
  使い捨ての Python パッケージで課題 7 種類（機能追加・バグ修正・リファクタリング・テストの追加・
  複数ファイルにまたがる変更と、難しめの 2 種類）。採点は作業役に見せない隠しテストで行う。
  隠しテストは、模範解答で全件が通り、元のリポジトリで落ちることを確かめてから使う
  （`scripts/model-eval/worker/selftest.py`）

### 測る項目

| 項目 | `routine` | `worker` |
| --- | --- | --- |
| 仕上がり | コミットまで進んだか | 隠しテストと既存のテストが全件通るか |
| 書式・範囲 | Conventional Commits の件名・72 文字以内・`- Motivation:` / `- Change:` / `- Impact:` の 3 行、範囲外のファイルが入らないか | 担当外のファイルの編集・残した一時ファイル・作業ツリーの外への書き込み |
| 利用者の手間 | `git commit` 以外の確認と誘導の回数 | 確認と誘導の回数 |
| 時間 | 所要時間の中央値 | 同左（基本と難しめで分ける） |
| 費用 | 出力・キャッシュの読み書きのトークンと、OpenCode の費用（参考値） | 同左。Bedrock の候補は、同じトークン数に models.dev の Bedrock の単価を掛けて試算する |

- **差が出なければ課題を難しくする。** 易しい課題ではどの組も合格し、effort の差もモデルの差も
  見えない。「同じ質」ではなく「この難しさでは差が出ない」と書く
- **回数が少ないことを踏まえる。** 1 組 10〜14 回程度なので、並行実行の混み具合で所要時間は揺れる。
  結論は目安にとどめ、記録にもそう書く
- Bedrock の候補は Copilot の同じモデルで近似するしかない（この PC から Bedrock は使えない）。
  キャッシュの効き方が同じだという仮定になる
- `deep` と `second_opinion` は、良し悪しを機械的に採点できる課題を作れないので測っていない
  （[deep を計測しなかった理由](../research/opencode/tier-models.md#deep-を計測しなかった理由)）。
  公開の数字と使った感触で決める

### 道具の置き場

計測の道具（設定の生成・隔離実行・採点・集計のスクリプト、作業用リポジトリの作り方、課題の依頼文・
隠しテスト・模範解答、計装した plugin）は [`scripts/model-eval/`](../../scripts/model-eval/README.md) にある。
回し方はその README。実行記録は `.tmp/model-eval/` に出て、git に入らない。
2026-09-30 までの記録は、同じ道具の元になった `.tmp/opencode/` の下の版で測った。

## 決め方の目安

- **同等なら、Copilot は速いほう、Bedrock は 1 件あたり安いほう。** 同等かどうかは、
  上の測る項目の仕上がり・書式・範囲で見る
- **中身が同じ階層があってもよい。** 階層名は用途なので、今 `routine` と `worker` が同じモデルでも
  分けたままにし、片方だけ差し替えられるようにしておく
- **`default` には `#variant` を付けられない**（付けると `apply` が止まる）。Copilot の `default` の
  推論の強さは、設定では変えられない（[階層](agent-config-generation.md#階層)の注記）
- **Bedrock の variant は、付けられるかを Bedrock の PC で確かめる。** models.dev に段があっても、
  その PC で通るかは別。今の Bedrock の Sonnet 5.5 の effort は利用者が確かめた
- 子エージェントの階層は計測で決め、測れない階層（`deep` / `second_opinion`）は公開の数字で決める。
  判断と根拠は、変えたときに[階層](agent-config-generation.md#階層)の表の下の注記へ書く

## 変えるときの手順

1. `home/dot_config/agents/common.toml.tmpl` の `[opencode.model.tier.<プロバイダ>]` を書き換える。
   どのプロバイダにも同じ階層名をそろえる
2. テストを直して通す。`test/agents/test_generate_opencode_models.py` は各プロバイダの ID と
   variant を具体的に固定しているので、変えた値に合わせる

   ```bash
   uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q
   ```

3. [階層](agent-config-generation.md#階層)の表と、その下の根拠の注記を書き換える。
   隔離起動（`ocs`）の既定モデルは別の設定（`[opencode.sandbox] model_preference`）なので、
   合わせるなら一緒に変える（[隔離起動（`ocs`）](agent-config-generation.md#隔離起動ocs)）
4. 計測や調べた数字を調査記録に残す。同じ問い（その階層にどのモデルを当てるか）の測り直しなら
   既存の記録に日付付きの節を足し、問いが変わるなら新しい記録にする。
   [調査記録の索引](../research/index.md)の行も直す
5. 配備する。`chezmoi apply` で `~/.config/opencode/opencode.json` が変わり、OpenCode は設定ファイルを
   自動で読み直す（[公式](https://opencode.ai/v2/docs/models/)。実行中のリクエストは始めたときの
   設定のまま）

## 再考の候補

見直しのたびに、次の候補の条件が変わっていないかを確かめる。

| 候補 | 採らなかった理由 | 再考するなら |
| --- | --- | --- |
| Bedrock の `default` を Opus 5.5 の `low` にする。公式の資料は、上位モデルを低い effort で使うほうが 1 件あたり安くなる例を挙げている | Sonnet 5.5 と同じ条件で比べた数字が無い。主エージェントに effort を付けられるかも確かめていない（`default` は `#variant` を持てない。上の目安）。利用者の判断で Sonnet 5.5 のまま | Bedrock の PC で実際の作業を Sonnet 5.5 と Opus 5.5 low で比べ、1 件あたりの費用と手戻りを数える（[記録](../research/opencode/tier-models.md#再考の候補-bedrock-の主エージェントを-opus-55-の-low-にする)） |

[仕様・運用の一覧へ戻る](index.md)
