# 文脈の引き継ぎ (checkpoint)

コンテキスト圧縮を跨いで、作業の経緯・決定・残作業を失わないための仕組み。

> **2026-09-24: OpenCode 専用にした。**
> 圧縮の捕捉に `session.hook("compaction")`、印の保存に `ctx.storage` と、
> **OpenCode V2 の独自機能に強く依存する**ため、CLI 横断を諦めた。
> 置き場も `~/.claude/skills` から OpenCode 標準の
> `~/.config/opencode/skills` へ移した。経緯は
> [CHG-0001](../change/0001-compaction-context-handover.md)。

設計判断の理由は [ADR-0009](../adr/0009-save-before-documenting.md)、
両 CLI のイベント仕様は
[compaction 関連の hook 仕様](../research/agents/compaction-hooks.md) を参照。

## 構成

強制の層を 3 つに分ける。**圧縮を跨いで生き残るのは指示ファイルだけ**なので、
恒久ルールはそこへ置く。

| 層 | 実体 | 役割 |
| --- | --- | --- |
| 指示ファイル | `home/dot_claude/CLAUDE.md` / `home/dot_copilot/copilot-instructions.md` | 恒久ルール。「文脈の引き継ぎ」節 |
| スキル | `home/dot_config/opencode/skills/checkpoint/` | 手順・雛形・CLI の単一ソース |
| plugin | `home/dot_config/opencode/checkpoint-plugin/` | 圧縮直前の記録と直後の復帰注入 |

### plugin が担うこと

hook 層は 2026-09-25 に撤去し、OpenCode plugin へ寄せた。口は 3 つある。

| 口 | いつ | すること |
| --- | --- | --- |
| `session.hook("compaction")` | 圧縮の LLM 要求を組み立てるとき | `checkpoint.py snapshot` を呼ぶ**だけ** |
| `ctx.event.subscribe()` | `session.compaction.ended` が流れたとき | `ctx.storage` に印を置く |
| `session.hook("context")` | 毎要求 | 印があれば checkpoint を `event.system` へ入れる。ユーザの手番なら印を消す |

**記録する口と印を置く口を分けてある。** 圧縮フックは「圧縮を試みる側」に
付いていて、その後 `Nothing to compact yet` で**失敗することがある**（実測）。
ここで印を置くと、起きていない圧縮の引き継ぎを後続の要求へ流し込む。

上流（v2.0.14 `packages/core/src/session/compaction.ts`）では、この門番が
`prepare` より前にあり `Failed` を publish して返る。`Ended` は成功経路でしか
出ない。**だから印は `Ended` にだけ結び付ける。**

設計上の約束:

- **plugin は機械節を自分で組み立てない。** 生成と保存先の解決は
  `checkpoint.py` が単一ソース。二重に持つと必ずずれる
- **どの口も例外を投げない。** 圧縮を壊さないことが最優先
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

`ocs` の `read` は `~/.config/opencode` を**丸ごとは開けない**（R4）。
次の 2 つを名指しで開けている。**これが無いと境界内でだけ checkpoint が
動かない。**

- `~/.config/opencode/checkpoint-plugin`（plugin 本体）
- `~/.config/opencode/skills`（スキルと CLI）

## 保存先

**常にセッション別の名前**を使う。固定名を奪い合わないので、ロックも所有権の
交渉も要らない。

```text
<リポジトリルート>/.tmp/checkpoint-<sid8>.md        本体
<リポジトリルート>/.tmp/checkpoint-<sid8>.prev.md   直前の世代
<リポジトリルート>/.tmp/checkpoint-<sid8>.state.json 状態 (Tier 2 用、未実装)
```

- リポジトリルートは `git rev-parse --show-toplevel` で決める。
  **hook の `cwd` はサブディレクトリのことがある**ので `./` を前提にしない
- git の無視設定は `git rev-parse --git-path info/exclude` で解決する。
  **`.git` はファイルのこともある**（linked worktree / chezmoi の source state）
- `.gitignore` は共有ファイルなので書き換えない
- **セッション横断の削除をしない。** 件数や日数で消すと、稼働中の別セッションの
  記録まで消える。各セッションは自分の 3 ファイルだけを管理する

## 記録の形

見出しは 6 つを順序どおりに置く。雛形は
`~/.config/opencode/skills/checkpoint/references/checkpoint-template.md`。

| 節 | 内容 |
| --- | --- |
| `## Goal` | 達成したら終わりと言える条件（3 行以内） |
| `## Constraints` | ユーザー指定の制約、却下済みの方針 |
| `## State` | 完了 / 未完 / 未解決の論点 |
| `## Evidence` | 実行したコマンドと結果（推測を書かない） |
| `## Next` | 次の 1 手。「何を」で止めず**「どうやって」**まで |
| `## Refs` | `docs/...` のパス + 読む理由。未作成なら「未作成」と明記 |

`<!-- machine: -->` より下は hook が上書きするので、人も AI も書かない。

**圧縮時刻（`snapshot_at`）は機械節にだけ置く。** hook はヘッダを触らない設計
なので、ヘッダに書くと誰も更新せず「未取得」に見え続ける。旧雛形の名残として
残っていた場合は `lint` が警告する。

**文字数予算は 2000 文字**（意味内容のみ。機械節は別枠）。復帰試験の実測では
1098 文字で「引き継ぎに十分」と判定された。

## 鮮度の判定

**`covered_through` を、その保存要求の固定境界と比べる。**

- **mtime では判定しない。** 圧縮直前の hook が機械節を書くと mtime が更新され、
  古い意味内容が「新鮮」に見えてしまう
- **「現在の会話地点」とも比べない。** 保存や検査そのもので境界が進み、正しく
  保存しても永久に一致しない
- 境界は要求が立った時点で 1 つだけ固定し、以降動かさない

## hook

| イベント | スクリプト | 動作 |
| --- | --- | --- |
| Claude `PreCompact` / Copilot `PreCompact` | `checkpoint_precompact.py` | 機械的事実だけを記録し、復帰待ちの印を置く。**絶対にブロックしない** |
| Claude `SessionStart` matcher `compact` | `checkpoint_restore.py` | 自分の記録を stdout へ出し、印を消す（**Claude 専用**） |
| Copilot `PostToolUse` | `checkpoint_restore_pending.py` | 印があれば `additionalContext` で記録を返す（**Copilot 専用**） |

**Copilot も PascalCase で登録する。** camelCase だと入力に `hook_event_name` が
入らない（記録 E3）。

**Copilot は hook の登録を起動時にしか読まない。** 追加・変更したら `/restart`
が要る。しないと、設定は正しいのに発火しない（記録 E5）。

**発火しないときは `~/.copilot/session-state/<id>/events.jsonl` を見る。**
`hook.start` / `hook.end` が時系列で残る。ただしそこに載る入力は**内部表現**で、
hook へ渡る形式とは違う。キー名を実装の前提にしない（記録 E5）。

**ブロックしない理由**: 公式は、context-limit エラーからの回復として発火した
自動圧縮をブロックすると「元のエラーが表面化し、現在のリクエストが失敗する」と
明記している。機械記録のためにユーザーの作業を失わせるのは割に合わない。

**Copilot の復帰が 2 段になっている理由**: Copilot には `SessionStart`
matcher `compact` に相当する単一のイベントが無い。代わりに `PreCompact` が印を
置き、次の `postToolUse` が `additionalContext` で本文を返す。**通知専用の
イベントでも印を置くことはできる**ので、注入の担い手を別のイベントへ委ねれば
繋がる（記録 E7）。差は「不可能」ではなく**1 ツール分の遅れ**である。

| | Claude | Copilot |
| --- | --- | --- |
| 届く時点 | 作業を再開する**前** | 最初のツール実行の**直後**（同じターン内） |
| 上限 | なし（stdout 全文） | **10 KB**（`additionalContext`。超えたら末尾を切って在処を示す） |

**`postToolUse` は全ツールで発火する。** 印が無いときのコストがツール 1 回ごとの
税になるため、印まわりは `checkpoint_pending.py` へ切り出し、置き場も
`~/.cache/checkpoint-hooks/` に固定してある（`git rev-parse` を避けるため）。
実測 41ms/回。内訳は記録 E7。

**自動圧縮でも取りこぼさない**: 自動圧縮はツールループへの割り込みではなく
assistant ターンの境界で起きるため、`PreCompact` は確実に呼ばれる（記録 E6）。
ただしその時点でモデルに意味内容を書かせる余地は無いので、**意味内容は
区切りごとに手で保存しておく**必要がある。

**文脈が小さいときに `/compact` を打たない**: 要約文の方が長くなり、
かえって増えることがある（実測で 42,649 → 54,650 トークン。記録 E6）。

## 使い方

```bash
CP=~/.config/opencode/skills/checkpoint/scripts/checkpoint.py

# 保存先を解決する（固定パスを自分で組み立てない）
uv run --no-project python "$CP" paths --session "<セッションID>" --ensure-ignored

# 書く
uv run --no-project python "$CP" write <checkpoint パス> --keep-prev <prev パス>

# 構造を検査する
uv run --no-project python "$CP" lint <checkpoint パス> --structure
```

hook が静かに失敗したときは `CHECKPOINT_HOOK_DEBUG=1` を立てると stderr に
理由が出る。

## 現在の状態と制限

- **スキルは手動起動でも使える。** 「checkpoint して」で A1（実行状態の保存）が走る
- **A2（案件の更新）と B（`docs/` への文書化）の手順は
  `references/procedure.md` にある。** A1 を終えてから読む
- **Copilot でも圧縮直後の自動注入ができる**（`PreCompact` の印 + `postToolUse`。
  記録 E7）。Claude より 1 ツール分だけ遅い
- **Copilot では文脈使用率を推定できない。** `PostToolUse` の入力に
  `transcript_path` が無く（記録 E4）、トークン情報は圧縮時とセッション終了時に
  しか出ない（記録 E6）。閾値監視は**見送りで決着**
- **圧縮試験は Copilot で実施済み**（記録 E5 / E6）。
  **圧縮直後の復帰注入は実機未検証**。hook 単体では両経路とも動作確認済み
- **Windows 実機での検証は未実施**（source state は更新済み）

## 関連

- 設計理由: [ADR-0009](../adr/0009-save-before-documenting.md)
- docs の運用: [ADR-0010](../adr/0010-exploratory-spec-driven-docs.md)
- イベント仕様の実測: [compaction 関連の hook 仕様](../research/agents/compaction-hooks.md)
- 進行中の案件: [CHG-0001](../change/0001-compaction-context-handover.md)

[仕様一覧へ戻る](index.md)
