# オーケストレーションの役割別のモデル割り当ての調査

<!-- 現在の運用の正本は docs/spec/agent-model-assignment.md（階層と割り当て）と docs/spec/guard/pi-subagents.md（子の役割）。ここは「いつ何を調べたか」を積む場所 -->

## 記録 M1 — 2026-10-27

- **問い**: オーケストレーター（計画役の親）と子（`explore`・`review`・`worker`・`commit`）に、どのモデルを当てるのがよいか。
  世間で言われる「計画役は Claude 系、ワーカーは GPT 系」に根拠はあるか。理想の設定は何か
- **方法**: 探索の子 3 本（一次資料と通説の出どころ／公開ベンチマークと適性／手元の割り当てと癖）。Web は `websearch.py` の `search` と `fetch`。**子が取得できなかった出典（取得失敗・429・拒否）は、検索のスニペットだけで確認したと書いてある**。ここでは、一次資料・ベンダーの自社値・二次ブログ・体験談を分けて書く
- **対象の世代**: 公開評価は、Claude Sonnet 5.5 / Opus 5.5 対 GPT-6 / 6.1（Sol・Astra・Luna）の世代（2026 年 9〜10 月）。**世代が違えば結論は変わる**
- **限界**: ほぼ全部がベンダーの自社値か二次ブログ。同じ Sonnet 5.5 でも、harness 次第で Terminal-Bench が 59〜70% とぶれる。Cursor の公式資料と、Codex・Agents SDK の公式ガイドの本文は読めていない。pi の `guarded_task` 経由の実測は、まだ無い

## 結論

1. **「計画は Claude、実装は GPT」を裏づける一次資料の実測は、見つからなかった。** 向きが逆の記事もある。体験談で、世代・日付・根拠が不明なものが多い。通説は、役割の優劣ではなく、**「Claude は高性能・高価でトークンが多く、GPT は安価・低トークン」という費用構造の差の言い換え**の可能性が高い（推測）
2. **一次資料が支持するのは、ベンダーの分担ではなく、能力と費用の分担**（強い推論モデルが計画し、安い・速いモデルが実行する）。ただし、公表された例は、**同じ系統の中**（Claude Code の `opusplan`、Anthropic の Opus リード + Sonnet サブ）。コーディングは、並列化できる部分が少なく、効果が小さい（Anthropic 自身の記述）
3. **別系統のモデルが効く場面は、レビュー**（作った者と別の誤りの癖を持つので、見落としが重ならない）。この環境の `review` は、すでに別系統（GPT）にしてある
4. **公開評価は、役割を 1 つに決める根拠にならない**: ターミナル作業・長期の知識労働は Claude 優位、マージ可能な差分と 1 タスクの費用は GPT-6 Sol 優位、同費用ならほぼ同点。**委譲の巧さ・指示追従を、役割別に比べた公開評価は、見つからなかった**
5. **手元の計測は、OpenCode の `fleet-worker` と `commit` だけ**（pi の子の経由では測っていない）。そこでは、worker は Sonnet 5.5 の `medium` で Opus 5.5 と合格率が同じで、約 2/3 の時間。haiku は難しめの課題で不合格が多い。課題が易しく、上限に張り付いている可能性がある

## 根拠

### 一次資料（確認済みの事実）

| 出典（日付） | 内容 | 条件・限界 |
| --- | --- | --- |
| Anthropic「multi-agent research system」（2025-06-13、<https://www.anthropic.com/engineering/multi-agent-research-system>） | Opus 4 リード + Sonnet 4 サブが、単独の Opus 4 を 90.2% 上回った。トークンの量が性能の分散の 80% を説明する。マルチエージェントは、チャットの約 15 倍のトークンを使う。「ほとんどのコーディングの課題は、本当に並列化できる部分が少ない」「LLM エージェントは、まだ、調整と委譲が得意でない」 | 研究タスクの社内評価。サブは同じ Claude 系。コーディングは条件外 |
| Claude Code の model-config（<https://code.claude.com/docs/en/model-config>） | `opusplan`: 計画モードは Opus、実行は Sonnet | 同一ベンダー内の分担 |
| Aider の architect/editor（2024-09-26、2025-01-24、<https://aider.chat/2024/09/26/architect.html>） | R1 + Sonnet が polyglot で 64.0%、o1 の 14 分の 1 の費用。**o1 + Sonnet は、o1 単独より良くならなかった** | 古い世代（o1・R1）。世代が変わると効果が消えた＝モデル依存 |
| Google/MIT「Towards a Science of Scaling Agent Systems」（2025-12-09、arXiv 2512.08296） | 単独の性能が約 45% を超えると、協調は効果が減るか逆効果。独立のエージェントは誤りを 17.2 倍に増幅し、中央集権型は抑える | 系統ごとの効果量（Google +164%・Anthropic +127%・OpenAI +70%）は、二次の記事経由で、原文では未確認 |
| arXiv 2602.01011「Multi-Agent Teams Hold Experts Back」（v4、2026-05-28） | 異なるモデルのチームが、最良の個体を下回る例 | — |
| OpenAI の Codex のドキュメント（検索のスニペットのみ） | reasoning effort を上げると、質が上がるが、時間とトークンが増える。計画は高 effort、サブは低 effort という使い分け（第三者の記事、2026-03-27） | 公式のガイド本文は、取得できず未確認 |

### 公開ベンチマーク（Sonnet 5.5 / Opus 5.5 対 GPT-6 / 6.1。2026 年 9〜10 月）

| 観点 | Claude 優位 | GPT 優位 | 出典 |
| --- | --- | --- | --- |
| Terminal-Bench 4.0 | Opus 5.5 64.8%・Sonnet 5.5 61.8%（独立の評価では Sonnet 63.6%） | Astra・6.1 Sol は 58.2%。**harness 次第で順位が入れ替わる**（Sonnet 5.5 は、自社値 70.6%・独立 63.6%） | codingfleet（2026-10-23）、vals.ai（2026-10-24） |
| 長期の知識労働（GDPval-AA 等） | Sonnet が 300 Elo 以上リード | — | kingy.ai（2026-09-28、10-08 更新） |
| マージ可能な差分（FrontierCode 1.1） | Sonnet 5.5 46.2% | Sol 49.3〜52.1% | 同上 |
| 費用 | Sonnet 5.5: 19.4B トークンで $7.3k（Terminal-Bench） | **Sol: 1.5B トークンで $0.6k**。1 タスクの費用は、Sonnet が 2.4〜7.2 倍。約 $1/タスクの同費用では、Sonnet high 47・Sol max 48 でほぼ同点 | codingfleet・kingy.ai |
| 単価 | Sonnet 5.5 と Sol は、ともに $2/$10。キャッシュ読み取りは Sonnet $0.10・Sol $0.20 | Sol は、入力が 272K を超えると、全体が約 2 倍に再課金される | 同上 |
| DeepSWE（2026-09-22） | Opus 5: 74% を $11.84/件 | Astra: 74% を $4.43/件（解決率は同じで、費用が 63% 安い） | morphllm（スニペット） |
| 小型 | Haiku 5.5: Terminal-Bench 39.2%（Sonnet 5.5 は 70.6%、自社値） | Luna は Haiku と同じ定価で、1 タスクの費用が約 1/3。指数は Haiku 43・Luna 38 | djtal・codingfleet（スニペット） |

- **scope creep の一次情報**: Anthropic 自身が、Sonnet 5.5 が最大の effort のとき、multi-agent の code-review のスキルを多用し、タイムアウトや範囲外の編集が出たと開示している（FrontierCode）
- **推測（二次情報）**: Opus 4.7 で、Task ツール経由のカスタムサブエージェントへの委譲が「約 50%」という Reddit の投稿がある（親が自分でやってしまう傾向の例だが、一般化できない）

### 通説の出どころ（いずれも体験談で、実測の記載なし）

- Reddit r/ClaudeCode: 「Opus 4.6 が計画、GPT 5.4 が review、Sonnet 4.6 が実装」
- Nathan Onn: GPT-5 で計画、Claude Code で実装。Medium: GPT-5.2 Codex で計画、Claude で実装（**向きが逆**）
- GitHub の claude-codex / claude-gpt-workflow: Claude が計画、Codex が実装と review
- Reddit の一部: 「Claude が必ず計画、Codex が必ず実装、という固定ルールは使わない」

### 手元の事実

| 役割 | 今のモデル（Copilot の個人機。Bedrock は階層で別） | 根拠と限界 |
| --- | --- | --- |
| 親 | `claude-sonnet-5.5`（`default`。`deep` は `#high`） | Opus と Astra が Copilot で制限（2026-10）。`default`・`deep` は計測なし |
| `explore` | 親の現在のモデルに追従（`tier` 無し） | 計測なし |
| `review` | `second_opinion` = `gpt-6.1-terra`（2026-10-27 に `gpt-6-sol` から変更）。Bedrock は `us.openai.gpt-6-sol` | `gpt-6-astra` は pi の Copilot 経由で `model_not_supported`。Terra は一覧に無く、custom model id の警告つきで動く。**`review` の指摘の質は、実モデルで未確認** |
| `worker` | `claude-sonnet-5.5#medium` | OpenCode の `fleet-worker` で、計 98 回（記録 E1、2026-09-30、OpenCode v2.0.14）。6 組とも基本 10/10・難しめ 4/4（課題が易しく、上限に張り付く可能性）。haiku 4.5 は基本 9/10・難しめ 0/4。Bedrock の値は、Copilot での近似 |
| `commit` | `claude-sonnet-5.5#medium`（Bedrock は `#low`） | 旧方式（子がコミットまで行う）の測定。2026-10-07 から計画だけを返す役に変わっており、採点は作り直しが要る |

**モデル別の癖**（pi の実機。`docs/research/agents/pi-bg-experiments.md` など。各シナリオ 1 回で、モデルは 4 つ）:

| モデル | 観察 |
| --- | --- |
| `gpt-6-sol` | 厳格なスキーマで、使わない省略可能な引数を空値（`list:false` など）で埋め、`guarded_task` が 5 回連続で拒まれた。**ハーネス側で「空値は指定なし」と扱うよう修正済み** |
| `gpt-6-sol`・`grok-4.7` | 行の途中の `&`（`sleep 20 & echo $!`）が拒否をすり抜けた。修正後は、どちらも拒否され、`bg_run` に切り替えた |
| 4 モデル（sonnet-5.5・gemini-3.8-flash・grok-4.7・gpt-6-sol） | サーバー起動を、`bg_run` と `bg_kill` だけで済ませた |
| `claude-haiku-4.5` | 難しめの課題で担当外にファイルを残し、仕様の細部を落とす |
| opus の medium/high | リファクタリングで、作業ツリーの外へ比較用ファイルを書き、確認待ちで止まった |

## 見立て（推測を含む。実測で確かめるまで、設定には入れない）

- **固定の「ベンダー別の分担」は採らない。** 役割は、**能力・費用・独立性**で決める
  - 親（オーケストレーター）: **最も強く、長い自律作業と委譲に強いモデル**。今の環境では Sonnet 5.5（`deep` の `#high`）。**最大の effort は避ける**（scope creep の開示があるため）。ハーネス側の制約（入れ子にしない・書込みを担当ファイルに限る・範囲外の検出）で補う
  - `worker`: 仕様が固まった実装は **Sonnet 5.5 `#medium`（計測済み）が既定**。**GPT-6.1 Sol / Terra を、代替の階層として足して、同じ課題で比べる**（費用が小さく、マージ可能な差分で優位という公開値があるため。ただし、Copilot は使い放題なので、費用の利点は、予算が有限な Bedrock のほうが効く）
  - `explore`: 読み取り専用で、並列にでき、結果は短い要約。**安価な小型（Haiku 5.5 か Luna）を、候補にして比べる**。ただし、報告の正確さ（「不明」と書くか）が肝なので、計測が要る
  - `review`: **「作った者と別の系統」を規則にする**（親・worker が Claude なら GPT、GPT なら Claude）。今の固定（GPT）は、親が Claude の間は妥当
- **異系統の組み合わせは、調整の費用が増える**（厳格なスキーマの癖、ツールの規律の違い）。ハーネスの寛容さで吸収してあるが、系統を増やすほど、癖の対応が増える
- **同じ系統の中の分担（`opusplan` 型）が、一次資料の裏づけがある**唯一の形。この環境で言えば、親は Sonnet `#high`、worker は Sonnet `#medium`

## 次に確かめること（実験の設計案）

- 同じ 3〜5 個のタスクで、構成を変えて、pi の `guarded_task` 経由で比べる: ① 親 Sonnet・子 Sonnet ② 親 Sonnet・worker Sol ③ 親 Sol・worker Sonnet
- 測るもの: 合格率、**委譲率（親が自分でやった割合）**、範囲外の編集、トークン・時間・費用、異系統の癖による失敗（拒否・空値）
- 前提: オーケストレーター役（親の指示で、委譲に徹する）と、待ち合わせの実装（[調査 O1](pi-orchestrator-survey.md)）

## 検索語

「Anthropic multi-agent research system Opus lead Sonnet subagents」「aider architect editor mode benchmark」「Claude plans GPT Codex implements workflow」「multi-agent LLM same model all roles vs heterogeneous models」「Terminal-Bench leaderboard Claude GPT」「orchestrator subagent delegation Claude Sonnet 5.5 vs GPT-6」「GPT-6 Sol vs Claude Sonnet 5.5 instruction following scope creep」ほか
