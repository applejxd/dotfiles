# CHG-0001: compaction を跨いで作業文脈を失わない

- **状態**: Done
- **更新日**: 2026-09-25
- **終了日**: 2026-09-25
- **基準**: OpenCode V2（plugin API の `session.hook`）。
  Claude Code 2.1.x / Copilot CLI 1.0.87-0 での実装は**当時の記録**として残す

> **この文書は当時の記録。** 現在の仕様は
> [checkpoint](../../spec/checkpoint.md)。
>
> 当初の設計（逐次保存 + 圧縮直前の機械記録 + 圧縮直後の注入）は、
> OpenCode V2 の plugin API により**圧縮フック 1 本**へ縮んだ。
> 撤回した前提とその理由は「重要な更新」にある。

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

#### 実機の圧縮で `compaction` フックの発火を確認した

`chezmoi apply` 後、このリポジトリでの実作業中に自動圧縮が起きた。

```text
.tmp/checkpoint-sesf3286.md
- snapshot_at: 2026-09-25T02:55:20+09:00
- trigger: compaction
- head: b8e7765 (main)
```

`trigger: compaction` は **plugin にしか書けない値**である（撤去した hook は
`auto` / `manual` を入れていた）。**最後まで静的解析しか根拠が無かった
「`compaction` フックが実機で発火するか」が、これで実測に置き換わった。**

#### そのかわり欠陥が 2 つ出た（2026-09-25）

同じ圧縮で**復帰注入は届かなかった**。印は消えているのに、圧縮後の手番の
文脈に記録が無い。調べたところ原因は 2 つあった。

**欠陥 A — 起きていない圧縮で印が置かれる。** 使い捨てリポジトリで再現した。

```text
COMPACTION 発火 → snapshot → 印を置いた
Error: Nothing to compact yet      ← 圧縮は起きていない
（次の普通の要求） 印あり → 注入した (408 文字)
モデル: KUJIRA42                   ← 起きていない圧縮の引き継ぎを読んだ
```

圧縮フックは「圧縮を**試みる**側」に付いている。上流
（v2.0.14 `packages/core/src/session/compaction.ts`）では
`Nothing to compact yet` の門番が `prepare` より前にあり、そこでは `Failed`
を publish して返る。`Ended` は成功経路でしか出ない。

**欠陥 B — 印がユーザの手番まで残らない。** `context` フックは 1 手番のうち
**ステップごとに**走る（実測で 5 回）。圧縮の直後に走るのは内部の継続要求の
ことがあり、そこで読み捨てると次にユーザが話しかけたときには残っていない。

#### 直した（2026-09-25）

記録する口と印を置く口を分けた。

| 口 | すること |
| --- | --- |
| `session.hook("compaction")` | `checkpoint.py snapshot` を呼ぶ**だけ** |
| `ctx.event.subscribe()` | `session.compaction.ended` を見て印を置く |
| `session.hook("context")` | 印があれば注入。**ユーザの手番なら**消す |

##### 上流ソースで裏を取った

実測と deepwiki の説明が食い違ったため、`gh` で v2.0.14 のソースを直接読んだ。
**deepwiki の説明は誤りで、実測が正しかった。**

| 項目 | deepwiki | 実ソース v2.0.14 |
| --- | --- | --- |
| `subscribe` の引数 | イベント型で絞り込む | `SubscribeOptions`（`signal` / `onActivity`）のみ。**絞り込まない** |
| ペイロードの場所 | `properties` | **`data`**（`SessionEvent.Compaction.Failed["data"]`） |
| `session.compaction.failed` | 存在しない | 存在する |

`packages/client/src/shared-events.ts` の
`subscribe(options?: SubscribeOptions): AsyncIterable<A>` が実体。購読の容量は
**4096 件**で、消費が遅れると購読ごと落ちる。一致しないイベントは何もせずに
素通しすること。

##### 通しの実測

使い捨てリポジトリで**本物の自動圧縮**を起こした（`compaction.buffer` を
極端に大きくする）。`session_message` に `status: completed` の圧縮が記録され、
その後の再試行だけが `failed` になった。

```text
圧縮 completed → Ended → 印を置いた
再試行 failed  → 印は増えない          ← 欠陥 A が直っている
圧縮後のユーザ手番 → 注入 → 印を消費
モデル: KUJIRA42                        ← 記録にしか無い語を答えた
```

**圧縮を跨いでユーザの手番へ引き継ぎが届くことを、通しで確認できた。**

### 圧縮要約と引き継ぎを一本化した（2026-09-25）

ここまでの構成には穴が残っていた。**意味内容を書くのは人（モデル）の手作業**で、
plugin が自動で書けるのは機械節だけだった。実際にこのリポジトリの作業中、
機械節は 02:55 に更新されたのに意味内容は前日 22:30 のまま取り残された。

#### 使える口を実測した

| 口 | 結果 |
| --- | --- |
| `e.result = { summary }` | **採用される。** `status=completed` で要約が差し替わり、OpenCode 自前の生成は走らない |
| `ctx.session.generate({ sessionID, prompt })` | **成功。** `{"text":"..."}` を返す |
| `generate` から会話履歴が見えるか | **見える。** 会話中の合言葉（`KIRIN9`）を即答した |

上流の型にも明記がある。

```ts
export interface SessionCompaction extends SessionContext {
  /** Set to use this compaction and skip the model request. */
  result?: SessionCompactionResult
}
```

#### 設計

圧縮フックで `session.generate` を呼び、雛形どおりの 6 節を書かせて
checkpoint に保存し、**同じものを `e.result.summary` に入れる**。

- **モデル呼び出しは増えない。** OpenCode はもともと圧縮で 1 回呼ぶ。その 1 回を
  自前の生成に置き換えるだけ
- **会話を詰め直さない。** `generate` は履歴が見えている
- **書式は `references/checkpoint-template.md` が単一ソース。** プロンプトに
  そのまま貼る

#### 退避の設計

`generate` は**同じプロンプトでも空文字を返すことがある**（実測。使い捨て環境の
無料モデルで再現）。そのため:

- 機械節は生成の前に**無条件で**書く。生成が失敗しても事実だけは残る
- 空なら 1 度だけ引き直す
- 6 節が揃わなければ捨てて `e.result` を**設定しない** → OpenCode 標準の要約に戻る
- `generate` もモデル呼び出しなので、同じセッションでの再入を禁じる

実際に生成が空になった回では、この退避どおり機械節だけが残り、OpenCode の要約で
会話が続いた。**壊れ方が設計どおりであることも確認できた。**

### skill が読まれない（2026-09-25）

`chezmoi apply` の直後、`checkpoint` スキルがモデルの一覧から消えた。
`~/.claude/skills/checkpoint`（移動前のコピー）が `.chezmoiremove` で削除され、
移動先の `~/.config/opencode/skills/checkpoint` が**代わりに入ってこなかった**。

#### 切り分け

公式ドキュメントは `~/.config/opencode/skills` を Global の探索先として挙げる。
それでも読まれないので、使い捨てスキルを各所に置いて `/api/skill` で数えた。

| 置き場 | 登録された |
| --- | --- |
| `~/.opencode/skills` | **される** |
| `~/.config/opencode/skills` | されない |
| `skills` 設定で名指し | **される** |

サービスのログでも裏が取れる。監視対象に `~/.config/opencode/skills` が無い。

```text
path=/home/applejxd/.claude/skills    type=directory
path=/home/applejxd/.opencode/skills  type=file
```

**登録は動的に更新される。** 置いた 3 秒後には `/api/skill` に現れるので、
再起動は要らない。最初「登録が起動時のまま」と結論したのは誤りで、待ち時間を
置かずに問い合わせていたための誤読だった。

#### 対処

`~/.opencode/skills` へ移せば動くが、**この置き場は文書化されていない**。
一方 `skills` 設定は文書化されていて、既定の探索先がどちらでも効く。
そちらを採った。`merge_opencode_config` が `skills` を常に書く。

`plugins` と同じく、宣言外のエントリは残して重複は足さない。

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
**実機の `/compact` で `PreCompact` が発火することを確認した**（[E5](../../research/agents/compaction-hooks.md)）。
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
| `PostCompact` で注入 | — | decision control が無く注入できない（[E1](../../research/agents/compaction-hooks.md)） | — | **見送り** | — |
| 指示ファイルで無条件に読ませる | システムプロンプト側なので圧縮されない | 自律実行の途中では発火しない | 実効性 | **検証中** | P0-3 |
| Copilot `PostToolUse` で 1 回注入 | `exec`/`args` でシェル非依存。当初の Windows 理由は撤回 | 復帰後の最初のツールは注入前に実行される | 発火頻度 | **保留** | P0-3 の結果しだい |
| `PreCompact` をブロックして書かせる | 手動なら安全 | `auto` を止めると context-limit 回復時にリクエストが失敗する | — | **見送り（auto）** | — |
| `fork` に checkpoint を書かせる | 会話全体を継承し、親の文脈を使わない | 分岐はスナップショット。古い fork が親の新しい記録を上書きする | — | **見送り** | — |
| `TaskCompleted` で促す | タスク完了は自然な区切り | `additionalContext` 非対応（[E2](../../research/agents/compaction-hooks.md)）。exit 2 の強制しかできない | — | **見送り** | — |
| セッション横断の GC | ファイルが溜まらない | 稼働中の他セッションの記録を消す | — | **見送り** | — |
| Copilot で文脈使用率を推定して閾値監視 | 長い探索の取りこぼしを拾える | **`PostToolUse` 入力に `transcript_path` が無い**（[E4](../../research/agents/compaction-hooks.md)）。トークン情報は圧縮時とセッション終了時にしか出ず、閾値を跨ぐ前に読めない（[E6](../../research/agents/compaction-hooks.md)） | — | **見送り（決着）** | — |

## 次の調査・実験

| # | 減らしたい不確実性 | 方法 |
| --- | --- | --- |
| P0-3 | 圧縮後、作業再開前に checkpoint が届くか | Claude 実機で圧縮を起こし、最初のモデル要求時点を観測 |
| P1-4 | Windows 実機での動作 | 実機の PowerShell で配備・発火・起動時間を確認 |

**決着済み**: P0-7（Copilot の hook 入力契約、[E3](../../research/agents/compaction-hooks.md) /
[E5](../../research/agents/compaction-hooks.md)）、
P0-2（使用率の取得、[E4](../../research/agents/compaction-hooks.md) /
[E6](../../research/agents/compaction-hooks.md)）、
P0-1（ターン途中の圧縮、[E6](../../research/agents/compaction-hooks.md)）

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| 指示ファイル | （なし）→ 「文脈の引き継ぎ」節 | 圧縮を跨いで生き残る唯一の層 | 適用済み `7c6703c` |
| スキル | （なし）→ `checkpoint` | 手順の単一ソース | 適用済み `7c6703c` |
| `docs/` | 3 分類 → 4 種類 + ダッシュボード | [ADR-0010](../../adr/0010-exploratory-spec-driven-docs.md) | 適用済み `2e7b44e` |
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
[E5](../../research/agents/compaction-hooks.md)。

| 項目 | 期待 | 実測 |
| --- | --- | --- |
| `## Snapshot` の `snapshot_at` | 圧縮時刻へ更新 | `2026-09-19T15:59:37+09:00` |
| `trigger` | 手動圧縮を記録 | `manual` |
| ヘッダ `updated_at` | 不変 | `2026-09-19T13:45:00+09:00` |
| ヘッダ `covered_through` | 不変 | `manual@2026-09-19T13:45:00+09:00` |
| 意味内容 6 節 | 無傷 | 無傷 |

**実機での圧縮試験（2026-09-25、OpenCode 2.0.14）:**

**この案件の主目的がここで成立した。** 自動圧縮が走り、`session.hook("compaction")`
が意味内容 6 節を生成して `.tmp/checkpoint-sesf3286.md` へ書き、同じ内容が
圧縮要約としてセッションへ戻った。**書いたものと戻ったものが同一**である。

| 項目 | 期待 | 実測 |
| --- | --- | --- |
| 意味内容 6 節 | 圧縮時点の内容で埋まる | 埋まった（`## Goal` 〜 `## Refs`） |
| `## Next` の具体性 | 次の一手が読める | 「この圧縮の結果を検査する」と手順つきで書かれた |
| `## Snapshot` の `snapshot_at` | 圧縮時刻 | `2026-09-25T05:01:10+09:00` |
| `trigger` | 自動圧縮を記録 | `compaction` |
| 前世代の退避 | `.prev.md` へ | 同時刻で退避された |
| 圧縮要約としての復帰 | 同じ内容が戻る | 戻った（この文書の更新はその文脈で書いている） |

モデル呼び出しは増えていない。圧縮のために元々走る 1 回を `session.generate` で
使い回しているため、**要約の代わりに checkpoint が出てくる**構図になる。

**未検証**: Windows 実機、
`chezmoi diff`（sandbox 内では `~/` が不可視のため無意味）

## 重要な更新

| 日付 | 変更 | 理由 |
| --- | --- | --- |
| 2026-09-18 | 主方式を「圧縮直前の一括記録」→「重要な区切りでの逐次保存」へ | ターン途中の自動圧縮に間に合わない経路がある |
| 2026-09-18 | 保存と文書化を A1 / A2 / B に分離 | 記憶を失う前の保存が、判断の要る作業の後ろにあった |
| 2026-09-18 | checkpoint の書き手を親に限定 | 古い fork が親の新しい記録を上書きする |
| 2026-09-19 | 保存先を常にセッション別名へ | 所有権の交渉・ロック・固定名の奪い合いが不要になる |
| 2026-09-19 | 文字数予算を 2000 で確定 | 復帰試験の実測が 1098 文字で「ちょうどよい」判定 |
| 2026-09-19 | Copilot の閾値監視を「見送り」へ | `PostToolUse` 入力に `transcript_path` が無いことを実測（[E4](../../research/agents/compaction-hooks.md)） |
| 2026-09-19 | `.chezmoiremove` をディレクトリ指定へ | `adr` skill を消したのにファイルを個別に並べたため、空の `skills/adr/` が残った。ディレクトリを書けば再帰削除される（実測）。同じ理由で残っていた `commit/scripts/` も直した |
| 2026-09-19 | Copilot の閾値監視を「決着（見送り）」へ | `preCompact` の `transcriptPath` をたどっても、本体会話の消費量は記録されない（[E5](../../research/agents/compaction-hooks.md)） |
| 2026-09-19 | `snapshot_at` をヘッダから機械節へ一本化 | hook はヘッダを触らない設計なので、ヘッダに置くと誰も更新せず「未取得」に見え続けた。旧雛形の名残は `lint` の警告で拾う |
| 2026-09-19 | 「逐次保存 + 圧縮直前の機械記録」の構成を実測で裏付け | 自動圧縮は assistant ターンの境界で起き、`PreCompact` は確実に呼ばれるが、その時点でモデルに意味内容を書かせる余地は無い（[E6](../../research/agents/compaction-hooks.md)） |
| 2026-09-25 | 対象を OpenCode V2 のみへ絞り、hook 層 3 本を撤去 | `session.hook` に専用の口があり、両 CLI 前提で要った工夫がまるごと不要になる |
| 2026-09-25 | 「圧縮の時点でモデルに意味内容を書かせる余地は無い」を撤回 | `session.hook("compaction")` は `session.generate` を呼べる。**圧縮要約と引き継ぎを一本化**でき、モデル呼び出しも増えない |
| 2026-09-25 | skill 置き場を `skills` 設定で名指し | `~/.config/opencode/skills` は公式ドキュメントに載るが v2.0.14 は走査しない |

## 終了結果

**採用・配備済み（2026-09-25）。**

圧縮要約そのものを checkpoint にした。圧縮が走ると
`session.hook("compaction")` が意味内容 6 節を生成してファイルへ書き、
同じものを `e.result` に入れてセッションへ返す。**保存と復帰が同じ成果物**に
なったので、両者がずれる余地が無くなった。

当初の設計（逐次保存 + 圧縮直前の機械記録 + 圧縮直後の注入）から、
**圧縮フック 1 本**へ縮んだ。撤回した前提は「圧縮の時点でモデルに意味内容を
書かせる余地は無い」で、これは両 CLI の hook が外部プロセスだったことに
由来する制約だった。plugin はホストの中で動き、モデルを呼べる。

現行仕様は [checkpoint](../../spec/checkpoint.md)。

**引き継ぐ未検証**: Windows 実機での動作（`300_windows/346` の順序変更）。
