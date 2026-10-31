# 判定 API（`decide`）

pi のフルガードが、ツールの呼び出しを実行してよいかを問い合わせる判定器。CLI に依存せず、
**どの入力にも allow / ask / deny と理由を返す**。本番の実装は TS 版（`home/dot_config/pi/harness/judge/`。[TS 版への移植](#ts-版への移植)）。
Python 版（`decide.py` と、`bashrules` / `command_policy.py`）は、TS 版の正解データの出力元として残っている（撤去は [CHG-0035](../../change/0035-retire-python-judge-oracle.md)）。
以下の `check_bash.py` は Claude Code / Copilot CLI の Python 版の hook の名前で、判定の hook の登録は外してある。`check_bash.py` はこの判定器を使わない。

移行の計画と経緯は [CHG-0020](../../change/0020-pi-migration.md)。呼び出し側は [pi のガード](pi-guard.md)。

## 置き場

| 実体 | 配置先 | 役割 |
| --- | --- | --- |
| `home/dot_claude/hooks/executable_decide.py` | `~/.claude/hooks/decide.py` | CLI。stdin の JSON を 1 つ読み、stdout に応答を 1 つ書く |
| `home/dot_claude/hooks/lib/decide.py` | `~/.claude/hooks/lib/decide.py` | `decide(request)` の本体（Python 版。正解データの出力元。本番の判定は `judge/decide.ts`） |
| `home/dot_config/agents/common.toml.tmpl` の `[pi]` | `~/.config/agents/common.toml` | 役割（`[pi.profiles]`）と、pi が正本の共有の節（[pi と共有する節](../agent-config-generation.md#pi-と共有する節)） |

`~/.claude/hooks/` に置くのは、判定の中身（`bashrules`）がそこにあるため。`AGENTS_CONFIG_DIR` で
`command_policy.py` と `common.toml` の置き場を差し替えられる（hook と同じ）。

## 入力と応答

```text
request:  { tool, input, cwd, role, bypass?, boundary? }
response: { decision: allow | ask | deny, reason, source: rule | check | default | error, ... }
```

| キー | 中身 |
| --- | --- |
| `tool` | `bash` / `read` / `edit` / `write` / `grep` / `find` / `ls` / `task`（子エージェントの起動）/ `todo`（タスクリストの拡張）/ `ask`（利用者への質問の拡張）と MCP のツール（`mcp__…`）。フルガードがツールを別名で登録していても、元の名前で渡す。役割の `tools` に無い名前は deny |
| `input` | ツールの引数。`bash` は `command`、ファイルのツールは `path`（`grep` / `find` / `ls` は省略すると `.`） |
| `cwd` | 作業ディレクトリの絶対パス。相対パスの解決と「作業ツリーの中か」の判定に使う |
| `role` | `[pi.profiles]` の名前（「役割」の表） |
| `bypass` | 真なら ask を allow にする（deny は変えない。[confirm](#confirm) の ask は除く） |
| `boundary` | サンドボックス（Fence）の内側と**証明できているか**（フルガードがカナリアで実測した結果。環境変数の自己申告ではない）。真のときだけ、評価の順番の 4' の緩和が効く |
| `allowed` | `{ read, write }`。サンドボックスが実際に開けた場所。`boundary` が真のとき、作業ツリーの外の読み書きの判定に使う（形が違えば `source: error` の deny） |

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
     次に役割が `action` ツールを持つときだけ、`[[pi.actions]]` の `replaces` に当たれば deny（呼び出し例つき。bypass でも外れない。[guarded_action](pi-extensions.md#guarded_action承認つきの外部操作)）。
     次に役割の `shell_deny` に当たれば deny（bypass でも外れない）。次に [confirm](#confirm)（bypass でもサンドボックスの緩和でも allow にならない ask）。次に `check_bash.py` の ask 側（`[bash] ask` と意味解析）。
     当たらず、全部の区切りが `[pi.shell] allow`（役割に `shell_allow` があればそちら）に当たれば allow。
     `>` `<` `` ` `` `$` `--output` を含む形は allow にしない（`$` は変数展開と語分割で、`env LANG=C${IFS}GIT_PAGER=id git log` のように代入を後から作れるため）。元のセグメントの `git` のグローバル領域（`git` とサブコマンドの間）に `-c` `--config-env` `--exec-path` `--paginate` `-p` があるか、サブコマンド以降に `--ext-diff` `--textconv` `--exec` `--upload-pack` `--receive-pack` がある形も allow にしない（ページャーや外部 diff でプログラムが起動しうるため。正規化前のトークンで見る。サブコマンドの後ろの `-p` `-c`（`git log -p` など）は従来どおり。`-C` `--no-pager` `-P` `--git-dir` `--work-tree` も従来どおり）。コマンド全体（位置に関係なく。括弧・波括弧・`if` の中や `xargs env` の後ろも含む）の `NAME=value` 形のトークン（先頭の `(` `{` `;` `!` は除いて見る）は、名前が `LANG` `LC_*` `TZ` `NO_COLOR` `COLUMNS` `LINES` `TERM` `CI` `FORCE_COLOR` `CLICOLOR` `PYTHONDONTWRITEBYTECODE` のときだけ許し、それ以外のトークンや、`-` 始まりの引数を持つ `env`（`-i` `-u` `-S` `-C`）があれば allow にしない（既定の判定に落ちる。`-` 始まりの `--grep=a=b` は対象外。引用の中や shlex が失敗する形も同じ）。`[pi.skill_scripts]` の宣言どおりの形も allow
   - 読み取り: `[file] read_ask_globs` は ask。作業ツリーの中と `[pi.external_read]` の中は allow。それ以外の外は ask
   - 書き込み: `[file] write_ask_globs` は ask。作業ツリーの外は ask。中は allow
   - `task`: allow（子は同じフルガードと判定器で、子の役割で判定される）
   - `todo`: allow（メモリの状態だけを変える。拡張は[自作の拡張](pi-extensions.md#自作の拡張-todo--plan--btw)）
   - `ask`: allow（利用者への質問。UI だけを使い、ファイルも外部も触らない。[自作の拡張](pi-extensions.md#自作の拡張-todo--plan--btw)）
   - `action`: 役割の `tools` にあれば allow（`source: rule`。確認はツール自身が `execute()` で 1 回だけ行うので、汎用の ask は出さない。[guarded_action](pi-extensions.md#guarded_action承認つきの外部操作)）
4. **既定**。役割の `default`（実装役は ask、読み取り役は deny）
4'. **サンドボックスの緩和**（`boundary` が真のときだけ）。bash は、どの規則にも当たらず役割の既定（ask）になったものだけを allow にする（`sandboxed: true`）。
   作業ツリーの外の読み書きは、`allowed` が開けた場所なら allow、外は理由つきの deny（`allowed` が無ければ基準の ask）。ask の規則・deny・誘導は変えない
5. **bypass**。3・4 の ask だけを allow にする（`mustConfirm` の ask は除く）

`rm` の承認の免除（`ask_hook_owned`）は、hook と同じく `[bash] ask` から外れる。判定器ではその先の
既定（実装役は ask）に落ちるので、作業ツリーの中の `rm` も確認になる（今の OpenCode と同じ）。

## confirm

bypass でも確認を出す ask。外部への送信・公開（issue や PR の投稿など）を、`pis` の標準起動（サンドボックス＋bypass 既定オン）でも確認なしに通さないための仕組み
（[CHG-0038](../../change/0038-guard-reclassification.md)）。ガードは境界ではなく「うっかり防止」（Python などで迂回できる）。強い保証は PAT のスコープとブローカーで。

- **属性**: 応答の `mustConfirm: true`（`decision` が `ask` のときだけ）。**bypass（手順 5）も、サンドボックスの緩和（手順 4'。`source: default` だけに効く）も、この ask を allow にしない**。
  理由の先頭は「確認が必要な外部への送信・公開 (bypass でも確認する): 」。確認の UI と時間切れは[ハーネス側](pi-guard.md#confirm-の確認)
- **確認表**（`[pi.confirm] bash`。前方一致の文字列の配列。`[bash] ask` と同じ正規化済みセグメントの照合なので、`cd x && gh pr create`、`gh -R o/r pr create` も当たる）: `gh pr create/edit/review/comment/close/reopen/ready`、
  `gh issue create/edit/comment/close/reopen/lock/unlock/transfer/pin/unpin/delete`、`gh repo fork/rename/archive/unarchive`、`gh workflow run/enable/disable`、`gh variable set/delete`、`gh gist edit/delete`。
  評価の位置は、**役割の `shell_deny` の後、`bashAsk` の前**（`[bash] allow`・`skill_scripts` に先取りされない）
- **確認に格上げする検査**（`[pi.confirm] checks`）: `check_gh_api_mutation` の ask。**他の ask（`check_policy_ask` など）より先に引く**
  （`git commit -m x && gh api -X POST …` のような複合で、先に別の ask が当たって bypass で通らないように）。`curl`/`wget` の POST と MCP は、従来どおり bypass 可能な ask
- **本文を確認できない形は deny**: 確認表に当たった `gh pr|issue create|comment|edit|review` で、本文・タイトルが標準入力（`--body-file -`、`-F -`、`-b -`）、
  またはコマンド置換（`$(…)`・バッククォート）を含むとき
- **公開・配布は deny**: `[bash] deny` に `gh repo edit`・`gh repo create`・`gh release delete/edit`・`npm/yarn/pnpm/uv publish`・`twine upload`・`cargo publish`・`gem push`・`docker push`。
  `gh api` の兯開・配布に当たる操作は、新しい deny 検査 `check_gh_api_publish`（TS と Python の両方）: REST の `repos/{o}/{r}` の PATCH・DELETE、
  コンテンツ・git refs/commits/trees/blobs/tags・releases・pages・hooks・collaborators・dispatches・actions secrets、`user/repos`・`orgs/*/repos` の POST、
  GraphQL の `createRepository`・`updateRepository`・`deleteRepository`・`archiveRepository`・`transferRepository`・`createRef`・`updateRef`・`deleteRef`・`createCommitOnBranch`・`mergePullRequest`。
  これは **GitHub API 経由の push 相当**（コンテンツ API・Git データ API）を塞ぐ。それ以外の書き込みは ask（確認に格上げ）
- **表に無い外部書き込みは、従来どおり**（役割の既定の ask。サンドボックスでは allow）。この表では「すべて」を捕捉できない（すり抜けを許容する範囲）
- **元に戻せないローカルの git 操作**（`[pi.confirm] local_git = true`。`judge/gitdestructive.ts`）: `git branch -D/-M/-f/--delete --force`（`-fd`・`-df` など束ねた形を含む）、`git clean`（`-n`/`--dry-run` が無いもの）、`git tag -d/--delete/-f`、`git checkout -B`、`git switch -C/--force-create`。
  前置の環境変数・`env`・`git` のグローバルオプション（`-C`・`-c`・`--git-dir`・`--work-tree` など）を読み飛ばしてから、サブコマンドとフラグを見る（`--` 以降と、値を取るオプションの値は数えない。`git clean -e '-n' -f` は dry-run と見なさない）。
  評価の位置は、確認表の直後・`bashAsk` の前。**ask が既定の役割（親・`worker`）は、bypass でもサンドボックスの緩和でも ask のまま（理由の先頭は「確認が必要な元に戻せない git 操作 (bypass でも確認する): 」）**。
  **既定が deny の役割（`explorer`・`reader`・`committer`）は deny**: これらは `[bash] ask` が役割の既定の deny より先に当たり、`git branch -D`・`git clean`・`docker rm` が bypass で allow になっていた（2026-10-29 に実測。ask 一般の扱いは[次の節](#既定が-deny-の役割の-ask)）。
  保証の範囲は既存と同じ「うっかり防止」で、git の alias・外部スクリプト・動的に組み立てた文字列は見ない。素の `git branch` の作成・切り替え・`git tag` の作成などは従来どおり。ブランチモデル（[CHG-0047](../../change/0047-gitflow.md)）の `git flow` は、利用者が自分のシェルで実行する（bash の `git flow` の deny は [CHG-0050](../../change/0050-slim-guarded-action.md) で撤去した）
- **保護ブランチへの統合の確認（`[pi.confirm] integration = true`。[CHG-0053](../../change/0053-worktree-integration-gate.md)）**: bash（と `bg_run`）の統合コマンドを、**bypass でも省略できない必須確認**（`mustConfirm` の ask。見出しは「保護ブランチへの統合」）にする。判定器ではなく、**ハーネスの `decide`（`index.ts`）が、判定器の結果を引き上げる**（`integration-gate.ts`。緩める方向には働かない: deny と、すでに必須確認のものはそのまま）。Python 版と golden の判定は変わらない（TS だけ）。分類は `judge/gitintegration.ts` の静的な検出器（前置の環境変数・`env`・`command`・git のグローバルオプションを読み飛ばし、引用内と heredoc の本文は数えない）:
  - **always**（どこからでも必須確認）: 保護 ref を直接変える操作。`git flow {feature,release,hotfix,support,bugfix} {finish,delete,abort}`、`git flow integrate`、`git-flow` の同じもの、`update-ref <保護 ref>`、`symbolic-ref`、`branch -m/-c/-f` の対象が保護 ref、`branch <保護 ref>`、`fetch` の宴先が保護 ref、`worktree add -b/-B <保護 ref>`
  - **unknown**（必須確認）: 対象を静的に決められない。`cd`・`-C`・`--git-dir`・`GIT_DIR=` と統合系を同じコマンドに含む、`-c alias.`、`update-ref --stdin`、`reflog delete`、`fast-import`、宴先が `$VAR`
  - **head**（`merge`・`cherry-pick`・`revert`・`pull`・`am`・`reset`）: 現在のブランチを動かす。**cwd が自由区（feature の linked worktree。`freezone.ts`）なら日常の操作なので判定器の結果のまま**、自由区の外と、判定できないとき（deny にせず）は必須確認
  - git を起動するのは head のときだけ（最大 2 回、時間切れ 3 秒）。毎回の edit / write や通常の bash では起動しない。一覧外の git の書き込みは今までどおり
  - 保護の範囲は「ガードが識別する直接経路」。alias・外部スクリプト・別プロセスの中の ref の書き込み・利用者のシェルは見ない。子のエージェントと UI の無い実行では、確認を出せないので拒否する
  - 設定: `[pi.integrate]`（`enabled`・`target`・`protected_refs`・`risk_paths`・`skip_confirm_in_free_zone`）は、`protected_refs` だけが今は効く。下限（`main` / `master` / `develop` / `release/*` / `hotfix/*`）を欠くと生成器が拒否する。ワイルドカードは末尾の `/*` だけで、比較は大文字小文字を区別しない（`judge/protectedrefs.ts`）。OpenCode の生成物には写さず、Python 版は読まない。`risk_paths`・`enabled` は後続の段（専用操作）が使う。`skip_confirm_in_free_zone` は同梱の設定で true（feature の linked worktree の `git_commit` を確認なしで実行する。[pi-extensions.md](pi-extensions.md#guarded_action)）
  - 試験: `test_pi_integration_judge.py`（分類の表）、`test_pi_integration_gate.py`（引き上げと自由区の実 git・git の起動回数）、`test_pi_freezone.py`、`test_pi_integrate_config.py`、`test_pi_harness.py`（実際の tool_call での確認）、`test_pi_confirm_view.py`（見出し）。未確認: 実機（Orca・TUI）での見え方
- **Python 版（照合用）**: `local_git` も知らない。`[pi.confirm] local_git` の判定は TS だけで、[正解データの照合](#差分試験正解データ)の標本に `git branch -D` などがあれば、TS が ask＋mustConfirm、Python が ask または allow＋bypassed の組を一致とみなす
- **Python 版（照合用）**: `mustConfirm` を知らない。[正解データの照合](#差分試験正解データ)では、`mustConfirm` を比較から外し、
  TS が ask＋mustConfirm、Python が ask または allow＋bypassed の組を一致とみなす（標本は除かない）。`[bash] deny` と `check_gh_api_publish` は両方に効く

## 既定が deny の役割の ask

`[bash] ask` と意味解析の ask は、**役割の既定より先に**返る。bypass は ask を allow にするので、既定が deny の役割（`explorer`・`reader`・`committer`。いずれも子）でも、
`docker rm`・`git clean`・`git branch -D`・`gh pr checkout` などが、親から bypass を継ぐと確認なしで通っていた（2026-10-29 に実測）。

- **規則**（`judge/bash.ts` の `denyForDenyDefaultRole`）: `profile.default` が `deny` の役割で、`bashAsk` の結果が **ask（`mustConfirm` でない）**なら、**deny** にする。
  理由は元の ask の文言に「この役割は既定が deny なので、承認で通さない (bypass でも通さない)」を添える。`source` と `check` は元のまま
- **変えないもの**: ask が既定の役割（親・`worker`）。`mustConfirm` の ask（子では UI が無く、ハーネスが拒否する）。許可（`shell_allow`・`[pi.skill_scripts]`）は `bashAsk` の後ろで評価されるので、
  ask に当たらないコマンド（Web 検索のスクリプト・`wc`・読み取りの `git log/diff/status`）は従来どおり通る。**許可と ask の両方に当たるコマンドは、この規則で deny になる**
- **`local_git` との関係**: `local_git` の deny は残す。検出器が違い、複合（`git clean -fd && gh api -X POST …`）や別の書き方でも、後続の ask（mustConfirm を含む）に緩めずに先に deny を返すため
- **照合**: Python の正解データは ask（bypass なら allow）。TS の deny は、`judge_golden.mjs` が、役割・bash・元の理由・`source`・`check` を比べて一致とみなす
- **残る範囲**: ファイル読み取りの ask は bypass で allow のまま。`worker` は ask 既定で bypass を継ぐので、`docker rm` などは通る

## ssh / scp の許可

`[bash] deny` の `ssh` は残したまま、`[pi.remote_exec] targets` に載せた宛先（`sbx@sandbox-gpu`）への `ssh <宛先> <コマンド>` だけを、
`<コマンド>` をリモートで実行される文字列として**通常の判定**（共通の禁止・誘導・ask・allow）にかける（`judge/bash.ts` の `unwrapRemoteExec`）。
`ssh sbx@sandbox-gpu git push` は `git push` の deny、`... git log` は `[pi.shell] allow` の allow になる。

- 展開するのは 1 段だけ。リモート側の `ssh` は deny に当たる
- 次の形は展開せず、`ssh` の deny のまま。宛先の前のオプション（`-o ProxyCommand=…` / `-J`）、コマンドなし（対話 shell）、他の宛先、
  ローカルの shell が先に解釈する文字（クォート外の `; & | < > ( ) { } $ \` * ? [ ~ # !`・改行・`\`、二重引用符内の `$` `` ` `` `\` `!`）、閉じていないクォート
- 判定のパスの検査（`~/.ssh` など）はローカルの `cwd` / ホームで行う。リモートのパスとは対応しない（厳しめに倒れる）
- リモートで動くので、リモート側のファイルへの `read` / `write` の境界判定は効かない。信頼できる宛先だけを載せる

`scp` も同じ宛先だけを許す。リモート側を `/dev/null` に置き換えた `cp` として判定するので、ローカル側の読み取り（`.env` / `~/.ssh` などの持ち出し）と
書き込み（`~/.bashrc` など）の検査が `cp` と同じに効く。許すのはオプション `-r -p -q -C -v` だけ、リモートがちょうど 1 つの
アップロード（`scp a b <宛先>:パス`）かダウンロード 1 件（`scp <宛先>:パス ローカル`）。
`-o` / `-P` / `-J`、別ホスト、`scp://`、リモート同士の転送は deny のまま。リモートのパスは判定しない。

## 誘導

`[[pi.guide]]` に当たる bash のコマンドは、より適したツールへの案内を理由にして deny する（応答の `guide` に id）。
今は 6 件で、読み書きを pi のツールへ寄せるものと、バックグラウンド実行を `bg_run` へ寄せるもの（2 件。長い `sleep` を含む）。

| id | 止める形 | 案内 |
| --- | --- | --- |
| `read-cat-head-tail` | `cat` / `head` / `tail` での読み取り（パイプ・リダイレクト・`-c` / `-f` は除く） | read ツール |
| `read-sed-n` | `sed -n` での読み取り | read ツール |
| `write-cat-tee-heredoc` | `cat >` / `tee` とヒアドキュメントでのファイル作成 | write ツール |
| `write-heredoc-script` | ヒアドキュメントでスクリプトを渡す形 | write ツールで書いてから実行 |
| `bg-run-instead-of-ampersand` | 行末の `&`、両側が空白の `&`（`a & b`）、行頭の `nohup` / `setsid`、`disown` | `bg_run` ツール（終了通知でターンが再開する。bash の `&` は通知が届かない） |
| `long-sleep-in-foreground`（`scope = "foreground"`） | コマンドの先頭や `;` `&&` `&` `(` `do` `then` `else`、パイプの直後の `sleep`。秒数が 10 以上、`m` / `h` / `d`付き、`infinity` | `bg_run` で待つコマンドを起動する（終わったときの通知でターンが再開し、待つ間も会話を続けられる） |

`scope = "foreground"` の誘導は、**`guarded_bash` だけ**に効く（`judge/call.ts` が当てる。`bg_run` の中身（`sleep 300` を待つジョブそのもの）には当てない）。
判定器本体（`judge/bash.ts`、`decide.py`）は scope 付きを評価しない。`sleep 9` 以下と `sleep 1.5` は通る。`echo sleep 30` や `grep 'sleep 30'` は、先頭の条件で当たらない。
**既知の限界**（`&` の規則と同じ、引用を解釈しない。試験で固定済み）: 引用内やヒアドキュメント本文の `; sleep 30` や行頭の `sleep 30` は当たる（過剰な拒否）。
`unless` はコマンド全体に効くので、`git commit -m 'ok'; sleep 30` のように git / gh の `-m` と併記した本物の `sleep` は見逃す。
計測した頭数は少ない（利用者の設計としては「うっかり防止」で、悪意の回避は対象外。`timeout 30 sleep 30`、`bash -c 'sleep 30'`、`read -t 30`、`sleep 9; sleep 9` は通る）。
連結や `bg_log` の連打で待つ形は、規則では止めず、`bg_run` / `bg_log` の説明・戻り値の「通知が届くので待たない」の案内で減らす（[ツール側に置く理由と経緯](pi-guard.md)）。
`scope` 付きの id を `[[opencode.shell.guide]]` の `pi = "<id>"` から参照すると、生成で止まる（OpenCode の guide plugin は scope を読まず、意味が変わるため。`test_bad_guide_references_stop_generation`）。
この規則の由来と実モデルでの確認は[記録](../../research/agents/pi-decide-guide-sleep-origin.md)。

`bg-run-instead-of-ampersand` は pi 専用。`&&` / `2>&1` / `&>` / `|&` / URL の `?a=1&b=2` は当たらない。
引用内の `a & b`（`echo "Q & A"`、`git log --grep='a & b'`、`echo a \& b`、ヒアドキュメント本文、コメントなど）は、引用と区別できないので**当たる**
（割り切り。回避: `&` の両側の空白を外す。git / gh の `-m` / `--title` / `--body` などは `unless` で外す）。
**`unless` はコマンド全体に効くので、`gh pr create --title x & sleep 20` のように本物のバックグラウンドを併記する形は見逃す**（既知。
実際に起きる頻度は低いと見ているが未計測）。引用を考慮した判定（TS の判定器で引用外の演算子だけを見る）は、これらが実害になったときの候補。
行の途中の `&` を対象に足したのは、実際のモデルがすり抜けたため（`grok-4.7` の `sleep 20 & echo $!`、`gpt-6-sol` の `… & pid=$!`。
[実験 B1 の F6](../../research/agents/pi-bg-experiments.md)）。

- OpenCode の guide plugin も同じ `[[pi.guide]]` を使う。`[[opencode.shell.guide]]` の `pi = "<id>"` が、
  並びのどこに差し込むかを決める（[pi と共有する節](../agent-config-generation.md#pi-と共有する節)）
- 正規表現は Python（判定器）と JavaScript（guide plugin）の両方で同じ意味になるものだけを書く。
  `test_pi_shared.py` が代表のコマンドで両方の結果を突き合わせる
- OpenCode の誘導のうち、次は pi には入れていない（判定器のほかの規則で足りる）。
  > OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は[評価の順番](#評価の順番)。

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
| `implementer` | 7 つのツール・`task`・`todo`・`ask`・`mcp__*` | ask | `shell_deny` は git の状態を変える操作など（`git flow`・`git-flow` の拒否は [CHG-0050](../../change/0050-slim-guarded-action.md) で撤去） | 親（主エージェント） |
| `reader` | read・grep・find・ls | deny | — | 利用者が `pis --role reader` で選ぶ読み取り専用の親。子の `plan` 役も使う（`[pi.agents.plan]`。bash を持たないので、`skill_scripts` の許可が通らない）。harness の読み取り専用の子の一覧 `READ_ONLY_CHILD_PROFILES` に含む（`/btw` の入口と、計画モードの間に起動できる子）。bash を持たない役割の試験にも使う |
| `explorer` | `reader` + bash | deny | `shell_allow` に `wc` と読み取り専用の git（`status` / `diff` / `log` / `show` / `ls-files`） | 子の `explore` / `review` |
| `committer` | bash・read・grep・find・ls | deny | `shell_allow` に `git status` / `git diff` / `git log` など。`shell_deny` に git の状態を変える操作 | 子の `commit` |
| `orchestrator` | read・grep・find・ls・task・todo・ask・action | deny | 許可リスト。`bash`・`edit`・`write`・MCP を持たない。`/orchestrate on` の間だけ、親の役割になる（[親の絞り込み](pi-subagents.md#親の絞り込みorchestrate)） | 親（利用者が切り替える） |
| `worker` | 7 つのツール | ask | `shell_deny` に git の状態を変える操作 | 子の `worker` |

**既定の役割**は `[pi] default_role`（`common.toml`。既定は `implementer`）。`pis` は `--role` / `PI_HARNESS_ROLE` で上書きでき、
`[pi.profiles]` に無い名前は、生成が止まる。

`git status` / `git diff` は `.git/config` 経由でコマンドを起動しうるので、全体の `[pi.shell] allow` には載せず、
`committer` の `shell_allow` だけに置く（今の OpenCode の `commit` と同じ）。

`tools` が文字列の配列でない・`default` が allow / ask / deny でない・`shell_allow` / `shell_deny` が文字列の
配列でない・名前が無いときは、`source: error` の deny。

## 試験

`test/agents/test_decide.py`。

- 契約: 不正な入力と、CLI の空・不正な入力が、形の正しい deny になる
- 評価順: bash・ファイル・役割・bypass・skill のスクリプトの代表例
- **等価**（Python 版の hook と Python 版の `decide()` の照合。TS 版は[差分試験](#差分試験正解データ)）: `test_check_bash_*.py` の `parametrize("command", …)` に並ぶ全コマンド（1000 件余り）を
  `check_bash.py` と判定器の両方に通し、hook の deny / ask と判定器の decision が一致し、hook が何も
  返さないものを判定器が規則や意味解析で止めないことを確かめる

## TS 版への移植

判定の本番は TS 版（`home/dot_config/pi/harness/judge/`）で、フルガードがプロセスの中で呼ぶ。
Python 版（`decide.py`・`bashrules/`・`command_policy.py`）は**撤去されておらず**、
TS 版の正解データの出力元（照合用）として残る。Claude Code / Copilot CLI の判定 hook は登録を外してあり、Python 版は実行時には走らない。
Python 版の撤去は [CHG-0035](../../change/0035-retire-python-judge-oracle.md)（段 R1〜R5 は未着手）。
移植の進捗・実測・修正済みの不具合の経緯は、同案件の「判定器の TS 移植の記録（旧 pi-decide.md から移設）」。

### 差分試験（正解データ）

Python 版の判定結果を正解として、TS 版との全件一致を確かめる。

- `scripts/agents/export_decide_golden.py`: `test_check_bash_*.py` のコマンド × 役割 × bypass、ファイルツール × パス、そのほかのツール、不正な入力を `decide()` に流し、
  `test/agents/golden/decide_golden.jsonl`（応答）と `common.json`（描画した `common.toml` の JSON）に書く。パスは `${ROOT}` / `${HOME}` の記号で保存する。
  規則や判定器を変えたら引数なしで書き出し直す。`--check` は全件を作り直して比べる（約 1 分）
- `test/agents/test_decide_golden.py`: 正解データが Python 版と一致していること（一定間隔の標本）
- `test/agents/pi/judge_golden.mjs`: TS 版との差分。`node` の型除去で動く（22.18 以上）。`--bash` で bash も必須にする
- `test/agents/test_pi_judge_ts.py`: 上を pytest から呼ぶ。bash を含む全件の一致を必須にしている
- 部品ごとの正解データ: `scripts/agents/export_policy_golden.py`（`shlex`・分割・正規化・置換と関数の抽出・`find_match`）が `golden/policy_golden.jsonl` に、
  `export_checks_golden.py`（検査関数）が検査ごとの正解データに書く。`test/agents/pi/policy_golden.mjs` / `checks_golden.mjs` が TS 版と突き合わせる（食い違ったときに部品を特定できる）。
  `test_pi_judge_ts.py` が全件一致を必須にし、`test_decide_golden.py` が正解データの鮮度を標本で見る

### 判定が前の呼び出しに依存していた（修正済み）

同じ入力でも、同じプロセスで前に何を判定したかで結果が変わる不具合があった（`bashrules/_shared.py` の `_LITERAL_HEREDOC_BODIES`、引用付き heredoc の本文の記録がモジュールのグローバルに残る）。
**TS 版へ写してはいけない（判定ごとの状態にする）**。Python 版は `decide()` が bash の判定の前にこの記録を空にする。
試験は `test_decision_does_not_depend_on_earlier_calls`。経緯と標本の確認は[移植の記録](../../change/0035-retire-python-judge-oracle.md)。

### 状態

TS 版は、Python 版の正解データと全件一致している（`node test/agents/pi/judge_golden.mjs --bash`。検査関数は `checks_golden.mjs` でも個別に一致する）。

- 土台: `judge/pathutil.ts`・`context.ts`（`Ctx`）・`shellparse.ts`・`shared.ts`・`pystr.ts`・`normalize.ts`
- 検査: `sensitive.ts`・`http.ts`・`rules_exec.ts`・`rm.ts`・`bashpolicy.ts`（policy）・`rules_files.ts`・`rules_guard.ts`・`ghapi.ts`・`docker.ts`
- 登録簿と順序: `judge/checks.ts`（`CHECKS` と `DENY_NAMES` / `PATH_NAMES` / `ASK_NAMES`。順序は `bashrules/__init__.py` と同じ）
- bash の組み立て: `judge/bash.ts`（`makeBashDecider(tables)`。誘導・役割の shell_deny / shell_allow・skill_scripts）。`decide.ts` の `setBashDecider` へ差し込む
- 差分試験の約束:
  - 正解データは `None` を書かないので、**記録の無いコマンドは `None` のはず**という照合もしている（TS が誤って理由を返す＝誤検知を拾う）
  - 検査を足したら、手書きの入力（`export_checks_golden.py` の `EXTRA_*`）も足す
  - `urlsplit` / `ipaddress` は CPython 3.13.11 の実装に合わせた。Python を上げたら `local_url` の正解データで確かめる
- 既知の差: `expandUser` は `~` と `~/` だけを展開する（Python は `~user` も解く）。正解データの範囲では差が出ていない

### 切り替え（済み）

フルガード（`harness/index.ts`）は、同じプロセスで `judge/decide.ts` の `decide()` を呼ぶ。
bash は `setBashDecider(makeBashDecider(tables))` で差し込む。

- 設定の渡し方: `generate.py` の `build_pi_harness` が、`rules.json` の `judge` に
  `common`（`common.toml` の `[bash]` / `[file]` / `[pi]`）と `tables`（`home/dot_config/pi/harness/judge/tables.toml`）を JSON で入れる。
  `chezmoi apply` のたびに作り直されるので、`common.toml` を編集して apply すれば TS の判定に届く
- 失敗は deny: `judge` が無い・壊れていれば、起動時に失敗する（ツールが無くなる）か、判定が `source: error` の deny になる
- 試験: `test_pi_harness.py` は実際の pi を TS の判定器で動かす（`judge/` を一緒に置く）。
  壊れた設定の試験は `rules["judge"]["common"] = {}`

### 次

- Python 版の撤去は [CHG-0035](../../change/0035-retire-python-judge-oracle.md)。撤去のときは正解データを固定の入力として残し、`--check` の鮮度検査を外す方針
- `tables.toml` の置き場: `home/dot_config/pi/harness/judge/tables.toml`。TS 版が `rules.json` 経由で読む。
  Python 版の `tables.py` は、同じディレクトリ → リポジトリのソース → 配備先 `~/.config/pi/harness/judge/` の順に探す（撤去までの橋渡し。
  Windows は `harness/` を配らないので、Windows の Python の hook は表を読めず fail-closed で止まる）
- 構文解析の堅牢化（`shellparse` を正式な構文解析に替える）は別の変更。差分試験を残したまま進める

## 既知の制約

- gitflow-lite のリポジトリで develop / main を直接編集・コミットさせない制限は、判定器の外側の層（[CHG-0049](../../change/0049-gitflow-convention-guard.md)）に置いていたが、2026-10-31 に撤去した（[CHG-0050](../../change/0050-slim-guarded-action.md)）。今は機械では止めず、指示で運用する。`decide` は変えていない
- `[pi.external_read]` だけを開けている。OpenCode が開けている `[opencode.sandbox] work_read`（`~/src` など）は
  まだ読まないので、隣のリポジトリを読むと確認になる
- `boundary` の緩和は TS 版だけにある（Python 版 `decide.py` は持たない。正解データは `boundary` なしの要求）。試験は `test_pi_judge_ts.py`
- フルガードは判定を TS 版で同じプロセスの中で行うので、判定ごとのプロセス起動は無い（[切り替え](#切り替え済み)）。Python 版の `decide.py` を CLI として呼ぶのは正解データの書き出しだけ
