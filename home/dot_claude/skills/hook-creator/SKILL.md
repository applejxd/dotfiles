---
name: hook-creator
description: "Claude Code / Copilot CLI 両対応の hook を作成・検証する。「hook を作って」「ツール実行をブロックしたい」「hook が動かない」「PreToolUse / Stop を書いて」「Claude の hook を Copilot で動かしたい」と言われたときに使う。"
context: fork
agent: general-purpose
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# hook-creator skill

Claude Code / Copilot CLI 双方で動く hook を作成・検証するための skill。
今回の hook 移植プロジェクトで得た知見 (仕様差、出力規約、落とし穴) を
凝縮した references / templates / scripts / payload examples を備える。

## 適用範囲

- 新規 hook の作成 (PreToolUse / PostToolUse / Stop / SessionStart など)
- 既存 hook の動作確認・トラブルシュート
- Claude Code 用 hook の Copilot CLI 対応 (簡易移植)

スコープ外: 既存 hook を一括変換する自動マイグレーションツール。
必要に応じて手作業で `references/` を参照しながら対応する。

## 前提確認 (1 メッセージにまとめて質問)

以下が未確定の場合、まとめて確認する:

1. **どのイベント?** (PreToolUse / PostToolUse / Stop / SessionStart / その他)
2. **対象ツール?** (Claude Code のみ / Copilot CLI のみ / 両対応)
3. **目的?** (block / 警告 / ログ / 副作用)
4. **既存スクリプトの拡張か新規か?**

すでに会話の文脈で答えが見えている項目は再確認しない。

## 既存ヘルパのチェック

新規 hook を書く前に、`~/.claude/hooks/lib/agent_compat.py` または
`~/.claude/hooks/lib/agent_compat.sh` が存在するか確認する:

```bash
ls -la "$HOME/.claude/hooks/lib/" 2>/dev/null
```

- **存在する**: そのまま import / source して使う (DRY 優先)
- **存在しない**: skill の `templates/agent_compat.py` または `.sh` を
  `~/.claude/hooks/lib/` にコピーして使う

## 判断フロー

1. **イベント名を決める**
   → `references/hook-spec.md` の対応表で Claude/Copilot 両側の名前を確認
2. **deny / block / 警告 / 副作用 のどれか決める**
   → `references/decision-output.md` で正しい JSON 出力規約を確認
3. **tool_name の絞り込み (PreToolUse/PostToolUse の場合)**
   → `references/hook-spec.md` の正規化マッピングで kind に統一
4. **path / command の取り出し方を決める**
   → `agent_compat.py` の `get_path()` / `get_command()` を利用
5. **設定ファイル (`~/.copilot/hooks/*.json` または `~/.claude/settings.json`)
   への登録**
   → `templates/hook-config-examples.json` の該当箇所をコピペ
6. **検証**
   → `scripts/verify-hook.sh` に `examples/payloads/*.json` を流して挙動確認

## テンプレート選択と配置

| 用途 | テンプレート | 配置先 (推奨) |
|---|---|---|
| Python の PreToolUse hook | `templates/agent_compat.py` + 自作スクリプト | `~/.claude/hooks/<name>.py` |
| Bash の PostToolUse hook | `templates/agent_compat.sh` + 自作スクリプト | `~/.claude/hooks/<name>.sh` |
| Claude の hook 設定 | `templates/hook-config-examples.json` (`_claude_example`) | `~/.claude/settings.json` の `hooks` 節 |
| Copilot の hook 設定 | `templates/hook-config-examples.json` (`_copilot_example`) | `~/.copilot/hooks/<name>.json` |

### スクリプトの呼び出しパス

Copilot CLI 用設定ファイルからスクリプトを呼ぶときは **absolute path** が安全:

```json
{ "bash": "python $HOME/.claude/hooks/my_hook.py" }
```

`$HOME` は環境変数として展開される。`${CLAUDE_PROJECT_DIR}` のような Claude 専用
変数は Copilot では展開されないので注意 (`references/pitfalls.md` 参照)。

## 検証手順

skill の base directory にある `scripts/verify-hook.sh` と
`examples/payloads/*.json` を使う。Claude / Copilot どちらの hook かによらず
動作する。

LLM が skill の絶対パスを推論する必要がある場合は、以下のいずれかで取得する:

```bash
# Copilot CLI から見える skill base
ls -d ~/.copilot/skills/hook-creator
# Claude Code から見える skill base
ls -d ~/.claude/skills/hook-creator
```

### 例: PreToolUse hook を payload でテスト

```bash
bash ~/.claude/skills/hook-creator/scripts/verify-hook.sh \
  "python ~/.claude/hooks/check_bash.py" \
  ~/.claude/skills/hook-creator/examples/payloads/pretool-bash.json
```

出力:

- `=== exit code ===` で 0/2/その他
- `=== stdout (parsed) ===` で JSON とその decision フィールド抽出
- `=== verdict ===` で「両ツール対応か」「Claude 専用か」「no-op か」を判定

### 例: ユーザの hook 設定全体を検査

```bash
bash ~/.claude/skills/hook-creator/scripts/check-hook-config.sh
```

JSON 形式エラー、参照スクリプトの不在、matcher の anchored 規則違反などを検出。

### 例: 各 event の payload を試す

`examples/payloads/` の 4 ファイルでひととおり試せる:

| payload | 用途 |
|---|---|
| `pretool-bash.json` | bash 系 PreToolUse (`env` でブロック確認) |
| `pretool-edit.json` | ファイル系 PreToolUse (`/tmp/` でブロック確認) |
| `posttool-edit.json` | PostToolUse |
| `stop.json` | Stop / TaskCompleted / agentStop (`hook_event_name` 書き換えで試す) |

## 必読: 既知の落とし穴 (ダイジェスト)

`references/pitfalls.md` の特に致命的な 4 項目:

1. **exit 2 単独では Copilot で block されない**: 何の警告もなく素通り
2. **並列 hook で空 stdout が deny を上書き** (Copilot): 自作 hook で
   「該当しないなら何も出さず即 sys.exit(0)」を徹底
3. **Copilot の PostToolUse は LLM に出力を渡さない**: 警告メッセージは
   CLI UI に表示されるだけで agent は知らない
4. **`${CLAUDE_SKILL_DIR}` / `${COPILOT_SKILL_DIR}` は Copilot で展開されない**

詳細は `references/pitfalls.md` 全項目を参照。

## chezmoi 管理下に置く流儀

このリポジトリでは hook 関連ファイルを以下の場所で管理:

| 種類 | chezmoi source | 配備先 |
|---|---|---|
| 共通ヘルパ | `home/dot_claude/hooks/lib/{agent_compat.py,agent_compat.sh}` | `~/.claude/hooks/lib/` |
| Python hook 本体 | `home/dot_claude/hooks/executable_<name>.py` | `~/.claude/hooks/<name>.py` (実行属性付) |
| Bash hook 本体 | `home/dot_claude/hooks/executable_<name>.sh` | `~/.claude/hooks/<name>.sh` (実行属性付) |
| Claude 設定 | `home/dot_claude/dot_settings.json` (の `hooks` 節) | `~/.claude/settings.json` |
| Copilot 設定 | `home/dot_copilot/hooks/<name>.json` | `~/.copilot/hooks/<name>.json` |

新規スクリプトを追加するときは:

1. `home/dot_claude/hooks/executable_<name>.{py,sh}` を作成
2. `chezmoi apply ~/.claude/hooks/` で配備
3. 必要に応じて Claude/Copilot 双方の設定ファイルに登録
4. `scripts/verify-hook.sh` で動作確認
5. Conventional Commits でコミット
   (例: `feat(hooks): add <name> for <purpose>`)

## ポリシー

- Claude Code / Copilot CLI で **動作確認していないものは「未確認」と明示する**
- 仕様変更が頻繁な領域 (特に Copilot CLI 新興機能) は references に
  検証日時を明記
- ヘルパスクリプト (`agent_compat.{py,sh}`) は両ツールの最小公倍数 (`stdout
  JSON + exit 0`) を使う前提。これを破る必要が出たらまず `pitfalls.md` を確認
- ユーザの hook を勝手に書き換えない (必ず確認してから適用)
