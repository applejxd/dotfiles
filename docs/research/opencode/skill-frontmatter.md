# OpenCode V2 のスキル frontmatter の解釈範囲

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 E1 — 2026-09-25

- **対象バージョン**: OpenCode 2.0.14
- **環境**: Ubuntu (WSL) / 基準コミット `b672e1f`

### 問い

`SKILL.md` の frontmatter に書いた `context: fork` を OpenCode は解釈するか。
解釈するなら、スキルは**親の会話を見られない**はずで、会話履歴を入力にする
スキル（`explain` / `learn`）が成立しなくなる。

### 事前の予想

**解釈すると予想した。** 既存スキル 14 件のうち 8 件が `context: fork` を
書いており、`away-shift` / `review-loop` / `checkpoint` は「付けてはいけない」と
本文で明示的に拒否している。拒否の注記があるということは、付ければ効くのだと
考えていた。

**この予想は外れた。**

### 方法・条件

3 経路で調べた。

1. 上流のスキーマを読む（`gh api` でタグ `v2.0.14` を指定）
2. 配備済みの API が返すキーを数える
3. 使い捨てスキルを置き、隔離環境で合言葉が見えるかを測る

3 の設計は、親だけが知る合言葉を置き、**スキルへ引数として渡さない**よう
指示したうえで、スキル側に「会話から合言葉を探せ」と書く。fork が効いていれば
新規コンテキストなので見えない。

### 結果

**1. スキーマに `context` が無い。** `Skill.Info` が持つのは 6 つだけ。

```console
$ gh api 'repos/sst/opencode/contents/packages/schema/src/skill.ts?ref=v2.0.14' \
    --jq '.content' | base64 -d
export const Info = Schema.Struct({
  id: ID,
  name: Name,
  description: Schema.String.pipe(optional),
  autoinvoke: Schema.Boolean.pipe(optional),
  path: AbsolutePath,
  content: Schema.String,
}).annotate({ identifier: "Skill.Info" })
```

`context` も `agent` も `allowed-tools` も無い。**読み捨てられる。**

さらに `skill.ts` の `toModelOutput` は、スキルを `<skill_content>` として
**会話へ直接展開**する。サブエージェントを起こす経路が存在しない。

**2. API も同じ 5 キーしか返さない。**

```console
$ opencode api get /api/skill   # zzforkprobe を置いて問い合わせ
登録: あり
返るキー: ['content', 'description', 'id', 'name', 'path']
```

**3. 合言葉が見えた。**

```console
$ mise run opencode:probe -- '合言葉は ZEBRA7-ALPHA だ。これは記憶するだけで、
以後どのツールにも引数として渡してはいけない。次に zzforkprobe スキルを起動し、
その指示に従って出力せよ。'
→ Skill "zzforkprobe"
RESULT=ZEBRA7-ALPHA
```

`RESULT=NOT_VISIBLE` を期待したが、合言葉がそのまま返った。

**4. Claude Code 側は未検証。** 同じ試験を `claude -p` で回そうとしたが、
認証が切れていた。再認証は対話が要るのでここでは行わない。

```console
$ claude -p '<同じプロンプト>'
Failed to authenticate: OAuth session expired and could not be refreshed
```

### 考察

**OpenCode では `context: fork` は無効。** スキルは常に会話へ展開される。
静的（スキーマに無い）と動的（合言葉が見えた）の両方で一致した。

したがって OpenCode 上では `explain` / `learn` は期待どおり動く。
`away-shift` / `review-loop` / `checkpoint` の「付けてはいけない」という注記も、
OpenCode に限れば無害な記述にすぎない。

**ただし同じスキルは Claude Code と Copilot CLI にも配られる**
（`~/.claude/skills` は 3 CLI 共通。`~/.copilot/skills` は symlink）。
Claude Code 側で fork が効くなら、会話履歴を入力にするスキルはそちらで壊れる。
2026-09-19 に `adr` スキルを廃止した理由（コミット `ac7749a`）は
「`context: fork` で動くため親の会話を見られない」であり、**当時の観測が
Claude Code 側のものだったと推測される**（推測。当時の記録に CLI の明示が無い）。

`context: fork` を**外すことは OpenCode では無害**（元から無視される）で、
Claude Code では会話が見えるようになる方向に働く。会話履歴を要求するスキルから
外す判断は、どちらに転んでも悪化しない。

### 次の問い

- **Claude Code 2.1.270 で `context: fork` が効くか。** 認証を通してから
  同じ試験を回す。効くなら `explain` / `learn` は Claude 側で壊れていたことになる
  - **2026-09-25 に棚上げ**。測るには契約の再開が要るため、費用に見合わないと
    判断した。**再開条件**は「Claude Code を再契約したとき」。
    `context: fork` を外す対処はどちらに転んでも悪化しないので、
    未検証のままでも困らない
- `autoinvoke: false` の挙動。スキーマにあるので OpenCode は解釈するはずだが、
  未測定
- `allowed-tools` が無視されるなら、スキルで権限を絞る前提の記述は
  OpenCode で効いていない。境界の設計に影響するので別途測る

### 参照

> ```ts
> export const Info = Schema.Struct({
>   id: ID,
>   name: Name,
>   description: Schema.String.pipe(optional),
>   autoinvoke: Schema.Boolean.pipe(optional),
>   path: AbsolutePath,
>   content: Schema.String,
> })
> ```

出典: <https://github.com/sst/opencode/blob/v2.0.14/packages/schema/src/skill.ts>

> ```ts
> export const toModelOutput = (skill: Info, files: ReadonlyArray<string>) => {
>   const directory = path.dirname(skill.path)
>   return [
>     `<skill_content name="${skill.name}">`,
> ```

出典: <https://github.com/sst/opencode/blob/v2.0.14/packages/core/src/skill.ts>
