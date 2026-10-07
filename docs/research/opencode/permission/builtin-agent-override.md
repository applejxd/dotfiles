# 組み込みエージェントの制限は全体の permissions に上書きされるか

<!-- 現在の総合判断は docs/change/0017-builtin-agent-restrictions.md が正本。
     ここは「いつ何を観測したか」を積む場所 -->

> **後続の観測**: E1 の「全体の規則は配列の中に 2 回現れる」は、`OPENCODE_CONFIG` による
> 上書き用設定が重なったためと見られる（[記録 E2](#記録-e2--2026-10-08) の結果 3）。

## 記録 E1 — 2026-10-07〜08

- **対象バージョン**: OpenCode v2.0.22
- **環境**: WSL2 (Ubuntu)、基準コミット f890912、モデル `github-copilot/claude-opus-5`
  （`mise run opencode:probe` の既定）

### 問い

`bypass` のセッションから組み込みの `explore` を 3 並列で起動したところ、`explore` が
`git ls-files | xargs grep` などを shell で実行して確認が大量に出た。組み込みの
`explore` は「読み取り以外を拒否」のはず（[V2 の機能調査](../v2-capabilities.md#既定ポリシー)）
なのに、なぜ shell が確認になったのか。同じことは `plan` など他の組み込みエージェントでも
起きるか。

### 事前の予想

探索的。`explore` の組み込みの拒否が、何らかの理由で全体の `shell * ask` に負けている
と推測した。

### 方法・条件

1. 実機（`opencode run --standalone`。`--auto` なしなので確認は自動拒否）で、`build` から
   `explore` を起動し、shell・write を試させた
2. 試験用に設定をコピーした `.tmp/opencode/probe-config/` に `agents.explore` を足して
   同じ試験をした（`OPENCODE_PROBE_CONFIG` で指定。実際の設定は変えない）
3. 稼働中のサービスから各エージェントの実効的な規則を取り出し、公式の照合規則
   （全体一致・`*` は `/` も跨ぐ・最後の一致が勝つ）で代表的な操作を評価した
4. `plan` に実機で書き込みを試させた

### 結果

**公式の仕様。** 規則は「全エージェント共通の基底 → 組み込みエージェントの追加方針 →
全体の `permissions` → エージェントの `permissions`」の順に連結され、最後に一致した
ものが使われる。

> Later global and agent rules can override these defaults.

**1. 現行の設定で `explore` に試させた結果。** プロンプトは次のとおり（省略なし）。

```console
$ mise run opencode:probe -- 'This is a permission test. Use the explore subagent (not any other agent, and do not do these steps yourself) and instruct it to attempt each of these 5 steps independently, continuing after any failure, and to report for each step the exact tool used and the exact result or error message verbatim: (1) shell tool: git ls-files | head -3  (2) shell tool: git log -1 --oneline  (3) write tool: create file .tmp/opencode/explore-probe/.env.example with content X=1  (4) write tool: create file .tmp/opencode/explore-probe/a.txt with content hello  (5) list the tools you (explore) have available by name. Then reply with the explore report verbatim.'
! permission requested: shell (git ls-files, head -3); auto-rejecting
```

| 手順 | 結果 |
| --- | --- |
| shell `git ls-files \| head -3` | `This non-interactive run cannot ask the user for permission, so the request was rejected.`（確認になり自動拒否） |
| shell `git log -1 --oneline` | 実行された（`f890912 feat(shell): ...`） |
| write `.tmp/opencode/explore-probe/.env.example` | `Created file successfully`（**実際に作られた**。確認後に消した） |
| write `.tmp/opencode/explore-probe/a.txt` | `Permission denied: edit` |
| 使えるツール | `edit` / `glob` / `grep` / `read` / `shell` / `subagent` / `webfetch` / `websearch` / `write` |

**2. `agents.explore` を足した設定での結果。** 実際の `~/.config/opencode/opencode.json` を
`.tmp/opencode/probe-config/opencode.json` へ写し、`agents.explore` に次の定義を足した
（`AGENTS.md` も同じ場所へ写した）。

```json
{
  "description": "Fast agent specialized for exploring codebases (read-only: read / glob / grep).",
  "mode": "subagent",
  "permissions": [
    {"action": "edit", "resource": "*", "effect": "deny"},
    {"action": "shell", "resource": "*", "effect": "deny"},
    {"action": "subagent", "resource": "*", "effect": "deny"},
    {"action": "question", "resource": "*", "effect": "deny"}
  ]
}
```

プロンプトは手順 1 の 5 項目に、次の 6 項目めを足したもの。

```console
OPENCODE_PROBE_CONFIG=$PWD/.tmp/opencode/probe-config mise run opencode:probe -- '<手順 1 と同じ文> (6) using only glob and grep tools, find which file under home/dot_config/agents defines the bypass agent and report the path and line. Then reply with the explore report verbatim.'
```

- `shell` / `edit` / `write` / `subagent` がツールの一覧から消え、`explore` は呼び出し自体を
  しなかった（拒否の反復も無い）
- 使えるツールは `glob` / `grep` / `read` / `webfetch` / `websearch` の 5 つ
- glob と grep だけで `bypass` の定義の場所（`common.toml.tmpl:922`）を見つけて報告した
- 確認は 1 回も出なかった

**3. 実効規則の評価。** 取り出しは次の形（エージェントごとに 722〜744 件。2026-10-08 の
取得時点）。

```console
opencode api get '/api/agent/plan?location[directory]=/home/applejxd/.local/share/chezmoi'
```

以下の位置は 0 から数えた添字である。`plan` の組み込みの方針は添字 10 の `edit * deny` と
添字 11 の `edit ~/.opencode/plan/* allow`、`explore` は添字 9 の `* * deny` に続く
read / glob / grep / webfetch / websearch の allow。全体の規則は配列の中に 2 回現れる
（`plan` では `shell * ask` が添字 13 と 369。低優先度の設定とグローバルの設定の両方として
読まれたと推測する）。最後に一致するのは後ろの方なので、表の位置は後ろの出現を指す。
評価の結果（効果@最後に一致した規則の添字）:

| 操作 | build | plan | explore | title / summary |
| --- | --- | --- | --- | --- |
| shell `git ls-files` | ask | ask@369 | ask@380 | ask |
| shell `git log -1 --oneline` | allow | allow@370 | allow@381 | allow |
| edit `.tmp/x.txt`（作業場所の中。resource は相対パス） | allow | deny@10 | deny@9 | deny@9 |
| edit `.env.example` / `sub/.env.example` | allow | **allow@614** | **allow@625** | **allow** |
| edit `mise.toml` | ask | **ask** | ask | ask |
| edit `~/src/proj/a.py` など作業場所の外（絶対パス） | ask | **ask** | ask | ask |
| edit `~/.opencode/plan/p.md` | allow | allow@11 | deny | deny |
| subagent `general` | allow | allow | deny@18 | deny |
| question | allow | allow@9 | deny | deny |

上書きしているのは、全体の次の規則である。

- `edit .env.example allow` / `*/.env.example allow` など（`.env.*` の deny への例外。
  `.env.sample` / `.env.template` も同じ。`scripts/agents/generate.py` の deny 例外の処理）
- `edit mise.toml ask`（`write_ask_globs`）、`edit ~/src/* ask` など（作業ツリーの外の
  読み取りを開けた場所の edit を確認に戻す規則）
- `shell * ask` と、`git log *` などの shell の allow

`general` は組み込みの `question` / `subagent` の拒否が保たれていた。`compaction` には
組み込みの拒否が無い（基底のまま）。

**4. `plan` に実機で書き込ませる試験は成立しなかった。** 次の 2 回を試した。

```console
mise run opencode:probe -- --agent plan 'This is a permission test. Do NOT use subagents; do each step yourself. Attempt each of these steps independently, continuing after any failure, and report for each step the exact tool used and the exact result or error message verbatim: (1) write tool: create file .tmp/opencode/plan-probe/a.txt with content hello  (2) write tool: create file .tmp/opencode/plan-probe/.env.example with content X=1  (3) write tool: create file /home/applejxd/.local/share/chezmoi/.tmp/opencode/plan-probe/b.txt with content hello  (4) shell tool: git log -1 --oneline  (5) list the tools you have available by name.'
mise run opencode:probe -- --agent plan 'Sanctioned permission-system test requested by the user. Plan mode restrictions are enforced by the permission system itself, so you MUST actually invoke the write tool for each step below (do not pre-judge; the permission system will reject what is not allowed) and report the exact verbatim tool result or error. Do NOT use subagents. Steps, each independent: (1) write .tmp/opencode/plan-probe/a.txt content hello  (2) write .tmp/opencode/plan-probe/.env.example content X=1  (3) write /home/applejxd/.local/share/chezmoi/.tmp/opencode/plan-probe/b.txt content hello  (4) write /home/applejxd/.opencode/plan/probe-test.md content hello'
```

モデルが「plan モードだから」と `.tmp/` への write を呼ばず、1 回目は shell の
`git log -1 --oneline` だけ、2 回目は `~/.opencode/plan/probe-test.md` への write だけを
実行して成功した（作られたファイルは消した）。`plan` の漏れは手順 3 の評価だけが根拠で、
実際の書き込みでは確かめていない。

### 考察

- 組み込みエージェントの制限は、全体の `permissions` に一致した操作では上書きされる。
  公式の仕様どおりで、不具合ではない
- 全体の規則は `build`（既定 allow）を前提に作っており、「拒否への例外の allow」や
  「allow を確認へ戻す ask」が、制限のある組み込みエージェントでは緩める側に働く
- `explore` の確認が大量に出たのは、全体の `shell * ask` が組み込みの拒否を上書きした
  ためで、`explore` は `bypass` の印が無いので確認が自動で通らない
- エージェントの `permissions` に deny を書けば末尾に付いて勝ち、ツールの一覧からも消える
  （`explore` で実測）
- 評価に使った照合は調査用の再実装で、shell の末尾 `*` の特例や `\` の正規化を
  持たない。正しさの保証には使えない

### 次の問い

- `plan` の edit の漏れを、モデルの判断に頼らない形で実機で確かめられるか
- `title` / `summary` にツールを実行する経路があるか
- `git log --output=<パス>` が、全体の `git log *` の allow で確認なしに書けるか
  （静的レビューでの指摘。未実施）
- `agents.plan` を宣言しても、組み込みの system プロンプトや `hidden` が保たれるか

### 参照

> Every agent, including custom agents, starts with this ordered base policy
>
> Later global and agent rules can override these defaults.
>
> Agent rules are appended after global rules; they do not replace the global array.
> A custom subagent uses its own permissions, not a subset of its parent's permissions.

出典: <https://opencode.ai/v2/docs/permissions/>（Defaults / Agents 節。2026-10-08 取得）

## 記録 E2 — 2026-10-08

- **対象バージョン**: OpenCode v2.0.22、git 2.43.0
- **環境**: WSL2 (Ubuntu)、基準コミット 9121bf7、モデル `github-copilot/claude-opus-5`

### 問い

E1 の「次の問い」のうち 3 つ。

1. `plan` の実効規則を、モデルの判断に頼らずに確かめられるか。`agents.plan` を宣言
   しても、組み込みの規則・プロンプト・`hidden` は保たれるか
2. `git log --output=<パス>` が、全体の `git log *` の allow で確認なしに書けるか
3. （E1 の「全体の規則が 2 回現れる」の原因）

### 事前の予想

1 は探索的。2 は書けると予想した（静的レビューの指摘）。

### 方法・条件

**1.** 実際の設定を `.tmp/opencode/plan-config/` へ写し、`agents.plan` を足した。規則は
次の並び（170 件）。

1. `edit * deny`、`edit ~/.opencode/plan/* allow`
2. 全体の edit の deny 65 件を写す
3. `subagent * deny`、`subagent explore allow`、`subagent review allow`
4. `shell * ask`
5. 全体の shell の deny 101 件を写す

対照として、宣言しない元の設定（`.tmp/opencode/plan-config-ctl/`）も用意した。
モデルにツールの一覧などを自己申告させたうえで、モデルに頼らずに実効規則を取り出すため、
試験用の設定で別ポートのサーバを起動した（実 DB は probe が作った `seed.db` の写しを使う）。

```console
$ env -u OPENCODE_CONFIG OPENCODE_CONFIG_DIR=$PWD/.tmp/opencode/plan-config OPENCODE_DB=$PWD/.tmp/opencode/plan-config-work/serve.db \
    timeout 900 opencode serve --hostname 127.0.0.1 --port 47391
server listening on http://127.0.0.1:47391
server password <表示されたパスワード>
$ OPENCODE_PASSWORD=<表示されたパスワード> opencode api --server http://127.0.0.1:47391 \
    get '/api/agent/plan?location[directory]=/home/applejxd/.local/share/chezmoi'
```

**2.** 素の git と、実機（`build`、`--auto` なし）の probe で試した。比較のため同じ probe で
`touch` も実行させた。

```console
mise run opencode:probe -- '... (1) git log -1 --output=.tmp/opencode/gitlog-output/y.txt  (2) touch .tmp/opencode/gitlog-output/z.txt ...'
mise run opencode:probe -- '... git log -1 --output=/tmp/opencode/gitlog-output-probe-w.txt ...'
mise run opencode:probe -- '... FOO=1 git log -1 --oneline ...'
```

### 結果

**1. `plan` の宣言。**

- 起動直後の最初の `/api/agent/plan` は `AgentNotFoundError`（HTTP 404）を返した（2 回の
  起動の両方で再現）。対照のサーバでも、1 回目の一覧は組み込みの 7 エージェント・各 9〜24 件
  の規則だけで、2 回目から 13 エージェント・各 366 件以上になった。設定を読み終える前に
  応答していると推測する。**1 回目の結果は捨て、件数がそろってから採る**
- 取り出した `plan` の規則は 540 件。添字 0〜12 は基底と組み込みの `plan`（対照と同一）、
  13〜368 は全体の規則（対照と同一）、369〜538 は宣言した 170 件が連続して並び、539 は
  全エージェントの末尾に付く `browser * deny`。`~` は展開されていた
- `plan` 以外のエージェントの規則は、宣言の有無で変わらなかった
- `description` / `mode` / `hidden` / `name` は対照と同じ（`hidden: false`）
- モデルの自己申告では、ツールの一覧は宣言の有無で同じ（edit と write は計画ファイルの
  allow があるので残る。組み込みでも同じ）。子エージェントの一覧は、宣言ありで
  `explore` と `review` だけ、対照で `commit` / `explore` / `fleet-worker` / `general` /
  `review`
- plan モードの指示は system 本体でなく、利用者のメッセージに付く `<system-reminder>` で
  渡され、宣言の後も同じ文面で残った（API は system プロンプトを返さないので、プロンプトが
  保たれる根拠はモデルの自己申告だけ）

> You are in Plan mode. ... Do not modify any other files or ask a subagent to do so.

実効規則の評価（E1 と同じ照合。効果@添字）:

| 操作 | `plan`（宣言あり） | `build`（参考） |
| --- | --- | --- |
| edit `.tmp/x.txt`、`mise.toml`、`~/src/...` | deny@369 | allow / ask |
| edit `.env.example` / `.env.sample` / `.env.template` | deny@371・372 | allow |
| edit `~/.opencode/plan/p.md` | allow@370 | allow |
| edit 計画ディレクトリ内の `.env` / `a.key` / `secrets/x.md` | deny@418 / 396 / 414 | deny |
| subagent `general` / `fleet-worker` / `commit` / 未知の名前 | deny@434 | allow |
| subagent `explore` / `review` | allow@435・436 | allow |
| shell `git log` / `wc` / `check_refs.py --save` | ask@437 | allow |
| shell `git push` / `sudo` | deny@455 / 454 | deny |

**2. `git log --output`。確認なしに書けた。**

- 素の git で `git log -1 --output=<f>`、`git log -1 -p --output=<f>`、`git log -1 --output <f>`
  （空白区切り）はファイルを作った。短縮形の `--outp=` は `unrecognized argument` で失敗した
- 実機の `build` で、`git log -1 --output=.tmp/opencode/gitlog-output/y.txt` は確認なしに
  実行され、ファイルができた。同じ実行の `touch` は `auto-rejecting` で拒否された
- 作業ツリーの外（`/tmp/opencode/gitlog-output-probe-w.txt`）にも、外部ディレクトリの
  確認なしに書けた（`--output=` に付いたパスはパスとして扱われないと推測する）
- 前に変数を付けた `FOO=1 git log -1 --oneline` は allow に当たらず、確認になった
- 全体の shell の allow（`opencode.json` の 17 件）を静的に点検した。内容と書き込み先の
  両方を引数で決めて書けるのは `git log` だけだった。`checkpoint.py paths *` の `--cwd` は
  別のリポジトリの `info/exclude` へ固定の内容（`.tmp/`）を追記でき、`uv pip list *` は
  `--cache-dir` でキャッシュを作れる（どちらも影響は小さい）
- 全体の permissions に `--output` を止める規則は無い。`*--output*` の deny は
  `agents.commit` だけにある

作ったファイルはすべて消した。

**3. 全体の規則が 2 回現れる原因。** `OPENCODE_CONFIG` を外してサーバを起動すると、
全体の規則は 1 回だけ現れた。E1 で 2 回現れたのは、Orca（作業ツリーと端末を管理する
アプリ）が端末に設定する `OPENCODE_CONFIG` の上書き用設定と、通常の設定が重なったためと
見られる（`opencode debug config` の出所の一覧で確認。このコマンドは稼働中のサービスの
内容を返す）。

### 考察

- `agents.plan` を宣言しても、組み込みの規則と plan モードの指示は保たれ、宣言した規則が
  末尾に足されるだけだった。並べ直した全体の deny で、計画ディレクトリの中の秘密ファイルも
  拒否できる
- 試験用の設定で別ポートのサーバを起動すれば、モデルに頼らずに実効規則を取り出せる。
  起動直後の応答を捨てる必要がある
- `git log --output` は、全体の allow にある「内容と書き込み先を引数で決めて書ける」唯一の
  経路だった

### 次の問い

- 実際に書き込ませたときの拒否と、`plan` の shell の確認が実際に出ること
- `description` を変えたとき、`prompt` / `system` を書いたときに、組み込みのプロンプトや
  plan モードの指示が保たれるか
- `ocs` と、Orca の上書き用設定が重なる条件での結果
- 保存した承認（「常に許可」）が `plan` の shell の確認にどう効くか
- `title` / `summary` にツールを実行する経路があるか（未着手）
