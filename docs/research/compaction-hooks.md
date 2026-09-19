# compaction 関連の hook 仕様

<!-- 現在の総合判断は docs/change/0001-compaction-context-handover.md の
     候補比較表が正本。ここは「いつ何を観測したか」を積む場所 -->

context compaction を跨いで作業文脈を保つために、両 CLI の hook で何ができて
何ができないかを調べた記録。

## 記録 E1 — 2026-09-18

- **対象バージョン**: Claude Code 2.1.x 系ドキュメント / GitHub Copilot CLI 1.0.84-8
- **環境**: 公式ドキュメントの読解（実機発火は E3 以降）

### 問い

圧縮の直前・直後に割り込む hook イベントは、両 CLI にあるか。

### 事前の予想

`PreCompact` と `PostCompact` が対になっていて、後者で内容を注入できると考えていた。

### 結果

**Claude Code:**

| イベント | matcher | コンテキスト注入 | ブロック |
| --- | --- | --- | --- |
| `PreCompact` | `manual` / `auto` | **不可** | 可（exit 2 / `decision:"block"`） |
| `PostCompact` | `manual` / `auto` | **不可**（decision control 無し） | 不可 |
| `SessionStart` | `startup` / `resume` / `clear` / **`compact`** / `fork` | **可** | 不可 |
| `PostToolBatch` | なし | **可**（次のモデル呼び出しの直前） | 可 |
| `Stop` | なし | 可 | 可 |

**Copilot CLI:**

| イベント | コンテキスト注入 | ブロック |
| --- | --- | --- |
| `preCompact` / `PreCompact` | **不可**（"No — notification only"） | **不可** |
| postCompact 相当 | — | **イベント自体が存在しない** |
| `sessionStart` | 可 | 不可 |
| `agentStop` / **`Stop`** | — | 可 |
| `postToolUse` / `PostToolUse` | 可 | 不可 |

### 考察

**予想は外れた。** `PostCompact` では注入できない。圧縮直後の注入点は
`SessionStart` の matcher `compact` だった。Copilot には対応するイベントが無く、
圧縮直後の自動注入は原理的にできない。

`PreCompact` は `prompt` / `agent` hook に非対応なので、hook からモデルを動かす
こともできない。

### 次の問い

- 圧縮の直後、作業を再開する**前**に記録が届くか（E4 で確認予定）
- Copilot で文脈使用率を取得できるか（E4 で確認予定）

### 参照

> Events that support `command`, `http`, and `mcp_tool` hooks but not `prompt` or `agent`:
> … `PostCompact` … `PreCompact` …

出典: <https://code.claude.com/docs/en/hooks>

> `preCompact` — Context compaction is about to begin (manual or automatic).
> **No — notification only.**

出典: <https://docs.github.com/en/copilot/reference/hooks-reference>

## 記録 E2 — 2026-09-18

- **対象バージョン**: Claude Code 2.1.x 系ドキュメント
- **環境**: 公式ドキュメントの読解

### 問い

hook から「促すだけ」で保存を促せるイベントはどれか。

### 事前の予想

`TaskCompleted` はタスク完了という自然な区切りなので、そこで促せると考えていた。

### 結果

`additionalContext` に対応するイベントは次のとおり。

`SessionStart` / `SubagentStart` / `UserPromptSubmit` / `UserPromptExpansion` /
`PreToolUse` / `PostToolUse` / `PostToolUseFailure` / `PostToolBatch` /
`Stop` / `SubagentStop` / `PostModelSwitch`

**`TaskCompleted` は含まれない。** このイベントでできるのは exit 2 による
ブロックだけ。

あわせて次を確認した。

- `agent_id`: "Present **only when** the hook fires inside a subagent call."
- `agent_type`: "Present when the session uses **`--agent`** or the hook fires
  inside a subagent."

### 考察

**予想は外れた。** `TaskCompleted` では「ブロックせず促す」ができない。
促しは `PostToolBatch` / `PostToolUse` に寄せる必要がある。

また、子エージェントの判定に `agent_type` を使うと、`--agent` で起動した**親**
セッションでも hook が無効になる。判定には `agent_id` だけを使う。

### 次の問い

なし（設計へ反映済み）

### 参照

> Where the reminder appears depends on the event: … `Stop` and `SubagentStop` …

出典: <https://code.claude.com/docs/en/hooks#add-context-for-claude>

## 記録 E3 — 2026-09-19

- **対象バージョン**: GitHub Copilot CLI 1.0.84-8
- **環境**: WSL / Ubuntu。本リポジトリの稼働中セッション

### 問い

Copilot に **PascalCase** でイベントを登録したとき、入力は
VS Code 互換形式（snake_case + `hook_event_name`）で来るのか。

### 事前の予想

公式が「Two payload formats are supported, selected by the event name used in
the hook configuration」と書いているので、PascalCase 登録なら snake_case が
来るはず。ただし未実測だった。

### 方法・条件

稼働中のセッションで、既に配備されている hook の実装と発火状況を突き合わせた。

```console
$ grep -n "copilot_event" home/dot_config/agents/common.toml.tmpl
677:copilot_event = "PreToolUse"
691:copilot_event = "PreToolUse"
708:copilot_event = "PreToolUse"
719:copilot_event = "PostToolUse"
730:copilot_event = "PostToolUse"

$ grep -n "tool_name\|tool_input" home/dot_claude/hooks/executable_check_bash.py
3198:    tool_name = data.get("tool_name")
3204:    tool_input = data.get("tool_input")
```

### 結果

- 登録は **PascalCase**（`PreToolUse` / `PostToolUse`）
- hook 実装は **snake_case の `tool_name` / `tool_input` だけ**を読む。
  camelCase の `toolName` / `toolArgs` は参照していない
- それでいて、**このセッションで hook が実際に発火してコマンドをブロックした**

観測した発火の例:

```text
Denied by preToolUse hook: [hook blocked] `python` のインラインコードから
外部コマンドを実行しようとしています。
```

```text
Denied by preToolUse hook: [hook blocked] エージェントのガード設定を
操作しようとしています。
```

### 考察

**PascalCase 登録 → snake_case 入力**が、稼働中の実装で裏付けられた。
snake_case のキーしか読まない実装が現に機能しているので、camelCase 形式では
来ていない。

したがって、新しく追加する hook も **PascalCase で登録する**。
本設計は `hook_event_name` で分岐するが、これも VS Code 互換形式にしか
含まれないため、この前提が要る。

**注意**: これは `PreToolUse` / `PostToolUse` についての観測である。
`Stop` / `PreCompact` / `SessionEnd` でも同じかは、それらを登録してから確認する。

### 次の問い

- `PostToolUse` の入力に `transcript_path` は含まれるか（下記 E4）

### 参照

> Two payload formats are supported, **selected by the event name used in the
> hook configuration**. … **VS Code compatible format** — Configure the event
> name in PascalCase (for example, `SessionStart`). Fields use snake_case…

出典: <https://docs.github.com/en/copilot/reference/hooks-reference>

## 記録 E4 — 2026-09-19

- **対象バージョン**: GitHub Copilot CLI 1.0.84-8
- **環境**: WSL / Ubuntu

### 問い

Copilot の `PostToolUse` 入力から文脈使用率を推定できるか。

### 事前の予想

`transcript_path` があれば、Claude と同じく JSONL の末尾から usage を読めると
考えていた。

### 方法・条件

公式の入力スキーマと、既存 hook が実際に読んでいるキーを確認した。

```console
$ grep -rn "transcript_path\|transcriptPath" home/dot_claude/hooks/
（出力なし）
```

### 結果

- 公式の `postToolUse` / `PostToolUse` の入力スキーマに **`transcript_path` は無い**
  （`sessionId` / `timestamp` / `cwd` / `toolName` / `toolArgs` / 結果）
- 既存の hook も一切参照していない
- `preCompact` には `transcriptPath` がある

### 考察

**予想は外れた。** `PostToolUse` からは transcript へ到達できないため、
**この経路で文脈使用率を推定することはできない。**

さらに、Copilot SDK のイベント型では `assistant.usage` と `session.usage_info` が
`ephemeral: true`（ディスクのイベントログに永続化されない）とされている。
`preCompact` の `transcriptPath` に usage が載るかは**未確認**。

したがって現時点では、**Copilot で閾値監視を成立させる根拠が無い**。
閾値監視に依存しない構成（逐次保存 + 圧縮直前の機械記録 + 復帰）を
基本にする判断は妥当だった。

### 次の問い

- `preCompact` の `transcriptPath` の中身に usage は含まれるか（未着手）
- 圧縮直後、作業再開前に記録が届くか（未着手）

### 参照

出典: <https://docs.github.com/en/copilot/reference/hooks-reference>

## 記録 E5 — 2026-09-19

- **対象バージョン**: GitHub Copilot CLI 1.0.87-0
- **環境**: WSL / Ubuntu

### 問い

配備した `PreCompact` hook が実機の圧縮で発火するか。発火しないとき、
何を見れば原因を切り分けられるか。

### 事前の予想

登録が正しければ発火すると考えていた。最初の `/compact` では発火しなかったため、
hook の実装か登録の誤りを疑った。

### 方法・条件

1. `/compact` 後に checkpoint を確認
2. Copilot のデバッグログで圧縮の時刻と hook の実行窓を測る
3. `~/.copilot/session-state/<id>/events.jsonl` から hook の入力を取り出す
4. 取り出した入力で配備済み hook を手で再実行
5. `ps` でプロセスの起動時刻と hook 登録ファイルの更新時刻を比べる
6. `/restart` 後に `/compact` をやり直す

### 結果

#### 1 回目（発火せず）

- 圧縮は起きたが checkpoint の `## Snapshot` は更新されなかった
- 圧縮直前の hook 実行窓は 63ms。自前 hook の実測は成功時 120ms
- その 63ms の stdout は `{}` で、出所は `~/.orca/agent-hooks/copilot-hook.sh`
  （`~/.copilot/hooks/orca.json` が `PreCompact` を含む全イベントを登録している）
- 取り出した実ペイロードで配備済み hook を手で流すと**成功し `## Snapshot` を書いた**

| 事実 | 時刻 |
| --- | --- |
| copilot プロセス（PID 94180）の起動 | 12:38:40 |
| `~/.copilot/hooks/from-claude.json` の更新 | 12:51:32 |

#### 2 回目（`/restart` 後、発火した）

- 設定は一切変えず `/restart` しただけで `## Snapshot` が更新された
- `snapshot_at: 2026-09-19T15:59:37+09:00` / `trigger: manual`
- ヘッダの `updated_at`・`covered_through` と意味内容は無傷
- `events.jsonl` 側にも同時刻の `preCompact` が残っている

#### `events.jsonl` に記録される入力（`hook.start` の `data.input`）

```json
{"transcriptPath": "…/session-state/<id>/events.jsonl", "trigger": "manual",
 "customInstructions": "", "sessionId": "<id>",
 "timestamp": 1789801177127, "cwd": "…"}
```

イベント別のキー（この 1 セッション分を全件走査した結果）:

| hookType | 入力キー | `transcriptPath` |
| --- | --- | --- |
| `preCompact` | `customInstructions` `cwd` `sessionId` `timestamp` `transcriptPath` `trigger` | あり |
| `agentStop` | `cwd` `sessionId` `stopReason` `stop_hook_active` `timestamp` `transcriptPath` | あり |
| `subagentStart` / `subagentStop` | （略）`transcriptPath` を含む | あり |
| `postToolUse` | `cwd` `sessionId` `timestamp` `toolArgs` `toolName` `toolResult` | **なし** |
| `preToolUse` | `cwd` `sessionId` `toolCalls` | **なし** |

#### ★この記録は hook プロセスへ渡る形式とは別物

- `events.jsonl` の `preToolUse` は `{sessionId, cwd, toolCalls:[…]}` で、
  `tool_name` を持たない
- 一方 `executable_check_bash.py:3237` は `data.get("tool_name")` **だけ**を読む
- それでいて同セッションで実際にブロックが発生した
  （`rm ./.git/.write-probe`、`git stash drop`）

両立する説明は 1 つだけで、**`events.jsonl` は内部表現を記録しており、
PascalCase 登録の hook へ実際に渡るのは E3 のとおり snake_case 形式**である。
デバッグで入力を読むときは、キー名をそのまま実装の前提にしてはいけない。

#### usage（E4 の未解決点への回答）

`transcriptPath`（= `events.jsonl`）に `responseUsage.prompt_tokens` は**ある**。
ただし内訳は次のとおりで、本体の会話ではない。

| 記録された `model.model_call_started` | 件数 |
| --- | --- |
| `gpt-5.4-nano` | 35 |
| `gpt-4o-mini` | 2 |
| `claude-opus-5` | 2 |

usage を伴う `model.model_call_success` は 39 件、`prompt_tokens` は 530〜806。
同セッションの `assistant.message` は 1014 件あるので、本体のモデル呼び出しは
ここに載っていない。`session.usage_checkpoint`（47 件）が持つのは
`totalNanoAiu` / `totalPremiumRequests` という**課金量**で、文脈使用量ではない。

### 考察

**原因は実装ではなく設定の読み込み時期だった。** Copilot は hook の登録を
**起動時にしか読まない**。hook を追加・変更したら `/restart` が要る。
`check_bash.py` などが動き続けていたのは、起動前から登録済みだったため。

`events.jsonl` は hook デバッグの一次情報として使える。ただし上記のとおり
記録される形と配送される形が違うので、**「何が起きたか」の時系列を追う用途**に
限り、**入力スキーマの根拠には使わない**。

usage については、**`transcriptPath` を得ても文脈使用率は推定できない**。
E4 の「Copilot で閾値監視を成立させる根拠が無い」は、`preCompact` に
`transcriptPath` があると分かった後も**変わらない**。

### 次の問い

- 圧縮直後、作業再開前に記録が届くか（Claude でのみ検証可能。未着手）
- Windows 実機での発火と起動時間（未着手）

### 参照

出典: <https://docs.github.com/en/copilot/reference/hooks-reference>

## 記録 E6 — 2026-09-19

- **対象バージョン**: GitHub Copilot CLI 1.0.87-0
- **環境**: WSL / Ubuntu

### 問い

ターン途中で自動圧縮が起きたとき、hook はどの順で呼ばれるか。
圧縮に先回りして意味内容を書く余地はあるか。

### 事前の予想

自動圧縮はツールループの途中に割り込むため、`PreCompact` が呼ばれない経路が
あるかもしれないと考えていた。

### 方法・条件

`events.jsonl`（1 セッション、全 12,000 行超）を全件走査し、
`trigger: auto` の `preCompact` を含む前後のイベントを時系列で復元した。
同セッションには auto 1 回・manual 2 回の圧縮が記録されている。

### 結果

#### 自動圧縮（`trigger: auto`）前後のイベント順

```text
03:45:25.830  assistant.turn_end
03:45:25.830  assistant.turn_start      ← 次のモデル呼び出しへ入る
03:45:26.928  hook.start   preCompact
03:45:26.947  hook.end     preCompact   (success: true)
03:45:26.957  session.compaction_start
03:46:37.732  session.compaction_complete
03:45:35.365  assistant.message         ← 圧縮後、同じツールループを継続
```

**割り込みではなく、assistant ターンの境界**で起きていた。直前のツール実行は
`tool.execution_complete` まで完了しており、`user.message` は挟まらない。

#### auto と manual で順序が逆になる

| trigger | 順序 |
| --- | --- |
| `auto` | `hook.start/end` → `session.compaction_start` |
| `manual` | `session.compaction_start` → `hook.start/end` |

どちらも `session.compaction_complete` より前に hook は終わっている。
auto では `hook.end` の 10ms 後に `compaction_start` が来ており、hook の完了を
待っているように見える（**1 例のみ**なので断定はしない）。

#### `trigger` の呼び名がイベントと hook 入力で違う

| 場所 | 自動圧縮の値 |
| --- | --- |
| hook 入力の `trigger` | `auto` |
| `session.compaction_start` の `trigger` | `threshold` |

#### 3 回の圧縮の実測

| 時刻 | trigger | 圧縮前 | 圧縮後 | 除去メッセージ | 増減 |
| --- | --- | --- | --- | --- | --- |
| 03:45 | threshold | 748,942 | 94,257 | 1,155 | -654,689 |
| 04:52 | manual | 170,929 | 54,840 | 302 | -116,089 |
| 06:59 | manual | 42,649 | 54,650 | 72 | **+12,001** |

- 自動圧縮の発動点は `currentTokens 748,942 / tokenLimit 936,000` = **80.0%**
- `tokenLimit` は `threshold` のときだけ入り、manual には無い
- **3 回目は圧縮して逆に増えた。** 要約文が元の 73 メッセージより長かったため。
  短い文脈で `/compact` を打つと目減りしないどころか増える

#### トークン情報の所在（E5 の訂正）

E5 では「本体の会話の消費量は記録されない」と書いたが、**不正確だった**。
全イベント種別を数え直した結果は次のとおり。

| キー `currentTokens` / `tokenLimit` を持つ種別 | 件数 |
| --- | --- |
| `session.compaction_start` | 3 |
| `session.compaction_complete` | 3 |
| `session.shutdown` | 2 |

正しくは「**圧縮時とセッション終了時にしか記録されない**」。
`model.*`（41 件）は補助モデルの呼び出しで、本体の `assistant.message`
1,054 件とは対応しない、という E5 の観測自体は変わらない。

### 考察

**予想は外れた。** 自動圧縮でも `PreCompact` は確実に呼ばれる。
割り込みではなくターン境界なので、機械記録を取り損ねる経路は無い。

一方で、**その時点でモデルに意味内容を書かせることはできない**。
hook は外部プロセスであり、圧縮は hook の完了直後に始まる。
「重要な区切りでの逐次保存（Tier 1）＋圧縮直前の機械記録」という構成は、
この観測によって裏付けられた。圧縮直前に一括で書かせる設計だと、
自動圧縮では間に合わない。

閾値監視については、**E5 の結論は変わらない**。トークン情報は
圧縮時と終了時にしか出ないので、閾値を跨ぐ前に読むことができない。
「載っていない」ではなく「読みたい時点には出ていない」が正確な理由である。

**運用上の注意**: 文脈が小さいときの手動 `/compact` は逆効果になりうる
（実測で +12,001 トークン）。

### 次の問い

- 圧縮直後、作業再開前に記録が届くか（Claude でのみ検証可能。未着手）
- Windows 実機での発火と起動時間（未着手）

### 参照

出典: <https://docs.github.com/en/copilot/reference/hooks-reference>
