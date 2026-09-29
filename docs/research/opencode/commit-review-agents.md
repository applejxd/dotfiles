# OpenCode V2 の commit / review エージェントの実機確認

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

> **現行の仕様**: [子エージェント](../../spec/agent-config-generation.md#子エージェント)

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
  [`commit` の権限](../../spec/agent-config-generation.md#commit-の権限)
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
