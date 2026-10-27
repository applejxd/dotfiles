# CHG-0043: 子エージェントのモデルを、最新のカタログから、ユーザの指示で選べるようにする（effort は自由）

- **状態**: Exploring
- **更新日**: 2026-10-27
- **基準**: pi 1.4.0、コミット `1bededf`。許可の判定は `home/dot_config/pi/harness/index.ts:809-821` を読んだ。pi の thinking の段と `--model provider/id:level` の解釈は pi 本体のドキュメントの `models.md`・`settings.md` と `pi --help` を読み、Copilot の `gpt-6.1-sol:medium`・`gpt-6.1-terra` の動作は 2026-10-27 に実機で確かめた

## 目的と非目的

**目的**: `guarded_task` で起動する子（`review`・`worker` など）の**モデルと effort（推論の強さ）を、ユーザが指示したときに、自由に選べる**ようにする。選べる範囲は、**最新のモデルだけを載せたカタログ**で決める。
今は、選べるのが「親が今使っているモデル」と「役割の既定のモデル」だけで（`index.ts:809-821`）、**集合に無いモデルや、集合に無い effort の段は拒否される**。例えば `review` を Sol にしたい、`review` を `high` にしたい、と言われても、できない。
**古いモデルを使いたくない**ので、カタログを正本にし、**階層の既定が、確認済みカタログの中の、同じ系統の最新を指していること**を試験で固定する（新しい世代をカタログに足すと、古い世代を使う階層が落ちる）。**保証の範囲**: 外部（プロバイダ）の最新との一致は、試験では保証できない。`models:check` の警告と、定期的な手動の見直し（カタログの `reviewed_on`）で補う。

**非目的**:

- 親のモデルの切り替え（pi の `/model` の仕事）
- ユーザの指示なしに、親（LLM）がモデルを選ぶこと（既定は、役割の階層のまま。指示があったときだけ変える）
- OpenCode の階層（撤去予定。`[opencode.model.tier.*]` はそのまま）
- Windows の素の pi の `task`（読み取り専用で、`model` を持たない）
- モデルの性能の優劣の判断（比べる実験は、[調査の記録](../research/agents/subagent-model-assignment.md)の「次に確かめること」）

## 実施計画

この文書で使う段のラベルを、ここで定義する。

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | 方針を実装の前に決める | この案件の起草と、`review` による指摘の反映 | 完了（`review`（terra）の 1 回目の指摘を反映。R1-2 は利用者がリスク受容） |
| 2 | 使ってよいモデルを、設定の 1 か所に置く | `common.toml.tmpl` にカタログ（プロバイダごと）を書き、`generate.py` が検査して `rules.json` に出す。**世代は整数の列**（`[6, 1]`）。**階層の既定は、カタログの中の、同じ系統の最新**で、**`enforce_verified = true` のプロバイダでは `verified = true`** でなければならない（検査と試験）。ID は、`(provider, id)` に正規化する | 完了（2026-10-27。`generate.py` の `pi_catalog`・`check_pi_tiers_against_catalog`、`rules.json` の `models`。`test_pi_model_catalog.py` 24 件） |
| 3 | ユーザの指示で、モデルと effort を選べる | ハーネスの許可の判定を、「カタログ ∪ 親のモデル（完全な `provider/id`）∪ 役割の既定」にし、`guarded_task` に `effort` 引数（単発・batch の各項目）を足す。**`effort` は `minimal`・`low`・`medium`・`high`・`xhigh`・`max` の 6 段（`off` は拒否）**。起動には、完全修飾のモデル ID と `--thinking` を使う。結果（単発・batch・背景・保持した job の追加依頼）に、使ったモデルと effort（要求した段と、`get_state` で得た実効の段）と、既定か指定か・未確認・高コストの印を必ず表示する。`guarded_task` の説明（`promptGuidelines`）に、カタログと「ユーザが指示したときだけ変える」を出す。**確認画面は付けない**（U1。利用者の決定） | 完了（2026-10-27。`harness/model-choice.ts`・`index.ts`・`children.ts`。`test_pi_model_choice.py` 10 件、`test_pi_harness.py` に結果の表示・`off` の拒否・追加依頼で変えられないことの試験。**実効の段（RPC の `get_state`）の表示は未実装**） |
| 4 | カタログの鮮度と確認を、道具にする | `mise run models:check`（カタログと `pi --list-models` を比べ、新しい世代・一覧に無いものを警告）と `mise run models:probe`（短い応答とツール呼び出しで確かめる） | 完了（2026-10-27。`scripts/models.py`・`mise run models:check`・`models:probe`。`test_models_tool.py` 16 件。この PC で、Copilot の 3 件を probe して OK） |
| 5 | 初期のカタログを確かめて入れる | Copilot はこの PC で probe する。Bedrock は、使える環境で確かめるまで `verified = false` で入れ、**`enforce_verified = false`**（強制の検査を有効にしない。未確認のまま、環境の生成が止まらないように）。確認後に `true` へ直す。docs（`agent-model-assignment.md`・`model-lineup-review.md`・`pi-subagents.md`）を更新 | 進行中（Copilot は probe 済み。**Bedrock は、使える環境で probe するまで `verified = false`・`enforce_verified = false`**。docs は更新済み） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

**確かめた事実**（2026-10-27）:

- **許可の集合は、完全一致の文字列**: `allowedModels(parentModel) = {親のモデル} ∪ {各役割の既定のモデル}`（`index.ts:810`）。`model` を指定しても、集合に無ければ `model not allowed: ... Allowed: ...` で拒否する（`index.ts:818-820`）。effort は別の引数ではなく、モデル名の接尾辞（`gpt-6.1-terra:high` の `:high`）で、**集合にその文字列があるときだけ**使える
- **pi の thinking の段は `off`・`minimal`・`low`・`medium`・`high`・`xhigh`・`max`**（pi 本体の `settings.md`）。**選んだモデルが対応しない段は、pi が丸める**（pi 本体の `models.md`: 「Pi limits the choices to levels supported by the selected model」「Pi first clamps unsupported thinking levels」）。したがって、**effort を自由に選ばせても、対応しない段で壊れない**（丸められる）
- `pi --model` は `provider/id` と、任意の `:<thinking>` を受け付ける（`pi --help`）。子の起動は `--model <model>` を渡している（`index.ts:821` 付近）
- **Copilot（個人機）で実機確認済み**: `claude-sonnet-5.5`・`gpt-6.1-sol`（`:medium`・`:high`、ツール呼び出しも可。一覧にある）・`gpt-6.1-terra`（一覧に無いが、「custom model id」の警告つきで動く。ツール呼び出しも可）。`gpt-6-astra` は `model_not_supported`
- **Bedrock は未確認**: `us.openai.gpt-6.1-terra`・`us.openai.gpt-6.1-sol`（AWS の公式モデルカードで GA。2026-10-26・2026-09-29）への、pi からのツール呼び出し。Bedrock の GPT-6 系の推論の強さは `additionalModelRequestFields.reasoning.effort`（pi が渡せるか未確認）
- **effort の丸めの観測**（2026-10-27、Copilot、短い応答）: `claude-sonnet-5.5` の `:xhigh`・`:max`・`:minimal`、`gpt-6.1-sol` の `:minimal`・`:off`、`gpt-6.1-terra` の `:max`・`:off` は動く（pi が丸めるか、受け付ける）。**`claude-sonnet-5.5:off` は HTTP 400**（「thinking を切るには `between_tools` を送る」。pi が `disabled` を送るため）。7 段以外の文字列（`:bogus`）は、モデル名の一部として扱われ、`model_not_supported`。したがって、**`off` は選択肢に含めない**、**7 段以外は、ハーネスで先に拒否する**
- Copilot の一覧の例（`pi --list-models`）: `claude-sonnet-5`・`claude-sonnet-5.5`・`claude-haiku-5.5`・`gpt-6-luna`・`gpt-6-sol`・`gpt-6.1-sol`・`gpt-5.6-*`・`grok-4.7`・`gemini-4-argon` など。**最新に絞るには、手で選ぶ必要がある**（一覧は、古いものも含む）

**カタログの形（案）**:

```toml
# プロバイダごと。[opencode.model] の provider と同じプロバイダのものだけが使われる
[[pi.model.catalog.github-copilot]]
id = "gpt-6.1-sol"            # pi のモデル ID（provider/ は付けない）
family = "gpt-sol"            # 系統（世代違いを同じ系統として比べる）
generation = 6.1              # 世代（系統の中の新しさ）
verified = true               # 実機で、短い応答とツール呼び出しを確かめた
cost = "normal"               # normal / high（high は、ユーザが明示したときだけ。結果に注意を出す）
note = "2026-10-27: :medium・:high とツール呼び出しを Copilot で確認"
```

**effort は、カタログに書かない**（どのモデルにも、pi の 7 段のどれでも指定できる。対応しない段は pi が丸める）。

## 未解決点

| 問い | 暫定の答え | 再開条件・決める場 |
| --- | --- | --- |
| U1: 親（LLM）が、ユーザの指示なしに、高価なモデルや高い effort を選ぶ・文書の注入で選ばされる危険（レビュー R1-2。MAJOR） | **リスク受容（利用者の決定、2026-10-27: 確認なし・表示だけ）**。レビューは「表示や説明は安全境界ではない」として、既定からの変更に確認画面を付けることを勧めた。選ばなかった案: (a) 既定からの変更に確認画面（効果は大きいが、確認が増える）(b) 利用者専用のスラッシュコマンドでの事前設定（最も安全だが、会話の流れで頼めない）。**補い（境界ではない）**: 既定は階層のまま。`guarded_task` の説明に「ユーザが指示したときだけ変える」と書く。結果に、使ったモデルと effort・既定か指定か・未確認・高コストの印を必ず表示する。カタログは、最新で、確認済みのものだけに絞る。**残るリスク**: 文書の注入や親の誤判断で、高額なモデルや `max` が使われうる。費用が問題になったら、(a) を足す | 費用・誤用の実績が問題になったとき |
| U2: モデル名の表記と、プロバイダ（レビュー R1-6） | 入力を `(provider, id)` に正規化する。**カタログは、設定のプロバイダのものだけ**。`id`（bare）は、設定のプロバイダのカタログでだけ解決し、`provider/id` の `provider` が設定と違えば拒否する。**親のモデルは、完全な `provider/id` が一致するとき、例外として許可する**（`/model` で別のプロバイダに切り替えた親にも、子を追従させるため）。pi への起動には、必ず完全修飾の ID を渡す | 段 3 |
| U3: 指定した effort が、丸められたとき | 要求した段と、`get_state`（RPC）で得た子の実効の段（`thinkingLevel`）を分けて表示する。**provider 側の実際の推論強度まで証明したとは書かない**。`off` は選択肢に含めない（Claude で 400）。7 段以外は、起動の前に拒否する | 段 3 の実機の確認 |
| U4: 「同じ系統の最新」の判定（レビュー R1-3・R1-4） | カタログの `family`（明示の分類）と `generation`（**整数の列**。辞書順に比べる）で、**カタログの中**の最新を比べる。ID の重複・同順位は検査で拒否。プロバイダごとの ID の表記の違い（Copilot `claude-sonnet-5.5`、Bedrock `us.anthropic.claude-sonnet-5-5`）は、カタログに**明示の `family` と `generation` を書く**ことで吸収し、ID から推測しない。**保証の範囲は「確認済みカタログ内で最新」**。カタログの外の新しい世代の検出は、`models:check` が担当し、**一覧の取得時刻・対象プロバイダ・取得失敗・分類不能を表示する（失敗や不完全な一覧を「問題なし」にしない）**。一覧に無いことは、廃止の証明ではない（Terra は、一覧に無いが動く） | 段 2・4 |
| U5: 親のモデルが古いとき | 許可の集合に、親のモデルは常に入る（今と同じ。親は利用者が `/model` で選ぶ）。ただし、`models:check` が、親になりうる古いモデルを警告することはしない | 見送り |
| U6: `verified` の強制と、Bedrock の導入（レビュー R1-5） | `enforce_verified` を、プロバイダごとに持つ。**`true` のプロバイダでは、階層の既定（pi が実際に使う階層: `second_opinion`・`worker`・`routine`。OpenCode 専用の `deep` を含めるかは、段 2 の棚卸しで決める）に `verified = true` を要求する**。Bedrock は、使える環境で probe するまで `enforce_verified = false`（`verified = false` のモデルを、既定に置ける）。明示の指示で未確認のモデルを選ぶときは、結果に「未確認」と表示する。**例外を恒久化しない**（確認後に `true` へ直す） | 段 2・5 |
| U7: カタログの更新の手順 | `model-lineup-review.md` の手順に、`models:check` と `models:probe` を組み込む | 段 5 |
| U8: `models:probe` が実行する内容 | 短い応答 + 固定のファイルを読むツール呼び出し（今回、手で行った確認）。結果を表に出し、`verified` の更新は**手で**行う（自動で設定を書き換えない） | 段 4 |
| U9: 既存の `:level` と、新しい `effort` 引数の優先（レビュー R1-7） | 既存の `:level`（役割の既定の `claude-sonnet-5.5:medium`、既存の呼び出しが渡す完全な文字列）は、後方互換として解析し、**モデル ID と effort に分けて**持つ。優先順位: **明示の `effort` ＞ 明示の `model` の接尾辞 ＞（モデルを上書きしないときの）役割の既定の effort ＞ pi の既定**。起動には、接尾辞を除いた完全修飾の ID と `--thinking` を渡す。両方が指定されて食い違うときは、明示の `effort` を採る。試験: 既知・custom の ID、無効な接尾辞、既存の `commit` の既定 | 段 3 |
| U10: batch・追加依頼・背景通知・保存結果（レビュー R1-8） | `effort` は、**単発と batch の各項目**に足す。**保持した job への追加依頼では、モデルも effort も変えられない**。`Job` に、要求値・正規化した値・既定か指定か・未確認か高コストかを持たせ、単発・batch・背景の通知・保存した結果・再取得に、同じ情報を載せる。`""`・`null` は「指定なし」（スキーマの検証が `parseTaskInput` の前にあるので、スキーマ側も直す。記録 B1 の F5） | 段 3 |
| U11: `models:probe` の成功条件（レビュー R1-9） | 固定の無害なファイルを読ませ、**応答に、そのファイルの固定の文字列が含まれ、ツール呼び出しの結果が成功**であることを見る。タイムアウト・回数・費用の上限を持ち、失敗時は終了コードを非 0 にする。結果の表を出し、`verified` は、手で更新する | 段 4 |
| U12: `effort` の選択肢 | `minimal`・`low`・`medium`・`high`・`xhigh`・`max`（`off` を除く）。モデルが対応しない段は、pi が丸める（観測は「現在地」） | 段 3 |

## 次の調査・実験

1. **`guarded_task` のスキーマ**（`children.ts` の `parseTaskInput`・`index.ts` のツール定義）に、`effort` を足したときの、厳格なスキーマのモデル（`gpt-6-sol` など）が、空値で引数を埋める癖（記録 B1 の F5）への影響を確かめる（`""` を「指定なし」と扱う既存の規則に合わせる）
2. **丸めの観測**: `claude-sonnet-5.5:xhigh`・`gpt-6.1-terra:max` で、pi が何を返すか（丸めて動くか、エラーか）を、この PC で確かめる
3. `pi --list-models` の出力から、系統と世代を取り出す規則（`gpt-6.1-sol`・`claude-sonnet-5.5`・Bedrock の `us.anthropic.claude-sonnet-5-5` の表記の違い）を決める

## 評価基準

**必須**:

1. カタログのモデル（`id` と `provider/id`）は、`effort` の 6 段（`minimal`〜`max`）で指定でき、起動できる。**カタログに無いモデル**（親の完全な `provider/id` と役割の既定を除く）と、設定と違うプロバイダは、拒否される
2. **`off` を含む無効な effort は、起動の前に拒否される**。**空値（`""`・`null`）は「指定なし」**（単発・batch の各項目）。追加依頼で、モデル・effort を変えようとすると拒否される
3. `model`・`effort` を省略したときは、今までと同じ（役割の既定）
4. 各階層の既定のモデルは、カタログの中にあり、**同じ系統（`family`）の最新**（`generation` の辞書順）で、**`enforce_verified = true` のプロバイダでは `verified = true`**。新しい世代をカタログに足すと、古い世代を使う階層の試験が落ちる。`6.9 < 6.10`・ID の重複・別系統の混在の fixture で試験する
5. 結果に、使ったモデルと effort（と、既定か、ユーザの指定か）が表示される
6. `guarded_task` の説明に、カタログ（`id`・`cost`・`verified`）と、「ユーザが指示したときだけ変える」が出る
7. `models:check` が、一覧に無いカタログの項目と、カタログの系統の新しい世代を警告し、**取得時刻・対象プロバイダ・取得失敗・分類不能を表示する**（失敗を「問題なし」にしない）。`reviewed_on` が古ければ警告する。`models:probe` は、固定のファイルの内容が応答に含まれることを確かめ、失敗で非 0 を返す
8. 親のモデルは、カタログに無くても、今までどおり許可される

**望ましい**: `cost = "high"` のモデル（Bedrock の Opus など）を選んだときに、結果に注意が出る

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A: 今のまま（親 + 役割の既定） | 変更が要らない | 集合に無いモデル・effort の段を選べない。古いモデルの排除は、人が気をつけるだけ | — | 見送り | — |
| B: 階層ごとに、許可の effort の段を書く | 範囲が狭く、安全 | 設定が増える。pi が段を丸めるので、制限の効果が薄い | — | 見送り（丸めがあるので、不要） | — |
| C: カタログ（最新だけ）+ effort は自由 | ユーザの希望に合う。古いモデルを試験で排除できる。pi が段を丸める | 範囲が広がり、高価なモデルを選ぶ危険が増える（U1）。カタログの更新が要る | Bedrock・丸めの観測 | **有望（提案）** | 次の調査・実験 1〜3 |
| D: 許可を無くし、任意のモデルを指定可能にする | 最も自由 | 古い・未確認・制限されたモデル（`gpt-6-astra` など）を選べてしまう。「階層の範囲内」という安全の考え方を捨てる | — | 見送り | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `docs/spec/agent-model-assignment.md` | カタログの節を足し、階層の既定の規則（同じ系統の最新・`verified`）を書く | 段 2・5 | 未適用 |
| `docs/spec/guard/pi-subagents.md` | 許可の判定を「カタログ ∪ 親 ∪ 役割の既定」に、`guarded_task` の `effort` 引数と、結果の表示を書く | 段 3 | 未適用 |
| `docs/spec/model-lineup-review.md` | 見直しの手順に、`models:check`・`models:probe` を組み込む | 段 4・5 | 未適用 |
| `docs/spec/development.md` | `mise run models:check`・`models:probe` | 段 4 | 未適用 |

## 実装・検証

（採用が決まった段から具体化する）

## 重要な更新

| 日付 | 更新 | 理由・証拠 |
| --- | --- | --- |
| 2026-10-27 | 案件を起票 | 利用者が、「最新モデルのカタログを用意し、ユーザの指示があればそれに従って選ばせたい。古いモデルは使いたくない」「effort は自由に選べるように」と判断した。pi が対応しない段を丸めることは pi 本体の `models.md` で確認した |
| 2026-10-27 | **段 2〜5 を実装した**（未コミット） | 設定・生成器・ハーネス・道具・試験・docs。**実装で分かったこと**: (1) `test/agents/pi/faux.ts` の子の結果の表示が先頭 400 文字で切れ、結果に足した 1 行で既存の試験が落ちた（700 に広げた）(2) ハーネスのファイルを 1 つずつコピーする試験は、新しいファイル（`model-choice.ts`）の追加で全部落ちる（`session-tmp.ts` と同じ。コピーの一覧に追加）(3) `models:check` の新しい世代の検出は、ID の「前が `-`・後ろが `-` か末尾の数字の列」を世代として取り出し、同じ形の ID と比べる（`gpt-6.1-sol`・`claude-sonnet-5.5`・`us.anthropic.claude-sonnet-5-5` で確認）(4) この PC で `models:check` を実行すると、Copilot の Terra だけが「一覧に無い」と警告される（動くことは probe で確認済み）。**未実装**: 実効の段（`get_state`）の表示、`cost = "high"` の確認画面（利用者が見送り） |
| 2026-10-27 | **`review`（`gpt-6.1-terra`。改善案つき）の 1 回目を反映した**。BLOCKER 1・MAJOR 6・MINOR 1 | **(R1-1) 環境の具体を一般化した**（「会社の機」→「Bedrock を使える環境」。リポジトリの約束は『会社 PC』のような条件つきの一般論なら可、なので、実質は誤検知に近いが、念のため）**(R1-2) 利用者が『確認なし・表示だけ』を選び、リスク受容にした**（U1に、選ばなかった案と残るリスクを書いた）**(R1-3) 保証の範囲を『確認済みカタログ内で最新』に限り**、`models:check` の取得時刻・失敗の表示、`reviewed_on` を足した **(R1-4) 世代を整数の列にした** **(R1-5) `enforce_verified` をプロバイダごとに持つ**（Bedrock は、確認まで `false`）**(R1-6) `(provider, id)` に正規化し、親の完全な `provider/id` を例外として明記** **(R1-7) 優先順位を定義**（明示の `effort` ＞ 接尾辞 ＞ 役割の既定 ＞ pi の既定）**(R1-8) batch・追加依頼・背景・保存結果・`get_state` を、U10 に** **(R1-9) probe の成功条件（U11）**。**観測**: `claude-sonnet-5.5:off` は 400 なので、`off` を選択肢から除いた（U12）。`effort` の丸めは、xhigh・max・minimal で動く |
