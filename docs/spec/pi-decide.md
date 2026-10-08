# 判定 API（`decide`）

pi のハーネスが、ツールの呼び出しを実行してよいかを問い合わせる判定器。CLI に依存せず、
**どの入力にも allow / ask / deny と理由を返す**。判定の中身は Claude Code / Copilot CLI の
hook（`check_bash.py` / `check_file_read.py`）と同じ `bashrules` と `command_policy.py` を使う。
hook の出力は変えない（`check_bash.py` はこの判定器を使わない）。

移行の計画と経緯は [CHG-0020](../change/0020-pi-migration.md)。呼び出し側は [pi のハーネス](pi-harness.md)。

## 置き場

| 実体 | 配置先 | 役割 |
| --- | --- | --- |
| `home/dot_claude/hooks/executable_decide.py` | `~/.claude/hooks/decide.py` | CLI。stdin の JSON を 1 つ読み、stdout に応答を 1 つ書く |
| `home/dot_claude/hooks/lib/decide.py` | `~/.claude/hooks/lib/decide.py` | `decide(request)` の本体 |
| `home/dot_config/agents/common.toml.tmpl` の `[pi]` | `~/.config/agents/common.toml` | 役割（`[pi.profiles]`）と、pi が正本の共有の節（[pi と共有する節](agent-config-generation.md#pi-と共有する節)） |

`~/.claude/hooks/` に置くのは、判定の中身（`bashrules`）がそこにあるため。`AGENTS_CONFIG_DIR` で
`command_policy.py` と `common.toml` の置き場を差し替えられる（hook と同じ）。

## 入力と応答

```text
request:  { tool, input, cwd, role, bypass?, boundary? }
response: { decision: allow | ask | deny, reason, source: rule | check | default | error, ... }
```

| キー | 中身 |
| --- | --- |
| `tool` | `bash` / `read` / `edit` / `write` / `grep` / `find` / `ls`。ハーネスがツールを別名で登録していても、元の名前で渡す。ほかの名前（MCP など）は役割の `tools` に無いので deny |
| `input` | ツールの引数。`bash` は `command`、ファイルのツールは `path`（`grep` / `find` / `ls` は省略すると `.`） |
| `cwd` | 作業ディレクトリの絶対パス。相対パスの解決と「作業ツリーの中か」の判定に使う |
| `role` | `[pi.profiles]` の名前（`implementer` / `reader`） |
| `bypass` | 真なら ask を allow にする（deny は変えない） |
| `boundary` | 境界（Fence）の内側か。**受け取るだけで、まだ判定に使っていない**（CHG-0020 の段 4） |

`source` は判定がどこで決まったか。

| `source` | 意味 |
| --- | --- |
| `rule` | `[bash]` / `[file]` / `[pi]` の一覧、役割の `tools`、作業ツリーの内外 |
| `check` | `bashrules` の意味解析（`curl \| sh`・秘密の環境変数の表示など） |
| `default` | どの規則にも当たらず、役割の既定（`default`）で決まった |
| `error` | 入力の不備・設定の欠落・判定中の例外。必ず deny |

Claude Code / Copilot CLI の hook は「何も返さない」と「CLI 自身の判定に任せる」の意味になる。
判定器では、それに当たるものが `source: default` で、役割の既定が decision に入る。
**呼び出し側は、空の応答を allow と読まない。** CLI はどんな異常でも形の正しい deny を返し、
呼び出し側は形の正しい応答以外（空・不正な JSON・異常終了・タイムアウト）を deny と読む。

## 評価の順番

順番はコードに固定してある（設定の並びに意味は無い）。

1. **共通の禁止**。どの役割・bypass でも外れない
   - `bash`: `check_bash.py` の deny 側と同じ検査（`[bash] deny` の照合と意味解析。`cd` を挟んだ形も見る）
   - ファイル: `[file] read_deny_globs`（`read` / `grep` / `find` / `ls`）と `write_deny_globs`（`edit` / `write`）。
     例外（`[[file.deny_exceptions]]`）は対の deny にだけ効く。パスは渡された形・`cwd` で解いた絶対パス・
     symlink を解いた実体の 3 つで照合する。ディレクトリを渡す `grep` / `find` / `ls` は、中のファイルの形でも照合する
2. **役割のツール**。役割の `tools` に無いツールは deny
3. **役割の確認と許可**
   - `bash`: `check_bash.py` の ask 側（`[bash] ask` と意味解析）。当たらず、全部の区切りが `[pi.shell] allow` に当たれば allow。
     `>` `<` `` ` `` `$(` `--output` を含む形は allow にしない。`[pi.skill_scripts]` の宣言どおりの形も allow
   - 読み取り: `[file] read_ask_globs` は ask。作業ツリーの中と `[pi.external_read]` の中は allow。それ以外の外は ask
   - 書き込み: `[file] write_ask_globs` は ask。作業ツリーの外は ask。中は allow
4. **既定**。役割の `default`（実装役は ask、読み取り役は deny）
5. **bypass**。3・4 の ask だけを allow にする

`rm` の承認の免除（`ask_hook_owned`）は、hook と同じく `[bash] ask` から外れる。判定器ではその先の
既定（実装役は ask）に落ちるので、作業ツリーの中の `rm` も確認になる（今の OpenCode と同じ）。

## 役割

```toml
[pi.profiles.implementer]
tools = ["bash", "read", "edit", "write", "grep", "find", "ls"]
default = "ask"

[pi.profiles.reader]
tools = ["read", "grep", "find", "ls"]
default = "deny"
```

`tools` が文字列の配列でない・`default` が allow / ask / deny でない・名前が無いときは、`source: error` の deny。

## 試験

`test/agents/test_decide.py`。

- 契約: 不正な入力と、CLI の空・不正な入力が、形の正しい deny になる
- 評価順: bash・ファイル・役割・bypass・skill のスクリプトの代表例
- **等価**: `test_check_bash_*.py` の `parametrize("command", …)` に並ぶ全コマンド（1000 件余り）を
  `check_bash.py` と判定器の両方に通し、hook の deny / ask と判定器の decision が一致し、hook が何も
  返さないものを判定器が規則や意味解析で止めないことを確かめる

## 既知の制約

- `[pi.external_read]` だけを開けている。OpenCode が開けている `[opencode.sandbox] work_read`（`~/src` など）は
  まだ読まないので、隣のリポジトリを読むと確認になる
- `[[opencode.shell.guide]]`（誘導）はまだ判定に入れていない（CHG-0020 の「未解決点」）
- `boundary` を判定に使っていない
- 1 回の判定ごとに Python を起動する（hook と同じ）。呼び出しの多いハーネスで遅さが問題になるかは未計測
