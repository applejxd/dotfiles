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
