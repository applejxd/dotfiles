# Claude Code（予備のハーネス）の設定

pi が主で、Claude Code は予備のハーネスです（[ADR-0041](../adr/0041-claude-code-spare-harness-static-config.md)）。**導入は自動化せず**（[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md)）、すでに入っている機に、標準の設定だけを配ります。**会社 PC で使う前提**で、家の機だけの設定（Tailscale の指示など）は置きません。
pi の設定とは**共有しません**。pi の指示・権限の方針・プロンプト・スキルから、反映できるものを手で写した静的なスナップショットで、pi 側を直しても追随しません。
**試験の対象外**です（[下](#試験の対象外)）。

[ドキュメント一覧へ戻る](../index.md)

## 配るもの

| 配る先 | ソース | 内容 |
| --- | --- | --- |
| `~/.claude/CLAUDE.md` | `home/dot_claude/CLAUDE.md` | **最低限**の常設の指示（説明と報告・検証・書式と秘密・拒否されたとき・`git config` の deny）。会社用の前提なので、家の機だけの指示は無い。ファイル全体を chezmoi が持つ |
| `~/.claude/settings.json` の `permissions.deny` と `permissions.ask` | `home/dot_claude/modify_private_settings.json`（`chezmoi:modify-template`）と、データ `home/.chezmoitemplates/claude-permissions.json` | この 2 つのリストだけを、データの内容に置き換える。ほかのキーは保つ（下）。会社 PC（`is-work`）だけ、`permissions.allow` に MCP のサーバ名 `mcp__<名前>` を足す（置き換えない） |
| `~/.claude.json` の `mcpServers`（会社 PC だけ） | `home/modify_private_dot_claude.json`（`chezmoi:modify-template`）と、データ `home/.chezmoitemplates/claude-mcp-servers.json` | 宣言した 2 サーバ（`agentcore-websearch`・`webfetch`）の定義だけを置き、ほかのキーを保つ（[MCP](#mcp会社-pc-だけ)） |
| `~/.claude/commands/stepback.md` | `home/dot_claude/commands/stepback.md` | pi の prompt `stepback` の写し（`$ARGUMENTS` の書式が同じ）。`/stepback` で使う |
| `~/.claude/skills/commit/` | `home/dot_claude/skills/commit/` | pi の `commit`（Conventional Commits のメッセージ作成と、既定では承認を取ってからのコミット）を、Claude Code 向けに直した写し |
| `~/.claude/skills/sdd-docs/` | `home/dot_claude/skills/sdd-docs/` | pi の `sdd-docs`（`docs/` の案件・ADR・調査記録・仕様・索引の整え方）の写し。検査のスクリプト 3 本（`lint_docs.py`・`check_refs.py`・`docs_state.py`）と雛形を含む |

**配る範囲**: claude が PATH にある機だけ。`.chezmoiignore.tmpl` が、`lookPath "claude"` が空の機では `.claude` を除外する。Claude Code の導入は、このリポジトリは行わない。**MCP（`~/.claude.json`）は、そのうえで `is-work` の機だけ**（`.chezmoiignore.tmpl`。家の機には配らない）。

**触らないもの**（`settings.json` の中）: `hooks`（Orca が入れる）・`enabledPlugins`・`env`・`sandbox`・`includeCoAuthoredBy`・`permissions.defaultMode`・`permissions.allow`（会社 PC で MCP の 2 件を足すだけ。ほかは保つ）。`~/.claude.json` は、宣言した MCP の定義のほかを触らない。
`modify_private_settings.json`（`private_` を付けてある。`env` に秘密が入りうるので 0600 を保つ）は、他のキーを保ったまま 2 つのリストを置き換え、何度流しても同じ結果になる（キーの並びは辞書順に整う）。ファイルが無い・空・空白だけのときと、`permissions` が object でないときは、`permissions` を作り直す。壊れた JSON と BOM 付きの JSON は、黙って直さず、その変換で apply をエラーにする（ファイルは変えない）。CRLF は読めるが、書くときは LF になる。整数は int64 の範囲なら保つ（2^53 を超える整数も実測で保った）。int64 を超える整数は丸められる（`settings.json` には無い）。

**配らないもの**: 上の 2 つ以外のスキル（Claude Code は `~/.agents/skills` を読まない。`~/.agents/skills` への symlink による共有もしない）・子の定義（`agents/`）・MCP のうち会社 PC の 2 件以外（家の機の `websearch` など）・hook・`sandbox`・
リポジトリ直下の `CLAUDE.md`（`@AGENTS.md`）・導入のスクリプト。

## スキルの写し（`commit`・`sdd-docs`）

pi の版（`home/dot_agents/skills/`）を複製し、Claude Code 向けに次だけ直した。**独立した写し**で、pi の版を直しても追随しない。

- pi 固有の記述を除いた: 子エージェントへの委譲（`subagent`・`worker`・`references/delegation.md`・「子エージェントに分担させるとき」の節）、`session-recall`・stock の pi・`pi-permission-system` への言及、このリポジトリ（dotfiles）固有の括弧書き。
- 置き場を読み替えた: `~/.agents/skills/sdd-docs` → `~/.claude/skills/sdd-docs`（`SKILL.md` の手順・雛形・スクリプトの使い方）。リポジトリの規約の置き場に、`CLAUDE.md` を足した（`AGENTS.md` と並べる）。
- `allowed-tools` は、`commit`（`git add`・`git commit` など）は pi の版のまま。`sdd-docs` は、スクリプトの実行（`python3 …/scripts/*`）の許可を**外した**（`check_refs.py --save <パス>` が任意のパスへ書け、Python 内部の書き込みには Read・Edit の deny が効かないため）。`Edit`・`Write`・`git mv`・`git check-ignore` は残した。Claude Code では、スキルを呼んだターンの許可になり、**deny・ask の規則が先に当たる**（例: `commit` の `git restore --staged` は、`git restore` の ask に当たって確認が出る）。
- `commit` は既定でメッセージ全文を提示して承認を得る。リポジトリ規約が対象のローカルコミットのメッセージの個別承認を省けると明示している場合だけ、個別承認を求めない。Claude Code では、同名の `~/.claude/commands/commit.md`（旧い生成器の残り）よりスキルが優先される（公式 docs「Resolve skills that share a name」）。
- `sdd-docs` の検査のスクリプトは、pi の版と**別の写し**（`~/.claude/skills/sdd-docs/scripts/`）。このリポジトリの pre-commit が呼ぶのは、pi の版のまま。

## MCP（会社 PC だけ）

会社 PC は Bedrock 経由で、モデル提供元の内蔵の検索が使えない（[AgentCore Web Search](mcp-servers.md#agentcore-web-search)）。そこで、pi と同じ 2 サーバを Claude Code にも入れる。

| サーバ | 用途 | 起動 |
| --- | --- | --- |
| `agentcore-websearch` | AgentCore Web Search で web 検索する。Gateway の URL（環境変数 `AGENTCORE_GATEWAY_URL`）が無い機では、ツールの無い空のサーバになる | `uv run --no-project --quiet ~/.config/agents/agentcore_websearch_mcp.py …`（ラッパーは全機に配られている） |
| `webfetch` | URL を指定してページ本文を取得する（既製の `mcp-server-fetch`。検索はしない） | `uvx --exclude-newer <日付> mcp-server-fetch==<版> --no-readability-js` |

- **宣言の写し**: `home/.chezmoitemplates/claude-mcp-servers.json` は、`pi-mcp-servers.toml` の同名の宣言を**手で写した静的な写し**（共有しない）。pi 側の版・引数（`mcp-server-fetch` の版と `--exclude-newer` の日付など）を変えたら、写しも直す（pi の TOML の先頭にも注記がある）。家の機の `websearch`（自作）は写さない。
- **配備**: `modify_private_dot_claude.json`（`private_` を付けてある）が、`~/.claude.json`（user スコープの置き場。公式 docs）の `mcpServers` のうち、宣言した名前の定義だけを置く。宣言した名前のサーバは、定義ぜんぶを宣言にそろえる（手の編集は消える）。ほかのキーと、利用者が足したサーバは保つ。
  すでに宣言どおりなら、入力をそのまま返して書き換えない（本体の整形のまま）。宣言と違うときだけ書き直し、そのとき、キーの並びは辞書順になる（`toPrettyJson`）。
  **`private_`（0600）が要る**: `~/.claude.json` は認証の状態を持ち、本体は 0600 で作る。chezmoi は、`private_` が無いと、既存の 0600 のファイルを、内容が同じでも 0644 に広げる（2026-11-18 に実測: 新規作成・書き直し・変化なしのどれでも 0644 になった）。`private_` を付けると、新規作成も、既存の 0644 の締め直しも 0600 になる。整数は int64 の範囲なら保つ（2^53 を超える `9007199254740993` も実測で保った）。範囲を超える整数は丸める。ファイルが無い・空・空白だけのときは、`mcpServers` だけのファイルを作る。壊れた JSON は、apply がこのファイルの変換でエラーにする（ファイルは変わらない）。
- **許可**: `modify_private_settings.json` が、`permissions.allow` に `mcp__agentcore-websearch`・`mcp__webfetch` を足す（利用者が承認。pi の方針と同じ。検索・取得は読み取りで、`fetch` は URL に情報を載せて外へ送れる点を受容する）。すでにあれば足さず、順序は保つ。
- **前提（管理外）**: `AGENTCORE_GATEWAY_URL`・AWS の認証・プロキシの環境変数は、シェルの環境に置く（[設定](mcp-servers.md#制約のある環境の機での設定)）。stdio のサーバは、親の環境変数を引き継ぐ（2026-11-18 に実測: 印を付けた変数が子から見えた）。
- **消し方**: 宣言を消しても配備先からは消えない。`claude mcp remove --scope user <名前>` で消す。
- **限界**:
  - 管理者の方針によっては、user スコープの MCP は読み込まれない（公式 docs [Control MCP server access](https://code.claude.com/docs/en/managed-mcp.md)）。排他的な `managed-mcp.json` では、user スコープのサーバは読み込まれない。許可リスト（`allowedMcpServers` など）の方式では、許可されないサーバだけが Blocked になる。`claude mcp list` が「Blocked by enterprise managed policy」を出す。迂回しない。
  - MCP のサーバ（Claude Code の子プロセス）が、Claude Code の `sandbox` の対象かは、**未確認**。既存の `sandbox` が MCP の外部送信を制限するとは見なさない（`fetch` の外部送信・取得した本文の危険は、pi と同じく受容している）。
  - `private_` の 0600 は、Unix 系の話。Windows では、モードは効かず、継承された ACL になる（未確認。CRLF・BOM の実際の apply も未実行）。
  - `~/.claude.json` は、本体が自分で頻繁に書くファイル（公式 docs は「編集する必要はない」と書く。MCP の設定・認証の状態・プロジェクトごとの信頼を持つ）。書き込みが要るのは宣言と違うときだけだが、書くときは **Claude Code を終了してから apply する**。壊れたときは、本体が `~/.claude/backups/` へ退避し、起動時に復元を尋ねる（公式 docs）。
  - 会社の実機（AgentCore の実接続・PyPI やプロキシ越しの取得）と Windows は未確認。
- **確認（手で）**: ① 一時の宛先へ `chezmoi apply` して、`.claude.json` と `settings.json` を見る（`--config` に `[data]` の `work = true` を書いた toml を渡し、PATH に `claude` を置く）。② `HOME=<一時の宛先> claude mcp list` が、両サーバを ✔ Connected と出す（agentcore は URL が無いので空のサーバで接続する。webfetch は PyPI から取得するので、ネットワークが要る）。③ 会社の機では、配備後に `claude mcp list` が Blocked を出さないこと。
- **実測（2026-11-18、Claude Code 2.1.270、一時の HOME）**: 2 サーバとも ✔ Connected。新規作成・既存ファイルへの追加（他のキーと利用者のサーバを保つ）・再 apply（変化なし）・本体の整形のままの再保存（書き換えない）・宣言した定義の編集（元に戻す）・`work = false`（作らない・触らない）・`claude` が PATH に無い（除外）・空/空白（作る）・壊れた JSON（エラーでファイルは不変）を確認した。`allow` の足し方（既存 46 件を保つ・重複しない・`work = false` では触らない）と `claude doctor`（Invalid settings なし）も確認した。

## pi から写したもの・写さなかったもの

データ `claude-permissions.json` は、`pi-permission-policy.json`（2026-11-18 時点）から**一度だけ**作った。変換は使い捨てで、コミットしていない。

**pi の規則を、そのまま同じ意味では写せない**（独立した監査で見つかった）。pi と Claude Code は、どちらも `*` を「空白を含む任意の文字列」として扱うが、次が違う。

- **末尾の `*` の省略**: pi は、`*` の数によらず、末尾の `*`（直前の空白ごと）を省略して、引数なしのコマンドにも当たる。Claude Code は、`*` がその 1 つだけのときに限る（`Bash(ls *)` は `ls` に当たるが、`Bash(* --help *)` は `npm --help` に当たらない）。
  `*` が複数の規則（`git flow * publish *` など）は、末尾の `*` と直前の空白を除いた規則を足した（6 件）。
- **パスの書式**: pi は `*id_rsa*` のように「名前に含む」を書く。Claude Code は gitignore の書式なので、`**/*id_rsa*` のように書き直した（`**/id_rsa*` は「名前の先頭」になり、`customer_id_ed25519` が抜ける）。
- **例外**: Claude Code は、allow で ask・deny の例外を作れない。pi が例外にしているもの（`git config --get`・`*.env.example`・`git worktree remove` の `.tmp/worktrees/` 配下）は写せない。

| 写し元（pi） | 写し先（Claude Code） | 件数 | 扱い |
| --- | --- | --- | --- |
| `bash` の deny（51） | `permissions.deny` の `Bash(...)` | 53 | 規則をそのまま写し（上の違いを除く）、2 件を除き、末尾の `*` と直前の空白を除いた形を 4 件足した。除いた 2 件: `nohup *`（Claude Code が wrapper として剥がしてから照合するので当たらず、理由も pi の `bg_run` への誘導）、`git config*--no-*`（次の広い deny に覆われる）。`git config*` は、広い deny をそのまま写す（**読み取りも止まる**。`git remote get-url`・`git var -l` などで代える。書き込みの形の列挙は、alias・大文字のキー・否定オプションが抜けるので置かない） |
| `bash` の ask（114） | `permissions.ask` の `Bash(...)` | 114 | 規則をそのまま写し、`git config*user.name*`・`git config*user.email*`（広い deny に覆われる）の 2 件を除き、末尾の `*` と直前の空白を除いた形を 2 件足した（`gh` の変更系・`gh api` の書き込み・公開・統合・履歴の書き換え・外部送信・永続化。`git -C * config*` を含む） |
| cc-safety-net（pi の `cc-safety-net` が、破壊的なコマンドを解析して止める層） | `permissions.deny` の `Bash(...)` 22（git の破壊的な形 17・ディスク・デバイスの破壊 5）と、`permissions.ask` の 19（`git -C * …` の 17・`git restore` の 2） | 41 | Claude Code には対応する層が無いので、glob で最小限を足した。git: `reset --hard`・`reset --merge`・`clean -f`・`branch -D`・`stash drop`・`stash clear`・`checkout --`・`checkout -f`・`checkout .`・`rm -f`・`tag -d`・`reflog delete`（先頭が固定の形は deny）。ディスク・デバイス: `mkfs`・`mke2fs`・`wipefs`・`sgdisk`・`shred`。**`git -C <dir> …` の形は ask**（AI が常用するが、`*` が引用符の中まで当たり、コミットメッセージの語で誤検知するため）。`git restore` は `--staged`（無害）も当たるので ask。`rm -rf` の危険な対象・`find -delete` は、文法で表せない（`rm -rf` の一律 deny は誤って止める）ので足さない。Claude Code の承認の流れ（`find -delete` は確認が出る）に任せる |
| `bash` の allow の例外（8） | 写さない | – | 上のとおり、例外を作れない |
| `path` の deny（秘密） | `permissions.deny` の `Read(...)` | 35 | gitignore の書式に直した（`**/*.env.*`・`**/*id_ed25519*`・`~/.ssh/**` など）。`Read` の deny は Edit・Write も止める。Claude Code 自身の認証（`~/.claude.json`・`~/.claude/.credentials.json`）を足した（pi の `auth.json` の対応物） |
| `path_write` の deny | `permissions.deny` の `Edit(...)` | 19 | 道具・設定の置き場（`~/.local/bin`・mise・uv・cargo・git の設定など）。pi の置き場は `Edit(~/.pi/agent/**)` の 1 本にまとめた。Claude Code の設定（`settings.json`・`CLAUDE.md`・`commands/`）を足した（変えるのは利用者＝chezmoi） |
| `mcp`（`websearch`・`agentcore-websearch`・`webfetch` を allow） | `permissions.allow` の `mcp__<名前>`（会社 PC の 2 サーバだけ） | 2 | 検索・取得は読み取り（pi と同じ）。`websearch` は家の機の自作で、写さない |
| `external_directory`・`skill`・子の道具 など | 写さない | – | Claude Code に対応物が無い、または pi 固有 |
| `AGENTS.md`（委譲の節・`cd` は絶対パス・pi の確認の節） | 写さない | – | pi-subagents・pi の権限の拡張が前提 |
| `AGENTS.md`（応答・検証・書式・安全・作業場所） | `CLAUDE.md` | – | 手で写した。拒否への対処は、Claude Code の拒否（コメント付き）の言い方に直した |

deny は合計 129（Bash 75・Read 35・Edit 19）、ask は 133。deny と ask に同じ規則は無い（deny が先に当たる）。

## 変更のしかた

- **規則を足す・外す**: `claude-permissions.json` を直す。pi 側の変更は追随しない（必要なら手で写す）。個人用の一時的な追加は、`.claude/settings.local.json`（リストは結合される）。
- **スキルを直す・足す**: `home/dot_claude/skills/<名前>/`。pi の版との食い違いは、検査されない（手で写す）。足すスキルの名前が `.chezmoiremove` の `.claude/skills/…` にあれば、そこから外す（`commit`・`sdd-docs` は外した）。
- **MCP を直す・足す**: `home/.chezmoitemplates/claude-mcp-servers.json`（写し）。pi の `pi-mcp-servers.toml` を変えたときも直す。許可（`mcp__<名前>`）は、`modify_private_settings.json` が宣言から作る。
- **指示を直す**: `home/dot_claude/CLAUDE.md`（最低限に絞ってある。足すときは、スキルや仕様で足りないかを先に見る）。Claude Code の `#` で足した内容は、次の `chezmoi apply` で消える（`Edit(~/.claude/CLAUDE.md)` も deny にしてある）。
- **反映の前に**: `chezmoi diff` で差分を見る。初回は、既存の deny（209）・ask（22）が消え、古い `CLAUDE.md`（撤去した生成器が作ったもの）が置き換わり、スキル `commit`・`sdd-docs` が増える。会社 PC では、`~/.claude.json` に MCP の 2 件が入り、`settings.json` の `allow` に 2 件が増える。`settings.json` の退避コピーを取っておく（`~/.claude/backups/`）。`~/.claude.json` へ書く前は、Claude Code を終了する。初回は、`~/.claude.json` のキーの並びが辞書順に変わる（内容は同じ）ので、`chezmoi diff` には、認証の状態を含むほぼ全体が出る（人に見せない。画面共有の前に確かめる）。
- **反映の確認**: Claude Code で `/permissions`（規則の一覧とその出どころ）と `/status`（読み込んだ設定ファイル）。文法は `CLAUDE_CONFIG_DIR=<一時の場所> claude doctor`（認証なしで動き、誤りを「Invalid settings」に出す。終了コードは 0 のまま）。
- **戻す**: `home/dot_claude`・`home/modify_private_dot_claude.json`・`claude-permissions.json`・`claude-mcp-servers.json` を消し、`.chezmoiignore.tmpl` の `.claude`・`.claude.json` の除外も外す（管理から外れる。配った中身は残る）。`settings.json` は退避コピーから戻す。配った MCP は、`claude mcp remove --scope user agentcore-websearch`・`claude mcp remove --scope user webfetch` で消す。

## 限界

- **Bash の deny・ask は境界ではない。** 公式 docs は、`/usr/bin/curl`・`sh -c '…'`・`git -C . push` のような別の形は止まらないと書いている。実際の囲いは、既存の `sandbox`（このリポジトリは管理しない）。
- 照合の前処理も pi と違う。Claude Code は、`timeout`・`time`・`nice`・`nohup`・`stdbuf`・`command`・`builtin`・`noglob` を剥がしてから照合し、複合コマンドを分けて 1 つずつ見る（deny・ask は、どれかが当たれば効く）。
- **cc-safety-net 本体は、Claude Code に入っていない。** 上の glob は、その代わりの最小限で、`git -c k=v reset --hard`・`/usr/bin/git reset --hard`・`bash -c '…'` の中のような別の形は止まらない。同じ package は Claude Code にも対応している（公式の手順 `npx -y cc-safety-net@latest install --claude-code`。Node.js 22 以上。プラグイン `cc-safety-net@cc-marketplace` として入り、`PreToolUse` の hook で各ツールの呼び出しの前に判定する。[公式 docs](https://ccsafetynet.com/docs/installation/claude-code)、取得 2026-11-18）。`modify_private_settings.json` は `enabledPlugins`・`hooks` などを保つので、入れたあとの `chezmoi apply` で消えない。入れるかは利用者が決める（このリポジトリは導入を自動化しない）。
- **誤検知（受容）**: pi と同じ広い規則で、`*` が引用符の中まで当たる。コミットメッセージ・検索語に、`flow publish`・`flow * publish`・`auth token` を含む `git -C …`・`git flow …`・`gh …` は deny、`config` を含む `git -C …` は ask になる（例: `git -C . commit -m 'docs: explain flow publish behavior'`）。語を変えるか、利用者が実行する。判定の表に例を入れてある。
- **`git config` は、読み取りも deny になる。** Claude Code は allow で例外を作れない。`git -C <dir> config …` は pi と同じ ask。
- **同時の書き込み**: `modify_private_settings.json` は、現在の内容を読んでから書く。その間に Orca や Claude Code の `/config` が書くと、その更新を取り落とす。実行中の設定変更と `chezmoi apply` は重ねない。`modify_private_dot_claude.json` も同じ（`~/.claude.json` は、本体がもっと頻繁に書く。上の「MCP」）。
- **`claude` が PATH に無い機**では、`.chezmoiignore.tmpl` が `.claude` を除外するので、`.chezmoiremove` の `.claude/…` の掃除（旧いスキル・hook）も働かない（chezmoi は、除外した対象を消さない）。
- 規則が実際の対話で意図どおり当たるかは、Claude Code を動かさないと確かめられない（認証が要る）ので、**未確認**。試験を置かないので、壊れても検査では気づけない。Windows も未確認。
- 既存の `sandbox` は、ネットワークの許可リストが厳密で、機のパスを含む。`settings.json` のほかの部分は、このリポジトリの管理外。

## 試験の対象外

Claude Code の設定には、**試験を置かない**（利用者の決定、2026-11-18。維持するコードを減らす。[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md) の教訓: pi 以外のハーネスの試験が、全体の約 84% を占めた）。
`scripts/verify.py` の規則は、`home/dot_claude/**` と `claude-permissions.json` の変更に、Claude 専用の試験を選ばず、テンプレートの検査だけを足す（この規則が無いと、どの規則にも当たらず全件に回る）。パスが重なる共通の規則（`modify_*` の「modify ラッパー」・`.chezmoitemplates` の「共有テンプレート」）の試験は、ほかと同じく選ばれる（それらは Claude を対象にしていない）。`test_skill_frontmatter` の「配布先の更新漏れ」の検査からは、`home/dot_claude/skills/` を明示して除いた（`SKILL_ROOTS`・pre-commit の frontmatter の検査にも足していない）。

変えるときは、次を手で確かめる（MCP は、上の「MCP」の「確認（手で）」）。

- `chezmoi --source <リポジトリ> --destination <一時の場所> --config <[data] だけの toml> --persistent-state <一時のファイル> apply <一時の場所>/.claude` で、既存の `settings.json`（Orca の hook・`allow`・`defaultMode`・`sandbox` を含む）を保ったまま、2 つのリストだけが置き換わること。もう一度流して差分が無いこと（冪等）。
  `PATH` に `claude` があること（`.chezmoiignore.tmpl` の `lookPath`）。
- `CLAUDE_CONFIG_DIR=<一時の場所>/.claude claude doctor` が「Invalid settings」を出さないこと（認証なしで動き、終了コードは 0 のまま）。
- `chezmoi diff` で、反映する前の差分を見る。

**実装時（2026-11-18）に確かめて、試験は残していない内容**: 上の 3 つに加え、壊れた JSON・BOM 付きは apply がエラーになりファイルは変わらない、CRLF は読めて LF で書く、空・空白・`permissions` が null や object でないときは `permissions` を作り直す。
規則の判定は、公式 docs の記述（`*` の意味・末尾の `*` の省略の条件・複合コマンドの分割・deny → ask の順）を写した模型で、約 75 件の操作の表と、秘密のパス・保護するパスの表を確かめた（実物の照合器ではない）。

## 出典

- Claude Code の docs（2026-11-18 取得）: [Settings](https://code.claude.com/docs/en/settings)・[Permissions](https://code.claude.com/docs/en/permissions)・[Skills](https://code.claude.com/docs/en/skills)。
- chezmoi の `modify` テンプレート: [Manage part, but not all, of a file](https://www.chezmoi.io/user-guide/manage-different-types-of-file/#manage-part-but-not-all-of-a-file)（取得 2026-11-18。`chezmoi:modify-template`・`setValueAtPath`・「`.tmpl` を付けない」）。
