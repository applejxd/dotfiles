# AI CLI 統合 permission / hook 管理

Claude Code / Copilot CLI の permission (allow/deny/ask) と hook 登録を
**単一ソース** で管理し、`chezmoi apply` で両 CLI の設定ファイルへ自動展開する仕組み。

## ファイル構成

```text
home/dot_config/agents/
    common.toml                              単一ソース (permissions + hooks)
    command_policy.py                        hook が import する normalizer / matcher
                                             (deny / ask リストの loader も兼ねる)
scripts/agents/
    generate.py                              modify_ / .tmpl から呼ばれる変換器
home/dot_claude/
    modify_settings.json.py.tmpl             ~/.claude/settings.json を更新
home/dot_claude/hooks/
    executable_check_bash.py                 deny / ask を判定 (fail-closed)
    executable_redirect-tmp.py               /tmp 利用を ./.tmp へ誘導
    executable_markdownlint.sh               Markdown の lint
    executable_format-file.sh                拡張子別のフォーマッタ実行
    executable_update-adr-on-stop.py         ターン終了時に ADR 更新を促す
home/dot_copilot/
    hooks/from-claude.json.tmpl              ~/.copilot/hooks/from-claude.json を生成
    modify_private_settings.json.py.tmpl     ~/.copilot/settings.json を更新
    modify_private_permissions-config.json.py.tmpl
test/agents/
    test_command_policy.py                   shell normalize / match の unit test
    test_check_bash_decision.py              deny/ask 判定と rm root guard の test
    test_generate_hooks.py                   hook 生成の unit test
```

`modify_private_*` のように `private_` を付けることで mode 600 を保持し、
`~/.copilot/settings.json` に含まれる `gho_xxx` トークンを保護している。

## 2 層構成

| 層 | 仕組み | 効く CLI |
| --- | --- | --- |
| 1. permission リスト | `~/.claude/settings.json` の `permissions` (generate.py が生成) | **Claude のみ** |
| 2. hook | `check_bash.py` が同じリストを読んで deny / ask を返す | **Claude + Copilot** |

人が書くのは `common.toml` の `[bash] allow / ask / deny` の **3 つだけ**。
そこから permission リストが生成され、hook も同じリストを読む。
ルールを 2 箇所に書く必要はない。

**なぜ 2 層に配るのか**: hook は設定の読み込みに失敗しうる
(`~/.config/agents/__pycache__` 由来の import 失敗など、トラブルシュートに実例あり)。
permission リストは CLI 本体が評価するので、hook が落ちても Claude 側の deny は残る。
hook 自体も設定を読めないときは **fail-closed** で deny する。

Copilot CLI の `permissions-config.json` は deny / ask を表現できない
(公式仕様) ため、Copilot 側の強制は hook が全面的に担う。

### 照合規則

パターンは素のトークン列で書く (例: `git push`)。
hook は normalize 後のセグメント先頭トークンで一致を見る。
normalize は「実際に走るコマンドを変えずに先頭トークンだけを変える飾り」を
すべて剥がすので、下記はいずれも `git push` として捕捉される:

```bash
cd /elsewhere && git push      # 作業ディレクトリの付け替え
git -C /elsewhere push         # 同上 (-C オプション)
bash -c "git push"             # シェル経由 (中身を再帰的に評価)
eval 'git push'                # 文字列のコード実行
env FOO=1 git push             # 環境変数プレフィクス
timeout 5 git push             # ラッパーコマンド
/usr/bin/git push              # 絶対パス
(git push)  /  { git push; }   # グループ化
```

加えて `curl x | sh` のようなパイプ実行は `check_pipe_to_shell` が deny する
(`bash script.sh` のようにスクリプトを渡すだけの呼び出しは対象外)。

コマンド名の照合だけでは捕まらない形は、専用のチェックが個別に見る。

| チェック | 対象 |
| --- | --- |
| `check_reverse_shell` | `/dev/tcp` へのリダイレクト、`nc -e` / `-l`、`socat EXEC:` |
| `check_shell_startup_write` | `~/.bashrc` / `~/.zshrc` / `authorized_keys` への書き込み |
| `check_privilege_escalation` | `chmod u+s`、`usermod` / `passwd`、`/etc/sudoers` |
| `check_encoded_command` | `base64 -d` / `xxd -r` の出力をシェルへ渡す形 |
| `check_guard_tampering` | hook・permission 設定の改変、`PYTHONPATH` の差し替え |
| `check_git_config_write` | `alias.*` / `core.hooksPath` / `credential.*` などの書き込み |
| `check_block_device_write` | `dd of=/dev/sda` |

`cd <dir> && <cmd> <relpath>` のように作業ディレクトリを移してから相対パスで触る形は、
パスを結合した変種を作ってパス系のチェックだけ再適用する。

heredoc の本文は、実行される形 (`bash <<'EOF'` / `python3 - <<'PY'`) のときだけ
検査する。`cat <<'EOF' > note.md` のようにファイルへ書くだけの本文は
検査対象から外すので、ドキュメントにコマンド例を書いても誤検知しない。

評価順は **deny → ask → allow**。より具体的なパターンを deny に置けば、
一般形を ask にできる。

```toml
ask  = ["git reset"]          # index を戻すだけなら承認で実行
deny = ["git reset --hard"]   # 作業ツリーを壊す形だけ拒否
```

### deny と ask の使い分け

| 分類 | 例 | 置き場所 |
| --- | --- | --- |
| 承認の余地なく禁止 | `sudo`, `git push`, `git reset --hard`, `git rebase`, `gh pr merge` | `deny` |
| 外部への漏洩・システム変更 | `ssh`, `telnet`, `npm install -g`, DB クライアント | `deny` |
| 規約違反 | `pip` / `pip3` (uv / uvx を使う) | `deny` + hook の `check_pip_redirect` |
| 壊滅的な削除 | `rm -rf /`, `rm -rf ~`, `rm -rf /etc` | `check_rm_root_guard` (hard-deny) |
| 提案 → 承認 → 実行 | `rm`, `git clean`, `git commit`, `docker rm`, `gh pr create` | `ask` |
| **LLM 判定へ委譲** | `npx`, `uvx`, `pipx run`, `python -c`, `npm install`, `mv` | **未掲載** |
| 用途で危険度が変わる | `nc` (疎通確認は `ask`、`-e` / `-l` は hook が deny) | `ask` + hook |
| サブコマンドで分ける | `systemctl status` は許可、`systemctl enable` は `deny` | 用途ごとに列挙 |
| 自動承認 | `git status`, `grep -n`, `uv sync` | `allow` |
| GitHub 読み取り | `gh pr list`, `gh issue view`, `gh search code`, REST GET | **未掲載** |

### 「未掲載」という 4 つ目の選択肢

両 CLI には LLM が安全性を判定するモードがある。

| | Claude Code | Copilot CLI |
| --- | --- | --- |
| 手動 | `default`（別名 `manual`） | `manual` |
| **LLM 判定** | **`auto`**（classifier という別モデルが審査） | **`assisted`**（LLM safety check） |
| 全許可 | `bypassPermissions` | `allow-all` |

**`ask` に載せるとこのモードに到達しない。**
Claude Code は「explicit ask rule に一致するツールは、`bypassPermissions` を含む
どのモードでも自動承認しない」と明記している。hook が返す `ask` も同様に
プロンプトを最低保証する。

したがって「LLM の判断に任せたい」コマンドは、`allow` ではなく
**どのリストにも載せない**のが正しい。`allow` に入れると手動モードでも
無条件に通ってしまい、かえって緩くなる。

| 状態 | Claude auto | Copilot assisted |
| --- | --- | --- |
| `allow` | 無条件実行 | 無条件実行 |
| `ask` | プロンプト | プロンプト |
| **未掲載** | **classifier が判断** | **safety check が判断** |

未掲載にしても hook の個別 deny チェックは効く。
`uvx ruff format .` は通るが `uvx pip install x` は deny、
`python -c 'print(1)'` は通るが `python -c "os.system('git push')"` は deny になる。

`gh` も全て allow から外している。Copilot の `permissions-config.json` は
`gh pr list` のような allow を先頭トークン `gh` に丸めるため、1件でも置くと
未列挙の mutation まで assisted を迂回してしまう。読み取り系は未掲載、
既知の mutation は ask / deny、`gh api` は hook の意味解析に委ねる。

| `gh` の分類 | 例 | 結果 |
| --- | --- | --- |
| 読み取り CLI | `issue/pr/release/repo` の list/view、`gh search`、`gh status` | 未掲載 |
| REST API 読み取り | 既定 GET、明示 GET / HEAD | 未掲載 |
| GraphQL 読み取り | inline の `query` / `{ ... }` | 未掲載 |
| API mutation | POST / PUT / PATCH / DELETE、暗黙 POST、GraphQL mutation | ask |
| API 判定不能 | query 未指定、file / stdin query、動的 method | ask |
| 秘密情報 | `auth token`, `auth status --show-token`, sensitive file payload | deny |

`gh api -f/-F` は通常は暗黙に POST へ切り替わる。ただし
`--method GET` を明示した場合は query parameter として扱うため未掲載にする。
GraphQL は読み取り query でも HTTP POST を使うので、method ではなく operation
本文を検査する。静的に安全性を確認できない場合は fail-open にせず ask へ倒す。

`git commit` は commit skill と permission / hook で確認が重複しないよう、確認点を
1つに保つ。スキルは `git add -- <files> && git commit ...` を1回の Bash 呼び出しで
実行するため、compound command を解析する hook がステージング前に全体を止める。
Claude Code の native permission は compound command の後半を再評価しないため、
この形式では hook が強制を担う。

ただし **Copilot CLI 1.0.53 以降は hook の `ask` が機能しない**。TUI が permission
dialog を数十 ms 表示しただけで自動承認する既知バグ
([github/copilot-cli#3590](https://github.com/github/copilot-cli/issues/3590), OPEN)
があるため。実測では hook 由来の permission 90 件のうち 79 件が
`outcome=auto_approved` / `source=assisted_approval` で中央値 58ms (min 6ms /
max 99ms) に解決され、人間が応答した 11 件は中央値 23.5 秒だった。
`deny` はこのバグの影響を受けず正常にブロックする。

このため `git commit` の確認点は CLI ごとに分ける。skill は
`echo "${COPILOT_CLI:-}"` で環境を判別し、コマンドを出す前に分岐する:

| CLI | 確認点 | 機械的強制 |
| --- | --- | --- |
| Claude Code | hook / permission の ask | あり |
| Copilot CLI | commit skill の明示確認 | なし (バグ回避のため指示ベース) |
| Codex CLI | `git.rules` の prompt | あり |

Copilot 側のバグが修正されたら、skill の明示確認を削除して hook 一本へ戻す。

`curl` / `wget` も allow には置かず、読み取りと通常ダウンロードを未掲載にする。
HTTP method と payload option は hook が transfer ごとに解析するため、
`curl --next` で複数 request を連結した場合も、1件でも mutation があれば ask になる。

| `curl` / `wget` の分類 | 例 | 結果 |
| --- | --- | --- |
| GET / HEAD | `curl URL`, `curl -I URL`, `wget URL`, `wget --spider URL` | 未掲載 |
| query parameter | `curl -G -d q=test URL` | 未掲載 |
| 通常ダウンロード | `curl -o file URL`, `wget -O file URL` | 未掲載 |
| HTTP mutation | `curl -X POST`, `curl -d`, `wget --method=PUT` | ask |
| upload / body | `curl -T file`, `curl -F file=@x`, `wget --post-file=x` | ask |
| 判定不能 | config file、動的 method、option 値欠損 | ask |
| 取得結果の直接実行 | `curl URL \| sh`, `wget -qO- URL \| bash` | deny |
| 秘密情報の送信 | sensitive file payload、`$TOKEN` の header/body 展開 | deny |
| 永続化先の上書き | `curl -o ~/.bashrc`, `wget -O ~/.ssh/authorized_keys` | deny |

明示 GET / HEAD でも request body を送る指定があれば ask とする。
例外は `curl -G` で、data option を URL query parameter に変換するため未掲載になる。
通常ファイルへの保存はローカル書き込みだが、auto / assisted の安全性判定へ委譲する。

モードは `common.toml` から両 CLI へ生成している。

```toml
[claude]
default_permission_mode = "auto"

[copilot]
default_permission_mode = "assisted"
experimental = true          # assisted は experimental な auto-approval に依存
```

Copilot の設定キーの権威ある一覧は Web ドキュメントではなく
`copilot help config` にある。

判断基準:

- **取り返しがつくか**: lockfile や git、再 pull で戻せるなら `ask` で十分
- **外部に出るか**: リモートや外部ホストへ情報が出るものは `deny`
  (`git push` / `gh pr merge` / `ssh` / `telnet`)
- **摩擦があるか**: そもそも使わないコマンドを緩めても利益が無い。
  DB クライアントは触る機会が無いので `deny` のまま置いている

### `allow` の粒度に注意

Copilot CLI へは `allow` の **先頭トークン (コマンド名)** だけが渡る。
`git diff` と書くと Copilot では `git` 全体が承認される。
ただし ask / deny は hook が強制するので実害は無い。

作業ディレクトリを付け替える `-C` 形式は `allow` に入れない。
permission を回避する既知のバイパス形式であり、対策を用意している意図と矛盾する。

`allow` の先頭トークンと衝突する `ask` / `deny` エントリ（例: `git diff` を
allow に置くと Copilot では `git push` まで承認される）は、
`test_shadowed_entries_are_enforced_by_hook` が hook 側で確実に止まることを
機械的に検査する。ここが落ちたら Copilot ではそのコマンドが無条件に通る。

`gh` は衝突を hook で補うのではなく、allow から完全に外して
`test_copilot_permissions_do_not_broadly_allow_gh` で再発を防ぐ。

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

### credential 系 glob は部分一致にしない

`[file.read_deny_globs]` / `[file.write_deny_globs]` に `**/*key*` のような
部分一致 glob を書くと、正当なファイルまで巻き込む。実例:

```text
home/AppData/Roaming/Keyhac/extension/fakeymacs/keyhac.bat
home/AppData/Roaming/Keyhac/.../key_bindings.org
home/AppData/Roaming/Keyhac/.../keymap_layer.drawio
```

いずれも chezmoi 管理下でエージェントが編集する必要がある。
一般的にも `tokenizer.py` / `keyboard.ts` / `monkey.md` などを誤検知する。

→ `**/*.key` / `**/*_key` / `**/id_*` / `**/*.pem` / `**/.ssh/**` のように
**拡張子・接尾辞・既知のファイル名で具体的に**書く。
`test_check_bash_decision.py` が「正当なファイルが deny されないこと」と
「秘密ファイルが確実に deny されること」の両方を検査している。

## hooks の単一ソース化

`[[hooks]]` に 1 度書けば、両 CLI の設定ファイルへ展開される。

| 生成先 | 生成方法 | 使うフィールド |
| --- | --- | --- |
| `~/.claude/settings.json` の `hooks` | `modify_settings.json.py.tmpl` → `--target claude-settings` | `claude_event` / `claude_matcher` / `timeout_sec` |
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
- `[bash] deny` は hook が hard-block し、Claude では permission でも拒否される
- `[bash] ask` は hook が `ask` を返す。承認すればそのまま実行される
- `[bash] allow` の先頭トークンだけが Copilot の承認済みコマンド名になる
  (Copilot は deny / ask を表現できないため、強制は hook が担う)
- `[file.write_ask_globs]` / `[file.write_deny_globs]` は Claude の
  **`Edit(path)`** rule として展開される。Claude Code v2.1.210 で
  `Write(path)` / `NotebookEdit(path)` / `Glob(path)` の permission rule は
  deprecated になり (起動時警告)、代替として `Edit(path)` / `Read(path)` が
  案内されている
  ([CHANGELOG v2.1.210](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md))。
  なお `Write` ツール自体は現役なので、hooks の `matcher` に書く `Write` は
  引き続き有効 (`MultiEdit` は v2.0 系で削除済みなので不要)

## Claude Code permission リストの既知バグ

下記は 2026-05 時点で open。hook 側の normalize で必ず防ぐべき理由。

| Issue | 概要 |
| --- | --- |
| [#59498](https://github.com/anthropics/claude-code/issues/59498) | `cd /elsewhere && git push` が `Bash(git push:*)` ask/deny を bypass |
| [#59006](https://github.com/anthropics/claude-code/issues/59006) | `git -C /path commit` が `Bash(git commit *)` deny を bypass |
| [#20085](https://github.com/anthropics/claude-code/issues/20085) | compound 命令 (`a && b`) が個別評価されない |
| [#52419](https://github.com/anthropics/claude-code/issues/52419) | VS Code 拡張の auto-attach が `.claudeignore` / deny を bypass |

`test/agents/test_command_policy.py` の `test_real_bug_*` ケースで、これらの
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
# -> 499 passed (normalize/match 37 + hook 生成 21 + deny/ask 判定 441)
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
| `~/.config/agents/command_policy.py` が読めない・壊れている | hook が fail-closed で全 bash を拒否する。`~/.config/agents/__pycache__/` を削除して `chezmoi apply` をやり直す |
| common.toml の編集が反映されない | `chezmoi diff` で差分を確認 → `chezmoi apply` |
