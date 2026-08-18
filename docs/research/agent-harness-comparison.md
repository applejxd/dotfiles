# エージェントハーネス比較（Claude Code / Copilot CLI / Codex CLI）

> **調査日時: 2026-08-08 11:39 JST**
> **検証バージョン: Claude Code 2.1.143 / GitHub Copilot CLI 1.0.79-5 / Codex CLI 0.146.1**
> （参考: Gemini CLI 0.33.1。本書の比較対象外）
>
> ハーネスの仕様は更新が激しい。本書を参照する前に必ず
> [再確認すべき情報源](#再確認すべき情報源)のリンクを開き、差分を反映してから使うこと。
> 本書は **3 ハーネスの差分** に絞った比較資料であり、各ツールの網羅的な仕様書ではない。
> Skills / Custom Agents / MCP などの個別仕様は公式ドキュメントを直接参照すること。

## 0. 本書の用途

`~/.claude/CLAUDE.md` / `~/.copilot/copilot-instructions.md` / `~/.codex/AGENTS.md` という
**個人用カスタム指示**を再設計するときの判断材料。指示に書くべきかどうかは
「そのハーネスが既に機械的に強制しているか」で決まるため、強制層の差分が最重要。

判断フロー:

1. ハーネスの既定システムプロンプトが持つ挙動 → **書かない**
2. hook / permission / rules / サンドボックスで機械的に強制済み → **書かない**
3. skill に委譲済み → **書かない**
4. 上記のいずれでもなく、全リポジトリで真 → **個人用指示に書く**
5. 特定リポジトリでのみ真 → リポジトリ側の `AGENTS.md` に書く

## 1. 指示ファイルの探索と結合

| | Claude Code | Copilot CLI | Codex CLI |
| --- | --- | --- | --- |
| 個人用 | `~/.claude/CLAUDE.md`、`~/.claude/rules/*.md` | `~/.copilot/copilot-instructions.md`、`~/.copilot/instructions/**/*.instructions.md` | `~/.codex/AGENTS.override.md`、無ければ `~/.codex/AGENTS.md` |
| リポジトリ | `./CLAUDE.md` / `.claude/CLAUDE.md`、`CLAUDE.local.md`、`.claude/rules/*.md` | `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`、`.github/copilot-instructions.md`、`.github/instructions/**/*.instructions.md` | 各ディレクトリで `AGENTS.override.md` → `AGENTS.md` → `project_doc_fallback_filenames` |
| 結合方式 | 全て連結。root → cwd 順で、cwd に近いものが後ろ | **列挙した全ソースを同時マージ** | 連結。root → cwd 順。1 ディレクトリ 1 ファイルのみ |
| サイズ上限 | 無し（公式推奨は 200 行未満） | 明示なし | `project_doc_max_bytes` 既定 32 KiB で打ち切り |
| 遅延ロード | サブディレクトリの CLAUDE.md は該当ファイル読み込み時 | 無し | 無し |

### 落とし穴（指示ファイルの探索）

- **Claude Code は `AGENTS.md` を読まない。** 併用するなら `CLAUDE.md` に `@AGENTS.md` と
  書いて import するか symlink する
- **Codex は `AGENTS.override.md` があると同一ディレクトリの `AGENTS.md` を無視する**
- Copilot CLI は `CLAUDE.md` も `GEMINI.md` も読むので、3 ツール併用時に同じ内容が
  三重にコンテキストへ載りうる
- 優先順位は「後に置かれたものが強い」であって、機構的な強制ではない。矛盾する指示が
  あるとモデルが恣意的に選ぶ

## 2. 決定論的な強制層（最重要の差分）

| 強制手段 | Claude Code | Copilot CLI | Codex CLI |
| --- | --- | --- | --- |
| hook | ✅ `~/.claude/settings.json` の `hooks` | ✅ `~/.copilot/hooks/*.json` / `settings.json` の `hooks` | ✅ `hooks.json` / inline `[hooks]`（feature flag `hooks`、既定 on） |
| hook イベント数 | **30 以上**（`InstructionsLoaded` / `CwdChanged` / `TaskCompleted` など独自イベント多数） | 13 前後 | 別系統（`learn.chatgpt.com/docs/hooks` を参照） |
| permission allow | ✅ `permissions.allow` | ✅ `permissions-config.json` の `tool_approvals` | ✅ rules の `decision = "allow"` |
| permission **deny** | ✅ `permissions.deny` が効く | ❌ **存在しない**（`permissions-config.json` は allow 専用） | ✅ rules の `decision = "forbidden"` |
| permission ask | ✅ `permissions.ask` | ❌（対話プロンプトのみ） | ✅ rules の `decision = "prompt"` |
| OS サンドボックス | `sandbox.enabled`（既定 `false`） | `/sandbox`（experimental、既定 off） | `sandbox_mode`（既定 `workspace-write`） |
| 承認ポリシー | permission mode（`default` / `plan` / `acceptEdits` / `auto` / `bypassPermissions`） | 対話プロンプト + `--allow-all` 系 | `approval_policy`（`untrusted` / `on-request` / `on-failure` / `never`） |
| 秘密情報の遮断 | `permissions.deny` の `Read(...)`、sandbox の `credentials.files` / `envVars` マスク | hook 頼み | `shell_environment_policy`。既定で `KEY` / `SECRET` / `TOKEN` を含む変数を子プロセスに渡さない |

### この差が指示文に与える影響

- Copilot CLI には deny が無いため、`common.toml` の `bash.deny` は **Copilot には届かない**。
  止めたいものは hook で hard-block するしかない
- Claude Code は deny が効くが、**permission リストに既知の bypass がある**
  （`cd foo && X`、`git -C foo X`。anthropics/claude-code#59498, #59006, #20085 ほか）。
  `critical_deny.py` の normalize は `cd` 剥がしと `git -C` 展開で一部を救済するが、
  `critical_deny` に載っていない項目（`pip` / `wget` / `ssh` / `docker rm` 等）は素通りする
- Codex は既定が read-only サンドボックス + `approval_policy = "untrusted"` のため、
  **書き込みを伴う検証（テスト実行など）が構造的に承認エスカレーションを必要とする**

## 3. この環境での実際の配線（2026-08-08 時点）

### 配線方針

共通資産は `~/.claude` 配下に集約し、他ハーネスからは参照する。同一スクリプトを
二重管理しないことが目的で、`agent_compat.py` が両ツールの I/O 差を吸収することを前提にしている。

- skill: `~/.copilot/skills` は `../.claude/skills` への symlink（Copilot CLI は
  `.claude/skills` を公式サポートするため、コピーではなく参照で済む）
- hook: `~/.copilot/hooks/from-claude.json` が `$HOME/.claude/hooks/*.py` を指す
- permission: `home/dot_config/agents/common.toml` を単一ソースとし、
  `scripts/agents/generate.py` が各ハーネスの形式へ変換する

### bind 一覧

| | 設定ソース | 実際に bind されているもの |
| --- | --- | --- |
| Claude Code | `home/dot_claude/modify_settings.json.tmpl`（`permissions` と `hooks` を生成、他キーは保持） | `~/.claude/settings.json` のキー: `enabledPlugins` / `env` / `hooks` / `includeCoAuthoredBy` / `permissions`。hook イベント: `PreToolUse` / `PostToolUse` / `Stop` |
| Copilot CLI | `home/dot_copilot/hooks/from-claude.json.tmpl`（common.toml から生成）、`modify_private_settings.json.tmpl`、`modify_private_permissions-config.json.tmpl` | `PreToolUse`（`check_bash.py` matcher=`^(Bash\|bash)$`、`redirect-tmp.py` matcher=`^(Bash\|bash\|Read\|view\|Write\|create\|Edit\|edit)$`）、`PostToolUse`（`markdownlint.sh` / `format-file.sh`）、`Stop`（`update-adr-on-stop.py`） |
| Codex CLI | `home/dot_codex/modify_config.toml`、`home/dot_codex/rules/*.rules` | `approval_policy = "untrusted"`、`sandbox_mode = "read-only"`、`web_search = "live"`、`personality = "pragmatic"`、`shell_environment_policy`（PATH/HOME/USER のみ）、rules 4 ファイル |

権限と hook の単一ソースは `home/dot_config/agents/common.toml`。
生成は `scripts/agents/generate.py`。
詳細は [`docs/agents-permissions.md`](../agents-permissions.md)。

### Codex rules の decision 分布

| decision | 対象 |
| --- | --- |
| `allow` | `git log` / `git status` / `git diff`、`gh pr list` / `gh issue list` / `gh issue view` / `gh repo view` / `gh run list` / `gh run view`、`docker ps` / `images` / `logs` / `inspect`、`grep` / `rg` / `awk` |
| `prompt` | `git add` / `commit` / `push` / `reset` / `clean` / `branch -D`、`gh pr view` / `pr create` / `pr merge` / `pr checkout` / `issue create` / `issue close` / `repo clone`、`docker run` / `exec` / `build` / `rm` / `rmi`、`sed` |
| `forbidden` | `git push --force`、`git push --force-with-lease`、`docker system prune` |

**Python 系のルールは無い。** Copilot は `uv.lock` があるときだけ hook が `pip` を止め、
Claude は `permissions.deny` の `Bash(pip:*)` で止まるが、**Codex は完全にノーガード**。

## 4. hook の I/O 差分

| | Claude Code | Copilot CLI | Codex CLI |
| --- | --- | --- | --- |
| 入力形式 | snake_case（`tool_name` / `tool_input`） | PascalCase イベント名なら snake_case、camelCase なら camelCase | 別系統 |
| ブロック方法 | exit 2 + stderr、または exit 0 + `hookSpecificOutput.permissionDecision` | exit 0 + stdout JSON の top-level `permissionDecision` | 要再調査 |
| exit 2 の意味 | イベント別（`PreToolUse` はブロック、`PostToolUse` は stderr を Claude に見せる） | `preToolUse` / `permissionRequest` は deny、他は警告 | 要再調査 |
| matcher | 英数字・`_`・`-`・空白・`,`・`\|` のみなら完全一致、他は非アンカー正規表現 | camelCase イベントなら runtime tool 名に anchored 正規表現、**PascalCase なら Claude tool 名で照合** | prefix_rule（コマンド先頭一致） |
| ハンドラ種別 | `command` / `http` / `mcp_tool` / `prompt` / `agent` | `command` / `http` / `prompt` | `command` ほか |

**両対応の最小公倍数は「stdout に JSON + exit 0」。** `home/dot_claude/hooks/lib/agent_compat.py`
がこの前提で書かれている。

**Copilot の PascalCase matcher の罠**: `PreToolUse` を PascalCase で書くと Claude 形式の
matcher セマンティクスになり、照合対象が `Bash` / `Read` / `Write` / `Edit` / `Grep` などの
Claude tool 名に変わる。`^bash$` は `Bash` にマッチしない。両対応させるなら
`Bash|bash` のように列挙する（`|` 区切りはリテラル一致として扱われる）。

## 5. 既知の抜け道（指示でしか塞げないもの）

`home/dot_claude/hooks/executable_check_bash.py` と
`home/dot_config/agents/critical_deny.py` の実装を読んだ結果:

| 抜け道 | 原因 | 影響範囲 |
| --- | --- | --- |
| `cd foo && pip install x` | `check_pip_redirect` が `re.match(r"\s*pip\b", cmd)` で生文字列の先頭にアンカー。`pip` は `critical_deny` に無いので normalize でも救済されない | Claude / Copilot |
| `python3 -m pip install x` | `\bpython\b` が `python3` に対して単語境界を作らない | Claude / Copilot |
| `pip3 install x` | 同上（`pip\b` が `pip3` にマッチしない） | Claude / Copilot |
| `bash -c "git push"` | `critical_deny.py` の `_split_compound` がクォート内を分割しないため、`shlex.split` 後の先頭トークンが `bash` になる | Claude / Copilot |
| `cd foo && X` / `git -C foo X` で permission deny を回避 | Claude CLI の既知バグ。`critical_deny` の 5 項目のみ normalize で救済 | Claude |
| `SENSITIVE_PATH_PATTERNS` の誤検知 | `['\"/\s]token` のような緩い部分一致。`grep -rn "api_key" src/` や `.env.example` も止まる | Claude / Copilot |

→ 個人用指示の「**拒否条件を満たす別手段に切り替える。条件自体を回避する迂回（コマンドの
分割・偽装、作業ディレクトリの付け替え）はしない**」は、この層を埋めるために存在する。
ハーネス既定の「ブロックされたら別アプローチを検討する」とは意図的に差分がある。

## 6. その他の差分（指示設計に影響するもの）

| 項目 | Claude Code | Copilot CLI | Codex CLI |
| --- | --- | --- | --- |
| 応答言語の設定 | `settings.json` の `language`（例 `"japanese"`） | 設定キーなし → 指示ファイルで指定 | `personality` は文体のみ。言語は指示ファイル |
| 自動メモリ | ✅ auto memory（Claude が自分で学習を書く） | `/chronicle` によるセッション履歴 | Memories（experimental、既定 off） |
| 組み込みサブエージェント | `general-purpose` / `Explore` / `Plan` ほか | `explore` / `task` / `general-purpose` / `research` / `code-review` / `security-review` / `rubber-duck` | `multi_agent`（既定 on） |
| skill | `~/.claude/skills/` | `~/.copilot/skills/`（本環境は `.claude/skills` への symlink）、`.claude/skills/` も公式サポート | `~/.codex/skills/` |
| プランモード | `plan` permission mode | `/plan`、Shift+Tab | `/plan` |
| Web 取得の既定 | `WebFetch` + ドメイン許可 | `allowedUrls` / `deniedUrls` | `web_search` 既定 `"cached"`（本環境は `"live"`） |

## 7. 現在の個人用指示（2026-08-08 版）

3 ファイルとも同じ 4 セクション構成。差分は以下だけ。

| セクション | 共通 | 差分 |
| --- | --- | --- |
| 応答 | 説明は日本語。成果物は対象外 | なし |
| 環境の前提 | 依存管理ツール未定のリポジトリでは `uv` / `uvx` | なし |
| 停止と報告 | 拒否条件を満たす別手段に切り替える。迂回はしない | Claude：「hook や permission」＋`cd` / `git -C` の付け替えを明示。Copilot：「hook や承認プロンプト」。Codex：「rules や承認プロンプト」＋`--no-verify` を明示 |
| 検証 | 定義されたテスト / lint / ビルドを探して実行し出力を示す。未実行の結果を推測しない | Codex のみ「サンドボックスで実行できない場合」を追加 |

各ファイル: [`home/dot_claude/CLAUDE.md`](../../home/dot_claude/CLAUDE.md) /
[`home/dot_copilot/copilot-instructions.md`](../../home/dot_copilot/copilot-instructions.md) /
[`home/dot_codex/AGENTS.md`](../../home/dot_codex/AGENTS.md)

## 8. 指示ファイル設計のベストプラクティス（出典付き）

| 原則 | 出典 |
| --- | --- |
| 短く高密度に。長いと個々の指示が埋もれて無視される。目安 200 行未満 | Claude Code memory / best-practices |
| 「この行を消したらモデルが間違えるか?」で取捨選択する | Claude Code best-practices |
| 標準の linter / formatter が既に強制することは書かない | VS Code custom instructions |
| 理由を添えるとエッジケースの判断精度が上がる | VS Code custom instructions |
| 仮説的な失敗にルールを足さない（hypothetical-rule inflation） | awesome-copilot `instructions.instructions.md` |
| 機械的に強制したいものは指示ではなく hook にする | Claude Code memory |
| 矛盾する指示があるとモデルが恣意的に選ぶ | Claude Code memory |
| 曖昧語（should / might / 適切に）を避け、検証可能に書く | awesome-copilot / Claude Code memory |

## 再確認すべき情報源

次に本書を更新するときは、この順で確認する。上ほど変化が速い。

### バージョン確認

```bash
copilot --version && claude --version && codex --version
```

### 一次ソース

| 優先 | 対象 | URL |
| --- | --- | --- |
| ★★★ | Copilot CLI 設定ディレクトリ / settings.json 全キー | <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference> |
| ★★★ | Copilot hooks（イベント・matcher・I/O） | <https://docs.github.com/en/copilot/reference/hooks-reference> |
| ★★★ | Claude Code hooks（イベント一覧が特に流動的） | <https://code.claude.com/docs/en/hooks> |
| ★★★ | Claude Code settings / permissions | <https://code.claude.com/docs/en/settings> |
| ★★★ | Codex config.toml（approval_policy / sandbox_mode / features） | <https://learn.chatgpt.com/docs/config-file/config-basic> |
| ★★☆ | Codex rules（Starlark） | <https://learn.chatgpt.com/docs/agent-configuration/rules> |
| ★★☆ | Codex AGENTS.md の探索順 | <https://learn.chatgpt.com/docs/agent-configuration/agents-md> |
| ★★☆ | Copilot CLI コマンド / スラッシュコマンド / 組み込みエージェント | <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference> |
| ★★☆ | Claude Code memory（CLAUDE.md の配置と書き方） | <https://code.claude.com/docs/en/memory> |
| ★☆☆ | Claude Code best practices | <https://code.claude.com/docs/en/best-practices> |
| ★☆☆ | Copilot カスタマイズ機能の全体像 | <https://docs.github.com/en/copilot/reference/customization-cheat-sheet> |
| ★☆☆ | VS Code のカスタム指示（書き方の指針） | <https://code.visualstudio.com/docs/copilot/customization/custom-instructions> |
| ★☆☆ | awesome-copilot（指示ファイルの書き方そのものの指針） | <https://github.com/github/awesome-copilot/blob/main/instructions/instructions.instructions.md> |
| ★☆☆ | AGENTS.md 標準 | <https://agents.md/> |
| ★☆☆ | Codex サブエージェント | <https://learn.chatgpt.com/docs/agent-configuration/subagents> |

Claude Code と Codex は LLM 向けの索引を公開しているので、全体差分を取るならこちらが速い。

- <https://code.claude.com/docs/llms.txt>
- <https://learn.chatgpt.com/llms.txt>（各ページは URL 末尾に `.md` を付けると Markdown 版）

### 次回に特に確認すべき差分ポイント

1. **Copilot CLI に permission deny が追加されたか**（追加されれば `common.toml` の
   `bash.deny` を Copilot にも反映できる）
2. **Claude Code の permission bypass バグが修正されたか**（修正されれば「停止と報告」の
   `cd` / `git -C` の明示を削れる）
3. **Codex の `sandbox_mode` 既定と本環境設定**（read-only のままか）
4. **Copilot の PascalCase matcher セマンティクス**（Claude tool 名照合が続くか）
5. **各ハーネスの既定システムプロンプトの範囲**（指示ファイルから削れる項目が増えるか）
6. Claude Code の hook イベント追加（`InstructionsLoaded` のような監査用途で使えるもの）
