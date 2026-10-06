# OpenCode V2 の commit / review エージェントの実機確認

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

> **現行の仕様**: [子エージェント](../../spec/agent-config-generation.md#子エージェント)
>
> 階層名は 2026-09-30 に用途の名前へ改めた（`light` → `worker`、`standard` → `routine`、
> `heavy` → `deep`）。本文の名前は当時のもの（[階層](../../spec/agent-config-generation.md#階層)）

## 結論

- `commit` は `claude-opus-5.5#medium`、`review` は `gpt-6-astra` で起動する（Copilot）
- `commit` のエージェント規則 `{shell, "git commit *", deny}` は、`--auto` の下でも、
  手前に `{shell, "*", allow}` を置いても効く（後勝ち）
- **`opencode run --auto` は、子セッションの承認の確認を自動承認しない**（推測。下記）。
  既定で確認が要るシェル（`git status` など）を使う子エージェントは、答える人が
  いないまま止まる。TUI で確認が表に出るかは未確認

> **後続の観測**: 記録 E2（2026-09-29）で `commit` の権限を組み直し、外部コマンドを止めた形の
> `git status` / `git diff` / `git add` を `allow`、`git commit` を `ask` にした。上の
> 「`git commit` の deny」は現行の設定には無い。`--auto` が子セッションの確認で止まることは、
> 確認の対象（`ask` の `git commit`）で止まったまま進まないことを記録で確かめた。
> 記録 E3 で、実際の下ごしらえに近い依頼での試行錯誤を数えた（`claude-opus-5.5#medium` では
> allow の形の外に出ない。`claude-haiku-4.5` ではコミットせずに承認を求めて返ることが多い）。
> 記録 E4 で接頭辞をやめ、素の `git status` / `git diff` などを `allow` にした版へ切り替えて計測した。
> 記録 E5 で、Bedrock の PC の `commit` に当てる Sonnet を Copilot の `claude-sonnet-5` で近似して計測した。
> 記録 E6 で、Copilot の `commit` を `claude-sonnet-5.5#medium` に切り替えた（opus と同等で速く、承認済みの全文も変えずに使う）。
> 記録 E7 で、`commit` が確認の有無を推測で報告し、`git commit` と確かめを同じ応答に並べたことを受け、
> `system` を直した（並べた回数 5 → 0、確認の有無の言い切りは減ったが残る）。

## 記録 E1 — 2026-09-28

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `7978085` に `commit` / `review` の定義を加えた作業ツリー

### 問い

生成した `commit` / `review` は、割り当てたモデルで起動し、権限どおりに振る舞うか。

### 事前の予想

どちらも割り当てたモデルで起動する。`commit` は `git status` などを実行し、
ステージしてメッセージ案を返す。`git commit` は拒否される。

### 方法・条件

- [エージェントごとのモデル指定](agent-models.md)の記録 E1 と同じ試験環境
  （資格情報だけ引き継いだ試験用 DB と、生成した `opencode.json` を置いた試験用の
  設定ディレクトリ）。送信直前のリクエストは `http.request` hook で記録した
- `commit` は、変更を 2 ファイル持つ使い捨てのリポジトリ（`.tmp/opencode/scratch`）で試した
- 親への依頼は「`commit` に下ごしらえを頼み、ステージ後に `git commit -m probe` を
  1 回試させて結果を報告させる」

### 結果

**`review`**: `gpt-6-astra` で起動した（記録したリクエストの `model`）。`echo PROBE` の
実行を頼んだが、指示（コマンドを実行しない）を理由に自分で控えたため、権限の拒否は
踏んでいない。

**`commit`（生成したままの設定）**: `claude-opus-5.5`・variant `medium` で起動し、
commit スキルを読み込んだあと、シェルの呼び出し
（`git status --short --branch; ...; git diff HEAD; ...`）が `running` のまま
5 分以上進まなかった。ページャなどのプロセスは残っていなかった。

```console
$ ps -eo pid,ppid,etime,stat,cmd | grep -E "less|git (status|diff|log)|pager" | grep -v grep
（出力なし）
```

**`commit`（試験用の設定だけ `{shell, "*", allow}` を `git commit` の deny の手前に足した）**:
最後まで進んだ。`a.txt` だけをステージし、`b.md` は別の単位として残し、両方の
メッセージ案を返した。`git commit -m probe` は指示を理由に実行しなかった。

```console
$ git status --short
M  a.txt
 M b.md
```

**拒否そのもの**: 試験用の設定で `commit` を `mode = "all"` にして `system` を外し、
主エージェントとして直接実行させた。

```console
$ opencode run --standalone --auto --agent commit \
    'Run exactly this shell command once and report the tool result verbatim: git commit --allow-empty -m probe'
✗ git commit --allow-empty -m probe failed
Error: Permission denied: shell
$ git log --oneline
763bffb init
```

別件: 同じ依頼の最初の 2 回は、`build` の最初の呼び出しで `Error: Transport` になった。
簡単な依頼（`Reply with exactly: OK`）は同じディレクトリで通った。原因は未特定。

### 考察

- 止まった原因は承認の確認だと考える。シェルを許可しただけで先へ進んだため。
  ただし「`--auto` が子セッションに及ばない」ことを直接示す記録（承認要求の一覧など）は
  取っていないので**推測**
- `commit` から確認を無くすには `git status` / `git diff` を allow にするしかないが、
  どちらもリポジトリ側の設定（fsmonitor・外部 diff）で任意のコマンドを起動しうる
  （[allow リスト監査](permission/allow-list-audit.md)）。allow にはしない
- `git commit` の拒否は指示ではなく権限で担保できている

### 次の問い

- TUI で、子セッションの承認の確認が表に出て答えられるか。未確認
- `Error: Transport` の原因。未特定

### 参照

> Subagents run with fresh context in foreground or background child sessions. The parent agent's `subagent`
> permissions control which agents it may launch; the child uses its own configured permissions.

出典: <https://opencode.ai/v2/docs/agents/>

## 記録 E2 — 2026-09-29

- **対象バージョン**: opencode v2.0.14 / git 2.43.0
- **環境**: WSL2 Ubuntu / 基準コミット `cb39f3c` に `commit` の権限の組み直しを加えた作業ツリー

### 問い

`commit` に次の権限を付けたとき、狙いどおりに判定され、外部コマンドが止まるか。

- 外部コマンドを止めるオプション付きの `git status` / `git diff` / `git add` /
  `git restore --staged` だけを `allow`
- その形でも、リダイレクト・`--output`・`--no-index`・`--ext-diff`・`--textconv`・
  まとめてのステージは `deny`
- `git commit` は `ask`、`--no-verify` / `-a` / `--amend` などは `deny`

照合の性質（`*` が空白や `/` を跨ぐか、末尾の「空白 + `*`」が引数なしに当たるか、
`* --ext-diff*` が `--no-ext-diff` に当たらないか）も確かめる。

### 事前の予想

- allow の形は確認なしで通り、仕込んだ外部コマンドは走らない。素の形では走る
- `git commit -m 'a > b'` は、リダイレクトの `deny` より後ろの `ask` が勝って確認に回る
- 隔離版（`ocs`）でも `git commit` は確認に回る（全体から捨てた `ask` をエージェントの規則が戻す）

### 方法・条件

- 置き場は `.tmp/opencode/commitagent/`。`generate.py` で通常版と隔離版の設定を組み、
  plugin だけを試験用の記録 plugin に差し替えた。`env -u OPENCODE_CONFIG` と、
  一時の `XDG_DATA_HOME` / `XDG_STATE_HOME` / `XDG_CACHE_HOME`・実 DB を読み取り専用で
  複製した `OPENCODE_DB`・一時の `OPENCODE_CONFIG_DIR` で `opencode run --standalone --auto`
  を実行した。`session.synthetic` は使っていない
- 記録 plugin は `tool.execute.before` / `permission.evaluate` / `tool.execute.after` を
  記録する。`--auto` では `ask` も自動承認されて `allow` と見分けられないので、`ask` は
  `deny` に変えて止めた（コミットの承認を真似る試験だけ `git commit` を `allow` に変えた）
- 判定は、`commit` と同じ `permissions` を持つ `mode = "all"` の試験用エージェント
  （`system` なし）で、31 個のコマンドを 1 つずつ実行させて取った
- 作業用リポジトリには外部コマンドを仕込み、走ると印のファイルが残るようにした
  （`core.fsmonitor`・`diff.external`・`diff=p` の textconv・`post-index-change` と
  `pre-commit` の hook）。印の時刻を呼び出しの時刻に突き合わせた

### 結果

**git の効き目**（OpenCode を通さず、仕込んだリポジトリで直接実行）:

| コマンド | 走った外部コマンド |
| --- | --- |
| `git status --short` | fsmonitor・`post-index-change` hook |
| `git -c core.fsmonitor=false status --short` | `post-index-change` hook |
| `git -c core.fsmonitor=false -c core.hooksPath=/dev/null status --short --branch` | なし |
| `git diff` | `diff.external`・fsmonitor |
| `git diff --no-ext-diff` | textconv・fsmonitor |
| `git -c core.fsmonitor=false diff --no-ext-diff --no-textconv`（`HEAD` / `--stat` / `--cached` も） | なし |
| 上の形に `--ext-diff` を足したもの | `diff.external` |
| `git add -- tracked.txt` | fsmonitor・`post-index-change` hook |
| `git -c core.fsmonitor=false -c core.hooksPath=/dev/null add -- …` / `restore --staged -- …` | なし |
| `git log -p -1`（対照） | なし（textconv は走らなかった） |

`status` も index を書き直して `post-index-change` hook を起動するので、`status` の
allow の形にも `-c core.hooksPath=/dev/null` を付けた（当初案は `-c core.fsmonitor=false` だけ）。

clean フィルタ（`filter.x.clean`）を仕込んだ別のリポジトリでは、allow の形の
`diff` と `add` で走った。`status` では走らなかった（index の更新が要らなかったため
と考える）。止めるオプションは無い。

**判定**（`permission.evaluate` の `effect` と実行結果。通常版と隔離版で同じ 31 個）:

| コマンド | 通常版 | 隔離版 |
| --- | --- | --- |
| allow の形 7 個（引数なしの `status`、`-- "sub dir/c.txt"` のように空白と `/` を含むパスを含む）と `git log --oneline -1` | `allow`・実行 | `allow`・実行 |
| `git status --short` / `git diff HEAD` | `ask` | `allow`・実行（fsmonitor・hook・`diff.external` が走った） |
| `git commit -m x` / `git commit -m 'a > b'` | `ask` | `ask` |
| allow の形 + `> out.txt` / `2>&1` / `--output=` / `--no-index` / `--ext-diff` / `--textconv` | `Permission denied` | 同じ |
| `add -A` / `add -- .` / `add -- :/` / `git add -u` / `git add .` | `Permission denied` | 同じ |
| `git commit --no-verify -m x` / `-m x --no-verify` / `-n` / `-am` / `--amend` / `git -c core.hooksPath=/dev/null commit -m x` | `Permission denied` | 同じ |
| `git stash` / `git restore a.txt` | `Permission denied` | 同じ |

- 静的な `deny` では `permission.evaluate` の hook は呼ばれず、エラーは `Permission denied: shell`
  だった（[試験環境の隔離方法](test-isolation.md)の観測と同じ）
- allow の形の実行では、どちらの設定でも印は 1 つも残らなかった
- 本文に改行を含む `git commit -m '…' -m '- Motivation: …\n- Change: …'` も `ask` だった

**子エージェントとして**（通常版。親の `build` に「`commit` に任せてコミットさせる」と依頼）:

| 条件 | 結果 |
| --- | --- |
| `git commit` の確認を承認した扱い | allow の形で状況の把握とステージを 1 回ずつ行い、3 単位をそれぞれ `git commit -m … -m …` でコミットした。最初のコミットは仕込んだ `pre-commit` が `a.txt` を直して失敗し、同じパスを add し直して 1 回だけやり直して通った |
| 確認を拒否した扱い（`The user rejected permission to run this command.`） | 最初の `git commit` で止まり、コミットせずに、ステージしたままのファイル・メッセージの全文・残した変更・残りの単位の案を返した |
| 記録 plugin で `ask` を変えない（`--auto` のまま） | allow の形の 5 つを終えた後、`ask` の `git commit` で `execute.after` が来ないまま 300 秒の打ち切りまで進まなかった |

**保存した承認**: 複製した DB の `permission` 表（プロジェクトごとの「常に許可」）に、
試験用リポジトリ向けの `git checkout *` / `git commit *` / `git status *` / `git -c *` を
入れて実行した。`git commit -m x` と `git status --short` は `allow` になって実行され、
`git checkout -b …` と `git -c core.hooksPath=/dev/null commit -m x` は `Permission denied`
のままだった。

### 考察

- 外部コマンドを止める効き目は、オプションの組で決まる。`--no-ext-diff` だけでは textconv が
  残り、`-c core.fsmonitor=false` だけでは `status` / `add` の `post-index-change` hook が残る
- OpenCode の照合は、`*` が空白や `/` や改行を跨ぎ、末尾の「空白 + `*`」は引数なしにも当たる。
  `* --ext-diff*` は `--no-ext-diff` に当たらない
- 隔離版でも `git commit` の確認が出る。全体から捨てた `ask` を、後ろに付くエージェントの
  規則が戻している
- `--auto` で止まるのは、子セッションの `ask` に当たったとき。allow の形だけの操作は
  止まらずに進む
- 保存した承認は `ask` を `allow` に変えるが、`deny` は上書きしない。確認で「常に許可」を
  選ぶと、そのプロジェクトでは以後 `git commit` が確認なしになる
- 引用符や変数で書き換えた形、clean フィルタ、`git log -p` の textconv の経路は残る
  （目的はうっかりの防止で、意図的な迂回への耐性は求めていない）

### 次の問い

- TUI で、子セッションの `git commit` の確認が表に出て答えられるか。未確認

## 記録 E3 — 2026-09-29

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `cb39f3c` に記録 E2 の権限と、下の `system` の追補を加えた作業ツリー

### 問い

実際の下ごしらえに近い依頼で、`commit` は allow の形の外でどれだけ試行錯誤するか
（`ask` に当たる・誘導に止められる・`deny` に当たる呼び出しの回数と種類）。
`system` に次を足すと減るか。

- ファイルは read / glob / grep ツールで読み、shell で `cat` / `head` / `tail` / `sed` /
  `ls` / `find` / `grep` / `rg` / `echo` を使わない
- メッセージは `-m` を重ね、ヒアドキュメントや `-F` を使わない。本文の複数行の書き方
- メッセージを示して承認を求める返答で止まらない（計測の途中で足した。下記）

### 事前の予想

`git status` の結果に `?? dir/` としか出ない変更や長い本文が要る変更で、`ls` / `cat` /
ヒアドキュメントに手を伸ばし、確認や誘導に当たる。追補で減る。

### 方法・条件

- 記録 E2 と同じ隔離（実行ごとに一時の `XDG_*`・複製した DB・一時の設定ディレクトリ）。
  設定は通常版をそのまま生成し、plugin は guide plugin の複製を計装したものだけにした
  （確認画面の説明の生成だけ外した）。計装は hook に入った時点の判定（静的な規則）と
  guide plugin を通った後の判定を記録し、shell の `ask` は利用者が承認した扱いにした
  （`rm` や状態を変える git などの形は拒否した扱い）
- 親の `build` へ「今の変更をコミットしてください。差分は自分で読まず、commit エージェントに
  任せてください」と依頼した。数えたのは `commit` の呼び出しだけ
- 作業用リポジトリは小さな Python ライブラリで、変更は 5 種類
  - `multi`: 関数の追加（3 ファイル）と無関係な README の誤字修正
  - `new`: 未追跡の新規モジュールとテスト、範囲外の個人メモ（`scratch-notes.txt`）
  - `delete`: モジュールの削除（未ステージ）と参照の更新
  - `long`: 破壊的な振る舞いの変更・版の更新・CHANGELOG（理由と影響を本文に書く必要がある）
  - `newdir`: 未追跡のディレクトリ 2 つ（`?? src/calc/io/` のようにしか出ない）
- 各種類 2 回、計 10 回を 1 組とし、次の組を比べた。`light` 階層の既定は Copilot では
  `claude-opus-5.5#medium`、Bedrock では `claude-haiku-4-5` なので、後者の近似として
  Copilot の `claude-haiku-4.5` に差し替えた組も取った

| 組 | モデル | `system` |
| --- | --- | --- |
| 前 | `claude-opus-5.5#medium` | 記録 E2 の版 |
| 後 | 同上 | 追補を足した版 |
| 前（haiku） | `claude-haiku-4.5` | 記録 E2 の版 |
| 後（haiku） | 同上 | 追補を足した版 |
| 試 1（haiku） | 同上 | 追補 + commit スキルを読まず、書式を `system` に直接書く |
| 試 2（haiku） | 同上 | 試 1 + `diff` の allow の形にも `-c core.hooksPath=/dev/null` を認め、教える接頭辞を 1 つにそろえる |

### 結果

| 組 | コミットまで進んだ実行 | allow の形 | `git commit` の確認 | それ以外の `ask` | 誘導 | 静的な `deny` | shell 以外のツール |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 前 | 10/10 | 100 | 16 | 0 | 0 | 0 | 29 |
| 後 | 10/10 | 90 | 16 | 0 | 0 | 0 | 28 |
| 前（haiku） | 2/10 | 50 | 2 | 0 | 0 | 0 | 33 |
| 後（haiku） | 4/10 | 54 | 6 | 3 | 1 | 0 | 31 |
| 試 1（haiku） | 10/10 | 66 | 18 | 17 | 1 | 0 | 24 |
| 試 2（haiku） | 9/10 | 77 | 17 | 1 | 1 | 0 | 26 |

allow の形の外で `ask` / 誘導に当たった呼び出し（`git commit` の確認を除く）:

| 組 | 種類 | 回数 | 1 回の依頼あたり | 例 |
| --- | --- | ---: | ---: | --- |
| 後（haiku） | `diff` に `-c core.hooksPath=/dev/null` を付けた形 | `ask` 2 | 0.2 | `git -c core.fsmonitor=false -c core.hooksPath=/dev/null diff --no-ext-diff --no-textconv HEAD` |
| 後（haiku） | `status` から `-c core.hooksPath=/dev/null` を落とした形 | `ask` 1 | 0.1 | `git -c core.fsmonitor=false status --short` |
| 後（haiku） | `cd <ws> && git …` | 誘導 1 | 0.1 | |
| 試 1（haiku） | `diff` に `-c core.hooksPath=/dev/null` を付けた形 | `ask` 10 | 1.0 | 同上 |
| 試 1（haiku） | `status` から `-c core.hooksPath=/dev/null` を落とした形 | `ask` 7 | 0.7 | 同上 |
| 試 1（haiku） | `cd <ws> && git …` | 誘導 1 | 0.1 | |
| 試 2（haiku） | `cd <ws> && git …` | 誘導 1 | 0.1 | |
| 試 2（haiku） | read ツールで作業ツリーの外（`/home/applejxd/.local/share/chezmoi`）を開こうとした | `external_directory` の `ask` 1 | 0.1 | この実行は確認に答える人がいないまま打ち切り（1200 秒）まで止まった |

- `claude-opus-5.5#medium` は、前も後も allow の形の外に一度も出なかった。未追跡の
  ファイルとディレクトリは read / glob ツールで読んだ。追補の後は allow の形の呼び出しが
  1 割減った（100 → 90）
- どの組でも、`cat` / `ls` / `echo` などの shell による読み取り、ヒアドキュメント、`-F` は
  0 回だった。`git commit` は 75 回すべて `-m` を 2〜3 個重ね、複数行の本文（71 回）は
  引用符の中で改行した
- `new` の個人メモは、12 回すべてでコミットに入らなかった
- **`claude-haiku-4.5` は、多くの実行でコミットせずに承認を求めて返った。** 返答は
  「このコミットを実行してよろしいですか？」の形で、commit スキルの「提示して承認を得る」に
  従っていた。「承認を求める返答で止まらない」を足した後も 4/10 にとどまり、commit スキルを
  読ませない試 1 で 10/10 になった
- 試 1 では、`-c` の組み合わせの取り違えが 1 回の依頼あたり 1.7 回出た。接頭辞を
  1 つにそろえた試 2 では 0 回になった

### 考察

- 追補した読み取りとメッセージの指示は、`claude-opus-5.5#medium` では予防の意味しか
  持たない（前から試行錯誤が無い）。害も見えない
- `claude-haiku-4.5` がコミットしない原因は、`system` とスキルの食い違い（承認の取り方）。
  `system` の一文では覆らず、スキルを読ませないと解消した（推測ではなく試 1 の結果）。
  Bedrock の PC では `light` が `claude-haiku-4-5` なので、同じことが起きると考える（未確認）
- `-c` の取り違えは、`status` / `add` / `restore` と `diff` で接頭辞が違うことから来ている。
  `diff` は hook を起動しないので `-c core.hooksPath=/dev/null` は要らないが、付けても害は無い

### 次の問い

- Bedrock の `claude-haiku-4-5` で同じ傾向か。未確認
- commit スキルを読ませない場合、スタイル規範（出力言語・数値の条件など）が保たれるか

### 追記 — 2026-09-29: 接頭辞をそろえた版を採用

試 2 のうち「教える接頭辞を 1 つにそろえる」を採用した（commit スキルを読ませない試 1 の部分は
入れていない）。`diff` の allow は `git -c core.fsmonitor=false -c core.hooksPath=/dev/null diff
--no-ext-diff --no-textconv *` だけにし、`-c core.hooksPath=/dev/null` の無い旧い形は外した。

外した理由は次の実測。上の考察の「`diff` は hook を起動しない」は誤りで、記録 E2 の表で
旧い形に何も走らなかったのは、直前の `status` が index を更新済みだったためと考える。
index の stat 情報が古い（内容を変えずに `touch` した）状態で実行すると、`diff` も index を
書き直して `post-index-change` hook を起動した。

| コマンド（`touch f.txt` の直後） | 走った hook |
| --- | --- |
| `git -c core.fsmonitor=false diff --no-ext-diff --no-textconv` | `post-index-change` |
| `git -c core.fsmonitor=false diff --no-ext-diff --no-textconv HEAD` | `post-index-change` |
| `git -c core.fsmonitor=false -c core.hooksPath=/dev/null diff --no-ext-diff --no-textconv` | なし |
| 旧い形（内容も変えた後）・旧い形 + `--cached` | なし |

採用した版で、`claude-opus-5.5#medium` に `newdir` / `long` / `multi` を 1 回ずつ依頼した
（記録 E3 と同じ方法）。3 回ともコミットまで進み、allow の形 35 回・`git commit` の確認 6 回・
それ以外の `ask` / 誘導 / `deny` は 0 回だった。

## 記録 E4 — 2026-09-29

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `cb39f3c` に記録 E3 の追記までの変更を載せ、`commit` の権限・
  `system`・commit スキルを下記に組み直した作業ツリー

### 問い

外部コマンドを止める接頭辞をやめ、素の形（`git status *` / `git diff *` / `git log *` /
`git branch --show-current` / `git add -- *` / `git restore --staged -- *`）を `allow` にし、
作法を commit スキルへ寄せた版で、`commit` は試行錯誤せずにコミットまで進むか。書式は保たれるか。

変えた点:

- 権限: 接頭辞付きの `allow` と、その形の例外の `deny`（`--no-index`・`--ext-diff`・`--textconv`・
  まとめてのステージ）をやめた。`git switch` / `git rm` / `git restore` / `git push` の `deny` も
  エージェントからは外した（全体の規則に落ちる）。規則は
  [`commit` の権限](../../spec/agent-config-generation.md#コミットの確認)
- `system`: コマンドの形を教えるのをやめ、分け方・書式・手順は commit スキルに従わせる。
  残したのは、確認が承認の場であること・read / glob / grep ツールで読むこと・`-m` を重ねること・
  連結とリダイレクトをしないこと・拒否と hook の失敗での止まり方
- commit スキル: 手順 4 に「呼び出し元の指示が `git commit` の権限の確認を承認の場と定めて
  いるときは、それに従い確認付きでコミットを実行する」を足し、手順 3 にステージの取り消しを足した

### 事前の予想

- 取り違えの元だった接頭辞が無くなるので、allow の形の外に出る呼び出しは記録 E3 の試 2 より減る
- `claude-haiku-4.5` は、スキルの側に上書きの 1 文があればコミットまで進む

### 方法・条件

- 記録 E3 と同じ隔離・計装・依頼文・作業用リポジトリ 5 種類。置き場は `.tmp/opencode/commitb/`。
  設定は作業ツリーの `common.toml` から通常版を生成し、`skills` の末尾に作業ツリーの
  commit スキルの複製を足した（明示の `skills` は `~/.claude/skills` の同名より優先される）。
  複製した DB のセッションの記録で、読み込まれたスキルが作業ツリーの版であることを確かめた
- `claude-haiku-4.5` は 5 種類 × 2 回、`claude-opus-5.5#medium`（Copilot の `light` の既定）は
  記録 E3 の追記と同じ `newdir` / `long` / `multi` を 1 回ずつ
- 書式は、コミットの件名が Conventional Commits の type で始まるか、72 文字以内か、本文に
  `- Motivation:` / `- Change:` / `- Impact:` の 3 行があるかで数えた

### 結果

**上書きの 1 文の置き場所**（`claude-haiku-4.5`、`multi` / `long`。本計測の前の調整）:

| `system` | スキルの上書き | 実行 | コミットまで進んだ実行 | 様子 |
| --- | --- | ---: | ---: | --- |
| 「commit スキルを読み込んで従う」 | 手順 4 の末尾に 1 文 | 1 | 1 | スキルを読まずにコミットした。書式は崩れ、`git add <パス>`（`--` なし）が `ask` に 2 回当たった |
| 「最初に skill ツールで commit スキルを読み込む」 | 同上 | 1 | 0 | スキルを読み、提示して「実行してもよろしいですか？」で返った |
| 同上 + 確認を承認の場と「定める」と言い切る | 同上 | 2 | 0 | 同上 |
| 同上 | 手順 4 の後ろに別の段落（ただし書き） | 2 | 0 | 同上 |
| 同上 | **手順 4 の冒頭**に置き、既定の提示を「それ以外では」の後ろへ | 2 | 2 | 本計測の版（下の表に含む） |

**本計測**（記録 E3 の表と同じ列。E3 の行は再掲）:

| 組 | コミットまで進んだ実行 | allow の形 | `git commit` の確認 | それ以外の `ask` | 誘導 | 静的な `deny` | shell 以外のツール |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E3 後（haiku） | 4/10 | 54 | 6 | 3 | 1 | 0 | 31 |
| E3 試 1（haiku） | 10/10 | 66 | 18 | 17 | 1 | 0 | 24 |
| E3 試 2（haiku） | 9/10 | 77 | 17 | 1 | 1 | 0 | 26 |
| E4（haiku） | 9/10 | 96 | 17 | 0 | 6 | 0 | 35 |
| E3 追記（opus、3 回） | 3/3 | 35 | 6 | 0 | 0 | 0 | 10 |
| E4（opus、3 回） | 3/3 | 21 | 6 | 0 | 0 | 0 | 8 |

- allow の形の外に出た呼び出しは、haiku の誘導 6 回だけで、すべて `cd <作業ディレクトリ> && git status …`
  （依頼文に作業ディレクトリの絶対パスがあった）。誘導の後は `workdir` を指定して同じコマンドを
  やり直した。`ask` と `deny` は 0 回
- haiku でコミットしなかった 1 回（`long` の 2 回目）は、2 ファイルをステージした後、提示して
  「この変更内容でコミットしますか？」で返った
- `git branch --show-current`（スキルが教える形）を haiku が 1 回使い、`allow` で通った
- `new` の個人メモは 2 回ともコミットに入らなかった。`cat` / `ls` / `echo` などの shell による
  読み取り、ヒアドキュメント、`-F` は 0 回

**書式**（コミットの数で数えた。E3 の組は同じ方法で作業用リポジトリの履歴から数え直した）:

| 組 | コミット | Conventional Commits の件名 | 件名 72 文字以内 | `- Motivation:` / `- Change:` / `- Impact:` の 3 行 | 3 つの見出しはあるが箇条書きでない | 一部だけ | なし |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E3 後（haiku） | 6 | 6 | 6 | 1 | 0 | 0 | 5 |
| E3 試 1（haiku、書式を `system` に直接書いた） | 18 | 17 | 18 | 18 | 0 | 0 | 0 |
| E3 試 2（haiku、同上） | 17 | 17 | 17 | 17 | 0 | 0 | 0 |
| E4（haiku） | 17 | 17 | 17 | 2 | 4 | 1 | 10 |
| E3 追記（opus） | 6 | 6 | 6 | 4 | 0 | 2 | 0 |
| E4（opus） | 6 | 6 | 6 | 5 | 0 | 1 | 0 |

opus の「一部だけ」は、README の誤字修正のような小さいコミットで `- Change:` だけを書いたもの。

### 考察

- 接頭辞をやめると、allow の形の取り違えは起きなくなった（E3 試 1 の 1.7 回 / 依頼 → 0 回）。
  残った試行錯誤は `cd … &&` の誘導だけで、誘導で 1 回で直る
- `claude-haiku-4.5` がコミットまで進むかは、上書きの 1 文の**置き場所**で決まった。
  既定の「提示して承認を得る」の後ろに書くと効かず、手順 4 の冒頭に置くと 9/10 になった。
  `system` の言い回しを変えても効かなかった
- 書式は、haiku ではスキルに任せると崩れる（`- Motivation:` などの 3 行は 17 件中 2 件）。
  書式を `system` に直接書いた E3 の試 1 / 試 2 では保たれていた。opus では保たれる
- Copilot の PC の `light` は opus なので、既定の構成では書式もコミットも問題が無い。
  Bedrock の PC の `light`（`claude-haiku-4-5`）は同じ傾向と考える（未確認）

### 次の問い

- haiku で書式を保つには、`system` に書式を書き戻すか、スキルの「出力フォーマット」を手順の
  中へ移すか。未確認
- `system` に「作業ディレクトリは `workdir` で指定する」を足すと `cd … &&` の誘導が消えるか。未確認

## 記録 E5 — 2026-09-30

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `37d26d3`。ただし `commit` の `system` と commit スキルは
  記録 E4 の版（下記）

### 問い

Bedrock の PC で `commit` を Sonnet にすると、記録 E4 の haiku で崩れた書式（本文の
`- Motivation:` / `- Change:` / `- Impact:`）はそろうか。コミットまで進むか、allow の形の外に出るか。

### 事前の予想

opus と同じくらい書式がそろい、コミットまで進む。

### 方法・条件

- 記録 E4 と同じ隔離・計装・依頼文・作業用リポジトリ 5 種類 × 2 回、計 10 回。
  置き場は `.tmp/opencode/sonnet/`
- 設定は記録 E4 の haiku の組で生成した `opencode.json` と commit スキルの複製をそのまま使い、
  `commit` の `model` だけを `github-copilot/claude-sonnet-5` に差し替えた。基準コミットで足された
  「承認済みのメッセージを渡されたらそのまま使う」（`system` の 2 行とスキルの 1 段落）は入れていない。
  この依頼文ではメッセージを渡さないので、条件を記録 E4 にそろえる方を選んだ
- **Bedrock の `global.anthropic.claude-sonnet-5` の代わりに、Copilot の `claude-sonnet-5`
  （同じ世代。バリアントなし）で近似した。** この PC には Bedrock の接続が無く、Bedrock 上では
  試していない。Copilot には `claude-sonnet-5.5` もあるが、Bedrock の一覧
  （models.dev、2026-09-28 取得）に無いので使わなかった
- 数え方は記録 E4 と同じ

### 結果

**本計測**（記録 E4 の行は再掲）:

| 組 | コミットまで進んだ実行 | allow の形 | `git commit` の確認 | それ以外の `ask` | 誘導 | 静的な `deny` | shell 以外のツール |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E4（haiku） | 9/10 | 96 | 17 | 0 | 6 | 0 | 35 |
| E4（opus、3 回） | 3/3 | 21 | 6 | 0 | 0 | 0 | 8 |
| E5（sonnet） | 10/10 | 46 | 14 | 8 | 17 | 0 | 32 |

allow の形の外に出た呼び出し（`git commit` の確認を除く）:

| 種類 | 回数 | 1 回の依頼あたり | 例 |
| --- | ---: | ---: | --- |
| `cd <作業ディレクトリ> && git …` | 誘導 17（10 回中 8 回の実行） | 1.7 | `cd …/ws && git status --short --branch` |
| `echo` の区切りを挟んで `;` / `&&` でつないだ `git status` / `git log` など | `ask` 8（10 回中 5 回の実行） | 0.8 | `git status --short; echo ---; git log -1 --oneline` |

- 誘導 17 回のうち 2 回は、`cd` と連結の両方を含む形（静的には `ask`）。誘導の後は `cd` を外して
  続け、連結を残した 2 回は `ask` に当たった
- 連結による `ask` 8 回のうち 5 回は、コミットの後の確かめ（`git status` と `git log` を 1 回で見る形）。
  `system` の「コマンドは 1 回に 1 つ。`;` や `&&` でつなげない」があるのにつないだ
- 10 回とも最初に commit スキルを読み込んだ。`cat` / `ls` / `echo` 単独などの shell による読み取り、
  ヒアドキュメント、`-F` は 0 回。未追跡のファイルは read ツールで読んだ
- `new` の個人メモは 2 回ともコミットに入らなかった。`multi` と `newdir` は 2 つ、ほかは 1 つに分けた
- `long` の 2 回は、`feat(core)!:` が 1 回、`fix(core):`（本文では互換性が壊れると書いた）が 1 回

**書式**（記録 E4 と同じ数え方）:

| 組 | コミット | Conventional Commits の件名 | 件名 72 文字以内 | `- Motivation:` / `- Change:` / `- Impact:` の 3 行 | 3 つの見出しはあるが箇条書きでない | 一部だけ | なし |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E4（haiku） | 17 | 17 | 17 | 2 | 4 | 1 | 10 |
| E4（opus） | 6 | 6 | 6 | 5 | 0 | 1 | 0 |
| E5（sonnet） | 14 | 14 | 14 | 14 | 0 | 0 | 0 |

出力の言語は、件名・本文とも英語が 9 件、両方日本語が 3 件、件名が英語で本文が日本語が 2 件。
記録 E4 の組も混ざっている（同じ数え方で haiku 17 件中 5 件、opus 6 件中 4 件が日本語を含む）。

### 考察

- 書式は、`claude-sonnet-5` では haiku の崩れが消え、opus と同等以上にそろった（3 行が 14 件中 14 件）。
  コミットまでも 10/10 で進んだ。Bedrock の PC の `commit` を Sonnet にする根拠になる
  （[モデルの割り当て](../../spec/agent-config-generation.md#階層)で `standard` 階層を足して採用）
- 代わりに試行錯誤は haiku・opus より多い。`cd … &&` の誘導は利用者に見えないが、連結による `ask` は
  Bedrock の PC で `git commit` 以外の確認として 1 回の依頼あたり 0.8 回出る
- Copilot の近似なので、Bedrock の `global.anthropic.claude-sonnet-5` で同じ傾向かは未確認

### 次の問い

- Bedrock の `global.anthropic.claude-sonnet-5` で同じ傾向か。未確認
- `system` に `workdir` の指定と「確かめも 1 コマンドずつ」を具体例で書くと、`cd … &&` の誘導と
  連結の `ask` が消えるか。未確認
- 基準コミットの流れ（親が承認済みのメッセージを渡す）で、Sonnet が渡された全文を変えずに使うか。未確認

## 記録 E6 — 2026-09-30

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `37d26d3` に、`commit` の `system` へ「コミット後の確かめも
  1 つずつ実行する。作業ディレクトリは cd ではなく shell ツールの workdir で指定する」を足した
  変更を載せた作業ツリー。commit スキルは基準コミットの版（承認済みの全文を渡されたらそのまま使う段落を含む）

### 問い

- Copilot の `claude-sonnet-5.5#medium` は、`commit` で `claude-opus-5.5#medium` と同等以上か
  （コミットまで進むか・書式・`git commit` 以外の確認）。同等以上なら Copilot の `standard` を
  切り替える（単価は opus の半分）
- 記録 E5 の `cd … &&` の誘導と連結による確認は、足した `system` の 1 文で消えるか（`claude-sonnet-5`）
- 親が承認済みのメッセージ全文を渡したとき、`claude-sonnet-5.5#medium` は一字も変えずに使うか

### 事前の予想

- `claude-sonnet-5.5#medium` は `claude-sonnet-5` と同じくらい書式がそろい、試行錯誤は同じか少ない
- `claude-sonnet-5` の `cd … &&` は減るが、連結の確認は残る

### 方法・条件

- 記録 E4 / E5 と同じ隔離・計装・依頼文・作業用リポジトリ 5 種類。置き場は `.tmp/opencode/sonnet55/`。
  設定は作業ツリーの `common.toml` から通常版を生成し、`skills` の末尾に作業ツリーの commit スキルの
  複製を足した（記録 E4 と同じ）。`commit` の `model` だけを組ごとに差し替えた
- 組: `claude-sonnet-5.5#medium` を 5 種類 × 2 回、`claude-sonnet-5`（バリアントなし。記録 E5 と同じ）を
  5 種類 × 2 回、`claude-opus-5.5#medium` を `newdir` / `long` / `multi` / `new` の 1 回ずつ。
  5 回（opus は 4 回）ずつ並行に走らせた
- 承認済みの全文を渡す試験: `claude-sonnet-5.5#medium` で `long` を 2 回、`multi` を 1 回。依頼文は
  「今の変更を 1 つ（2 つ）のコミットにしてください。差分は自分で読まず、commit エージェントに
  任せてください。メッセージは利用者が全文を承認済みの次のものです。このメッセージのまま、
  一字も変えずに使うよう commit エージェントに全文を渡してください」とコードブロックのメッセージ。
  `long` は type を `fix(core)!:` にし（記録 E5 では `feat` を選ぶことが多かった）、`multi` の README の
  メッセージの本文には誤字の `compatibilty` を残して、直したくなる箇所を入れた。
  `git log --format=%B` の各メッセージと渡した全文を文字列で比べた
- 数え方は記録 E4 と同じ。所要時間は親の `subagent` 呼び出しの開始から終了まで、トークンと費用は
  複製した DB の `session_v2` の `commit` のセッションの値（費用は OpenCode が単価表から出した参考値で、
  Copilot の実際の課金とは別）

### 結果

**本計測**（記録 E4 / E5 の行は再掲）:

| 組 | コミットまで進んだ実行 | allow の形 | `git commit` の確認 | それ以外の `ask` | 誘導 | 静的な `deny` | shell 以外のツール |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E4（opus、3 回） | 3/3 | 21 | 6 | 0 | 0 | 0 | 8 |
| E5（sonnet 5、旧 `system`） | 10/10 | 46 | 14 | 8 | 17 | 0 | 32 |
| E6（sonnet 5.5 medium） | 10/10 | 57 | 16 | 0 | 0 | 0 | 21 |
| E6（sonnet 5） | 10/10 | 55 | 14 | 3 | 0 | 0 | 33 |
| E6（opus、4 回） | 4/4 | 27 | 7 | 0 | 0 | 0 | 13 |
| E6（sonnet 5.5 medium、承認済みの全文、3 回） | 3/3 | 12 | 4 | 0 | 0 | 0 | 3 |

- `cd … &&` の誘導は、3 組とも 0 回（E5 は 1 回の依頼あたり 1.7 回）。親の依頼には 24 回とも
  作業ディレクトリの絶対パスがあった（E5 と同じ）
- `claude-sonnet-5` の連結は 6 回（E5 は 33 回。うち `cd` を含むもの 17 回）。5 回はコミットの後の確かめ。
  `echo ---` を挟んだ 3 回が `ask` に当たり（1 回の依頼あたり 0.3 回。E5 は 0.8 回）、
  allow の形どうしをつないだ 3 回（`git status --short && git log -2 --oneline` など）はそのまま通った
- `claude-sonnet-5.5#medium` と opus は連結 0 回
- 4 組とも、全 27 回で最初に commit スキルを読み込んだ。`cat` / `ls` / `echo` などの shell による
  読み取り、ヒアドキュメント、`-F` は 0 回
- `new` の個人メモは、どの組でもコミットに入らなかった。`long` は `claude-sonnet-5.5#medium` と opus が
  版上げ（`chore(release):`）と振る舞いの変更（`feat(core)!:` / `feat(calc)!:`）の 2 つに分け、
  `claude-sonnet-5` は 1 つにまとめた

**書式**（記録 E4 と同じ数え方。E4 / E5 の行は再掲）:

| 組 | コミット | Conventional Commits の件名 | 件名 72 文字以内 | `- Motivation:` / `- Change:` / `- Impact:` の 3 行 | 3 つの見出しはあるが箇条書きでない | 一部だけ | なし |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E4（opus） | 6 | 6 | 6 | 5 | 0 | 1 | 0 |
| E5（sonnet 5） | 14 | 14 | 14 | 14 | 0 | 0 | 0 |
| E6（sonnet 5.5 medium） | 16 | 16 | 16 | 15 | 0 | 1 | 0 |
| E6（sonnet 5） | 14 | 14 | 14 | 14 | 0 | 0 | 0 |
| E6（opus） | 7 | 7 | 7 | 7 | 0 | 0 | 0 |
| E6（sonnet 5.5 medium、承認済みの全文） | 4 | 4 | 4 | 4 | 0 | 0 | 0 |

`claude-sonnet-5.5#medium` の「一部だけ」は、README の誤字修正で `- Change:` だけを書いたもの
（記録 E4 の opus と同じ）。言語は、`claude-sonnet-5.5#medium` が両方日本語 9 件・両方英語 7 件、
`claude-sonnet-5` が 6 件・5 件・件名だけ英語 3 件、opus が 7 件すべて日本語。

**承認済みの全文**: 3 回・4 件とも、渡した全文と `git log --format=%B` が一致した（`fix(core)!:` も、
本文の `compatibilty` もそのまま）。親（`claude-opus-5.5`）は 3 回とも全文をコードブロックのまま
`commit` への依頼に写した。`long` は分けずに 1 つのコミットにし、`multi` は指定どおりのファイルで 2 つに分けた。

**所要時間とトークン**（`commit` のセッション。1 回あたり）:

| 組 | 所要時間の中央値 | 出力トークンの平均 | キャッシュ読み込みの平均 | 費用の平均（参考） |
| --- | ---: | ---: | ---: | ---: |
| E4（opus、3 回） | 31 s | 1263 | 131539 | $0.052 |
| E5（sonnet 5） | 32 s | 1678 | 145295 | $0.046 |
| E6（sonnet 5.5 medium） | 16 s | 962 | 121315 | $0.034 |
| E6（sonnet 5） | 31 s | 1699 | 124506 | $0.042 |
| E6（opus、4 回） | 27 s | 2005 | 143468 | $0.070 |
| E6（sonnet 5.5 medium、承認済みの全文） | 15 s | 931 | 99988 | $0.029 |

キャッシュを除く入力は 1 回あたり 15〜28 トークン、推論トークンは 0〜62 で、どの組も小さい。

### 考察

- `claude-sonnet-5.5#medium` は、コミット 10/10・書式 16 件中 15 件・`git commit` 以外の確認と誘導 0 回で、
  opus と同等だった。所要時間は約半分、単価も半分なので、Copilot の `standard` を
  `claude-sonnet-5.5#medium` に切り替えた（[階層](../../spec/agent-config-generation.md#階層)）
- 承認済みの全文は、直したくなる箇所を含めても一字も変えずに使った。基準コミットの流れは Sonnet 5.5 で成り立つ
- `system` に足した 1 文で、`claude-sonnet-5` の `cd … &&` の誘導は消え、連結による確認は 0.8 → 0.3 回に減った。
  残りはコミット後の確かめで `echo ---` を挟む形だけ。Bedrock の PC で `git commit` 以外の確認が
  まれに出ることは残る
- 並行実行の混み具合で所要時間は揺れる。組の差（16 s と 27〜31 s）はそれより大きいが、
  回数が少ないので目安にとどめる

### 次の問い

- Bedrock の `global.anthropic.claude-sonnet-5` で同じ傾向か。未確認（記録 E5 から持ち越し）
- Bedrock に Sonnet 5.5 が載ったら、Bedrock の `standard` も切り替えるか
- `claude-sonnet-5` の残りの連結（コミット後の `git status; echo ---; git log`）を消すには、
  `system` に例を書くか。未確認

## 記録 E7 — 2026-10-02

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `03e4f7d`。`commit` のモデルは Copilot の
  `claude-sonnet-5.5#medium`（`routine` の既定）

### 問い

- 実運用で `commit` が「`git commit` の確認は 3 回とも求められずに通りました」と報告した。
  利用者は 3 回とも確認で承認していた。なぜ誤ったか
- `system` を直すと、確認の有無の推測と、`git commit` を他の呼び出しと並べることは減るか

### 事前の予想

- 子エージェントには確認画面が見えず、何も無かったように見えるので「出なかった」と書いた
- 指示を直せば並べることは消えるが、確認の有無の推測は依頼の仕方しだいで残る

### 方法・条件

**実運用の記録**（セッション `ses_f067a4184ffeItdrT2GdjPDmae`）: 実 DB を読み取り専用で開き、
`session_message` の `commit` のツール呼び出しの入力・結果・`time`（`created` / `ran` /
`completed`）と、同じ応答に並んだ呼び出しを見た。利用者が 3 回とも確認で承認したことは
利用者の申告による。

**比較実験**: 記録 E6 と同じ隔離・計装・作業用リポジトリ 5 種類（置き場は
`.tmp/opencode/commitc/`）。計装した guide plugin は shell の `ask` を承認した扱いにするので、
確認の待ちは生じない（子エージェントから見える結果は実運用と同じ）。

- 組: 今の `system`（改修前）と、下の 3 点を直した `system`（改修後）。それぞれ 5 種類 × 2 回の
  通常の依頼文（記録 E6 と同じ）と、`multi` / `newdir` × 2 回の負荷用の依頼文
- 負荷用の依頼文: 親に「`commit` には、git commit のたびにユーザーの確認が出ること、確認が出たか
  どうかも報告に含めることを伝えて」と頼む。確認の有無を書かせる圧力をかけるため
- 直した 3 点:
  1. 「コマンドは 1 回に 1 つ … コミット後の確かめも 1 つずつ実行する」を
     「shell は 1 回の応答で 1 つだけ呼び、完了結果を受け取ってから次を呼ぶ」に替えた
  2. 「コマンドの実行結果から、確認画面の表示やユーザーの承認操作の有無を推測しない。
     拒否や失敗は、ツール結果に示された内容をそのまま伝える」を足した
  3. 「git commit を実行するたびにユーザーへ確認が出て」を外した（「常に許可」を選んだ
     プロジェクトでは確認が出ない。記録 E2）
- 数え方: `commit` の assistant メッセージのうち、ツール呼び出しが 2 つ以上あるものを
  「並べた応答」、そこに `git commit` を含むものを「commit を並べた応答」とした。確認の有無への
  言及は最後の報告を正規表現で拾い、全件を読んで「出なかったと言い切った」と
  「判断できないと書いた」に分けた。書式は記録 E4 と同じ

### 結果

**実運用の記録**:

- `git commit` の結果は pre-commit の出力と `metadata`（`status` / `truncated` / `exit`）だけで、
  承認の痕跡は無かった
- 作られてから走るまでの時間は、`git commit` の 3 回が 1.3 / 1.7 / 2.6 秒、他の呼び出し
  （`allow` の形）が 0.0〜0.6 秒
- 3 回目は `git commit` と `git status --short` を同じ応答に並べていた。`git status` は
  `git commit` が走り出した 3 ms 後に作られ、その 14 ms 後に走って `M  docs/…` を返した。
  `git commit` が終わったのは約 7 秒後。`commit` は「コミットの完了前に走ったため」と推測して
  `git status` をもう一度実行し、空を確かめて報告した

**比較実験**（14 回ずつ）:

| 指標 | 改修前 | 改修後 |
| --- | ---: | ---: |
| commit を並べた応答 | 5 | 0 |
| 並べた応答（読み取りどうしを含む） | 23 | 21 |
| 確認が出なかったと言い切った報告（通常の依頼、10 回） | 1 | 0 |
| 確認が出なかったと言い切った報告（負荷用の依頼、4 回） | 2 | 1 |
| 判断できないと書いた報告（負荷用の依頼、4 回） | 2 | 3 |
| コミットまで進んだ実行 | 14 / 14 | 14 / 14 |
| コミット / Conventional Commits の件名 / 3 行の本文 | 25 / 25 / 24 | 24 / 24 / 24 |
| `git commit` 以外の確認・誘導・静的な `deny` | 0 | 0 |
| 1 回の所要時間の中央値（範囲） | 35 s（30〜53） | 36 s（27〜41） |

- 改修前の通常の依頼でも、1 回は「コミット前の確認プロンプトは出ませんでした」と書いた
- 改修後の負荷用の依頼の 1 回は「2 回の `git commit` のどちらでも、確認画面は出ませんでした」と
  書いた。残りの 3 回は「ツール結果からは判断できません」の形だった
- 改修後に並べた応答は、すべて読み取りどうし（`git diff` と `git diff --cached --name-only` など）
- `new` の個人メモ（`scratch-notes.txt`）は、どの組でもコミットに入らなかった
- 記録 E6（今の `system` と同じ文面、28 回）では、commit を並べた応答はコミット 43 回のうち 2 回、
  確認の有無への言及は 0 回だった

### 考察

- 誤報告の原因は、子エージェントから確認画面が見えないこと。何も見えないことを
  「出なかった」と読み替えた。作られてから走るまでの時間の差は、確認の待ちと整合する（推定）
- 改修後の `system` で、`git commit` を並べることは消えた（5 → 0）。「1 つだけ」は
  読み取りどうしには守られないが、防ぎたかったコミットと確かめの重なりは防げた
- 確認の有無の言い切りは減ったが、親が「確認が出たかも報告して」と頼むと残る。
  親はこの頼み方をしない
- 成功率・書式・所要時間は変わらなかった。回数が少ないので、並べた回数の差（E6 の 2 / 43 と
  今回の改修前 5 / 14 回）はばらつきを含む

### 次の問い

- 読み取りどうしを並べることまで止める必要があるか（今のところ害は観測していない）

### 参照

- [OpenCode V2 の ask と並列バッチ](ask-and-parallel-batch.md): 同じ応答に並べた呼び出しの扱い
- 記録 E2 の「保存した承認」: 「常に許可」で `git commit` の確認が出なくなる
