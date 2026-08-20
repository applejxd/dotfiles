# AI CLI 統合 permission / hook 管理

Claude Code / Copilot CLI の permission (allow/deny/ask) と hook 登録を
**単一ソース** で管理し、`chezmoi apply` で両 CLI の設定ファイルへ自動展開する仕組み。

## ファイル構成

```text
home/dot_config/agents/
    common.toml                              単一ソース (permissions + hooks)
    critical_deny.py                         hook が import する shell normalizer
                                             (critical_deny / critical_ask の loader も兼ねる)
scripts/agents/
    generate.py                              modify_ / .tmpl から呼ばれる変換器
home/dot_claude/
    modify_settings.json.tmpl                ~/.claude/settings.json を更新
home/dot_claude/hooks/
    executable_check_bash.py                 critical_deny/critical_ask を判定
    executable_redirect-tmp.py               /tmp 利用を ./.tmp へ誘導
    executable_markdownlint.sh               Markdown の lint
    executable_format-file.sh                拡張子別のフォーマッタ実行
    executable_update-adr-on-stop.py         ターン終了時に ADR 更新を促す
home/dot_copilot/
    hooks/from-claude.json.tmpl              ~/.copilot/hooks/from-claude.json を生成
    modify_private_settings.json.tmpl        ~/.copilot/settings.json を更新
    modify_private_permissions-config.json.tmpl
test/agents/
    test_critical_deny.py                    shell normalize / match の unit test
    test_check_bash_decision.py              deny/ask 判定と rm root guard の test
    test_generate_hooks.py                   hook 生成の unit test
```

`modify_private_*` のように `private_` を付けることで mode 600 を保持し、
`~/.copilot/settings.json` に含まれる `gho_xxx` トークンを保護している。

## 4 層モデル

| 層 | 仕組み | 用途 | 無人実行時 |
| --- | --- | --- | --- |
| 1. CLI UI prompt | Claude/Copilot の対話モード | 都度確認 | 出せない |
| 2. permission リスト | `~/.claude/settings.json` / `~/.copilot/{settings,permissions-config}.json` | allow / ask / deny | deny は全モードで有効 |
| 3. **hook `critical_deny`** | `check_bash.py` → `deny` | 承認の余地なく止める | block |
| 4. **hook `critical_ask`** | `check_bash.py` → `ask` | 提案 → 承認 → そのまま実行 | 安全側 (拒否/スキップ) |

CLI 側 permission リストは「best-effort」と扱い、本当に止めたい命令は
`[bash.critical_deny]` に書く。逆に「危険だが承認すれば実行してよい」命令は
`[bash.critical_ask]` に書く。

第 3 / 第 4 層の hook 登録自体も `common.toml` の `[[hooks]]` から生成されるため、
新規マシンで `chezmoi init --apply` した直後から両 CLI で有効になる。

### ★ 評価順: `permissions.deny` は hook より優先される

> "Hook decisions don't bypass permission rules. Claude Code evaluates deny and ask
> rules regardless of what a PreToolUse hook returns"
> — <https://code.claude.com/docs/en/permissions>

```text
permissions.deny > hook の ask/deny > permissions.ask > hook の allow > permissions.allow
```

つまり **`[bash.critical_ask]` に書いたコマンドを `[bash.deny]` にも書くと、
hook の `ask` は無効化され、プロンプトすら出ずに拒否される**。
両方に書かないこと (`test_check_bash_decision.py` で自動検査している)。

### deny と ask の使い分け

| 分類 | 例 | 置き場所 |
| --- | --- | --- |
| 承認の余地なく禁止 | `sudo`, `git push`, `git reset --hard`, `git rebase` | `[bash.critical_deny]` + `[bash.deny]` |
| 壊滅的な削除 | `rm -rf /`, `rm -rf ~`, `rm -rf /etc` | `check_bash.py` の `check_rm_root_guard` (hard-deny) |
| 提案 → 承認 → 実行 | `rm -rf <プロジェクト内>`, `find -delete` | `[bash.critical_ask]` + `[bash.ask]` |
| 毎回判断したい | `git commit`, `curl`, `mv`, `npm install` | `[bash.ask]` |
| 自動承認 | `git status`, `grep -n`, `uv sync` | `[bash.allow]` |

### 無人実行時に `ask` がどうなるか

| 実行環境 | `ask` の結果 |
| --- | --- |
| Claude 対話 (`default`) | プロンプトが出る |
| Claude `auto` | プロンプトが出る (classifier の暗黙 approve を封じる) |
| Claude `bypassPermissions` | プロンプトが出る |
| Claude `dontAsk` | 自動拒否 |
| Claude `-p` (非対話) | プロンプト不能。auto では当該操作をスキップして継続 |
| Copilot cloud agent | `deny` 扱い |

→ 無人実行では必ず安全側に倒れるため、**`deny` を `ask` に緩めても無人時のリスクは
増えない**。対話時だけ「自分で手を動かす」手間が減る。

## hooks の単一ソース化

`[[hooks]]` に 1 度書けば、両 CLI の設定ファイルへ展開される。

| 生成先 | 生成方法 | 使うフィールド |
| --- | --- | --- |
| `~/.claude/settings.json` の `hooks` | `modify_settings.json.tmpl` → `--target claude-settings` | `claude_event` / `claude_matcher` / `timeout_sec` |
| `~/.copilot/hooks/from-claude.json` | `from-claude.json.tmpl` の `output` → `--target copilot-hooks` | `copilot_event` / `copilot_matcher` / `timeout_sec` |

- hook スクリプトの実体は `~/.claude/hooks/` に 1 つだけ置き、Copilot からも
  同じファイルを呼ぶ (`$HOME/.claude/hooks/...`)
- `hooks` キーは apply のたびに**全置換**される。CLI 側で手動追加した hook は
  消えるので、必ず `common.toml` に転記する
- `*_event` を空にすればその CLI には出力されない
- `*_matcher` を省略すると `matcher` キー自体が出力されない (= 全マッチ)。
  `Stop` / `UserPromptSubmit` など matcher 非対応イベントでは省略すること

### matcher の書き分け (共通化してはいけない)

| CLI | 意味論 | 書き方 |
| --- | --- | --- |
| Claude Code | tool 名の完全一致を `\|` で OR 連結 | `Edit\|Write` |
| Copilot CLI | `^(?:pattern)$` として anchored される | `^(Edit\|Write\|edit\|create)$` |

Copilot は PascalCase イベント名で書くと Claude の tool 名 (`Edit` / `Write` …)
で照合するため、両方の名前を列挙する。

### Claude Code のイベント名・timeout の注意 (2026-08 時点の公式 docs 準拠)

- `TaskCompleted` は実在するが、`TaskCreate` ツール経由のタスク完了時にのみ発火する。
  「ターン終了時」に 1 回だけ動かしたい hook は `Stop` を使う
  (`Stop` = "When Claude finishes responding"、cadence は "once per turn")
- `SubagentStop` は `Stop` とは独立。サブエージェント終了も拾いたいなら両方に登録する
- `timeout` キーの単位は秒。`command` 型 hook のデフォルトは **600 秒**と長いため、
  `timeout_sec` を明示している (Copilot 側のキー名は `timeoutSec`)

## common.toml の編集ルール

- 編集後は `chezmoi apply` で `~/.claude/settings.json` 等に反映される
- CLI UI で「Always allow」を押した場合は、その項目を common.toml に転記する
  (転記しないと次回 apply で消える。これは意図的な強制で、dotfiles を単一の
  真実とする方針)
- `[bash.critical_deny]` は hook が hard-block するので、Claude/Copilot 双方で
  確実に動作する
- `[bash.critical_ask]` は hook が `ask` を返す。承認すればそのまま実行される。
  **同じコマンドを `[bash.deny]` に書くと deny が優先されて無効になる**
- `[bash.deny]` は Claude 側のみ反映 (Copilot CLI は path-scope の設計のため
  CLI フラグでしか細粒度 deny を表現できない)
- `[file.write_ask_globs]` / `[file.write_deny_globs]` は Claude の
  **`Edit(path)`** rule として展開される。Claude Code v2.1.210 で
  `Write(path)` / `NotebookEdit(path)` / `Glob(path)` の permission rule は
  deprecated になり (起動時警告)、代替として `Edit(path)` / `Read(path)` が
  案内されている
  ([CHANGELOG v2.1.210](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md))。
  なお `Write` ツール自体は現役なので、hooks の `matcher` に書く `Write` は
  引き続き有効 (`MultiEdit` は v2.0 系で削除済みなので不要)

## Claude Code permission リストの既知バグ

下記は 2026-05 時点で open。`critical_deny` + hook で必ず防ぐべき理由。

| Issue | 概要 |
| --- | --- |
| [#59498](https://github.com/anthropics/claude-code/issues/59498) | `cd /elsewhere && git push` が `Bash(git push:*)` ask/deny を bypass |
| [#59006](https://github.com/anthropics/claude-code/issues/59006) | `git -C /path commit` が `Bash(git commit *)` deny を bypass |
| [#20085](https://github.com/anthropics/claude-code/issues/20085) | compound 命令 (`a && b`) が個別評価されない |
| [#52419](https://github.com/anthropics/claude-code/issues/52419) | VS Code 拡張の auto-attach が `.claudeignore` / deny を bypass |

`scripts/agents/test_critical_deny.py` の `test_real_bug_*` ケースで、これらの
bypass パターンを hook が確実に block することを保証している。

## Copilot CLI の制約 (実機確認済)

- `~/.copilot/permissions-config.json` は **対話モードでのみロード** される。
  `copilot -p` (非対話モード) では一切無視される。
- `tool_approvals` の `kind: "commands"` の `commandIdentifiers` は
  **command 名の完全一致** のみで、`shell(git:*)` のような glob パターンの
  永続化サポートは未確証。よって本仕組みでは `[bash.allow]` の first token を
  ユニーク化して `commandIdentifiers` に集約する粗粒度方式を採用している。
- `kind: "write"` は MCP write tool 用で、shell tool (`touch`/`rm` 等) には
  効かない。
- `~/.copilot/settings.json` の `copilotTokens` / `loggedInUsers` /
  `installedPlugins` 等は Copilot 自動管理なので、generate.py はキー名
  ホワイトリスト方式で温存する。

## 動作確認手順

### unit test

```bash
uv run --with pytest --no-project pytest test/agents/ -q
# -> 104 passed (critical_deny 26 + hook 生成 21 + deny/ask 判定 57)
```

hook は `AGENTS_CONFIG_DIR` で agents 設定ディレクトリを差し替えられるので、
`~/.config` へ apply する前でもリポジトリの `common.toml` に対してテストできる。

### dry-run

```bash
chezmoi diff ~/.claude/settings.json
chezmoi diff ~/.copilot/hooks/from-claude.json
chezmoi diff ~/.copilot/settings.json
chezmoi diff ~/.copilot/permissions-config.json

# 生成結果だけ見たいとき
chezmoi cat ~/.copilot/hooks/from-claude.json
```

### apply 後の hook 動作確認

```bash
# 正常コマンド (PASS)
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git status"}}' \
  | python3 ~/.claude/hooks/check_bash.py

# critical: cd && bypass を block
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cd /elsewhere && git push"}}' \
  | python3 ~/.claude/hooks/check_bash.py
# -> stdout に permissionDecision: deny の JSON が出力される

# format-file: Claude 形式 (file_path) / Copilot 形式 (path) の両方で動く
echo '{"tool_input":{"path":"/path/to/foo.py"}}' | bash ~/.claude/hooks/format-file.sh
```

## 新環境セットアップ

1. `chezmoi init --apply <repo>` で全ファイルが配置される
2. `~/.config/agents/common.toml` を編集して必要な項目を追加
3. `chezmoi apply` で両 CLI 設定が再生成される

なお初回 apply 時、Claude Code が未起動なら `~/.claude/settings.json` は存在しない。
chezmoi modify_ スクリプトは空 stdin を受けると空オブジェクトとして扱い、common.toml
ベースの最小 settings.json (permissions + hooks) を生成する。

## トラブルシュート

| 症状 | 対応 |
| --- | --- |
| apply 後 Claude が `permissions` / `hooks` を読まない | Claude Code は起動時に settings.json を読むので再起動 |
| Copilot CLI で hook の deny が効かない | `~/.copilot/hooks/from-claude.json` が apply されているか確認。`copilot --log-level debug` で hook がロードされているか確認 |
| `~/.config/agents/critical_deny.py` の import に失敗 | `~/.config/agents/__pycache__/` を削除して `chezmoi apply` をやり直し |
| common.toml の編集が反映されない | `chezmoi diff` で差分を確認 → `chezmoi apply` |
