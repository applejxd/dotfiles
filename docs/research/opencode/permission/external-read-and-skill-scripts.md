# 作業ツリーの外の読み取りとスキルのスクリプト

- **観測日**: 2026-09-30
- **対象バージョン**: opencode v2.0.14 / git 2.43.0 / uv 0.8.12 / Python 3.13.6
- **環境**: WSL2 Ubuntu / 基準コミット `37d26d3` に、この記録で決めた規則を加えた作業ツリー
- **一次情報**: <https://opencode.ai/v2/docs/permissions/>（`external_directory` は read / edit の
  前に確かめる、`~` は `external_directory` / `read` / `edit` でだけ展開し shell の resource では
  展開しない、後勝ち）

## 問い

通常起動の OpenCode で、作業ツリーの外を読むたびに確認が出る。特にスキルの中の
スクリプトの呼び出し（`uv run --no-project python ~/.claude/skills/sdd-docs/scripts/lint_docs.py …`）
で確認が出る。

1. どの確認が出ているのか（`shell` の `ask` か、`external_directory` の `ask` か、両方か）
2. よく使う場所の読み取りとスキルのスクリプトを確認なしにしたとき、秘密の deny・
   作業ツリーの外への edit・リダイレクトによる書き込みが止まり続けるか
3. 確認なしに通してよいスクリプトの条件は何か

## 方法・条件

- 置き場は `.tmp/opencode/extread/`。`gen.py` が作業ツリーの `generate.py` で通常版と
  隔離版（`ocs`）の `permissions` を組み、plugin を計装した guide plugin の複製だけにした
- 計装は `permission.evaluate` の `effect` を guide plugin の前後で記録し、`ask` を
  `deny` に変えて止める（`--auto` では `ask` も自動承認され `allow` と見分けられないため）。
  静的な `deny` では hook が呼ばれないので、`Permission denied: shell` の結果で判定した
- 実行は `env -u OPENCODE_CONFIG -u OPENCODE_CONFIG_CONTENT`、実行ごとに一時の
  `XDG_DATA_HOME` / `XDG_STATE_HOME` / `XDG_CACHE_HOME` / `TMPDIR`、実 DB を読み取り専用で
  複製した `OPENCODE_DB`（`permission` 表などは空にした）、一時の `OPENCODE_CONFIG_DIR` で
  `opencode run --standalone --auto --model github-copilot/claude-haiku-4.5`。
  `session.synthetic` は使っていない
- 作業ツリーは `.tmp/opencode/extread/ws`（独立した git リポジトリ）。作業ツリーの外の
  試料は `.tmp/opencode/extread/ext/`（`~/.local/share/chezmoi` の中）と `~/src/marimo`
- 30 個の呼び出し（read / grep / glob / write / shell）を 1 つずつ実行させた。一覧は
  下の表の左の列

**`TMPDIR` を実行ごとに分ける必要があった。** 最初の実行では `TMPDIR` がこのリポジトリの
`.tmp` を指しており、その配下の `ext/` への read と write が `external_directory` の
`allow` で通った。OpenCode は既定で一時ディレクトリへの `external_directory` を allow に
している（公式の「temporary … directories」）。`TMPDIR` を実行ごとの場所へ向けた 2 回目以降は
`ask` になった。

## 結果

### 変更前と変更後（通常版）

`ext` = `.tmp/opencode/extread/ext`。「確認」は計装が `ask` を止めたもの。

| 呼び出し | 変更前 | 変更後 |
| --- | --- | --- |
| read `~/src/marimo/README.md` | `external_directory` 確認 | 通る |
| read `~/.claude/skills/sdd-docs/SKILL.md`・`~/.agents/skills/…`・`~/.config/opencode/skills/checkpoint/references/…` | `external_directory` 確認 | 通る |
| read `ext/notes.txt` | `external_directory` 確認 | 通る |
| read `ext/id_rsa` | `external_directory` 確認 | `external_directory` は通り、read が `Permission denied`（`*/id_rsa*` の deny） |
| read `ext/.env` | `external_directory` 確認 | read の確認（OpenCode の既定の `*.env`） |
| read `/etc/hostname` | `external_directory` 確認 | 同じ |
| grep（path `~/src/marimo`）・glob（path `~/.claude/skills/sdd-docs`） | `external_directory` 確認 | 通る |
| write `ext/new.txt` | `external_directory` 確認 | `external_directory` は通り、edit の確認 |
| write `.tmp/inside.txt`・作業ツリーの中を絶対パスで write | 通る（resource は `.tmp/abs.txt` の相対） | 同じ |
| `python3 ~/.claude/skills/sdd-docs/scripts/lint_docs.py --docs docs`（絶対パスの形も） | shell の確認 | 通る |
| `python3 ~/.config/opencode/skills/checkpoint/scripts/checkpoint.py paths` / `read` | shell の確認 | 通る |
| `python3 …/check_refs.py --save .tmp/refs-before.txt` / `--baseline .tmp/refs-before.txt` | shell の確認 | 同じ（パスを渡す形は載せない） |
| `python3 …/lint_docs.py --docs docs > .tmp/lint.txt` / `… 2>&1` / `checkpoint.py lint - < docs/index.md` | shell の確認 | `Permission denied: shell` |
| `python3 ~/.claude/skills/../../…/ext/evil.py` | shell の確認 | 同じ |
| `uv run --no-project python …/lint_docs.py` / `S=…; python3 "$S/lint_docs.py"` | shell の確認 | 同じ |
| `python3 …/lint_docs.py --docs $(touch …; echo docs)`（`` `…` `` も） | shell の確認 | 同じ（下） |
| `python3 …/lint_docs.py --docs docs && echo ok` | shell の確認 | 同じ（`echo ok` が確認） |
| shell（workdir `~/src/marimo`）`ls` | `external_directory` 確認 | `external_directory` は通り、shell の確認 |
| shell（workdir `/etc`）`pwd` | `external_directory` 確認 | 同じ |

- スキルのスクリプトの呼び出しで出ていたのは **shell の `ask` だけ**だった。引数に書いた
  作業ツリーの外のパス（`python3 ~/.claude/skills/…`・`ls /home/…/src/marimo`）から、
  `external_directory` は立たなかった。立つのは read / grep / glob / write の対象と、
  shell の `workdir` が外にあるとき
- `external_directory` の resource は、触ったファイルのディレクトリに `/*` を付けたもの
  （`/home/…/.claude/skills/sdd-docs/*`）。`~/.claude/skills/*` の allow が当たる
- 変数に入れたパス（`S=…; python3 "$S/x.py"`）は、代入が落ちて `python3 "$S/lint_docs.py" --docs docs`
  という resource になった。引用符もそのまま残る

`check_refs.py` を `--save` / `--baseline` のパスを省ける形に変えた後の設定で、次も確かめた
（配備済みのスクリプトは変更前なので、実行自体は使い方の誤りで終わる。判定だけを見る）。

| 呼び出し | 変更後 |
| --- | --- |
| `python3 ~/.claude/skills/sdd-docs/scripts/check_refs.py --save`・`python3 /home/…/check_refs.py --baseline` | 通る |
| `… check_refs.py --save .tmp/refs-x.txt`・`… check_refs.py '--'save .tmp/refs-y.txt` | shell の確認 |
| `… check_refs.py --save > .tmp/out.txt` | shell の確認 |
| `… checkpoint.py lint docs/index.md --structure` | 通る |
| `… checkpoint.py write .tmp/cp.md` | shell の確認 |

### 隔離版（`ocs` の permissions。Fence なしで判定だけを見た）

| 呼び出し | 変更前 | 変更後 |
| --- | --- | --- |
| 作業ツリーの外の read / grep / glob（上の表と同じ場所） | `external_directory` 確認 | 通る |
| read `ext/id_rsa` / `ext/.env` / `/etc/hostname` | `external_directory` 確認 | deny / 確認 / 確認 |
| write `ext/new.txt` | `external_directory` 確認 | edit の確認 |
| shell（スキルのスクリプト・リダイレクト付き・`uv run`・コマンド置換を含む全部） | 通る（既定が allow） | 同じ |
| shell（workdir `~/src/marimo`）`ls` / （workdir `/etc`）`pwd` | `external_directory` 確認 | 通る / 確認 |

隔離版では `~/` 始まりの read / edit の規則を捨てる。最初の案では、開けた場所への edit の
`ask` も捨てていたため `write ext/new.txt` が通った（書き込みは Fence が止める前提）。
以前は `external_directory` の確認が止めていたので、この `ask` だけは残す形に直して
確認に戻ることを確かめた。

### scanner の扱い（通常版）

| 呼び出し | resource | 判定 |
| --- | --- | --- |
| `python3 …/lint_docs.py --docs $(touch …/subst-ran; echo docs)` | 全体・`touch …`・`echo docs` の 3 つ | 確認（`touch` が確認）。印は残らなかった |
| `FOO=1 wc -l docs/index.md` / `PATH=/x:$PATH wc -l …` / `FOO=1 python3 …/lint_docs.py …` | 代入を含む全体 | 確認（`wc *` などに当たらない） |
| `env FOO=1 wc -l docs/index.md` | 全体 | 確認 |
| `python3 …/lint_docs.py --docs '--'docs` | 引用符を含む全体 | 通る |

コマンド置換の中身は別の resource として照合される。前に付けた変数代入は resource に残る
（文として独立した代入 `S=…;` だけが落ちる）。引用符は残るので、`'--'save` のように
書くと、`--save` を含むかどうかの照合をすり抜ける。

### スクリプトがリポジトリの設定から起動するもの

OpenCode を通さず、仕込んだリポジトリで直接実行した（`fsm.sh`）。`core.fsmonitor` は
印を残すコマンド、`core.hooksPath` の `post-index-change` も印を残す。

| コマンド | 走った外部コマンド |
| --- | --- |
| `git ls-files --cached --others --exclude-standard` | fsmonitor |
| `git check-ignore -q b.txt` | fsmonitor |
| `git rev-parse --show-toplevel` / `--is-inside-work-tree` / `--git-path info/exclude` | なし |
| `git status --short`（対照） | fsmonitor・hook |
| 配備済みの `check_refs.py`（引数なし） | fsmonitor |
| 配備済みの `checkpoint.py paths --ensure-ignored` | fsmonitor |

`check_refs.py` と `checkpoint.py` を `git -c core.fsmonitor=false` で呼ぶように直し、
`test_check_refs.py` / `test_checkpoint.py` に印が残らないことの試験を足した（直す前は落ちた）。

`uv run --no-project python` は、作業ツリーの `.python-version` に書いた実行ファイルを起動した。

| コマンド（`.python-version` に `…/evil/python` を書いた場所で実行） | 起動した |
| --- | --- |
| `uv run --no-project python -c …` | する |
| `uv run --no-project --no-config python -c …` | しない |
| `uv run --no-project --python python3 python -c …` / `UV_PYTHON=python3 …` | しない |
| `uv pip list` | しない |
| `python3 -c …` | しない |

## 結論

- 作業ツリーの外の読み取りは `external_directory` を allow にすれば確認が消える。
  同じ場所の edit は `ask` に戻し、read の allow は足さない（既定の `*.env` の `ask` を残す）。
  秘密の read / edit の deny は後ろに置けば効き続ける
- スキルのスクリプトは shell の `ask` だけが問題だった。`python3 <パス>` の形を
  前方一致で allow にし、リダイレクトを deny にすれば、変数・引用符・`uv run` の形は
  確認に残る
- 引数の中身は静的な照合で検査できない（引用符・変数・argparse の省略形で外れる）。
  引数で書き込み先を決められる形は、引数ごと完全一致で固定するか載せない
- スクリプトが呼ぶ git や runner がリポジトリの設定（`.git/config`・`.python-version`）
  からコマンドを起動しないことも条件になる

仕様は [作業ツリーの外の読み取り](../../../spec/agent-config-generation.md#作業ツリーの外の読み取り)
と [スキルのスクリプト](../../../spec/agent-config-generation.md#スキルのスクリプト)。

## 未検証

- Windows の OpenCode。生成物には `python3` の形がそのまま出るので、`py -3` で呼ぶ
  Windows では確認が出たままになる（推測）
- Fence を張った実際の `ocs` での実行（ここでは permissions の判定だけを見た）
- 実験的な `portable_shell_scanner` を有効にしたときの resource の形
