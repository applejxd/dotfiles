# CHG-0001: compaction を跨いで作業文脈を失わない

- **状態**: In progress
- **更新日**: 2026-09-24
- **基準**: OpenCode V2（plugin API の `session.hook`）。
  Claude Code 2.1.x / Copilot CLI 1.0.87-0 での実装は**当時の記録**として残す

## 目的と非目的

**目的**: context compaction が走っても、探索の経緯・決定・残作業を失わないようにする。

満たしたいのは 2 つ。

1. ユーザーが現状と計画を把握できる
2. AI がセッション間でコンテキストを共有できる

**非目的**:

- 圧縮アルゴリズムそのものへの介入
- 全会話の保存（必要なのは復帰に要る最小限）
- **Claude Code / Copilot CLI への対応**（2026-09-24 に対象外とした。
  実装済みのものは動いているので残すが、以後は OpenCode V2 だけを見る）

### hook 層を撤去して plugin へ寄せた（2026-09-25）

Claude / Copilot 向けの hook 3 本を撤去し、OpenCode plugin で建て直した。

| 撤去したもの | 置き換え |
| --- | --- |
| `checkpoint_precompact`（Claude + Copilot） | `session.hook("compaction")` |
| `checkpoint_restore`（Claude `SessionStart`） | `session.hook("context")` |
| `checkpoint_restore_pending`（Copilot `PostToolUse`） | 同上（印は `ctx.storage`） |
| `checkpoint_core.py` / `checkpoint_pending.py` | `checkpoint.py snapshot` |

機械節の生成と保存先の解決は **`checkpoint.py` が単一ソース**。plugin は
それを呼ぶだけで、ロジックを持たない（二重に持つと必ずずれる）。

Copilot 側が必要としていた「印 + `PostToolUse` で相乗り」という二段構えは、
`ctx.storage` が使えるので**不要になった**。

#### 通しの実測

使い捨ての git リポジトリで、1 回の要求の中に「圧縮 → 復帰」を並べて実行した。

```text
onCompaction → checkpoint.py snapshot → .tmp/checkpoint-sesf2b79.md 生成
             → ctx.storage に印
onContext    → 印を読む → ファイルを読む → e.system へ push
```

モデルに「引き継ぎ記録の `head` の値だけを答えて」と尋ねたところ **`c5a92c8`**
と答え、リポジトリの実際の HEAD と**完全に一致**した。
**注入が届いて読まれていることを、通しで確認できた。**

> `compaction` フック自体の発火は、依然として実機の圧縮でしか確かめられない。
> ここで確かめたのは「発火したあと正しく動くか」まで。

## 方針転換: OpenCode 専用にする（2026-09-24）

スキルの置き場を `~/.claude/skills/checkpoint` から
**`~/.config/opencode/skills/checkpoint`** へ移した。

**理由は依存の深さ。** この仕組みが要るものは、どれも OpenCode V2 の独自機能。

| 要るもの | 使う口 | 他 CLI の同等物 |
| --- | --- | --- |
| 圧縮そのものの捕捉 | `session.hook("compaction")` | Claude は `PreCompact`、Copilot は印 + `PostToolUse` の二段 |
| 圧縮後の注入 | `session.hook("context")` | Claude は `SessionStart` matcher `compact` のみ |
| 印の永続化 | `ctx.storage` | **どちらも無い**（セッション単位の置き場しかない） |
| 要約の差し替え | `agent.compaction` / `compaction` フック | 無い |

横断させようとすると、**一番機能の薄い CLI に合わせる**ことになる。
`ctx.storage` の代替が無い時点で、印を置く設計が CLI ごとに変わる。
横断の維持費に見合わないと判断した。

### 移動にあたって踏んだ落とし穴

`ocs` の `read` は **`~/.config/opencode` を丸ごとは開けていない**。
`service.json`（常駐サービスの認証情報）が読めてしまうため、R4 で
`guide-plugin` だけに絞ってあった。

このまま移すと**境界の内側でスキルが読めなくなる**ので、
`~/.config/opencode/skills` を明示的に足した（read のみ、境界は弱まらない）。

### 残っている不整合

hook 層の 3 本は 2026-09-25 に撤去した（上記）。**不整合は解消済み。**

## 現在地

> **2026-09-24 — 対象を OpenCode V2 のみへ絞り、再評価した。**
> Claude Code / Copilot CLI は対象外とする（実装済みのものはそのまま残す）。
> **OpenCode V2 では、両 CLI の hook で組んだ構成より素直に実現できる。**

### OpenCode V2 の plugin API に専用の口がある

| 口 | できること |
| --- | --- |
| `session.hook("compaction")` | **圧縮そのものに介入**する。要約対象の transcript を `messages` で受け取り、`result` を入れれば要約自体を差し替えられる |
| `session.hook("context")` | エージェントループの**毎リクエスト直前**に `event.system` へテキストを push できる |
| `ctx.storage` | plugin スコープの**永続 JSON 置き場**（`get` / `set` / `remove` / prefix 走査） |

### 両 CLI 前提の設計で要った工夫が、まるごと不要になる

| 両 CLI で必要だったもの | OpenCode V2 では |
| --- | --- |
| Copilot の `PreCompact` は通知専用なので、**印を置いて `postToolUse` で注入**する | `context` フックが**次のモデル要求で直接** system に足せる |
| そのため**1 ツール分の注入遅れ**が残る（非目的として許容していた） | **遅れが無い**。ツール実行を待たない |
| 圧縮を跨ぐだけなら `.tmp` で足りる（永続の置き場が無いため） | `ctx.storage` が**永続する**。セッションを跨げる |
| Copilot は hook 登録を**起動時にしか読まない**（`/restart` が要る） | plugin の `setup` で登録し、`reload()` も持つ |

### 覆った結論が 2 つある

- 「**両 CLI とも『リポジトリ単位で永続する共有の置き場』を持たない**」
  → OpenCode には `ctx.storage` がある。`ctx.location.project` で
  プロジェクトを識別できるため、キーに含めればリポジトリ単位にできる
  （**スコープの実際の挙動は未検証**）
- 「圧縮直後の注入は 1 ツール分ずれる」
  → OpenCode では `context` フックが毎リクエスト直前に走るのでずれない

### まだ分からないこと

> **2026-09-24 に実測した。** 4 件のうち 3 件が解決。残り 1 件は長い会話が要る。

| 論点 | 結果 |
| --- | --- |
| `compaction` フックが**自動圧縮でも発火するか** | **静的には解決**（下記）。実測は未了 |
| `ctx.storage` のスコープ | **OpenCode の DB に入る**（`OPENCODE_DB` で指した DB 内にマーカーを検出）。したがって `ocs` ではワークスペースごと、通常版ではホスト DB で共通 |
| `context` フックで push した system が**要求に載るか** | **載る**。`event.system` の要素が 4 → 5 になった |
| 届くことと**効くこと** | **効いた**。返答が指定どおり `ZEBRA7` で始まった |

#### 実測の手順と結果

使い捨てディレクトリに `.opencode/plugins/hookprobe/index.js` を置き、
`OPENCODE_DB` を隔離して `opencode run --standalone` を実行した。

```text
setup: opencode=2.0.14
location: dir=<使い捨てディレクトリ>
project: id=29ee32ab...
storage: 読み戻し={"marker":"STORAGEMARK42"}
registered: context / compaction / generate / title    ← 4 つとも成功
fire: title messages=1
fire: context messages=1
inject: system になった要素数=5
```

モデルの返答は `ZEBRA7 ok` で始まった。**注入した system 指示がそのまま効いている。**

これで CHG-0001 の中核（圧縮後に文脈を注入する）は、**機構としては成立が
確認できた**。残るのは「圧縮という出来事を捉えられるか」だけ。

#### 自動と手動で経路が分かれないこと（2026-09-24、静的解析）

実機の `/compact` を待たずに、**バイナリの読み取りで決着した**。
セッション要求を組み立てる箇所に、4 つの経路とフック名の対応がある。

```js
primary:    (s) => I("primary",    s, i("context",    s.agent)),
compaction: (s) => I("compaction", s, i("compaction", s.agent)),
generate:   (s) => I("generate",   s, i("generate",   s.agent)),
title:      (s) => I("title",      s, ...),
```

`i` は `H.trigger("session", <名前>, ...)` を返す。つまり**フックは「圧縮を
起動する側」ではなく「圧縮の LLM 要求を組み立てる側」に付いている**。

自動圧縮も `/compact` も、要約を作るには同じ `request.compaction(...)` を
通る。**分岐が存在しないので、片方だけ発火しないことは起こらない。**

> **証拠の強さに注意。** これは難読化された配布バイナリの静的読み取りで、
> 実測より一段弱い。実機の `/compact` で発火を見たら、ここを実測に更新する。

あわせて設定スキーマから拾ったもの。

| キー | 内容 |
| --- | --- |
| `compaction.auto` | 自動圧縮の有効化（既定 `true`） |
| `compaction.keep.tokens` | 直近を逐語で残すトークン数 |
| `compaction.buffer` | 圧縮中のあふれを避ける余白 |
| `agent.compaction` | **圧縮専用エージェントを設定できる** |

最後の `agent.compaction` は**plugin を書かずに要約のプロンプト自体を
差し替えられる**可能性がある。実装手段の候補として未評価。

#### `compaction` フックを確かめる方法（未実施）

1 ターンでは起きないので、次のどちらかが要る。

- 長い会話を作って自動圧縮を跨ぐ
- `/compact` を手で実行する（TUI が要るので **assistant では回せない**）

**登録が成功し、`context` が確実に発火することまでは確認済み**なので、
`compaction` が発火しなくても「`context` 側で印を見て注入する」形に
退避できる（印の置き場は `ctx.storage`）。

### 実装済みのもの（Claude / Copilot、対象外だが残す）

段 1〜6 が完了し、本体へマージして `chezmoi apply` まで済んだ。
**実機の `/compact` で `PreCompact` が発火することを確認した**（E5）。
**Copilot 側の復帰注入も実装した**（`PreCompact` の印 + `postToolUse`、E7）。
これらは動いているので消さないが、**この案件の対象からは外す**。

段 1〜6 が完了し、本体へマージして `chezmoi apply` まで済んだ。
**実機の `/compact` で `PreCompact` が発火することを確認した**（[E5](../research/agents/compaction-hooks.md)）。
**Copilot 側の復帰注入も実装した**（`PreCompact` の印 + `postToolUse`、E7）。
残るのは両 CLI での復帰注入の実機確認と Windows 実機。

**分かったこと:**

- **両 CLI とも全工程を hook で構成できる。** Copilot に `SessionStart` matcher
  `compact` 相当は無いが、通知専用の `PreCompact` が印を置き `postToolUse` が
  `additionalContext` で返せば繋がる（E7）
- `compaction` はセッションを終わらせない。圧縮を跨ぐだけなら `.tmp` で足りる
- 両 CLI とも「リポジトリ単位で永続する共有の置き場」を持たない。
  Claude の `scratchpad_dir` も Copilot の session-state も**セッション単位**
- したがって、セッションを跨いで要る知識は **`docs/` 側（案件）が正本**であるべき
- **Copilot は hook の登録を起動時にしか読まない。** 追加・変更したら `/restart` が要る

**まだ分からないこと:**

- 圧縮後の最初のモデル要求時点で checkpoint が届くか（両 CLI とも実機未検証。
  hook 単体では両経路とも動作確認済み）
- Windows 実機での hook 発火と起動時間

**決着したこと（E3 / E4 / E5 / E6 / E7）:**

- **Copilot は PascalCase 登録で snake_case 入力が来る**。稼働中の hook が
  snake_case のキーしか読まずに機能していることで裏付けられた。
  `events.jsonl` に残る camelCase の記録は**内部表現**であり、配送形式ではない
- **Copilot では文脈使用率を推定できない**。`postToolUse` に `transcript_path` が
  無いのに加え、トークン情報は `session.compaction_start` /
  `session.compaction_complete` / `session.shutdown` にしか出ない。
  **閾値を跨ぐ前に読める場所が無い**（E5 / E6）
- **自動圧縮でも `PreCompact` は確実に呼ばれる**。ツールループへの割り込みではなく
  assistant ターンの境界で起きるため、機械記録を取り損ねる経路は無い（E6）
- **Copilot でも圧縮直後の自動注入はできる**（E7）。E1 の「原理的にできない」は
  誤りで、「圧縮イベントの有無」しか調べていなかったことが原因。
  **通知専用のイベントでも印は置ける**ので、注入は別イベントへ委ねられる

## 評価基準

**必須:**

- 圧縮後、**作業を再開する前に** checkpoint が読まれること
- 保存が、判断を要する文書化の完了に依存しないこと
- 別セッションの記録を読まない・壊さないこと

**望ましい:**

- 親の文脈をこれ以上消費しないこと
- 個人用 dotfiles に対して過剰でないこと

**重要な更新（評価基準の変更）**: 当初は「圧縮直前に docs を一括更新する」を必須に
置いていた。ターン途中の自動圧縮に間に合わない経路があると判明したため、
**「重要な区切りでその都度保存する」を主方式に変更**した（2026-09-18）。

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| `SessionStart` matcher `compact` で注入 | 公式が圧縮直後の注入点と明記。プレーン stdout も可 | Claude 専用 | 実機での発火 | **有望** | P0-3 |
| `PostCompact` で注入 | — | decision control が無く注入できない（[E1](../research/agents/compaction-hooks.md)） | — | **見送り** | — |
| 指示ファイルで無条件に読ませる | システムプロンプト側なので圧縮されない | 自律実行の途中では発火しない | 実効性 | **検証中** | P0-3 |
| Copilot `PostToolUse` で 1 回注入 | `exec`/`args` でシェル非依存。当初の Windows 理由は撤回 | 復帰後の最初のツールは注入前に実行される | 発火頻度 | **保留** | P0-3 の結果しだい |
| `PreCompact` をブロックして書かせる | 手動なら安全 | `auto` を止めると context-limit 回復時にリクエストが失敗する | — | **見送り（auto）** | — |
| `fork` に checkpoint を書かせる | 会話全体を継承し、親の文脈を使わない | 分岐はスナップショット。古い fork が親の新しい記録を上書きする | — | **見送り** | — |
| `TaskCompleted` で促す | タスク完了は自然な区切り | `additionalContext` 非対応（[E2](../research/agents/compaction-hooks.md)）。exit 2 の強制しかできない | — | **見送り** | — |
| セッション横断の GC | ファイルが溜まらない | 稼働中の他セッションの記録を消す | — | **見送り** | — |
| Copilot で文脈使用率を推定して閾値監視 | 長い探索の取りこぼしを拾える | **`PostToolUse` 入力に `transcript_path` が無い**（[E4](../research/agents/compaction-hooks.md)）。トークン情報は圧縮時とセッション終了時にしか出ず、閾値を跨ぐ前に読めない（[E6](../research/agents/compaction-hooks.md)） | — | **見送り（決着）** | — |

## 次の調査・実験

| # | 減らしたい不確実性 | 方法 |
| --- | --- | --- |
| P0-3 | 圧縮後、作業再開前に checkpoint が届くか | Claude 実機で圧縮を起こし、最初のモデル要求時点を観測 |
| P1-4 | Windows 実機での動作 | 実機の PowerShell で配備・発火・起動時間を確認 |

**決着済み**: P0-7（Copilot の hook 入力契約、[E3](../research/agents/compaction-hooks.md) /
[E5](../research/agents/compaction-hooks.md)）、
P0-2（使用率の取得、[E4](../research/agents/compaction-hooks.md) /
[E6](../research/agents/compaction-hooks.md)）、
P0-1（ターン途中の圧縮、[E6](../research/agents/compaction-hooks.md)）

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| 指示ファイル | （なし）→ 「文脈の引き継ぎ」節 | 圧縮を跨いで生き残る唯一の層 | 適用済み `7c6703c` |
| スキル | （なし）→ `checkpoint` | 手順の単一ソース | 適用済み `7c6703c` |
| `docs/` | 3 分類 → 4 種類 + ダッシュボード | [ADR-0010](../adr/0010-exploratory-spec-driven-docs.md) | 適用済み `2e7b44e` |
| `adr` スキル | 独立 → `checkpoint` へ統合 | 役割が重複していた | 適用済み（段 6） |
| `spec/` | （なし）→ `checkpoint.md` | 運用仕様の正本が要る | 適用済み `2e7b44e` |
| `.chezmoiremove` | ファイル個別指定 → ディレクトリ指定 | 配下を並べると空ディレクトリが残る（実測） | 適用済み `6ecdba7` |

## 実装・検証

**完了（段 1〜6）:**

- `home/dot_config/opencode/skills/checkpoint/` — スキル、雛形 4 種、CLI
- 両 CLI の指示ファイルへ恒久ルール
- `docs/` の 4 種類 + ダッシュボード + `scripts/lint_docs.py`
- `adr` スキルを `checkpoint` へ統合
- **hook 2 本**（`PreCompact` の機械記録 / `SessionStart` matcher `compact` の復帰）

**検証結果:**

- `pytest test/agents/ test/test_lint_docs.py -q` → 1702 passed, 7 skipped
- 古い記録（`covered_through=msg-42`）に新しい要求（`msg-99`）→ lint が exit 1
- 15 回書き込んでも他セッションのファイルは無傷
- 復帰試験: 1098 文字（予算 2000 の 55%）で「引き継ぎに十分」と判定
- 機械記録が意味内容・`updated_at`・`covered_through` を壊さないことを実測
- スキル未配備でも hook は exit 0（圧縮を止めない）

**配備の確認（2026-09-19、`chezmoi apply` 後）:**

- `~/.config/opencode/skills/checkpoint/` に SKILL.md・雛形 4 種・`checkpoint.py`（実行権限付き）
- **配備版の `checkpoint.py paths` が worktree ルートを正しく解決**した
  （`.git` がファイルでも `git rev-parse` 経由で解決できている）
- 生成される hook は Claude が `PreCompact` と `SessionStart`(matcher `compact`)、
  Copilot が `PreCompact`。matcher 省略時はキーごと省かれ `null` にならない
- `chezmoi managed` に hook 3 本が含まれ、`.chezmoiignore` で落ちていない
- **hook の実ファイルは sandbox から不可視**（`~/.claude/hooks` が ENOENT、
  `~/.copilot/settings.json` が EACCES）。追加許可は再起動まで効かない

**実機での圧縮試験（2026-09-19、Copilot CLI 1.0.87-0）:**

1 回目は発火しなかったが、原因は実装ではなく **Copilot が hook の登録を
起動時にしか読まない**ことだった（プロセス起動 12:38:40 / 登録更新 12:51:32）。
設定を変えず `/restart` しただけで 2 回目は発火した。詳細は
[E5](../research/agents/compaction-hooks.md)。

| 項目 | 期待 | 実測 |
| --- | --- | --- |
| `## Snapshot` の `snapshot_at` | 圧縮時刻へ更新 | `2026-09-19T15:59:37+09:00` |
| `trigger` | 手動圧縮を記録 | `manual` |
| ヘッダ `updated_at` | 不変 | `2026-09-19T13:45:00+09:00` |
| ヘッダ `covered_through` | 不変 | `manual@2026-09-19T13:45:00+09:00` |
| 意味内容 6 節 | 無傷 | 無傷 |

**未検証**: 圧縮直後の復帰注入（**Claude でのみ検証可能**。Copilot に
`SessionStart(compact)` 相当が無い）、Windows 実機、
`chezmoi diff`（sandbox 内では `~/` が不可視のため無意味）

## 重要な更新

| 日付 | 変更 | 理由 |
| --- | --- | --- |
| 2026-09-18 | 主方式を「圧縮直前の一括記録」→「重要な区切りでの逐次保存」へ | ターン途中の自動圧縮に間に合わない経路がある |
| 2026-09-18 | 保存と文書化を A1 / A2 / B に分離 | 記憶を失う前の保存が、判断の要る作業の後ろにあった |
| 2026-09-18 | checkpoint の書き手を親に限定 | 古い fork が親の新しい記録を上書きする |
| 2026-09-19 | 保存先を常にセッション別名へ | 所有権の交渉・ロック・固定名の奪い合いが不要になる |
| 2026-09-19 | 文字数予算を 2000 で確定 | 復帰試験の実測が 1098 文字で「ちょうどよい」判定 |
| 2026-09-19 | Copilot の閾値監視を「見送り」へ | `PostToolUse` 入力に `transcript_path` が無いことを実測（[E4](../research/agents/compaction-hooks.md)） |
| 2026-09-19 | `.chezmoiremove` をディレクトリ指定へ | `adr` skill を消したのにファイルを個別に並べたため、空の `skills/adr/` が残った。ディレクトリを書けば再帰削除される（実測）。同じ理由で残っていた `commit/scripts/` も直した |
| 2026-09-19 | Copilot の閾値監視を「決着（見送り）」へ | `preCompact` の `transcriptPath` をたどっても、本体会話の消費量は記録されない（[E5](../research/agents/compaction-hooks.md)） |
| 2026-09-19 | `snapshot_at` をヘッダから機械節へ一本化 | hook はヘッダを触らない設計なので、ヘッダに置くと誰も更新せず「未取得」に見え続けた。旧雛形の名残は `lint` の警告で拾う |
| 2026-09-19 | 「逐次保存 + 圧縮直前の機械記録」の構成を実測で裏付け | 自動圧縮は assistant ターンの境界で起き、`PreCompact` は確実に呼ばれるが、その時点でモデルに意味内容を書かせる余地は無い（[E6](../research/agents/compaction-hooks.md)） |

## 終了結果

（未終了）
