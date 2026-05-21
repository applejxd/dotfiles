# Pitfalls (落とし穴集)

hook 作成・移植時に踏みがちな問題。今回の実装プロジェクトで実際に遭遇した
ものを中心にまとめる。

## 1. exit code 2 単独では Copilot で block されない

- Claude Code: `exit 2 + stderr` で PreToolUse をブロック可能
- Copilot CLI: **stdout に JSON が必須**。`exit 2` 単独だとツールが実行されてしまう
- 実機検証: 何の警告もなく素通り。「block されているように見えて何も起きていない」最悪パターン

**対策**: `references/decision-output.md` の規約 B (stdout JSON + exit 0) を使う。
`templates/agent_compat.py` の `emit_pretool_deny` は両対応で出力する。

## 2. 並列 hook で空 stdout が deny を上書きする (Copilot)

設定で同じイベントに複数 hook を登録すると並列実行される。1 つの hook が
deny の JSON を出力しても、別 hook が空 stdout で終わると **deny が消える**
ケースを実機で観測。

```json
"PreToolUse": [
  { "bash": "python check_bash.py" },   // deny を返す
  { "bash": "python redirect-tmp.py" }, // 該当しない時は何も出さず exit 0
  { "bash": "echo 'debug'; cat - > /dev/null" }  // ← 空 stdout で上書き
]
```

**対策**:

- 自作 hook で「該当しないなら何も出さず即 `sys.exit(0)`」を徹底する
  (stdout に何も書かない)
- debug 用の payload キャプチャ hook は stdout に書かず stderr / file に書く

## 3. Copilot の PostToolUse は LLM に出力を渡さない

Copilot CLI のドキュメントに `Output processed: No` と明記。Claude では
agent にフィードバックされる stderr 警告も、Copilot では CLI UI に表示
されるだけで agent は知らない。

**対策**:

- Copilot 専用なら PostToolUse は副作用 (ログ書き出し、auto-fix 等) 専用にする
- agent に警告を渡したい場合は PreToolUse で事前検査するか、
  `PostToolUseFailure` で `additionalContext` を返す
  (ただし「ツールが失敗」した時のみ発火する制約)

## 4. `${CLAUDE_SKILL_DIR}` は Copilot で展開されない

実機検証 (2026-05):

```
CLAUDE_SKILL_DIR=<not set>
COPILOT_SKILL_DIR=<not set>
```

既存の Claude 用 skill は `${CLAUDE_SKILL_DIR}/scripts/foo.sh` を多用するが、
Copilot CLI では空文字に展開されて失敗する。

**対策**:

- skill 内のスクリプト参照は相対パス (`scripts/foo.sh`) + 文章説明にする
  → LLM が absolute path に自動展開する (Copilot で実証)
- または `~/.copilot/skills/<name>/scripts/foo.sh` の absolute パスを直書き
- 環境差判別が要るなら `COPILOT_CLI` 環境変数を使う

## 5. `readlink -f` は macOS で動かない

bash スクリプトで `dirname "$(readlink -f "$0")"` のように使うと、macOS の
標準 `readlink` は `-f` を持たないため失敗する。

**対策**:

```bash
__script_dir="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
```

`pwd -P` でシンボリックリンクも解決した絶対パスが得られる。

## 6. prompt 型 hook は新規 interactive session のみ発火 (Copilot)

`SessionStart` の `type: "prompt"` hook (擬似ユーザ入力) は:

- 新規 interactive session で発火
- resume / `-p` programmatic mode では発火しない
- Copilot cloud agent では発火する保証なし

**対策**: prompt hook に頼らず、`SessionStart` の `additionalContext` で
代用する。

## 7. 設定ファイル形式が両ツールで違う

Claude Code (`~/.claude/settings.json` の hooks 節、ネスト構造):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "..." }
        ]
      }
    ]
  }
}
```

Copilot CLI (`~/.copilot/hooks/*.json`、フラット構造):

```json
{
  "version": 1,
  "hooks": {
    "PreToolUse": [
      { "matcher": "^bash$", "type": "command", "bash": "..." }
    ]
  }
}
```

**対策**:

- 設定ファイルは両ツール別々に書く (スクリプト本体は共通化可能)
- ただし Copilot CLI は `.claude/settings.json` (リポジトリ単位) も読むので、
  プロジェクト hooks はそちらに集約すれば共通設定にできる
- 詳細は `templates/hook-config-examples.json` 参照

## 8. `~/.copilot/hooks/` は JSON 専用

Copilot CLI はこのディレクトリ配下を全件 JSON パース対象とする。間違って
シェルスクリプトや Python ファイルを置くと **起動時に parse error**。

**対策**: スクリプト本体は `~/.claude/hooks/` または別ディレクトリに置き、
`~/.copilot/hooks/*.json` からは absolute path で参照する。

## 9. matcher の regex は Copilot で anchored される

Copilot CLI: `matcher` は `^(?:pattern)$` で full-string match が必須。
`bash` という matcher は **`bash` という文字列 全体** にのみマッチする
(`Bash` などとは別)。Copilot のツール名は小文字なので注意。

**対策**: Copilot 用 matcher は `^bash$`, `^(edit|create)$` のように
明示的に書く。

## 10. Stop hook の無限ループ

Stop hook が常に `decision: "block"` を返すと、agent が永遠にターンを
継続する。

**対策**: session_id をキーにしてマーカーファイルを作り、1 セッションに
1 回だけ block する。

```python
import tempfile
from pathlib import Path

marker = Path(tempfile.gettempdir()) / f"hook_{session_id}"
if marker.exists():
    sys.exit(0)
marker.touch()
```

## 11. tool_name の大文字小文字違い (再掲)

最頻出のバグ。Claude `"Bash"` / Copilot `"bash"`。スクリプトが片方しか
受理しないと **何も検査せず exit 0** で素通り。

**対策**: `templates/agent_compat.py` の `normalize_tool_kind()` を使う。

## 12. JSON 出力に余計な print デバッグを混ぜると壊れる

`sys.stdout.write("debug\n"); json.dump(payload, sys.stdout)` のように
書くと、stdout が `debug\n{"permissionDecision":...}` となり JSON parse
失敗で deny が無効になる。

**対策**: デバッグは必ず `print(..., file=sys.stderr)` で出す。
