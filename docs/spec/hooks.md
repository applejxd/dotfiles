# Hooks 個別仕様

> 旧 `home/dot_claude/hooks/` 5 件の個別仕様。
> 全体方針は [`requirements.md`](./requirements.md)、I/O 規約は [ADR-0004](./adr/0004-hook-io-stdout-json.md) を参照。
> ID 規約: `HOOK-<name>-NNN`。

## インベントリ表

| 名称 | 旧パス | Claude bind | Copilot bind | ステータス | 関連 ADR | 関連 REQ |
| --- | --- | --- | --- | --- | --- | --- |
| `check_bash` | `hooks/executable_check_bash.py` | `PreToolUse` matcher=`Bash` | `preToolUse` matcher=`^bash$` | `migrated` | 0004, 0005 | HOOK-check-bash-* |
| `redirect-tmp` | `hooks/executable_redirect-tmp.py` | `PreToolUse` matcher=なし（全 tool） | `preToolUse` matcher=`.*` | `migrated` | 0004 | HOOK-redirect-tmp-* |
| `update-adr-on-stop` | `hooks/executable_update-adr-on-stop.py` | `TaskCompleted` | `sessionEnd`（代替） | `partial` | 0004 | HOOK-update-adr-* |
| `format-file` | `hooks/executable_format-file.sh` | （未 bind / 利用未確定） | `postToolUse` matcher=`^(Edit\|Write\|MultiEdit)$`（任意） | `dropped` | 0004 | HOOK-format-file-* |
| `markdownlint` | `hooks/executable_markdownlint.sh` | `PostToolUse` matcher=`Edit\|Write\|MultiEdit` | `postToolUse` matcher=`^(edit\|write\|multiEdit)$` | `partial` | 0004 | HOOK-markdownlint-* |

ステータス補足:

- `update-adr-on-stop`: TaskCompleted の任意ターン発火が Copilot に対応物なし → `sessionEnd` で代替するため `partial`
- `format-file`: Claude 側でも `modify_settings.json` に bind されていない（孤立スクリプト）。Copilot 側でも採用せず `dropped` とする。`tasks.md` で再評価
- `markdownlint`: PostToolUse stderr の LLM フィードバック経路が Copilot に無く、自動修正のみが残るため `partial`

---

## HOOK-check-bash

### 現状（Claude 側）

- 言語: Python (`#!/usr/bin/env python3`)
- bind: `PreToolUse` matcher=`Bash`（`modify_settings.json`）
- 入力: `tool_name`, `tool_input.command`, `cwd`
- 動作（カテゴリ別）:
  1. **環境変数全件露出**: `env`, `printenv`, `export`, `set`（引数なし）を deny
  2. **`git -C <path>` 経由の禁止サブコマンド**: `push`, `reset`, `rebase`, `config` を deny
  3. **`find` の破壊的 exec**: `-exec rm/unlink/shred/rmdir`, `-delete` を deny
  4. **ファイル読み取りコマンドの sensitive path target**: `grep`, `cat`, `head`, `tail`, `sed`, `awk`, `less`, `more`, `strings`, `xxd`, `hexdump`, `base64`, `od` が `SENSITIVE_PATH_PATTERNS` を引数に含む場合 deny
  5. **アーカイブの sensitive path 取り込み**: `tar`, `zip`, `gzip`, `bzip2`, `7z`, `xz` が同上に該当する場合 deny
  6. **curl/wget による sensitive ファイル送信**: `-d @`, `-F ...=@`, `--data-binary @` パターン で sensitive path target なら deny
  7. **xargs と読取コマンドの組み合わせ**: `xargs ... <FILE_READ_COMMAND>` が sensitive path target なら deny
  8. **`pip` / `python -m pip`**: cwd に `uv.lock` がある場合に限り deny し、`uv` / `uvx` 代替を提示
- **対象外（permission deny で別途防御されている）**: `rm`, `sudo`, `git push/reset/rebase/config`（`-C` 経由でない場合）, `wget`, `nc`, `telnet`, `ssh` 等は `modify_settings.json` の deny 側で扱われる
- 出力: exit 0 (許可) / exit 2 + stderr (ブロック)

### Copilot 移植方針

- 配置: `home/dot_copilot/hooks/executable_check_bash.py`
- bind: `~/.copilot/config.json` 内 `hooks.preToolUse[].matcher = "^bash$"`
- 入力スキーマの差異: `tool_name`/`toolName`, `tool_input`/`toolArgs` を両対応する helper を hook 内に持つ（ADR-0004）
- 出力変換: stderr メッセージ + exit 2 → stdout に `{"permissionDecision":"deny","permissionDecisionReason":"<message>"}` + exit 0
- fail-open: JSON パース失敗・例外時は exit 0（REQ-031）
- 既存ロジック（`SENSITIVE_PATH_PATTERNS`, `FILE_READ_COMMANDS`, `ENV_EXPOSURE_COMMANDS`, `ARCHIVE_COMMANDS`, `CURL_FILE_SEND_PATTERN`, `_FIND_DANGEROUS_EXEC_RE`, `check_pip_redirect`）は **そのまま流用**

### EARS 受け入れ基準

#### HOOK-check-bash-001 (Event-driven)

WHEN a Bash command is exactly `env`, `printenv`, `export`, or `set` (no arguments), THE hook SHALL deny it with a redirect message recommending `echo $VAR_NAME`.

#### HOOK-check-bash-002 (Event-driven)

WHEN a Bash command matches `git -C <path> ... (push|reset|rebase|config)`, THE hook SHALL deny it with a message about the security policy.

#### HOOK-check-bash-003 (Event-driven)

WHEN a Bash command matches `find ... -exec (rm|unlink|shred|rmdir)` or `find ... -delete`, THE hook SHALL deny it with a message about explicit approval being required.

#### HOOK-check-bash-004 (Event-driven)

WHEN a Bash command invokes one of `FILE_READ_COMMANDS` (`grep`/`cat`/`head`/`tail`/`sed`/`awk`/`less`/`more`/`strings`/`xxd`/`hexdump`/`base64`/`od`) AND its arguments match `SENSITIVE_PATH_PATTERNS`, THE hook SHALL deny it with a reason that names the matched pattern.

#### HOOK-check-bash-005 (Event-driven)

WHEN a Bash command invokes one of `ARCHIVE_COMMANDS` (`tar`/`zip`/`gzip`/`bzip2`/`7z`/`xz`) AND its arguments match `SENSITIVE_PATH_PATTERNS`, THE hook SHALL deny it.

#### HOOK-check-bash-006 (Event-driven)

WHEN a Bash command matches `(curl|wget) ... (-d @|-F ...=@|--data-binary @)` AND the surrounding arguments match `SENSITIVE_PATH_PATTERNS`, THE hook SHALL deny it.

#### HOOK-check-bash-007 (Event-driven)

WHEN a Bash command pipes through `xargs <FILE_READ_COMMAND>` AND its arguments match `SENSITIVE_PATH_PATTERNS`, THE hook SHALL deny it.

#### HOOK-check-bash-008 (Event-driven)

WHEN the cwd contains `uv.lock` AND the Bash command starts with `pip` or `python -m pip`, THE hook SHALL deny it and SHALL suggest the appropriate `uv` / `uvx` alternative.

#### HOOK-check-bash-009 (Unwanted)

IF stdin JSON parsing fails or any unexpected exception is raised, THEN THE hook SHALL exit 0 (fail-open) without emitting any deny JSON.

### 保留事項

- 入力の `toolName` (camelCase) / `tool_name` (snake_case) どちらが Copilot 実装の正となるか実機確認（実装フェーズの検証タスク）

---

## HOOK-redirect-tmp

### 現状

- 言語: Python (`#!/usr/bin/env python3`)
- bind: `PreToolUse`（matcher なし → 全 tool）
- 対象 tool: `Bash`, `Read`, `Write`, `Edit`, `MultiEdit`
- 動作: `/tmp/`, `${TMPDIR}`, `${TEMP}`, `${TMP}` をパス／コマンド内で検出してブロック
- 出力: exit 0 / exit 2 + stderr

### Copilot 移植方針 (redirect-tmp)

- 配置: `home/dot_copilot/hooks/executable_redirect-tmp.py`
- bind: `hooks.preToolUse[].matcher = ".*"`（全 tool）
- 出力変換: stderr → stdout `{"permissionDecision":"deny",...}` + exit 0
- fail-open（REQ-031）
- 対象 tool 名のマッピング: Claude `Bash`/`Read`/`Write`/`Edit`/`MultiEdit` → Copilot `bash`/`read`/`write`/`edit`/`multiEdit`（小文字、Copilot の tool 名規約に合わせる）

### 機能拡張（REQ-041 対応）

ADR-0005 / REQ-041 により、`Read(**/*token*)` 等の path 単位 deny は本 hook の責務として吸収する:

- 既存の `/tmp` 検出に加えて、`tool_input.file_path` / `tool_input.path` が **`check_bash` の `SENSITIVE_PATH_PATTERNS` と同等のパターン** にマッチする場合も deny する
- パターン定義は `check_bash.py` と共有することが望ましい（ただし共通モジュール化は ADR-0004 で「導入しない」と決めたため、定数を **コピペ二重定義** する。両方を同時に変更することを `tasks.md` の検証項目に含める）
- 対象 tool: `read`, `write`, `edit`, `multiEdit`（Bash は `check_bash` 側で処理）

### EARS 受け入れ基準 (redirect-tmp)

#### HOOK-redirect-tmp-001 (Event-driven)

WHEN a Bash command contains `/tmp/`, `${TMPDIR}`, `${TEMP}`, or `${TMP}`, THE `redirect-tmp` hook SHALL deny the call with a redirect message to `./.tmp/`.

#### HOOK-redirect-tmp-002 (Event-driven)

WHEN a Read/Write/Edit/MultiEdit tool input has a `file_path` or `path` starting with `/tmp/`, THE hook SHALL deny the call.

#### HOOK-redirect-tmp-003 (Event-driven)

WHEN a Read/Write/Edit/MultiEdit tool input has a `file_path` or `path` matching one of `SENSITIVE_PATH_PATTERNS` (per `check_bash.py`), THE hook SHALL deny the call with a reason that names the matched pattern.

#### HOOK-redirect-tmp-004 (Unwanted)

IF stdin JSON parsing fails or the tool name is not in the supported set, THEN THE hook SHALL exit 0 silently.

### 保留事項 (redirect-tmp)

- Copilot CLI の tool 名表記（小文字 vs キャメルケース vs PascalCase）の最終確認

---

## HOOK-update-adr-on-stop

### 現状 (update-adr-on-stop)

- 言語: Python
- bind: `TaskCompleted`（modify_settings.json）
- 動作: cwd に `docs/adr/` があれば、ADR 一覧をメッセージにして stderr に出し、exit 2 でタスク完了をブロックして Claude に再考を促す
- 重複防止: `tempfile.gettempdir()` 配下に `claude_adr_checked_<session_id>` マーカーを作成

### Copilot 移植方針 (update-adr-on-stop)

- 配置: `home/dot_copilot/hooks/executable_update-adr-on-stop.py`
- bind: `hooks.sessionEnd[]`（`TaskCompleted` 相当が無いため、セッション終了時に発火）
- 出力変換: 旧 stderr メッセージは **stdout の `additionalContext`** で会話への注入を試みる
  - ただし `sessionEnd` の output が ignored なのは公式 docs 上明示されているため、現実的には **stderr に同じメッセージを出してログとして残す** のみ
  - exit 0 固定
- 重複防止: `tempfile.gettempdir()` 配下のマーカー方式は維持（パス名のみ `copilot_adr_checked_<session_id>`）
- マーカー TTL の懸念は実装時に評価（古いマーカーが残ると次回起動時の挙動に影響）

### EARS 受け入れ基準 (update-adr-on-stop)

#### HOOK-update-adr-001 (Event-driven)

WHEN a Copilot session ends AND `docs/adr/` exists in cwd AND contains files, THE `update-adr-on-stop` hook SHALL log an ADR update reminder to stderr listing the existing ADR filenames.

#### HOOK-update-adr-002 (State-driven)

WHILE a `copilot_adr_checked_<session_id>` marker file exists in tempdir, THE hook SHALL skip emitting the reminder.

#### HOOK-update-adr-003 (Unwanted)

IF Copilot CLI does not relay `additionalContext` from `sessionEnd` hooks (currently expected behaviour), THEN the hook SHALL still complete with exit 0 so that session shutdown is not affected.

### 保留事項 (update-adr-on-stop)

- TaskCompleted 相当の任意ターン発火が将来 Copilot に追加された場合は ADR を更新して `migrated` に格上げ可能
- マーカーファイルの掃除戦略（chezmoi 適用時 / 起動時クリーンアップ）

---

## HOOK-format-file

### 現状 (format-file)

- 言語: Bash
- bind: **なし**（Claude の `modify_settings.json` には bind 記述が見当たらない）
- 動作: tool_input.file_path から拡張子を判定し、Python/C++/JS-TS-CSS-JSON-YAML を ruff/clang-format/prettier で自動整形
- 重複: `markdownlint` と機能が重複（特に `.md` は markdownlint 側で fix）

### Copilot 移植方針: `dropped`

- 旧 Claude 側で実利用されていない（bind されていない）ため、Copilot にも持ち込まない
- 移植したい要件が将来出た場合は別 hook として再導入する

### EARS 受け入れ基準 (format-file)

#### HOOK-format-file-001 (Ubiquitous)

THE `format-file` hook SHALL NOT be installed under `~/.copilot/hooks/`; the spec SHALL document this as `dropped` (rationale: not bound in current Claude config).

### 保留事項 (format-file)

- 将来 `postToolUse` で自動整形を再導入する要望が出た場合、新規 hook として ADR を追加して扱う

---

## HOOK-markdownlint

### 現状 (markdownlint)

- 言語: Bash
- bind: `PostToolUse` matcher=`Edit|Write|MultiEdit`
- 動作: `.md` / `.markdown` ファイルを `markdownlint-cli2 --fix` で自動修正、残存違反があれば exit 2 + stderr で Claude に再修正させる
- 依存: `markdownlint-cli2`（PATH 直 / npx fallback）

### Copilot 移植方針 (markdownlint)

- 配置: `home/dot_copilot/hooks/executable_markdownlint.sh`
- bind: `hooks.postToolUse[].matcher = "^(edit|write|multiEdit)$"`
- 自動修正は維持（`markdownlint-cli2 --fix`）
- **失われる機能**: PostToolUse stderr の LLM 再投入は Copilot に無いため、残存違反の Claude へのフィードバックは **諦める**（stderr へのログ出力のみ）
- exit 0 固定（REQ-035）

### EARS 受け入れ基準 (markdownlint)

#### HOOK-markdownlint-001 (Event-driven)

WHEN a tool input has `tool_input.file_path` (Read/Write style) OR `tool_input.path` (Edit/MultiEdit style) ending with `.md` or `.markdown`, THE `markdownlint` hook SHALL run `markdownlint-cli2 --fix` against that file.

#### HOOK-markdownlint-002 (Unwanted)

IF `markdownlint-cli2` is not on PATH AND `npx` is not available, THEN the hook SHALL exit 0 silently.

#### HOOK-markdownlint-003 (Ubiquitous)

THE hook SHALL exit 0 regardless of whether residual lint violations remain (since `postToolUse` stdout is ignored by Copilot CLI).

### 保留事項 (markdownlint)

- 残存違反を別の方法（次ターンの user prompt で `additionalContext` として注入する別 hook を `userPromptSubmitted` に追加する等）で再現するかは将来検討
