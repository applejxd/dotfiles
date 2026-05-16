# Hook Specification: events / tool names / payload

両ツールの hook 仕様の差分まとめ。本ドキュメントは **2026-05 時点** の
公式ドキュメント + 実機検証ベース。

- Claude Code: <https://docs.claude.com/en/docs/claude-code/hooks>
- Copilot CLI: <https://docs.github.com/en/copilot/reference/hooks-reference>

## 1. イベント名対応表

両ツールの hook イベント名対応。Copilot CLI は **PascalCase 互換モード** を
備えており、Claude と同じ PascalCase 名 + snake_case フィールドで書ける。

| カテゴリ | Claude Code | Copilot CLI | 備考 |
|---|---|---|---|
| ツール実行前 | `PreToolUse` | `PreToolUse` / `preToolUse` | block 可能 |
| ツール実行後 (成功) | `PostToolUse` | `PostToolUse` / `postToolUse` | Copilot は出力が LLM に渡らない仕様 |
| ツール実行後 (失敗) | `PostToolUseFailure` | `postToolUseFailure` | Copilot は additionalContext を返せる |
| ターン終了 | `Stop` | `Stop` / `agentStop` | block 可能 |
| Task 完了 | `TaskCompleted` | (相当なし) | Claude 固有 |
| サブエージェント終了 | `SubagentStop` | `SubagentStop` / `subagentStop` | block 可能 |
| サブエージェント開始 | (相当なし) | `subagentStart` | Copilot 固有 |
| ユーザ入力 | `UserPromptSubmit` | `UserPromptSubmit` / `userPromptSubmitted` | block 可能 |
| セッション開始 | `SessionStart` | `SessionStart` / `sessionStart` | prompt 型 hook あり |
| セッション終了 | `SessionEnd` | `SessionEnd` / `sessionEnd` | |
| 圧縮前 | `PreCompact` | `PreCompact` / `preCompact` | matcher で manual/auto 分岐 |
| 通知 | `Notification` | `notification` | 非同期、fire-and-forget |
| エラー | `ErrorOccurred` (?) | `errorOccurred` / `ErrorOccurred` | |
| permission 要求 | `PermissionRequest` | `permissionRequest` | Copilot CLI のみ独自 |
| permission 拒否 | `PermissionDenied` | (相当なし) | Claude 固有 |
| ファイル変更 | `FileChanged` | (相当なし) | Claude 固有 |
| 作業ディレクトリ変更 | `CwdChanged` | (相当なし) | Claude 固有 |

### マイグレーション指針

Claude → Copilot で hook を流用する場合の event 名対応:

| Claude の意図 | スクリプトで受理すべき event 名 |
|---|---|
| ツール実行を抑止 | `{"PreToolUse"}` |
| ターン終了で介入 | `{"Stop", "TaskCompleted", "agentStop"}` (3 つ全部受理) |
| 失敗からのリカバリ提案 | `{"PostToolUseFailure", "postToolUseFailure"}` |

スクリプト側で `hook_event_name` の集合チェックにすると、両ツール対応 +
将来の名前変更にも強い。

## 2. tool_name マッピング

`PreToolUse` / `PostToolUse` の `tool_name` フィールドはツールで違う:

| 用途 | Claude Code | Copilot CLI | matcher 例 |
|---|---|---|---|
| シェル実行 | `Bash` | `bash` | `^bash$` (Copilot) / `Bash` (Claude) |
| ファイル読み取り | `Read` | `view` | `^view$` / `Read` |
| ファイル新規作成 | `Write` | `create` | `^create$` / `Write` |
| ファイル編集 | `Edit`, `MultiEdit` | `edit` | `^edit$` / `Edit\|MultiEdit` |
| 検索 | `Grep` | `grep` | `^grep$` / `Grep` |
| Glob | `Glob` | `glob` | `^glob$` / `Glob` |
| ユーザ質問 | (相当なし) | `ask_user` | `^ask_user$` |

### 正規化パターン (推奨)

スクリプト内で `tool_name` を「kind」に正規化する table を持つ:

```python
_TOOL_KIND_MAP = {
    # Claude (PascalCase)
    "Bash": "bash", "Read": "view", "Write": "create",
    "Edit": "edit", "MultiEdit": "edit", "Grep": "grep",
    # Copilot (lowercase)
    "bash": "bash", "view": "view", "create": "create",
    "edit": "edit", "grep": "grep",
}
```

これで kind ベースで分岐できる: `if kind == "bash": ...`

### matcher の正規表現仕様

- **Copilot CLI**: `^(?:pattern)$` で **anchored** される。`bash` という
  matcher は `bash` という文字列 全体 にのみマッチ
- **Claude Code**: パターンは部分マッチ含む独自構文。`Bash` は Bash tool 名と
  exact 比較、`Edit|Write|MultiEdit` は OR 分岐
- → 同じ matcher 文字列を両ツールで使うのは非推奨。設定ファイルを別々に書く

## 3. Payload schema

stdin で受け取る JSON ペイロード。

### 3.1 共通フィールド

| フィールド | Claude (snake_case) | Copilot camelCase | Copilot PascalCase 互換 |
|---|---|---|---|
| セッション ID | `session_id` | `sessionId` | `session_id` |
| 現在の cwd | `cwd` | `cwd` | `cwd` |
| イベント名 | `hook_event_name` | (= 設定 key) | `hook_event_name` |
| transcript パス | `transcript_path` | `transcriptPath` | `transcript_path` |
| timestamp | (なし) | `timestamp` (number ms) | `timestamp` (ISO 8601) |

**推奨**: PascalCase 互換 (snake_case フィールド) で読むコードを書けば
両ツールで動く。

### 3.2 PreToolUse / PostToolUse 固有

```json
{
  "hook_event_name": "PreToolUse",
  "session_id": "...",
  "cwd": "/home/user/project",
  "tool_name": "bash",
  "tool_input": {
    "command": "echo hello",
    "description": "Print greeting"
  }
}
```

- bash 系: `tool_input.command` (両ツール共通キー)
- ファイル系: `tool_input.path` (Copilot 全般・Claude Edit/MultiEdit)
  または `tool_input.file_path` (Claude Read/Write)

**path 取得パターン**:

```python
path = tool_input.get("file_path") or tool_input.get("path") or ""
```

### 3.3 PostToolUse 固有

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "edit",
  "tool_input": { ... },
  "tool_result": {
    "result_type": "success",
    "text_result_for_llm": "..."
  }
}
```

### 3.4 Stop / TaskCompleted / agentStop

```json
{
  "hook_event_name": "Stop",
  "session_id": "...",
  "cwd": "/home/user/project",
  "transcript_path": "/path/to/transcript.jsonl",
  "stop_reason": "end_turn"
}
```

両ツールでフォーマットほぼ同じ。`hook_event_name` だけが違う
(`Stop` / `TaskCompleted` / `agentStop`)。

### 3.5 SessionStart

```json
{
  "hook_event_name": "SessionStart",
  "session_id": "...",
  "cwd": "...",
  "source": "startup" | "resume" | "new",
  "initial_prompt": "..."
}
```

## 4. 環境変数

| 変数 | Claude Code | Copilot CLI |
|---|---|---|
| `COPILOT_CLI` | (なし) | `1` |
| `CLAUDECODE` | (なし、または旧名) | (なし) |
| `CLAUDE_PROJECT_DIR` | `${CLAUDE_PROJECT_DIR}` | (なし) |
| `CLAUDE_SKILL_DIR` | あり (skill 内のみ) | **なし (展開されない)** |
| `CLAUDE_EFFORT` | あり (一部 event) | (なし) |

agent kind 判定例:

```python
import os
is_copilot = os.environ.get("COPILOT_CLI") == "1"
```

### 重要: `${CLAUDE_SKILL_DIR}` は Copilot で動かない

既存の Claude 用 skill で多用される `${CLAUDE_SKILL_DIR}/scripts/foo.sh` の
表記は Copilot CLI では展開されない (実機検証済 2026-05)。Copilot を
ターゲットに含める場合は:

- 相対パス + 文章説明 (`scripts/foo.sh` から実行) で書く → LLM が absolute
  path に解決する
- または `~/.copilot/skills/<name>/scripts/foo.sh` の absolute パスで書く
