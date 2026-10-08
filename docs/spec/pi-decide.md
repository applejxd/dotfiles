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
| `tool` | `bash` / `read` / `edit` / `write` / `grep` / `find` / `ls` / `task`（子エージェントの起動）と MCP のツール（`mcp__…`）。ハーネスがツールを別名で登録していても、元の名前で渡す。役割の `tools` に無い名前は deny |
| `input` | ツールの引数。`bash` は `command`、ファイルのツールは `path`（`grep` / `find` / `ls` は省略すると `.`） |
| `cwd` | 作業ディレクトリの絶対パス。相対パスの解決と「作業ツリーの中か」の判定に使う |
| `role` | `[pi.profiles]` の名前（「役割」の表） |
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
2. **役割のツール**。役割の `tools` に無いツールは deny（末尾が `*` の項目は前方一致）
3. **役割の確認と許可**
   - `bash`: [誘導](#誘導)に当たれば、案内を理由にした deny（bypass でも外れない）。
     次に役割の `shell_deny` に当たれば deny（bypass でも外れない）。次に `check_bash.py` の ask 側（`[bash] ask` と意味解析）。
     当たらず、全部の区切りが `[pi.shell] allow`（役割に `shell_allow` があればそちら）に当たれば allow。
     `>` `<` `` ` `` `$(` `--output` を含む形は allow にしない。`[pi.skill_scripts]` の宣言どおりの形も allow
   - 読み取り: `[file] read_ask_globs` は ask。作業ツリーの中と `[pi.external_read]` の中は allow。それ以外の外は ask
   - 書き込み: `[file] write_ask_globs` は ask。作業ツリーの外は ask。中は allow
   - `task`: allow（子は同じハーネスと判定器で、子の役割で判定される）
4. **既定**。役割の `default`（実装役は ask、読み取り役は deny）
5. **bypass**。3・4 の ask だけを allow にする

`rm` の承認の免除（`ask_hook_owned`）は、hook と同じく `[bash] ask` から外れる。判定器ではその先の
既定（実装役は ask）に落ちるので、作業ツリーの中の `rm` も確認になる（今の OpenCode と同じ）。

## 誘導

`[[pi.guide]]` に当たる bash のコマンドは、より適したツールへの案内を理由にして deny する（応答の `guide` に id）。
今は 4 件で、すべて読み書きを pi のツールへ寄せるもの。

| id | 止める形 | 案内 |
| --- | --- | --- |
| `read-cat-head-tail` | `cat` / `head` / `tail` での読み取り（パイプ・リダイレクト・`-c` / `-f` は除く） | read ツール |
| `read-sed-n` | `sed -n` での読み取り | read ツール |
| `write-cat-tee-heredoc` | `cat >` / `tee` とヒアドキュメントでのファイル作成 | write ツール |
| `write-heredoc-script` | ヒアドキュメントでスクリプトを渡す形 | write ツールで書いてから実行 |

- OpenCode の guide plugin も同じ `[[pi.guide]]` を使う。`[[opencode.shell.guide]]` の `pi = "<id>"` が、
  並びのどこに差し込むかを決める（[pi と共有する節](agent-config-generation.md#pi-と共有する節)）
- 正規表現は Python（判定器）と JavaScript（guide plugin）の両方で同じ意味になるものだけを書く。
  `test_pi_shared.py` が代表のコマンドで両方の結果を突き合わせる
- OpenCode の誘導のうち、次は pi には入れていない（判定器のほかの規則で足りる）

| OpenCode の誘導 | pi で入れない理由 |
| --- | --- |
| `cd` を `workdir` へ | pi の bash に `workdir` 引数が無い。判定器は `cd … &&` を外して照合する |
| allow したコマンドの書き込み形（リダイレクト）・`git log --output` | 判定器は `>` や `--output` を含む形を allow にしない（既定の確認になる） |
| `git -c … commit` | 判定器は `git` の前置きのオプションを外して `[bash] ask` の `git commit` に当てる |
| `pip` を `uv` へ | 意味解析の `check_pip_redirect` が案内付きで止める |
| `rm` の `.git` / `~` / `/` / 作業ディレクトリ全体、`find` の `-delete` / `-exec rm` | 意味解析の `check_rm_root_guard` / `check_find_root_guard` が止める |

## 役割

| 役割 | `tools` | `default` | ほか | 使うもの |
| --- | --- | --- | --- | --- |
| `implementer` | 7 つのツール・`task`・`mcp__*` | ask | — | 親（主エージェント） |
| `reader` | read・grep・find・ls | deny | — | 子の `explore` / `review` |
| `committer` | bash・read・grep・find・ls | deny | `shell_allow` に `git status` / `git diff` / `git log` など。`shell_deny` に git の状態を変える操作 | 子の `commit` |
| `worker` | 7 つのツール | ask | `shell_deny` に git の状態を変える操作 | 子の `worker` |

`git status` / `git diff` は `.git/config` 経由でコマンドを起動しうるので、全体の `[pi.shell] allow` には載せず、
`committer` の `shell_allow` だけに置く（今の OpenCode の `commit` と同じ）。

`tools` が文字列の配列でない・`default` が allow / ask / deny でない・`shell_allow` / `shell_deny` が文字列の
配列でない・名前が無いときは、`source: error` の deny。

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
- `boundary` を判定に使っていない
- 1 回の判定ごとに Python を起動する（hook と同じ）。呼び出しの多いハーネスで遅さが問題になるかは未計測
