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
  `command_policy.py` の normalize は `cd` 剥がしと `-C` 展開でこれらを救済するが、
  hook は `[bash] deny` / `ask` の全項目を同じ normalize で照合する
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

**Python 系のルールは無い。** Copilot / Claude は hook の `check_pip_redirect` が
プロジェクト種別を問わず `pip` を hard-deny し（`permissions.deny` の `Bash(pip:*)`
とあわせて二重）、uv / uvx への代替案を返すが、**Codex は完全にノーガード**。

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
`home/dot_config/agents/command_policy.py` の実装を読み、
実際に payload を流して確認した結果:

| 抜け道 | 状態 |
| --- | --- |
| `cd foo && pip install x` | **修正済**: normalize 後のセグメント先頭トークンで判定 |
| `python3 -m pip install x` / `pip3 install x` / `uvx pip install x` | **修正済**: `python[0-9.]*` / `pip[0-9.]*` / ランナー経由で判定 |
| `bash -c "git push"` / `sh -c '...'` / `eval '...'` / `su -c` / `script -qc` | **修正済**: `-c` の引数を再帰的に normalize する |
| `env FOO=1 X` / `command X` / `nohup X` / `timeout 5 X` / `nice -n 5 X` / `xargs -I{} X` | **修正済**: ラッパーを剥がして後続を評価 |
| `chroot` / `watch` / `parallel` / `flock` / `strace` / `pkexec` / `run0` 等 | **修正済**: 同上 (オプション値とコマンド名を判別) |
| `/usr/bin/git push` | **修正済**: 先頭トークンを basename 化 |
| `GIT_DIR=/x git push` | **修正済**: 先頭の環境変数代入を除去 |
| `(git push)` / `{ git push; }` / `> /dev/null git push` / 改行区切り | **修正済**: 飾りを除去し、セグメント分割に改行と `&` を追加 |
| `git --no-pager push` / `git -P push` / `git -c a=b push` | **修正済**: サブコマンド前のグローバルオプションを除去 |
| `git send-pack` / `npm i -g` / `npm -g install` | **修正済**: サブコマンド別名とフラグ位置を正規形に寄せる |
| `$(echo git) push` / `` `echo git` push `` / `echo $( (git push) )` | **修正済**: コマンド置換を展開 (1 段のネストまで) |
| `f(){ git push; }; f` / `alias gp='git push'; gp` / `p=push; git $p` | **修正済**: 関数・alias 定義と同一コマンド列の変数代入を展開 |
| `bash <<< "git push"` / `bash <(echo git push)` / `bash -c $'git push'` | **修正済**: here-string・プロセス置換・ANSI-C quoting を展開 |
| `python3 -c "os.system('git push')"` / `perl -e` / `node -e` / `awk 'BEGIN{system(...)}'` | **修正済**: インラインコードを展開し、外部実行の形も検出 |
| `curl x \| sh` | **修正済**: `check_pipe_to_shell` が deny (`bash script.sh` は対象外) |
| `env \| grep -i key` / `printenv AWS_SECRET_ACCESS_KEY` / `true; env` | **修正済**: 全件出力に加えセンシティブな変数名も検出 |
| `tac .env` / `sort ~/.aws/credentials` / `jq .` / `git add .env` / `tar czf out.tgz ~/.ssh` | **修正済**: 読み取り系コマンドを拡充し、アーカイブと `git add` も検査 |
| `scp` / `rsync` / `gh gist create` / `gh secret list` / `git remote add` | **修正済**: 外部へ出す経路として deny |
| `find . -exec git push \;` / `screen -dm` / `tmux new-session -d` / `docker run IMAGE CMD` / `git submodule foreach` | **修正済**: 引数に埋まったコマンドを取り出して評価 |
| `cat /proc/self/environ` / `echo $GITHUB_TOKEN` / `history` / `cat ~/.bash_history` | **修正済**: プロセス環境・履歴・秘密の環境変数名を検出 |
| `rm ~/.claude/hooks/check_bash.py` / `git config core.hooksPath /dev/null` / `chmod -x` | **修正済**: `check_guard_tampering` が hook と permission 設定の改変を deny |
| `rmdir /` / `find ~ -delete` / `rm -rf $PWD/../..` | **修正済**: root guard を rmdir/unlink と find の起点にも適用 |
| `mise exec -- git push` / `npm run x -- git push` / `cargo run --` / `uv run python -c` | **修正済**: ツールランナーの `--` と `run` 以降を評価 |
| `crontab` / `at` / `systemctl` による遅延実行 | **修正済**: deny リストに追加 |
| `git filter-branch` / `update-ref -d` / `reflog expire` / `checkout --` / `restore` / `stash clear` | **修正済**: 復旧できない git 操作を deny |
| `mkfs` / `dd of=/dev/sda` / `socat TCP-LISTEN` | **修正済**: デバイス破壊と待ち受けを deny |
| `> ~/.claude/settings.json` (リダイレクトによる上書き) | **修正済**: `check_guard_tampering` がリダイレクト先も見る |
| `cd foo && X` で permission deny を回避 | Claude CLI の既知バグだが、hook 側の normalize が `[bash] deny` / `ask` の全項目を救済する |
| シェル変数経由の間接的な組み立て (別コマンドで定義した変数、配列、`${x:0:3}` 等) | **未対応**。静的解析では追えない |
| エディタ・REPL 経由の間接実行 (`vim` の `:!` など) | **未対応** |
| ネスト 2 段以上のコマンド置換 | **未対応**。正規表現で追えるのは 1 段まで |
| 設定ファイル側で定義された名前の実行 (`pre-commit run <hook-id>` など) | **未対応**。実体はリポジトリの設定次第で静的に追えない |
| エンコードされたコマンド (`printf '\x67\x69\x74'`、base64 の復号結果) | **未対応**。復号結果は静的に追えない |

上記の「修正済」は `test/agents/test_check_bash_decision.py` と
`test_command_policy.py` に回帰テストがある (439 件)。日常的に使うコマンド
(`bash test/test.sh` / `timeout 900 chezmoi apply` / `grep -rn token .` /
`cp .env.example .env` / `git commit -m "fix token refresh"` /
`docker run --rm alpine echo hi` / `npm run build` / `mise exec -- shellcheck x.sh` /
`truncate -s 0 build.log` 等) が過剰検知されないことも併せて検査している。

### 検証の進め方

配備済み hook に payload を流す probe を角度を変えて 5 巡実施し、
各巡で見つかった素通りを塞いでから回帰テストに固定した。

| 巡 | 観点 | 発見 |
| --- | --- | --- |
| 1 | シェル経由・ラッパー・絶対パス | 23 中 14 件 |
| 2 | シェル構文・照合ロジック | 43 中 20 件 |
| 3 | 間接実行・別名・情報持ち出し | 167 中 54 件 |
| 4 | 引数に埋まったコマンド・秘密の露出・ガード改変 | 57 中 16 件 |
| 5 | ツールランナー・遅延実行・デバイス破壊 | 44 中 24 件 |

いずれの巡でも「正当なコマンドが過剰検知されないこと」を同時に測り、
両方が 0 件になるまで繰り返した。

→ 個人用指示の「**拒否条件を満たす別手段に切り替える。条件自体を回避する迂回（コマンドの
分割・偽装、作業ディレクトリの付け替え）はしない**」は、残る層を埋めるために存在する。
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
