# 文脈の引き継ぎ (checkpoint)

コンテキスト圧縮を跨いで、作業の経緯・決定・残作業を失わないための仕組み。

> **2026-09-24: OpenCode 専用にした。**
> 圧縮の捕捉に `session.hook("compaction")`、印の保存に `ctx.storage` と、
> **OpenCode V2 の独自機能に強く依存する**ため、CLI 横断を諦めた。
> 置き場も `~/.claude/skills` から OpenCode 標準の
> `~/.config/opencode/skills` へ移した。経緯は
> [CHG-0001](../change/closed/0001-compaction-context-handover.md)。

設計判断の理由は [ADR-0009](../adr/0009-save-before-documenting.md)、
Claude Code / Copilot CLI のイベント仕様は
[compaction 関連の hook 仕様](../research/agents/compaction-hooks.md) を参照。

## 構成

強制の層を 3 つに分ける。**圧縮を跨いで生き残るのは指示ファイルだけ**なので、
恒久ルールはそこへ置く。

| 層 | 実体 | 役割 |
| --- | --- | --- |
| 指示ファイル | `home/dot_config/opencode/AGENTS.md.tmpl` | 恒久ルール。「文脈の引き継ぎ」節（OpenCode にだけ置く） |
| スキル | `home/dot_config/opencode/skills/checkpoint/` | 復帰記録（A1）と復帰の手順・雛形・CLI の単一ソース |
| plugin | `home/dot_config/opencode/checkpoint-plugin/` | 圧縮直前の記録と直後の復帰注入 |

`docs/` への文書化（案件の更新（A2）と恒久的な文書化（B））は **`sdd-docs` スキル**が持つ。分離の理由は
[スキルを A1 と A2/B に分けた](#スキルを-a1-と-a2b-に分けた)。

### plugin が担うこと

hook 層は 2026-09-25 に撤去し、OpenCode plugin へ寄せた（旧構成は
[CHG-0001](../change/closed/0001-compaction-context-handover.md) の
「hook 層を撤去して plugin へ寄せた」節）。口は 3 つある。

| 口 | いつ | すること |
| --- | --- | --- |
| `session.hook("compaction")` | 圧縮の LLM 要求を組み立てるとき | 機械節を書き、`session.generate` で 6 節を生成して保存し、`e.result` に入れる |
| `ctx.event.subscribe()` | `session.compaction.ended` が流れたとき | その回に記録を保存できていれば `ctx.storage` に印を置く |
| `session.hook("context")` | 毎要求 | 印があれば `checkpoint.py read` の出力を `event.system` へ入れる。ユーザの手番なら印を消す |

**圧縮の要約と引き継ぎは同じ成果物にする。** 別々に持つと必ず片方が古くなる
（実際に意味内容だけ 1 日古いまま残った）。`e.result` を設定すると OpenCode は
自前の要約生成を飛ばすので、モデル呼び出しの回数は増えない。

生成は `ctx.session.generate({ sessionID, prompt })` で行う。**会話履歴が見えて
いる**ので、材料を詰め直す必要は無い。プロンプトは
`references/checkpoint-template.md` をそのまま貼る（書式の単一ソース）。

**記録する口と印を置く口を分けてある。** 圧縮フックは「圧縮を試みる側」に
付いていて、その後 `Nothing to compact yet` で**失敗することがある**（実測）。
ここで印を置くと、起きていない圧縮の引き継ぎを後続の要求へ流し込む。

上流（v2.0.14 `packages/core/src/session/compaction.ts`）では、この門番が
`prepare` より前にあり `Failed` を publish して返る。`Ended` は成功経路でしか
出ない。**だから印は `Ended` にだけ結び付ける。**

ただし `Ended` だけでは、生成に失敗して標準の要約に戻った回も区別できない。
圧縮フックは記録を保存して要約に採用できたときだけ `saved:<セッション>` を置き、
`Ended` はそれがあるときだけ注入の印に変える。

圧縮フックは始めに `saved:` と注入待ちの `pending:<セッション>` を**両方**消す。
`pending:` は内部の継続要求では消えないので、残すと「圧縮 A の印が注入待ちのまま、
同じ手番で圧縮 B が生成に失敗する」ときに、B の後の要求へ A の記録を入れてしまう。
消すのは印だけで、印を置くのは従来どおり `Ended` の側だけ。

設計上の約束:

- **plugin は機械節を自分で組み立てない。** 生成・保存先の解決・記録の持ち主の
  照合・生成物の受け入れ判定は `checkpoint.py` が単一ソース。二重に持つと必ずずれる
- **どの口も例外を投げない。** 圧縮を壊さないことが最優先
- **生成・保存に失敗したら `e.result` を設定しない。** 詳細は
  [失敗時の動作](#失敗時の動作)
- **`generate` の再入を防ぐ。** generate もモデル呼び出しなので、文脈が溢れた
  ままだと圧縮を誘発しうる。同じセッションで二重に走らせない
- **印が無いときは `ctx.storage` を 1 回読むだけで抜ける。**
  `context` は 1 手番のうち**ステップごとに**走る（実測で 5 回）
- **印を消すのはユーザの手番に届けてから。** 圧縮の直後に走るのは内部の継続
  要求のことがあり、そこで消すと**次にユーザが話しかけたときには残っていない**
- **購読では一致しないイベントを素通しする。** 購読の容量は 4096 件で、消費が
  遅れると購読ごと落ちる

`ctx.event.subscribe` の引数は**イベント名ではない**。上流の
`packages/client/src/shared-events.ts` では
`subscribe(options?: SubscribeOptions)` で、`SubscribeOptions` は
`{ signal?, onActivity? }` だけ。名前を渡しても絞り込まれないので、`type` は
自分で見る。ペイロードは `properties` ではなく **`data`** に入る。

### 境界の内側から読めること

`ocs` の `read` は `~/.config/opencode` を**丸ごとは開けない**（`service.json` があるため。
[組み立ての規則](opencode-sandbox.md#組み立ての規則)）。
次の 2 つを名指しで開けている。**これが無いと境界内でだけ checkpoint が
動かない。**

- `~/.config/opencode/checkpoint-plugin`（plugin 本体）
- `~/.config/opencode/skills`（スキルと CLI）

### スキルは `skills` 設定で名指しする

**置くだけでは読まれない。** 公式ドキュメントは `~/.config/opencode/skills` を
Global の探索先として挙げるが、v2.0.14 はそこを走査しない（実測。監視対象は
`~/.opencode/skills` 側）。`opencode.json` の `skills` に名指しすると登録される。

```jsonc
{ "skills": ["/home/<user>/.config/opencode/skills"] }
```

生成は `merge_opencode_skills`（`scripts/agents/generate.py`）が常に行う。
未文書の `~/.opencode/skills` へ移さないのは、既定の探索先が将来変わっても
`skills` 設定なら効くため。

登録は**動的に更新される**（置いた数秒後に `/api/skill` へ現れる）。反映を
確かめるときは待ってから数える。待たずに問い合わせると、反映前を見て
「読まれていない」と誤読する。

```sh
opencode api get /api/skill
```

### スキルを A1 と A2/B に分けた

**`checkpoint` は A1 だけを持つ。** `docs/` への文書化（A2 / B）は
`sdd-docs` スキルが持つ。

| スキル | 対象 | 置き場 | 起動 |
| --- | --- | --- | --- |
| `checkpoint` | `.tmp/` のセッション別記録 | `~/.config/opencode/skills` | 圧縮フックが自動。手動でも呼べる |
| `sdd-docs` | `docs/change/` `adr/` `research/` `spec/` と索引 | `~/.claude/skills` | 人が頼んだときだけ |

置き場が違うのは、**OpenCode への結合があるかどうか**で決まる。`checkpoint` は
plugin が絶対パスで読み、`ctx.storage` と `session.hook` を前提にするので
OpenCode 専用。`sdd-docs` は markdown を編集して `lint_docs.py` を回すだけで
依存が無いため、3 CLI に届く `~/.claude/skills` へ置く
（OpenCode がネイティブに監視し、`~/.copilot/skills` がそこへ張られている）。

分けた理由は 2 つ。

1. **description が 2 つの仕事を名乗っていた。** 「復帰記録を保存する。ADR の
   作成・更新も行う」という形で、ルーティングの手掛かりが濁っていた
2. **plugin が A1 を自動化した。** A1 と A2/B を束ねていたのは「先に保存」の
   順序を 1 ファイルで担保するためだったが、圧縮時の A1 はスキルと無関係に
   走るようになったので、束ねる必要が薄れた

2026-09-19 に `adr` スキルを `checkpoint` へ統合したのは**これを否定しない**。
当時退けたのは `context: fork` で動く別スキルで、親の会話を見られず棚卸しを
渡し直す手間が勝っていた。同じセッションで動く兄弟スキルにはその欠点が無い。

**残るコスト**: 「先に A1」の順序がスキルを跨ぐ約束になる。両方の `SKILL.md`
に明記して補う。

## 保存先

**常にセッション別の名前**を使う。固定名を奪い合わないので、ロックも所有権の
交渉も要らない。`<sid>` はセッション ID から英数字以外を除いた**完全な ID**。

```text
<リポジトリルート>/.tmp/checkpoint-<sid>.md         本体
<リポジトリルート>/.tmp/checkpoint-<sid>.prev.md    直前の世代
<リポジトリルート>/.tmp/checkpoint-<sid>.state.json 状態 (Tier 2 用、未実装)
```

- **ID を切り詰めない。** OpenCode のセッション ID は時刻由来で、近い時刻に
  作られたセッション（`ses_f1d80f67affe…` と `ses_f1d80c05cffe…`）は先頭が揃う。
  2026-09-27 まで使っていた「英数字の先頭 8 文字」ではどちらも `sesf1d80` になり、
  互いの記録を読み書きした。`paths` が返す `session_short` は表示用で、保存名には
  使わない
- **読むときはヘッダの `session:` でも持ち主を確かめる。** 英数字以外を除く正規化は
  可逆ではないので、名前だけでは一意と言い切れない。一致しない記録は `read` が
  exit 1 で拒み、`snapshot` も機械節を足さない
- 旧形式（`checkpoint-<sid8>.md`）は読まない。`.tmp/` の一時記録なので、移行期に
  1 度だけ自動注入が効かないだけで済む
- リポジトリルートは `git rev-parse --show-toplevel` で決める。
  **plugin の `cwd` はサブディレクトリのことがある**ので `./` を前提にしない
- git の無視設定は `git rev-parse --git-path info/exclude` で解決する。
  **`.git` はファイルのこともある**（linked worktree / chezmoi の source state）
- `.gitignore` は共有ファイルなので書き換えない
- **セッション横断の削除をしない。** 件数や日数で消すと、稼働中の別セッションの
  記録まで消える。各セッションは自分の 3 ファイルだけを管理する

## 記録の形

見出しは 6 つを順序どおりに、それぞれ 1 回だけ置く。`lint --structure` は
行頭の `##` だけを見出しとして数え（文中とコードブロックの中は数えない）、
欠け・重複・順序違いを不合格にする。雛形は
`~/.config/opencode/skills/checkpoint/references/checkpoint-template.md`。

```text
<!-- checkpoint: v1
     session: <完全なセッション ID。paths が返す session>
     cli: opencode
     updated_at: <ISO8601>
     covered_through: <その要求の固定境界>
-->
# Checkpoint — <作業名>
## Goal … ## Refs          意味内容 (モデルが書く)
<!-- machine: … -->
## Snapshot                機械節 (checkpoint.py snapshot が書く)
```

| 節 | 内容 |
| --- | --- |
| `## Goal` | 達成したら終わりと言える条件（3 行以内） |
| `## Constraints` | ユーザー指定の制約、却下済みの方針 |
| `## State` | 完了 / 未完 / 未解決の論点 |
| `## Evidence` | 実行したコマンドと結果（推測を書かない） |
| `## Next` | 次の 1 手。「何を」で止めず**「どうやって」**まで |
| `## Refs` | `docs/...` のパス + 読む理由。未作成なら「未作成」と明記 |

`<!-- machine: -->` より下は `checkpoint.py snapshot` が上書きするので、人も AI も
書かない。plugin は圧縮の直前に、生成の前後で 1 度ずつ呼ぶ。

**圧縮時刻（`snapshot_at`）は機械節にだけ置く。** `snapshot` はヘッダを触らない
設計なので、ヘッダに書くと誰も更新せず「未取得」に見え続ける。旧雛形の名残として
残っていた場合は `lint` が警告する。

**文字数予算は 2000 文字**（意味内容のみ。機械節は別枠）。復帰試験の実測では
1098 文字で「引き継ぎに十分」と判定された。

## 鮮度の判定

**`covered_through` を、その保存要求の固定境界と比べる。**

- **mtime では判定しない。** 圧縮直前の `snapshot` が機械節を書くと mtime が
  更新され、古い意味内容が「新鮮」に見えてしまう
- **「現在の会話地点」とも比べない。** 保存や検査そのもので境界が進み、正しく
  保存しても永久に一致しない
- 境界は要求が立った時点で 1 つだけ固定し、以降動かさない

## 失敗時の動作

**どの失敗も圧縮と会話を止めない。** 失敗したら「何もしない」側へ倒し、
OpenCode 標準の動作に任せる。壊れた・古い引き継ぎを要約として残すより、
標準の要約に戻る方が良い。

| 失敗 | 動作 |
| --- | --- |
| `snapshot` が書けない | 捨てる（`ok: false` を返し exit 0）。生成はそのまま続ける |
| `generate` が空を返す | 1 度だけ引き直す |
| 生成物が `lint --headings-only` に通らない | 空と同じく 1 度だけ引き直す。2 回とも通らなければ捨てる。保存せず `e.result` も設定しない → OpenCode 標準の要約 |
| `write` が失敗する | `e.result` を設定しない。**残っていた古い記録を要約に採用しない** |
| 読み直した記録に生成した本文が無い | `e.result` を設定しない |
| 上のどれかで記録を採用しなかった | 圧縮が成功しても注入の印を置かない。**以前の記録を「圧縮前に保存した引き継ぎ」として渡さない** |
| 注入時に記録が無い・持ち主が違う | 何も注入しない。印は残す |

**受け入れ判定は CLI の `lint` にだけ置く。** plugin はヘッダを付けた記録を
保存する前に `lint - --headings-only --session <ID>` へ stdin で渡し、exit 0 の
ものだけを保存して採用する。判定は[記録の形](#記録の形)と同じで、行頭の見出しの
欠け・重複・順序違いを不合格にする。以前は plugin が「`## Goal` などの文字列を
含むか」を自前で見ていて、見出しが重複した生成や、文中に見出しの文字列があるだけの
生成も要約に採用していた。

**`--headings-only` は文字数予算と長いフェンスを見ない。** `--structure` は鮮度を
外すだけで予算も検査する（スキルが「通るまで直す」ときの基準）。圧縮時に予算超過で
捨てると、新しい引き継ぎの代わりに標準の要約が使われ、保存先には古い記録か骨格が
残る。少し長いだけの新しい記録を採用する方がよい。

**コードフェンスで包んだ生成は不合格になる。** 見出しがフェンスの中に入り、
見出しとして数えないため。フェンスの開閉は CommonMark に合わせ、`` ``` `` と `~~~` の
どちらも扱う。閉じるのは開いたときと同じ文字で同じ長さ以上の行だけで、長いフェンスの
中の短いフェンスや別の文字のフェンスでは閉じない。行頭に 4 桁以上の空白がある行は
インデントのコードブロックなので、見出しにもフェンスの開閉にもならない。

**`write` の成否は必ず見る。** plugin の CLI 呼び出しは失敗を `null` に変えて
握りつぶす。成否を見ずに読み直すと、前回の正常な記録が残っていればそれを読み、
**古い引き継ぎが要約に化ける**（圧縮後の会話は古い `## Next` から再開する）。
2026-09-27 まではこの状態だった。

## 使い方

```bash
CP=~/.config/opencode/skills/checkpoint/scripts/checkpoint.py

# 保存先を解決する（固定パスを自分で組み立てない）
uv run --no-project python "$CP" paths --session "<セッションID>" --ensure-ignored

# 書く
uv run --no-project python "$CP" write <checkpoint パス> --keep-prev <prev パス>

# 構造と持ち主を検査する
uv run --no-project python "$CP" lint <checkpoint パス> --structure --session "<セッションID>"

# 自分の記録を読む（復帰。持ち主が違えば exit 1）
uv run --no-project python "$CP" read --session "<セッションID>"
```

`snapshot` は plugin 専用（`--session` / `--cwd` / `--trigger`）。結果を JSON で
返し、失敗しても exit 0 で抜ける。`lint` はパスに `-` を渡すと stdin を検査する
（plugin の受け入れ判定用。[失敗時の動作](#失敗時の動作)）。

## 現在の状態と制限

- **スキルは手動起動でも使える。** 「checkpoint して」で復帰記録（A1）の保存が走る。
  再開時は `read` で自分の記録を読む（SKILL.md の「復帰」節）
- **案件の更新（A2）と恒久的な文書化（B）は `sdd-docs` スキルが持つ。**
  文脈が逼迫しているなら A1 を先に終える
- **OpenCode の実機で、圧縮 → 記録の生成 → ユーザの手番への注入を通しで確かめた**
  （[CHG-0001](../change/closed/0001-compaction-context-handover.md)「通しの実測」）
- **保存名の変更（完全な ID + ヘッダ照合）と `write` 失敗時の退避は、
  テスト（`test/agents/test_checkpoint*.py`）だけで確認している。** 実機の圧縮では
  未検証
- **Windows 実機での検証は未実施**（source state は更新済み）

## 関連

- 設計理由: [ADR-0009](../adr/0009-save-before-documenting.md)
- docs の運用: [ADR-0010](../adr/0010-exploratory-spec-driven-docs.md)
- 文書化の手順: `~/.claude/skills/sdd-docs/SKILL.md`（A2 / B）
- イベント仕様の実測: [compaction 関連の hook 仕様](../research/agents/compaction-hooks.md)
- 経緯の記録: [CHG-0001](../change/closed/0001-compaction-context-handover.md)

[仕様一覧へ戻る](index.md)
