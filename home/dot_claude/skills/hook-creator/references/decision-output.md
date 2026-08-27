# Decision Output 規約 (deny / block の伝え方)

両ツールの hook で「ツール実行を抑止」「ターン継続を強制」する正しい伝え方。

## 1. 実機検証で得た 3 規約 (PreToolUse)

Copilot CLI で各規約をテストした結果 (2026-05 検証):

| 規約 | Copilot CLI | Claude Code (公式仕様) | 両対応 |
| --- | --- | --- | --- |
| (A) `exit 2` + stderr のみ | ❌ ブロックされない | ✅ ブロック | ❌ |
| (B) `exit 0` + stdout JSON | ✅ ブロック | ✅ ブロック (exit 0 で stdout JSON 解釈) | ✅ |
| (C) `exit 2` + stdout JSON + stderr | ✅ ブロック | ✅ ブロック (exit 2 優先、stderr 採用) | ✅ |

**結論: 両ツール対応の最小公倍数 = stdout JSON + exit 0** (規約 B)

### よくある間違い

- 既存 Claude スクリプトをそのまま Copilot に持ち込んで `exit 2 + stderr` で
  書くと、Copilot では何もブロックされない (権限プロンプトすら出ない)。

## 2. PreToolUse deny の JSON 形式

両ツール対応の出力 (1 つの JSON で両形式を併発):

```json
{
  "permissionDecision": "deny",
  "permissionDecisionReason": "Reason shown to the agent",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Reason shown to the agent"
  }
}
```

- top-level の `permissionDecision` / `permissionDecisionReason` → **Copilot CLI が読む**
- `hookSpecificOutput` ネスト → **Claude Code が読む**
- 出力後、`exit 0` で終了 (どちらのツールでも JSON 解釈可能)

### 各フィールドの値

| `permissionDecision` | 効果 |
| --- | --- |
| `"deny"` | ツール実行を拒否。`Reason` を agent に伝える |
| `"allow"` | 通常 permission チェックを skip して許可 |
| `"ask"` | ユーザに確認を求める。承認されればツールは実行される |
| `"defer"` | **Claude Code のみ / `-p` 専用**。ツールを保留し、呼び出し側プロセスが resume する |

### `ask` を使う場面 (提案 → 承認 → 実行)

「危険だが、人間が承認すれば実行してよい」操作は `deny` ではなく `ask` にする。
`deny` だとユーザーが自分で手を動かす羽目になるが、`ask` なら承認するだけで
エージェントがそのまま実行できる。

```python
from agent_compat import emit_pretool_ask

emit_pretool_ask("削除対象を確認して問題なければ承認してください。")
```

```bash
hook_emit_pretool_ask "削除対象を確認して問題なければ承認してください。"
```

各モードでの挙動 (2026-08 時点の公式 docs):

| 実行環境 | `ask` の結果 |
| --- | --- |
| Claude 対話 (`default`) | プロンプトが出る (`[User]` などの出所ラベル付き) |
| Claude `auto` | プロンプトが出る。classifier の暗黙 approve を封じる |
| Claude `bypassPermissions` | プロンプトが出る (bypass でも ask は尊重される) |
| Claude `dontAsk` | 自動拒否 |
| Claude `-p` (非対話) | プロンプト不能。auto では当該操作をスキップして継続 |
| Copilot CLI (対話) | **自動承認される** (既知バグ。下記) |
| Copilot cloud agent | **`deny` 扱い** (ユーザー不在のため) |

→ 無人実行では必ず安全側に倒れるので、`deny` を `ask` に緩めても無人時のリスクは増えない。

**ただし Copilot CLI の対話実行では `ask` が機能しない。** v1.0.53 以降、hook が
返した `ask` は permission dialog が数十 ms 表示されるだけで自動承認される
([github/copilot-cli#3590](https://github.com/github/copilot-cli/issues/3590)、
1.0.81 時点で OPEN)。`deny` はこのバグの影響を受けない。
Copilot で確実に止めたい操作に `ask` を使ってはいけない。`deny` にするか、
エージェント側で明示確認する (判別は `COPILOT_CLI` 環境変数)。
切り分け手順と実測値は `docs/research/agent-harness-comparison.md` の
「Copilot CLI では hook の `ask` が自動承認される」を参照。

### ★ hook の決定は permission リストを上書きしない

> "Hook decisions don't bypass permission rules. Claude Code evaluates deny and ask
> rules regardless of what a PreToolUse hook returns"
> — <https://code.claude.com/docs/en/permissions>

評価順:

```text
permissions.deny > hook の ask/deny > permissions.ask > hook の allow > permissions.allow
```

**hook で `ask` を返したいコマンドを `permissions.deny` に書いてはいけない。**
deny が先に評価され、プロンプトすら出ずに拒否される。

## 3. Stop / agentStop の block 形式

両ツール共通:

```json
{
  "decision": "block",
  "reason": "Next-turn prompt text"
}
```

- `reason` は **次ターンの追加プロンプト** として扱われる
- `decision: "allow"` で明示的に終了を許可 (デフォルトは終了)
- `exit 0` で終了

無限ループに注意: Stop hook が常に block を返すと、agent が永遠に終わらない。
session ごとに 1 回だけ block する marker パターンを使う:

```python
import tempfile
from pathlib import Path

marker = Path(tempfile.gettempdir()) / f"hookname_{session_id}"
if marker.exists():
    sys.exit(0)
marker.touch()
# ... 以下 block 処理
```

## 4. PostToolUse の規約 (両ツールの差)

| ツール | 動作 |
| --- | --- |
| Claude Code | `exit 2 + stderr` で agent にフィードバック (block 不可) |
| Copilot CLI | 出力は **LLM に渡らない仕様** (`Output processed: No`)。CLI UI に `!` プレフィックスで表示されるのみ |

### 含意

- Copilot CLI で PostToolUse hook を書いても、agent は警告に反応できない
- 例: 自動 lint 結果を agent に伝えたい場合、Copilot では機能しない
- 代替案:
  - 警告の代わりに `PostToolUseFailure` (Copilot) で `additionalContext` を返す
    (ただし「ツールが失敗」した時のみ発火する制約)
  - Copilot 用には PreToolUse で事前バリデーションを行う

## 5. SessionStart の context 注入

両ツール共通: stdout に以下を出すと session の context に追加される (block ではなく
「additionalContext」として LLM に渡る):

```json
{
  "additionalContext": "Read CONTRIBUTING.md before editing."
}
```

## 6. 出力時のお作法

- **stdout に書くのは 1 つの JSON のみ**。複数 JSON を改行で繋ぐと parse 失敗
- **`exit 0` で終了**。両ツール対応のため。`exit 2` だと Claude が stdout を
  捨てる
- 余計な print デバッグは **stderr に出す** (stdout は JSON 専用と割り切る)
- **空 stdout で `sys.exit(0)`** は安全。並列 hook の deny を上書きしない
  - 注意: 並列 hook の hook 内で「空 stdout を明示的に echo」すると、
    別 hook の deny を消す可能性 (実機で再現確認済)
