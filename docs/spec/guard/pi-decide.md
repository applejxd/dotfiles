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
| `tool` | `bash` / `read` / `edit` / `write` / `grep` / `find` / `ls` / `task`（子エージェントの起動）/ `todo`（タスクリストの拡張）/ `work`（作業台帳。親の役割だけ）/ `ask`（利用者への質問の拡張）と MCP のツール（`mcp__…`）。フルガードがツールを別名で登録していても、元の名前で渡す。役割の `tools` に無い名前は deny |
| `input` | ツールの引数。`bash` は `command`、ファイルのツールは `path`（`grep` / `find` / `ls` は省略すると `.`） |
| `cwd` | 作業ディレクトリの絶対パス。相対パスの解決と「作業ツリーの中か」の判定に使う |
| `role` | `[pi.profiles]` の名前（「役割」の表） |
| `bypass` | 真なら ask を allow にする（deny は変えない。[confirm](#confirm) の ask は除く） |
| `boundary` | サンドボックス（Fence）の内側と**証明できているか**（フルガードがカナリアで実測した結果。環境変数の自己申告ではない）。真のときだけ、評価の順番の 4' の緩和が効く |
| `allowed` | `{ read, write }`。サンドボックスが実際に開けた場所。`boundary` が真のとき、作業ツリーの外の読み書きの判定に使う（形が違えば `source: error` の deny） |
| `writeRoot` / `tmpRoots` | 任意。`writeRoot`（絶対パス）があるとき、`edit` / `write` は**既存の許可より先に**、書込み先が `writeRoot` と `tmpRoots`（文字列の配列。`writeRoot` を含むものは無視）の外なら deny（bypass でも）。書込み先は pi の正規化（`@`・`file://`・`~`・Unicode 空白）の全解釈と、symlink の厳格な解決（対象が無くても追う）で見る。無いときの判定は変わらない。形が違えば `source: error` の deny |

`writeRoot` の補足（[子エージェントの限界](pi-subagents.md#子エージェント)）:

- **全候補方式の代償**: pi が行いうる解釈のどれか 1 つでも外なら deny するので、まれに正当なパスが拒否される。
  例: cwd 内に `file:` という通常ファイルがあるとき、担当内を指す `file://` URL は拒否される。
  先頭が literal の `@` のファイル名は、pi が `@` を取り除くので `./@types/x` か絶対パスで渡す。
- **担当内の絶対パスは、プレフィックス（`@`・`file://`・`~`）なしで渡す**。
- 通常ファイルの後に成分が続くパス（`f/../x` など。リンクを辿った後も同じ）は、ENOTDIR 相当として deny する。
- **未実装の既知の限界**: 大文字小文字を区別しない FS・bind mount の別名では、許可ルートとの同一性を文字列の包含で見ているため、
  除外・許可が取りこぼしうる（対策案: `stat` の `dev` / `ino` で既存ディレクトリの祖先を照合。この環境の `/home` は
  大小文字を区別するので未実装）。Windows のパス（`\`・ドライブ・UNC）は未対応。

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
   - `bash`: `check_bash.py` の deny 側と同じ検査（`[bash] deny` の照合と意味解析。`cd` を挟んだ形も見る）。
     **例外**: 役割の `deny_except` に載る語は、条件つきで `[bash] deny` から外す（[`git worktree remove` の例外](#git-worktree-remove-の例外)・[`git restore --staged` の例外](#git-restore---staged-の例外)）
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
- **元に戻せないローカルの git 操作**(`[pi.confirm] local_git = true`。`judge/gitdestructive.ts`): `git branch -D/-M/-f/--delete --force`(`-fd`・`-df` など束ねた形を含む)、`git clean`(`-n`/`--dry-run` が無いもの)、`git tag -d/--delete/-f`、`git checkout -B`、`git switch -C/--force-create`、`git worktree remove` の force は、元に戻せない操作の一覧に残す (deny が外れる形に force は付かないので通常は働かない多層防御。[例外](#git-worktree-remove-の例外))。
  前置の環境変数・`env`・`git` のグローバルオプション（`-C`・`-c`・`--git-dir`・`--work-tree` など）を読み飛ばしてから、サブコマンドとフラグを見る（`--` 以降と、値を取るオプションの値は数えない。`git clean -e '-n' -f` は dry-run と見なさない）。
  評価の位置は、確認表の直後・`bashAsk` の前。**ask が既定の役割（親・`worker`）は、bypass でもサンドボックスの緩和でも ask のまま（理由の先頭は「確認が必要な元に戻せない git 操作 (bypass でも確認する): 」）**。
  **既定が deny の役割（`explorer`・`reader`・`committer`）は deny**: これらは `[bash] ask` が役割の既定の deny より先に当たり、`git branch -D`・`git clean`・`docker rm` が bypass で allow になっていた（2026-10-29 に実測。ask 一般の扱いは[次の節](#既定が-deny-の役割の-ask)）。
  保証の範囲は既存と同じ「うっかり防止」で、git の alias・外部スクリプト・動的に組み立てた文字列は見ない。素の `git branch` の作成・切り替え・`git tag` の作成などは従来どおり。ブランチモデル（[CHG-0047](../../change/0047-gitflow.md)）の `git flow` は、利用者が自分のシェルで実行する（bash の `git flow` の deny は [CHG-0050](../../change/0050-slim-guarded-action.md) で撤去した）
- **保護ブランチへの統合の確認（`[pi.confirm] integration = true`。[CHG-0053](../../change/0053-worktree-integration-gate.md)）**: bash（と `bg_run`）の統合コマンドを、**bypass でも省略できない必須確認**（`mustConfirm` の ask。見出しは「保護ブランチへの統合」）にする。判定器ではなく、**ハーネスの `decide`（`index.ts`）が、判定器の結果を引き上げる**（`integration-gate.ts`。緩める方向には働かない: deny と、すでに必須確認のものはそのまま）。Python 版と golden の判定は変わらない（TS だけ）。分類は `judge/gitintegration.ts` の静的な検出器（前置の環境変数・`env`・`command`・git のグローバルオプションを読み飛ばし、引用内と heredoc の本文は数えない）:
  - **always**（どこからでも必須確認）: 保護 ref を直接変える操作。`git flow {feature,release,hotfix,support,bugfix} {finish,delete,abort}`、`git flow integrate`、`git-flow` の同じもの、`update-ref <保護 ref>`、`symbolic-ref`、`branch -m/-c/-f` の対象が保護 ref、`branch <保護 ref>`、`fetch` の宴先が保護 ref（`--refmap` の値と、`-c remote.<名>.fetch=` で渡した refspec の宛先も同じ検査。判定できなければ unknown）、`worktree add -b/-B <保護 ref>`
  - **unknown**（必須確認）: 対象を静的に決められない。`cd`・`-C`・`--git-dir`・`GIT_DIR=` と統合系を同じコマンドに含む、`-c alias.`、`update-ref --stdin`、`reflog delete`、`fast-import`、宴先が `$VAR`、`update-ref`/`symbolic-ref` の宛先が他の worktree の ref の別名（`main-worktree/…`・`worktrees/<id>/…`。git が解決して主 worktree の保護ブランチや HEAD を動かせる）、`git replace` の書き換え（作成・`-f`・`-d`・`--graft`・`--edit`。一覧だけは none）
  - **head**（`merge`・`cherry-pick`・`revert`・`pull`・`am`・`reset`）: 現在のブランチを動かす。**cwd が自由区（feature の linked worktree。`freezone.ts`）なら日常の操作なので判定器の結果のまま**、自由区の外と、判定できないとき（deny にせず）は必須確認
  - **`cd` と `checkout`・`switch`**: 先頭が `cd <絶対パス> && git …` の形（区切りは `&&` だけ。空白は半角スペース・タブだけ。パスは引用なし・`'…'`・`"…"` で、使える文字は英数字と `_./@+:,=%-` だけ。`..`・`~`・`$`・グロブを含まない）で、残りが直接の `git` 1 コマンド（`env`・`eval`・`sh -c`・`command` などの前置き、環境変数の代入で始まらない。`;` `&` `|` 改行・CR・バッククォート・`$`・括弧・リダイレクト・波括弧を 1 文字も含まない）かつ head のときだけ、実体のパス（`realpath`）の cd 先が自由区なら許可（feature への develop の取り込みなど）。`GIT_DIR` などリポジトリを選ぶ継承環境変数があるときは許可しない。相対パス・`;`・`||`・改行・`&`・パイプ・サブシェル・保護ブランチの worktree・存在しない cd 先は必須確認で、それぞれ独立した負例の試験（`test_pi_integration_gate.py`）で裏づける（`git -C <パス>` の形は対象外）。`git checkout|switch` で保護ブランチへ切り替える・作り直す形は always（自由区の前提を崩すため）。start-point として読む形（`switch -c feature/y develop`）・detach・ファイルの復元は除く  - git を起動するのは head のときだけ（最大 2 回、時間切れ 3 秒）。毎回の edit / write や通常の bash では起動しない。一覧外の git の書き込みは今までどおり
  - **確認画面の内容（先頭が `git flow feature|bugfix finish <名前>` のとき。`confirm-view.ts` の `finishBodyLines`）**: **結論を先に、実行するコマンドを最後に**出し、**変更の一覧は出さない**（履歴で見る。スマホの画面で長すぎたため）。導入文と「理由:」も出さない（見出しと同じことなので）。上から順に、(1) **行き先**（`feature/<名前> → <統合先>`（`[pi.integrate] target`、既定 `develop`）。`--squash` は印）、(2) **衝突の事前検査が「あり」「確認できなかった」のときだけ**: `⚠ 衝突あり (N ファイル)` とファイル名 8 件まで。`merge-tree --write-tree --name-only --no-messages <統合先> <ブランチ>` の終了コード 0 は「なし」、1 は「あり」。出力の先頭が OID でないもの、想定外の終了コードは「確認できなかった」とし、**衝突なしにはしない**。git 2.38 未満や、オブジェクトを書けない環境（Fence の中の本体リポジトリなど）でもここに落ちる。**ref・インデックス・作業ツリーは変えない**（オブジェクトだけを書く。参照されないものは `git gc` が回収する）。**事前検査は確認の判定を変えない**（衝突があっても、承認するかは利用者が決める）、(3) **`--squash-message` の本文**（件名と地の文。**箇条書きは省き**（`-`・`*`・`・`・`1.` で始まる行と、その続きの字下げ行）、省いた項目数と全文の場所を 1 行で出す。連続する空行は 1 つにまとめ、地の文は 8 行まで、全体は 3000 字で切る。見出しにはファイル名だけを出す。引用された文字列はそのまま。**`"$(cat <path>)"` だけはファイルを読んで見せる**（`read` の判定が allow のときだけ、`--body-file` と同じ 32 KiB まで）。ほかの展開（変数・別のコマンド置換・読めないファイル）は、見せられないと書くだけで止めない。**ファイルから読んだメッセージは、gh の `--body-file` と同じ仕組みで、承認の後に変わったら実行を止める**）、(4) **衝突が「なし」のときだけ**、`衝突: なし` の 1 行、(5) **`実行:` とコマンドの全文**（省略しない）。メッセージが無いときだけ、コミットの件名を 5 件まで出す（何を統合するかが、ほかに見えないので）。git の呼び出しは `index.ts` が行う（各 3 秒で打ち切る）。取れないときは「取得できなかった」と理由を出すだけで、確認は止めない。git の結果もメッセージも無いときと、release・hotfix の finish、`cd` や `&&` が付く形、名前より先にオプションがある形は、従来の画面（導入文・コマンド・理由）のまま。未確認: 実機の TUI と Orca での見え方
  - 保護の範囲は「ガードが識別する直接経路」。alias・外部スクリプト・別プロセスの中の ref の書き込み・利用者のシェルは見ない。子のエージェントと UI の無い実行では、確認を出せないので拒否する
  - 設定: `[pi.integrate]`（`enabled`・`target`・`protected_refs`・`risk_paths`・`skip_confirm_in_free_zone`）は、`protected_refs` だけが今は効く。下限（`main` / `master` / `develop` / `release/*` / `hotfix/*`）を欠くと生成器が拒否する。同梱の設定は下限に `production` を足す（他のリポジトリの統合先）。ワイルドカードは末尾の `/*` だけで、比較は大文字小文字を区別しない（`judge/protectedrefs.ts`）。OpenCode の生成物には写さず、Python 版は読まない。`risk_paths`・`enabled` は後続の段（専用操作）が使う。`risk_paths` の同梱の対象には `.agents/config/pi.json`（プロジェクトごとの統合設定）が入る。`skip_confirm_in_free_zone` は同梱の設定で true（feature の linked worktree の `git_commit` を確認なしで実行する。[pi-extensions.md](pi-extensions.md#guarded_action)）
  - 試験: `test_pi_integration_judge.py`（分類の表）、`test_pi_integration_gate.py`（引き上げと自由区の実 git・git の起動回数）、`test_pi_freezone.py`、`test_pi_integrate_config.py`、`test_pi_harness.py`（実際の tool_call での確認。finish の確認に統合の内容と squash メッセージが出ること、承認の後にメッセージのファイルが変わったら止めること、git で要約できなくても確認は出ること）、`test_pi_confirm_view.py`（見出し、統合の内容、メッセージの読み方）。未確認: 実機（Orca・TUI）での見え方
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

## git worktree remove の例外

`[bash] deny` の `git worktree remove` は、**pi の `implementer`（親）と `worker` だけ**、単純な 1 行の force なしだけを許可する
（[CHG-0062](../../change-history/0062.md)）。force 付きは deny のまま（確認つきで通す案は、解析の取りこぼしが続いたので採らなかった）。`explorer`・`reader`・`committer`・`orchestrator` は deny のまま。

- **設定**: `[pi.profiles.implementer]` と `[pi.profiles.worker]` の `deny_except` に `git worktree remove`。implementer にはさらに `git restore --staged` を足す
  （[次の節](#git-restore---staged-の例外)。worker には足さない）。許す語は判定器（`decide.ts` の
  `DENY_EXCEPT_WORDS`）が「`git worktree remove`」「`git restore --staged`」の 2 語に固定し、未知の語・配列でない値は `source: error` の deny。`[bash] deny` と `[bash.deny_guide]` は変えない
  （Claude Code・Copilot・OpenCode の生成物は同じ。pi だけの変更）
- **deny を外す条件**（`judge/bash.ts` の `worktreeRemoveExcepted`、共通の deny を引く前）: `[pi.confirm] local_git` が真で、役割が例外に載っていること。
  **元のコマンド文字列の全体**が、正規表現 `^git worktree remove(?: [A-Za-z0-9_./@%+=:,][A-Za-z0-9_./@%+=:,-]*)+$` に一致すること
  （`git worktree remove` の後ろに、単一の空白で区切った、`-` で始まらない単純なトークンが 1 個以上）。
  `normalize` の結果や分割したセグメントは見ない（解析器の解釈に依存しない）。前後の空白・連続する空白・引用符・バックスラッシュ・行継続・
  リダイレクト・パイプ・`;` `&`・括弧・`$` `` ` `` `{` `*` `?` `[` `~` `!`・`-` で始まるトークン（`-f`・`--force`・`--`・`-C`）・
  前置の `env`・`git -C`・`xargs`・`bash -c`・`cd … &&`・複合は、すべて一致せず deny のまま（fail closed）。
  全体が 1 コマンドなので、複合コマンドの他の部分の deny には影響しない。`local_git` を切れば例外も無効
  - **代償**: 空白を含むパスなど引用が要る正当なコマンドも deny のまま（この repo の worktree 名は空白を含まない）
- **force の検出**（`judge/gitdestructive.ts` の `case "worktree"`、[confirm](#confirm)）: 多層防御として残す。deny が外れる形に force は付かないので通常は働かず、
  何かの不具合で force 付きが deny を通ったときだけ、`mustConfirm` の ask になる
- **緩めたあとの判定**: 他の規則に当たらない plain 形は `source: default`（親は ask、bypass で allow、`pis` の境界の中で allow。`[pi.shell] allow` には載せない）
- **ssh 経由では効かない**: 判定器は ssh を先に解いてリモート側の文字列を再帰判定するが、例外は元の入力そのもの（直接実行）にだけ効く。
  `ssh <許可済み宛先> 'git worktree remove …'` は deny のまま（代償: リモートの正当な掃除は、リモートで手動で行う）
- **Python 版と golden**: `decide.py` は `deny_except` を知らず deny のまま。TS も例外が効くのは force なしの 1 行だけで、golden の標本（force 付き）は
  どちらも deny なので、`judge_golden.mjs` に許容は無い。負例は `test_pi_worktree_remove.py`
- **残る限界**:
  - force なしでも、`.gitignore` 対象のファイル（例: `.tmp/`・`.venv`）と detached のコミットは失う。退避（tgz）は `wt_clean.py` と PR ビューアの cleanup（`apps/pr-viewer/merge.ts` の退避）にあるが、bash からの直接実行にはない
  - force なしの `git worktree remove` が守るのは、変更済み・未追跡のファイルがあるときと、`git worktree lock`（所有の表明）したときだけ。
    claim を忘れた worktree は lock で守られない。lock した worktree は force が 2 回要るが、force 付きは deny なので消せない
  - bypass を継ぐ worker は、claim のない clean な他の worktree を plain で消せる
  - 保証は「うっかり防止」。git の alias・外部スクリプト・動的に組み立てた文字列は見ない。反映には `chezmoi apply` と pi の再起動が要る
- **試験**: `test_pi_worktree_remove.py`

## git restore --staged の例外

`[bash] deny` の `git restore` は、**pi の `implementer`（親）だけ**、**index だけを戻す厳密な 1 形式**を許可する
（[CHG-0062](../../change-history/0062.md)）。作業ツリーを変える形は、従来どおり deny のまま。`worker`・`explorer`・`reader`・`committer`・`orchestrator` は deny のまま。

- **worker を対象にしない理由**: worker は `git add`・`git commit`・`git checkout`・`git switch`・`git restore` がすべて deny で、unstage の需要が無い。
  また index を更新する操作を許さない方針なので、この例外が worker に新しい能力（下の限界）を与えてしまう
- **設定**: 上の節の `deny_except` に、implementer だけ語 `git restore --staged` を足す（判定器の `DENY_EXCEPT_WORDS` が許す語を固定。役割の `deny_except` に語があるときだけ効く）。`[bash] deny`・`[bash.deny_guide]` は変えない。
  `shell_deny` にも `git restore` がある役割が将来載ったときのため、例外に当たったときは `shell_deny` の `git restore` も外す（他の語は残る）
- **許可する形**（`judge/bash.ts` の `restoreStagedExcepted`、`[pi.confirm] local_git` が真のときだけ）: **元のコマンド全体**が正規表現
  `^git restore (?:--staged|-S)(?: --)?((?: [A-Za-z0-9_./@%+=:,][A-Za-z0-9_./@%+=:,-]*)+)$` に一致し、パスが 1〜50 件で、どのパスも `..` を含まないこと。
  `.` 単独は許す（サブディレクトリで実行したときは index 全体でなく cwd 以下が対象。Git 本体の復元処理としては作業ツリーは変わらない。hook の副作用は除く）。解析器の解釈は見ない（fail closed）
- **許可しない形（従来の判定のまま）**: `--worktree`/`-W`（`-SW` を含む）・`--source`/`-s`・`-p`/`--patch`・`--overlay`/`--no-overlay`・`--ours`/`--theirs`・`--merge`・
  `--ignore-unmerged`・`--pathspec-from-file`・`--pathspec-file-nul`・`--staged` の省略形・フラグを後ろに置く形・`--` を 2 回・パス無し・`git restore .` と `git restore a`（作業ツリーを変える）・
  `..` を含むパス・空白/クォート/展開/グロブ/リダイレクト/`~`・前置き（`env`・`sudo`・`cd … &&`・`git -C`）・複合（`;` `&&` `|`）・ssh 経由・前後や連続の空白・51 件以上。
  大文字小文字違い（`GIT RESTORE`）は、従来から deny に当たらず役割の既定（ask）。例外でも変わらない
- **緩めたあとの判定**: 他の規則に当たらない許可形は `source: default`（親は ask、bypass で allow、`pis` の境界の中で allow）。bypass でも、通るのは許可形だけ
- **限界**: 保証は「うっかり防止」。**repo に `post-checkout` hook があると、許可した形でも git が最後にそれを実行する**（`builtin/checkout.c` の `checkout_paths()` が `post_checkout_hook` を呼ぶ）。
  implementer は `git checkout`・`git switch`・`git_commit` で既に repo の hook を動かせるので、新しい境界ではない（worker に許さないのはこのため）。
  index に積んだ内容（ステージ）は失うが、作業ツリーのファイルは残る（Git 本体の処理について。hook の副作用は除く）。`git reset`・`git checkout --`・`git stash` は変えない。
  git の alias・外部スクリプト・動的に組み立てた文字列は見ない。pi だけの変更（Claude Code・OpenCode の生成物は同じ）。反映には `chezmoi apply` と pi の再起動が要る
- **試験**: `test_pi_git_restore_staged.py`

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
| `implementer` | 7 つのツール・`task`・`todo`・`work`・`ask`・`mcp__*` | ask | `deny_except` に `git worktree remove`（force なしを許可。[例外](#git-worktree-remove-の例外)）と `git restore --staged`（[例外](#git-restore---staged-の例外)）。`shell_deny` は無い（`git flow`・`git-flow` の拒否は [CHG-0050](../../change/0050-slim-guarded-action.md) で撤去） | 親（主エージェント） |
| `reader` | read・grep・find・ls | deny | — | 利用者が `pis --role reader` で選ぶ読み取り専用の親。子の `plan` 役も使う（`[pi.agents.plan]`。bash を持たないので、`skill_scripts` の許可が通らない）。harness の読み取り専用の子の一覧 `READ_ONLY_CHILD_PROFILES` に含む（`/btw` の入口と、計画モードの間に起動できる子）。bash を持たない役割の試験にも使う |
| `explorer` | `reader` + bash | deny | `shell_allow` に `wc` と読み取り専用の git（`status` / `diff` / `log` / `show` / `ls-files`） | 子の `explore` / `review` |
| `committer` | bash・read・grep・find・ls | deny | `shell_allow` に `git status` / `git diff` / `git log` など。`shell_deny` に git の状態を変える操作 | 子の `commit` |
| `orchestrator` | read・grep・find・ls・task・todo・work・ask・action | deny | 許可リスト。`bash`・`edit`・`write`・MCP を持たない。`/orchestrate on` の間だけ、親の役割になる（[親の絞り込み](pi-subagents.md#親の絞り込みorchestrate)） | 親（利用者が切り替える） |
| `worker` | 7 つのツール | ask | `deny_except` に `git worktree remove`（同上）。`shell_deny` に git の状態を変える操作 | 子の `worker` |

**既定の役割**は `[pi] default_role`（`common.toml`。既定は `implementer`）。`pis` は `--role` / `PI_HARNESS_ROLE` で上書きでき、
`[pi.profiles]` に無い名前は、生成が止まる。

`git status` / `git diff` は `.git/config` 経由でコマンドを起動しうるので、全体の `[pi.shell] allow` には載せず、
`committer` の `shell_allow` だけに置く（今の OpenCode の `commit` と同じ）。

`tools` が文字列の配列でない・`default` が allow / ask / deny でない・`shell_allow` / `shell_deny` / `deny_except` が文字列の
配列でない・`deny_except` に未知の語がある・名前が無いときは、`source: error` の deny。

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

### 判定の退行検知（baseline と意図した差の台帳）

固定の golden は Python 由来で、TS の判定器の内部を入れ替えるときの「緩くなる差」は見えにくい。現行の TS 判定器の出力そのものを凍結して差を見る（判定は変えない）。

- **対象**: `decide_golden.jsonl` の全入力、`checks_golden.jsonl` の検査 id 単位の出力、新設の真理値表（複合・許可＋未知・`local_git`・例外・ラッパー・非 literal・引用・書き込み先を、全役割 × ask/bypass/boundary/両方で）。
- **ファイル**: `test/agents/golden/ts_baseline.jsonl`（baseline）・`intended_changes.jsonl`（意図した差の台帳）、`test/agents/pi/judge_baseline.mjs`・`judge_diff.mjs`、試験 `test_pi_judge_baseline.py`。
- **使い方**: `judge_baseline.mjs --write-baseline`（意図した変更のあとに書き出し直す）・`--check`（1 行でも違えば 1）。`judge_diff.mjs` は差を強さ（deny > mustConfirm > ask > allow）で `relax`・`tighten`・`reason` に分け、台帳に無い差があれば終了コード 1。`--emit-ledger` は台帳の雛形を出す。`--corpus <JSON の文字列配列>` は外部コーパス（`.tmp/keep` に置き、リポジトリには入れない）を回し、baseline に無い入力の分布だけを出す（コマンドは出さない）。
- **台帳の運用**: 1 行 `{kind, input, role, mode, old, new, class, reason, approver}`（`class` は `relax`・`tighten`・`false-positive`・`neutral`）。緩和は 1 件ずつ理由と承認者（`user`・`review`）を記録し、`relax` は台帳なしでは通らない。差が消えた台帳の行は警告（古い台帳）。承認した差は baseline を書き出し直して台帳を空に戻してよい。
- **限界**: golden とコーパスに無い入力の退行は検知できない。baseline は「現状」で、正しさは保証しない。check は golden に載る（ヒットのある）入力だけで、ヒット無しの入力の新規ヒットは見ない。

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

## 解析結果 Plan（G1(a)）

`judge/plan.ts` の `analyze(cmd, {sshTargets})` は、bash を構文木（同梱の mvdan-sh）から**1 回だけ**解析し、実行点 `ExecSite` の平坦な列 `Plan` を返す純関数。
**判定器には接続していない**（挙動は変えない。接続は後続）。Plan は、旧の判定を置換せず、拒否側の所見・追加の厳格化と shadow 比較の入力になる（tighten-only）。

- 型: `ExecSite` = `argv`（ラッパーを剥がした実効）・`rawArgv`・`assigns`・`redirs`・`via`・`cmd`・`cwd`（caller / chain / unknown）・`ctl`・入れ子（`parent`・`depth`）。
  語 `Word` は lit / tilde / pat / unk。literal は「展開後も 1 つの文字列に決まる語」で、`Lit` かどうかでは決めない
- 拒否側専用の view: `tails`（`--` の後ろ・runner・here-string・プロセス置換の echo など、旧の埋め込み抽出と同じ範囲）と
  `denyViews`（git のグローバル引数を除いた view）。許可の被覆には使わない。`varsVisible` は旧の字句上の代入名
- 入れ子: `bash -c`・heredoc・許可宛先の ssh・`find -exec`・xargs・`$()`・`<()` を同じ列に平坦化する。`eval`・`source`・インタプリタの本文は `opaque`
- fail-closed: 読み込み失敗・sha 不一致・評価失敗・構文エラー・CR/NUL ほかの C0・上限超え（長さ 10000・実行箇所 200・深さ 4・語 4000）は `ok:false`（呼び出し側が deny にする）
- 限界: `$'…'`・`$"…"` は復号せず unk（頭にあれば後段が deny にする印）。cwd の chain は実在確認をしない（G5 が解く）。`CDPATH`・関数・alias がある原文の `cd` は unknown
- 試験: `test_pi_plan_literal.py`（表 L・演算子番号・fixture）・`test_pi_plan_failclosed.py`・`test_pi_plan_sites.py`。実型は [mvdan-sh の構文木の実型](../../research/agents/mvdan-sh-ast-fixtures.md)

## shadow（観測）

`judge/shadow.ts` は、bash（`bash`・`bg_run`）の判定の**後**に `analyze` を呼び、観測の 1 行を `<cwd>/.tmp/work/shadow/<session>.jsonl` に追記する。
目的は、`analyze` を判定の先頭へ繋いで `ok:false` を deny にする案（G1(b)）の前に、**正当なコマンドを deny にする率**を実測すること。

- 記録: 時刻・役割・モード・旧の decision/source・コマンド長・先頭の語・`ok`・失敗種別 `why`・site 数・cmd 名（最大 8。安全な字種だけ、他は `?`）・`ms`・`would_tighten`（旧が allow/ask で新が `ok:false`）・`vendor_missing`。**コマンドの全文・引用・値は入れない**
- 不変: 応答（decision・reason・source）を変えない。`analyze` の例外・追記の失敗は握りつぶす。`PI_SHADOW=0` で無効（既定は有効）、子（`PI_HARNESS_CHILD`）では記録しない。1 ファイル 5 MB で止める
- 簡易ブレーカー: `analyze` が 200 ms を超えたら以降は呼ばない（同期処理なので 1 回の遅れは防げない。最初の 1 回は vendor 読み込みを含むので対象外）
- 集計: `python3 scripts/shadow_stats.py [パス]`（失敗率・`would_tighten` と理由・ms の p50/p90/p99・失敗した入力の先頭の語）。試験は `test_pi_shadow.py`
- 限界: 子と Windows の別実行は記録の置き場が無く観測しない。判定後の確認待ちの結果（承認・拒否）は記録しない

## 既知の制約

- gitflow-lite のリポジトリで develop / main を直接編集・コミットさせない制限は、判定器の外側の層（[CHG-0049](../../change/0049-gitflow-convention-guard.md)）に置いていたが、2026-10-31 に撤去した（[CHG-0050](../../change/0050-slim-guarded-action.md)）。今は機械では止めず、指示で運用する。`decide` は変えていない
- `[pi.external_read]` だけを開けている。OpenCode が開けている `[opencode.sandbox] work_read`（`~/src` など）は
  まだ読まないので、隣のリポジトリを読むと確認になる
- `boundary` の緩和は TS 版だけにある（Python 版 `decide.py` は持たない。正解データは `boundary` なしの要求）。試験は `test_pi_judge_ts.py`
- フルガードは判定を TS 版で同じプロセスの中で行うので、判定ごとのプロセス起動は無い（[切り替え](#切り替え済み)）。Python 版の `decide.py` を CLI として呼ぶのは正解データの書き出しだけ
