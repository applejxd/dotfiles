# OpenCode 向けの設定の生成（保留中のレガシー）

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の正本は `[pi]` / `[pis]`。pi と共有する設定（モデルの割り当て・コミットの確認・スキルのスクリプトなど）は [AI CLI 設定の生成と所有権](agent-config-generation.md) に残してある。

この文書は、`common.toml` の `[opencode.*]` のうち **OpenCode だけが使う設定**（plugin 層・bypass・キーバインド・隔離起動 `ocs` など）の生成の仕様を書く。OpenCode の撤去（CHG-0020 段 6）のとき、この文書ごと消せる。

## OpenCode 専用の設定

### glob の記法差

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

OpenCode のワイルドカードは `*` (**`/` を含む** 0 文字以上) と `?` だけで、
`**` という記法が無い。`[file]` の glob をそのまま渡すと `**/x` が「`*` 2 つ」
として読まれ、`foox` のような意図しないパスにも当たる。

`generate.py` の `opencode_path_patterns()` が次の規則で変換する。

| `[file]` の glob | OpenCode の resource | 理由 |
| --- | --- | --- |
| `**/.netrc` | `.netrc` と `*/.netrc` | `**/` は「0 段以上」なので 2 本に割る |
| `**/.ssh/**` | `.ssh/*` と `*/.ssh/*` | 同上 |
| `**/*.pem` | `*.pem` のみ | `*` が `/` を跨ぐので入れ子側を含む |
| `.env` | `.env` | `**` が無いものはそのまま |

`test_generate_opencode.py` が変換表と「出力に `**` が残らないこと」を固定する。

### 整形 (formatter)

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

`format-file.sh` / `markdownlint.sh` は PostToolUse hook なので OpenCode では
動かないが、ここだけは **CLI 本体の機能で等価な結果になる**。`opencode.json` の
`formatter` に `[opencode.formatter]` を出力する。

| hook が呼んでいたもの | OpenCode での担い手 |
| --- | --- |
| `ruff format` (`.py`) | 組み込み `ruff` |
| `clang-format -i` (`.c` / `.cpp` / `.h`) | 組み込み `clang-format` |
| `prettier --write` (`.js` / `.ts` / `.json` / `.yaml`) | 組み込み `prettier` |
| `markdownlint-cli2 --fix` (`.md`) | **組み込みに無い**。`[opencode.formatter.markdownlint]` |

テーブルを 1 つでも書くと組み込み formatter が全部有効になる（公式:
"An object also enables the built-ins"）。そのため `common.toml` に書くのは
**組み込みに無いものだけ**でよく、ruff / clang-format / prettier を
二重管理しなくて済む。

宣言したら `formatter` テーブルごと `common.toml` の持ち物になる。節ごと無ければ
触らない。空の `[opencode.formatter]` は `{}`（組み込みだけ）に置き換える。

`command` は argv 配列でシェルを通さない。`$FILE` が絶対パスに置換される。
組み込みに無い名前は `command` と `extensions` の両方が無いと **OpenCode が
黙って無視する**ため、`generate.py` が検査して `apply` を止める（拡張子の
先頭ドット忘れ・シェル文字列との取り違えも同様）。

hook 版との違いが 2 つある。

- **残った違反の警告が出ない**。`markdownlint.sh` は自動修正後に残った
  MD013 などを agent へ返すが、formatter は整形するだけ。違反の検出は
  pre-commit の `Markdown Lint` が受け持つ
- **同じ拡張子に複数が一致すると先勝ち**。組み込みが先、custom が後の順で
  試し、最初に成功したところで止まる。`prettier` は `package.json` に依存が
  宣言されている場合だけ動くので、このリポジトリでは `.md` は
  `markdownlint` に落ちる。JS プロジェクトでは `prettier` が先に取る

### OpenCode へ渡さないもの

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

| 渡さないもの | 理由 |
| --- | --- |
| `[web] allow_domains` / `deny_domains` | `webfetch` の resource は **URL 全体**で、`*` が `/` を跨ぐ。`*://*.example.com/*` は `https://evil.test/x.example.com/y` にも当たり、ドメイン許可を正しく書けない。過大な allowlist を出すより出さない方を選ぶ |
| `[file] claude_read_allow` | OpenCode は allow が既定 (`{action:"*", resource:"*", effect:"allow"}`)。同義の規則が増えるだけ |
| `[claude] mcp_deny` | Claude の `mcp__<server>__<tool>` と OpenCode の `<server>_<tool>` は別体系。機械変換すると実在しない名前を deny したまま気付けない |
| `[[hooks]]` | Claude の hook 契約とは別物。OpenCode 側は plugin で書く |
| `[sandbox]` | 通常起動に sandbox が無い (`claude_write_deny` の意図だけ `[file]` 側へ写している)。隔離起動 `ocs` は `[opencode.sandbox]` と `[sandbox] shell_network_allow` を使う ([OpenCode 隔離起動のアーキテクチャ](sandbox/opencode-sandbox.md)) |

### 既定は `ask`

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

`permissions` の先頭に `{action:"shell", resource:"*", effect:"ask"}` を置き、
**未掲載のコマンドが無条件に通らないようにしてある**。shell の `allow` は
`[pi.shell] allow` に書いた 5 件と、下のスキルのスクリプトだけで、`[bash]` とは共用しない
（`[bash]` は 3 CLI 共通のため、触ると効果の切り分けができなくなる）。

allow の基準は副作用なし・冪等・**任意コード実行を含まない**こと。
`git diff` / `git status` は `.git/config` 経由で任意コマンドを起動できる
ため載せない。

**allow に載せたコマンドは任意ファイル書き込みの手段にもなる。** scanner が
リダイレクトを分割せず resource に残すので、`wc -l f.txt > path` が `wc *`
に前方一致する。allow は最小に保つ以外の守り方が無い。

スキルのスクリプトの allow は `[pi.skill_scripts]` から出す
（[スキルのスクリプト](agent-config-generation.md#スキルのスクリプト)）。

### bypass から呼べる子エージェント

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

`bypass` は「通常と同じ permission のまま、確認（`ask`）だけを plugin が `allow` にする」
エージェント（[ADR-0014](../adr/0014-bypass-as-ask-upgrade.md)）。`common.toml` で
`bypass = true` と明示したものが対象で、`permission` に全 allow（`"*" = "allow"`）は
**書かない**（書くと deny の後ろに付いて静的 deny まで上書きする）。`bypass` の印は
生成時だけのキーで、`opencode.json` には出ない（V1 の `[opencode.agent]` でも
V2 の `[opencode.agents]` でも同じ）。

`bypass` のセッションから、同じく `bypass = true` の子エージェント `bypass-worker`（汎用）と
`bypass-fleet-worker`（`/fleet` の作業役）をサブエージェントとして起動できる。
**ほかのエージェント（`build` など）からは起動できない。** 逆に `bypass` が起動できる子は
**許可リスト**（`bypass-worker`・`bypass-fleet-worker`・`explore`・`review`・`commit`）に
限る。承認制の `general` / `fleet-worker` と、一覧に無い子（今後足す子、作業先のリポジトリや
plugin が定義する子）は起動できない。

```toml
[opencode.agent.bypass]
mode = "primary"
bypass = true
permission = { task = { "*" = "deny", bypass-worker = "allow", bypass-fleet-worker = "allow", explore = "allow", review = "allow", commit = "allow" } }

[opencode.agent.bypass-worker]
mode = "subagent"
bypass = true
permission = { task = "deny" }   # task は V2 の subagent

[opencode.agents.bypass-fleet-worker]
mode = "subagent"
bypass = true
system_from = "fleet-worker"
permissions = [
  { action = "subagent", resource = "*", effect = "deny" },
  # ... fleet-worker と同じ deny (git の状態を変える操作・question)
]
```

| 呼び出し元 | 起動できる子 |
| --- | --- |
| `bypass` | `bypass-worker`・`bypass-fleet-worker`・`explore`・`review`・`commit` |
| `build` | `general`・`fleet-worker`・`explore`・`review`・`commit`・一覧に無い子 |
| `plan` | `explore`・`review`（[子エージェント](#子エージェント)） |

- **許可リストにする理由。** 子は親が `bypass` でも自分の規則で動き、確認が自動で通るのは
  `bypass_agents` に載ったものだけ。承認制の子や一覧に無い子を起動すると、編集やシェルの
  たびに確認が出て無確認の前提が崩れる（[事例](../research/agents/agent-config-generation-notes.md)）。モデルは説明の広い `general` を選びがちでもある。子を足すときは
  一覧も見直す（一覧の更新が、確認なしで動けるかを見直す機会になる）
- **許可した子の作業ツリーの外の読み取りは、親が `bypass` なら確認を省く。**
  `explore` / `review` / `commit` は `bypass_agents` に無いので、自分の規則では確認が自動で
  通らない。guide plugin は、次の条件を**全部**満たすときだけ、その確認を `allow` にする
  （[CHG-0017](../change/closed/0017-builtin-agent-restrictions.md) の段 7）
  1. 効果が `ask`
  2. 評価しているエージェントが `rules.json` の `bypass_child_agents` に完全一致で含まれる
  3. action が `external_directory`
  4. その確認が `read` / `grep` / `glob` ツールから出たもの。`execute.before` でこの 3 つの
     呼び出しの ID を覚え、`evaluate` の `source.id` と突き合わせる（`execute.after` で忘れる）。
     shell（`workdir` など）や edit から出た確認は対象にしない。`commit` は `git status` /
     `git diff` を allow しているので、shell まで含めると外部のリポジトリで git が確認なしに動く
  5. `ctx.session.get` で引いたセッションのエージェントが、評価しているエージェントと一致する
  6. その `parentID` を 1 段だけ引き、親の**今の**エージェントが `bypass_agents` に入っている

  条件 1〜4 に当たらなければセッションを引かない。親を引けない（`parentID` が無い・取得の
  失敗や例外・エージェントが無い）ときは `ask` のまま。キャッシュせず、祖先は遡らない。
  判定は親の今のエージェントで行うので、途中で親を `build` に切り替えれば確認に戻り、逆に
  `build` から `bypass` に切り替えると、`build` が起動していた子にも効く。開けていない
  作業ツリーの外を読む確認だけを省くもので、`production.env` のような読み取りの `ask` は残る
- **自動で確認を省く子の一覧は別に持つ。** `[opencode.bypass_children] agents` に明示し、
  起動の許可リストからは導出しない（「起動してよい」と「確認を省いてよい」は別の権限で、
  導出すると編集できる子を起動の一覧に足しただけで確認まで省かれる）。`generate.py` は、
  空でない文字列の配列であること・ワイルドカードを含まないこと・`bypass` が名指しで起動を
  許可した子に含まれること・`bypass_agents` と重ならないことを検査し、違反は `apply` を止める
- `commit` は読むだけの計画役（コミットは呼び出し元が行う）
- **守れるのは自分の設定の下での事故まで。** 作業先のリポジトリの設定は公式の仕様で
  グローバルに勝つので、`bypass` の規則や、許可した名前の子の中身を上書きされると防げない
- **4 つの一覧は一致させない。** `bypass` が起動できる子（この許可リスト）、確認を自動で
  許可にする `bypass_agents`、`bypass` 以外から起動させない `guarded_subagents`、親が
  `bypass` のときに作業ツリーの外の読み取りの確認を省く `bypass_child_agents` は役割が違い、
  テストもそれぞれの期待値を固定する。`explore` などに `bypass = true` を付けて許可リストを
  組み立てると、`build` から呼べなくなり、起動元に関係なく確認が自動で通る別の仕様になる
- **deny した子は `subagent` ツールの一覧から消える**（実測）。`/fleet` の指示文は
  「一覧に `bypass-fleet-worker` があればそれ、無ければ `fleet-worker`」で使い分けさせる
- `bypass-fleet-worker` は、`/fleet` の作業役を `bypass` でも無確認で動かすためのもの。
  `system` は `system_from` で `fleet-worker` から写し（`generate.py` が生成時に展開し、
  `opencode.json` には `system` だけを出す。写し元は `system` を直接持つ
  `[opencode.agents]` に限る）、deny は `fleet-worker` と同じものを並べる。deny が
  そろっているかは `test_bypass_fleet_worker_keeps_every_fleet_worker_deny` が突き合わせる
- `generate.py` は、`bypass = true` でサブエージェントとして使えるエージェント
  （`mode` が `subagent` / `all`）ごとに、全体の `permissions` の**最後**へ
  `{ action: "subagent", resource: "<名前>", effect: "deny" }` を足す
  （`opencode_subagent_guards`）。印は真偽値の `true` だけを認め、自動判定はしない
  （全 allow を書いても印にならない）。数える対象は `common.toml` の `[opencode.agent]` と
  `[opencode.agents]` の宣言だけで、`rules.json` の `guarded_subagents` にも同じ名前を出す
  （`opencode_guarded_subagents`）。印のあるエージェントは `bypass_agents` にも入る
  （plugin が `ask` を `allow` にする対象）
- エージェントの規則は全体の規則の後ろに付き、最後に一致した規則が勝つ。
  `bypass` の `task` の個別の allow はこの deny を上書きする
  （[実測](../research/opencode/permission/bypass-ask-upgrade.md)の 5 は `*` の allow で確かめた）
- **全体の deny だけでは足りない。** `common.toml` に無いエージェント（手で足した
  別名のもの）の `permission` は残す（[所有の規則](#配置済みの設定の所有)で管理しない ID）。
  そこに `task = "allow"` などがあると、同じ理屈で deny が上書きされる。
  こうした個別の上書きは利用者の責任で、`generate.py` は各エージェントへ deny を
  差し込まない（[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md) の非目的）。
  組み込み（`build` など）の手書きの `permission` は所有の規則で消える。
  下の guide plugin の検査は、上書きされた後の effect でも止める
- guide plugin でも起動元を検査する（二重の検査）。`rules.json` の
  `guarded_subagents` に名前を出し、`permission.evaluate` の `action` が `subagent`、
  `resources` がこの一覧に当たり、`agent` が `bypass_agents` に無ければ effect を
  `deny` にする。`agent` が載らない場合も deny（安全側）。`common.toml` で
  印を付けていないエージェントも `bypass_agents` に入らないので止まる。
  plugin は一覧が空でなければ登録される（`opencode_guide_server_needed`）。
  プロジェクトの `opencode.json` のように `generate.py` が触らない設定は、こちらだけが守る。
  `rules.json` が読めないときの扱いは[下](#rulesjson-が使えないとき)
- 設定の deny に当たった呼び出しは hook が発火しないので、plugin は deny を
  緩める側には回らない（[Bypass モードの調査 5 章](../research/opencode/permission/bypass-agent.md#5-plugin-は-bypass-を貫通する段階-2-の前提)）
- `bypass` は `mode = "primary"` を明示する。`mode` を宣言しないと OpenCode の既定に任せる
  ことになり（所有の規則より前は既存設定の `mode` が残った）、`all` / `subagent` なら `bypass` を
  子として起動できてしまう
  （`build` → `bypass` → `bypass-worker`）。`bypass = true` のエージェントは `common.toml` で
  `mode` を必ず宣言する（`test_bypass_agents_in_common_declare_their_mode`）
- `bypass-worker` / `bypass-fleet-worker` 自身は子の起動が deny なので、さらに子を起動できない
  （入れ子にならない）
- 「Always allow」で保存した承認は、設定の deny を上書きしない
- `bypass` でも**静的 deny は効く**。秘密ファイルの read / edit の deny・`pip` の deny は
  外れない。誘導・結果フィルタ・伏字化も通常と同じに効く（下の plugin 層）
- 隔離起動（`ocs`）でも、全体の deny と guide plugin の検査の両方が効く
  （[隔離版の設定の書き出し方](sandbox/opencode-sandbox.md#エージェントとコマンド)）

実測の結果は[記録 N12](../research/agents/agent-config-generation-notes-2.md#記録-n12--bypass-の子の起動の実測)と
[Bypass モードの調査 6 章](../research/opencode/permission/bypass-agent.md#6-bypass-からだけ呼べる子エージェント2026-09-28)。
`bypass` から `general` / `fleet-worker` を外した構成と `bypass-fleet-worker` の実測は
同じ調査の [7 章](../research/opencode/permission/bypass-agent.md#7-bypass-の子の入れ替え2026-09-30)。
全 allow を外した構成の実測は [ask→allow の調査](../research/opencode/permission/bypass-ask-upgrade.md)。

### plugin 層 (`guide-plugin`)

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

`~/.config/opencode/guide-plugin/` に置く。判定表は `common.toml` の
`[[opencode.shell.guide]]`・`[bash.deny_guide]`・`[pi.redact]`・`[opencode.ask_description]`・
`[file] read_deny_globs`・`[opencode.agent]`・`[opencode.agents]`・`[opencode.bypass_children]` から `rules.json` として生成し、plugin は読むだけにする。
`index.js` はこのどれかが有効なら、`tui.ts` は `ask_description` が有効な
ときだけ登録する（`generate.py` の `opencode_guide_server_needed` /
`opencode_guide_tui_needed`）。

| 役割 | 実体 | 登録先 |
| --- | --- | --- |
| 誘導（deny + 代替案）と説明の生成 | `index.js` | `opencode.json` の `plugins` |
| allow したコマンドの書き込み形の歯止め（リダイレクト・`git log --output`。[詳細](guard/opencode-guard.md#opencode-の-allow-したコマンドの書き込み形)） | `index.js` | 同上 |
| 静的 deny の説明（前段停止。`deny_guide`。[詳細](guard/opencode-guard.md#opencode-の-deny-の説明前段停止)） | `index.js` | 同上 |
| `grep` / `glob` の結果フィルタ | `index.js` | 同上 |
| shell 出力の伏字化 | `index.js` | 同上 |
| bypass の子エージェントの起動元の検査（[上](#bypass-から呼べる子エージェント)）と `ask` → `allow` | `index.js` | 同上 |
| 親が `bypass` の読むだけの子の、作業ツリーの外の読み取りの `ask` → `allow`（[上](#bypass-から呼べる子エージェント)） | `index.js` | 同上 |
| 確認画面への説明表示（toast） | `tui.ts` | **`cli.json` の `plugins`** |
| `git commit` の件名と本文の表示（[下](agent-config-generation.md#git-commit-の件名と本文)） | `tui.ts` と `commit-message.js` | 同上 |

`2.0.14` では `opencode.json` の `plugins` に書いたディレクトリからも `tui.ts` が
読まれる（`cli.json` 無しで実測。[ask 画面の調査 12 章](../research/opencode/plugin/ask-description.md#12-v2014-の再確認確認画面のすぐ上に出せる2026-09-30)）。
隔離起動（`ocs`）は `cli.json` を渡さないが、`index.js` を載せていれば `tui.ts` も読まれる。
説明の生成だけでは隔離版の設定に `index.js` を載せない。

**登録先が分かれるのは仕様（2.0.12）。** `opencode.json` に書いたディレクトリからは
TUI 側が読まれない。どちらも**絶対パスのディレクトリ**でないと解決されず、
`~` も単一ファイルも黙って無視される。

**`cli.json` は Orca セッションでは読まれない。** `OPENCODE_CONFIG_DIR` が
overlay を指すためで、パス指定の環境変数は存在しない。`shellenv.sh` が
`OPENCODE_CLI_CONFIG_CONTENT` へ本文を流し込んで補う。TUI plugin と
[キーバインド](#キーバインド)の両方がこれに依存する。

plugin が守る規約は次のとおり。

- **`bypass` は ask を allow にするだけ。** `permission.evaluate` の**最後**で、
  `rules.json` の `bypass_agents` に載ったエージェントの `ask` を `allow` に書き換える
  （[ADR-0014](../adr/0014-bypass-as-ask-upgrade.md)）。誘導で `deny` にしたものは
  `deny` のまま、静的 deny は `evaluate` に届かないのでそのまま止まる。
  `bypass_agents` が読めない・壊れているときは書き換えず `ask` のまま（安全側）。
  説明（`ask_description`）は `allow` になるものには生成しない。
  判定は**エージェント名**で行う（`permission.evaluate` に `agent` が載ることを
  実測。[hook の呼ばれ方](../research/opencode/permission/hook-order.md)）。
  名前は `common.toml` の `bypass = true` から生成するので単一ソースが保たれる。
  `commit` など別の名前の子の `ask` は書き換えない。例外は、親が `bypass` のときの
  `bypass_child_agents` の作業ツリーの外の読み取り（[上](#bypass-から呼べる子エージェント)）
- **`bypass` にも誘導・前段停止（early）・`grep` / `glob` の結果フィルタ・shell 出力の
  伏字化を同じに効かせる。** 素通りさせる判定は持たない。誤爆は誘導規則側を直す。
  子エージェントの起動制限（`guardSubagent`）だけは `bypass_agents` を見る
- **`effect` では見分けない。** `allow` で判定すると
  `cd x && git log`（`git log` が静的 allow）のように、allow を含む呼び出しまで
  誘導が素通りする
- **リダイレクトを含むコマンドは `allow` へ引き上げない**（`bypass` 以外）

「秘密を読むために一時的に全部外す」逃げ道は OpenCode の中には残さない。
そのときは Copilot CLI を使うか、利用者自身がコマンドを実行する。

#### `rules.json` が使えないとき

plugin のロード（モジュールの評価と `setup`）が例外で失敗すると、OpenCode は
plugin 無しで続ける（fail-open。[plugin API の実測 6 章](../research/opencode/plugin/api-probe.md#6-失敗時の挙動最重要)）。
そのため `index.js` は `rules.json` の読み込みと正規表現のコンパイルを節ごとに
例外から切り離し、ロード自体は必ず通す。壊れた節は `console.error` に記録し、
節ごとに次のように倒す。hook の中の例外は fail-closed なので、そちらは切り離さない。
例外は親のセッションを引く処理（`bypass_child_agents` の判定）で、権限を足すための照会なので、
失敗したら例外を投げずに `ask` のままにする。受け止める範囲はこの照会だけに限る。

| 壊れたもの | 扱い | 理由 |
| --- | --- | --- |
| ファイルが無い・JSON でない・オブジェクトでない | 下の全部の節が「壊れた」扱い | — |
| `bypass_agents` が無い・文字列の配列でない | `bypass` の `ask` を `allow` にせず `ask` のまま。子エージェントの起動元も検査しない（止めずに警告） | 一覧が無いと `bypass` も守る子との関係も分からない。`ask` のままなら確認が出るだけで安全側。全部止めると普段の作業ごと止まる（[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md)） |
| `guarded_subagents` が無い・文字列の配列でない（`bypass_agents` は正常） | 子エージェントの起動元を検査しない（止めずに警告）。`bypass` の `ask` → `allow` は続ける | 起動元の検査と `ask` の引き上げは別の機能。子の一覧だけの破損で `bypass` 全体を止めない |
| `bypass_child_agents` が無い・`null`・文字列の配列でない・空 | 親が `bypass` の子の作業ツリーの外の読み取りを引き上げない（`ask` のまま。壊れていれば警告）。ほかの節は今までどおり | 権限を足す機能なので、分からなければ足さない |
| `read_deny` が無い・`null`・文字列の配列でない・正規表現にできない | `grep` / `glob` の結果を伏せ、理由を本文に残す | この 2 つには plugin が唯一の保護 |
| `guide` | 誘導しない（確認は静的な規則どおり出る） | 誘導は代替案の案内で、境界ではない |
| `redact` | 伏字化しない | 伏字化は安全網で、境界ではない |

- **`read_deny` の明示的な `[]` だけは有効な空**として扱い、結果を濾さずに通す。
  `generate.py` は `read_deny` を必ず出すので、欠落や `null` は壊れた `rules.json` の印になる
  （`test_malformed_read_deny_withholds_results` / `test_empty_read_deny_keeps_results`）
- 一覧が読めない間、`bypass-worker` を止めるのは全体の deny だけになる。個別に
  `task = "allow"` などを持つエージェントからは起動できる
- **直した `rules.json` は再起動するまで読まれない。** `index.js` はモジュールの評価時に
  一度だけ読むので、`chezmoi apply` で作り直しても、常駐サービスの中では壊れた扱いが続く。
  `chezmoi apply` の後に `opencode service restart` を実行する
  （[下](#shell-出力の伏字化)の、サーバ側 plugin の更新と同じ）。隔離起動（`ocs`）は
  `--standalone` の専用サーバなので、そのセッションを起動し直す。自動の読み直しは足さない
- 古い形（`guarded_subagents` が無い）の `rules.json` も同じく一覧が無い扱いになる
- 試験は `test_generate_opencode.py` の `test_plugin_leaves_subagents_alone_when_rules_are_unusable`
  など。一覧が読めないときに全部 deny していた版の実機の結果は
  [Bypass モードの調査 6 章](../research/opencode/permission/bypass-agent.md#plugin-の起動元の検査と-rulesjson-が壊れたとき2026-09-29)

#### `grep` / `glob` の結果フィルタ

permission の `read` deny は**この 2 つのツールに効かない**
（[permission の穴](../research/opencode/permission/gaps.md)）。そのため
`tool.execute.after` で結果から保護対象を落とす。

- 判定パターンは `[file] read_deny_globs` から生成する（単一ソース）。
  `*` は `/` を跨がず、`**` だけ跨ぐ
- `grep` はファイル単位の塊を落とし、**件数ヘッダも訂正する**
  （`Found 2 matches` → `Found 1 matches`）。放置すると存在だけ漏れて
  本文と矛盾する。`metadata` の件数も同時に直す
- 正規表現に `/g` を付けない。`lastIndex` が残って `.test()` が交互に
  `false` を返し、半分すり抜ける

**効くのは `grep` / `glob` ツールだけで、shell の `grep` には効かない。**
shell 経由の読み取りは誘導（`cat` / `head` / `tail` / `sed -n` を `read` へ）
で減らしているが、`grep -n` は静的 allow なので素通りする。ここは下の
出力伏字化が受け持つ。

**`~/` 始まりの glob は 2 本に展開する。** 結果には展開済みの絶対パスしか
載らないため、`~` のままの正規表現は一度も当たらない。コマンド文字列には
`~` のまま書かれるので、どちらの形も残す。

#### shell 出力の伏字化

誘導と結果フィルタを抜けて shell を通ったものへの安全網。
`tool.execute.after` で `result.content[].text` を書き換える
（`result.output` は文字列ではない）。手段は 2 つある。

| 手段 | 当てる先 | 効き方 |
| --- | --- | --- |
| 内容の形（`[[pi.redact.rule]]`） | 出力本文 | 当たった範囲だけを `[伏字:名前]` に替える |
| 参照したパス（`deny_path`） | コマンド文字列 | **出力全体**を伏せ、理由を本文に残す |

- 内容の形は**大文字小文字を区別せず**当てる（`GITHUB_TOKEN` と
  `github_token` を分けない）。当たった範囲がそのまま置き換わるので、
  前置きの語は後読み `(?<=…)` で外に出す
- **代入形の規則を緩めない。** 値が「不透明な長い文字列」か「引用符で
  囲まれたもの」のときだけ伏せる。緩めると `const token = getToken()` の
  ような**コード**まで伏字になり、shell 経由の `grep` が読めなくなる
- パス判定には `**/*secret*` のような**部分一致 glob を使わない**。
  コマンドには `docs/spec/secret-handling.md` のような正当なパスも載る
- 誤爆時は**黙って消さない**。理由を本文に残せば手が打てる

`deny_path_unless` は出力全体を伏せる判定の除外。保護パス名を**文章として**
書いたときの誤爆を外す（`git commit -m '… ~/.claude.json …'` で出力が
丸ごと消えるのを防ぐ）。**除外はコマンド全体に当たる**ので
`git commit -m x && cat ~/.aws/credentials` は素通りするが、そこは誘導の
`deny` が受け持つ。

**伏字化は shell の出力にだけ掛ける。`read` / `grep` へ広げてはいけない。**
伏せた本文を元に `edit` されると、ファイルへ `[伏字:…]` がそのまま
書き込まれる。

**境界ではない。** `base64` や `tr` で変換されるとすり抜ける（実測）。
事故と素朴なプロンプトインジェクションを想定した層で、意図的な持ち出しは
止まらない（[出力フィルタ](../research/opencode/permission/output-filter-and-subagents.md)）。

**サーバ側 plugin を更新したら `opencode service restart` が要る。**
常駐サービスのプロセス内で動くため、`chezmoi apply` だけでは反映されない。
TUI 側は CLI プロセスなので再起動は不要。

反映されたかは**サービスの起動時刻**で見る。`ps -C opencode -o pid,lstart`
を使うこと。`pgrep -f "opencode serve"` は**自分自身のシェル**に当たり、
`stat -c %Y /proc/<pid>` は**起動時刻ではない**。どちらも偽の「再起動済み」を
返す（[hook の呼ばれ方](../research/opencode/permission/hook-order.md)）。

効いているかは適用した規則を 1 つ叩けば分かる。

```sh
head -1 README.md   # 誘導が生きていれば permission.rejected が返る
```

### 確認画面に出るコマンドの説明

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

60 文字以上のコマンドで確認が出るとき、安価なモデルが 1 行の日本語説明を
作り、toast で表示する。破壊的操作・外部送信・秘密への接触があれば
先頭に `⚠` が付く。

```toml
[opencode.ask_description]
models = ["amazon-bedrock/us.anthropic...", "github-copilot/claude-haiku-4.5", ...]
```

`models` は上から試し、使えたものを採用する。**Bedrock 未設定なら自動的に
Copilot へ落ちる**（catalog に無いものは通信せず飛ばす）。
toast の表示時間は `duration_ms`（既定 20000）で、`tui.ts` が `rules.json` から読む。

**説明は判断の補助であって判定器ではない。** コマンド文字列は信頼できない
入力で、偽装は原理的に防げない。確認画面は常に生コマンドを表示するので、
そちらが一次情報。

モデル呼び出しが失敗・タイムアウトしても**確認は通常どおり出る**
（説明が付かないだけ）。

### キーバインド

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

TUI のキーバインドは **`cli.json` 側にしか無い**。`opencode.json` へ書いても
読まれず、誤配置に気づけないので `[opencode.keybinds]` を単一ソースにして
`merge_opencode_cli()` が `cli.json` へ出す。

```toml
[opencode.keybinds]
"app.exit" = "ctrl+d"
"session.interrupt" = "ctrl+c,escape"
"service.restart" = "<leader>v"
```

値は文字列・カンマ区切り・配列・`{key, preventDefault}` のテーブルが使える。
無効化は `false` か `"none"`。`<leader>` は既定 `ctrl+x` で、タイムアウトだけ
`keybinds` の外（`leader.timeout`）にある。ID・既定値・キー記法は
[公式一覧](https://opencode.ai/v2/docs/cli/keybinds)が正本。実測は
[キーバインドの調査](../research/opencode/keybinds.md)。

**公式一覧は最新版向けで、2.0.12 に無い ID が載っている。** しかも未知の ID は
「拒否される」と書かれているが、実際には**その行だけ黙って無視され**、
他の行は生きる。無視された leader 系の binding は次のキーが素通りして
文字入力になるため、気づきにくい。ID を足す前に実在を確認する。

```console
$ strings -n 4 ~/.opencode/bin/opencode | grep -x 'service.restart'
service.restart
```

実測で分かった不在の例が `permission.mode`（自動承認のトグル）。2.0.12 には
代替も無いので、確認の一時解除は
[bypass エージェント](../research/opencode/permission/bypass-agent.md)を使う。

**宣言したら `keybinds` テーブルごと `common.toml` の持ち物になる。**
1 件消したときに配備先へ残らないようにするため。節ごと無ければ触らない。
空の `[opencode.keybinds]` を書くと既存を空にする（すべて既定に戻る）。

割り当てで注意する点が 2 つある。

- **`ctrl+c` を `session.interrupt` へ渡すには `app.exit` から外す。**
  `app.exit` の既定は `ctrl+c,ctrl+d,<leader>q` で、残したままだと
  Ctrl+C が中断ではなくアプリ終了になる
  （`test_ctrl_c_interrupts_instead_of_exiting` で固定）
- `<leader>` の空きは `d` `f` `h` `j` `k` `o` `p` `v` `z` の 9 文字だけ。
  `d` は `diff.open`（既定 `none`）用に空けてある

`service.restart` は**サーバ側 plugin を更新したときに要る**再起動
（[plugin 層](#plugin-層-guide-plugin)）を 1 キーにしたもの。

**Orca セッションでは `shellenv.sh` の注入が前提**（[plugin 層](#plugin-層-guide-plugin)）。
`cli.json` が読まれないと**キーバインドは丸ごと既定に戻る**ので、
`app.exit` が `ctrl+c` を握ったままになり Ctrl+C で終了する。

### 常駐サービスのポート

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

Windows の常駐サービスだけ `port = 4098` にする（`common.toml` の `[opencode.service]`。
Windows で描画したときだけ現れる）。`merge_opencode_service()` が
`~/.config/opencode/service.json` の `port` だけを書き、`password` などは残す。
Windows 以外では `.chezmoiignore.tmpl` がこのファイルを外し、OpenCode に任せる。

**理由**: WSL と Windows の OpenCode が localhost を共有する構成で、どちらも既定で同じ 127.0.0.1 の
ポート（4097）を常駐サービスに使い、先に起きた側が握ると、もう一方は起動できずに止まるため
（[経緯](../research/agents/agent-config-generation-notes.md)）。

- `service.json` は秘密情報（`password` が平文）。生成側は `port` 以外を読み書きしない
- 反映には Windows 側で `opencode service restart` が要る
- 使えるキーは OpenCode の `opencode service set` と同じ
  `hostname` / `port` / `password` / `cors` / `env`。ここでは `port` だけを受け付ける
- `port` が無いときの既定は 49374（`0xc0de`。`latest` チャンネル。上流
  `packages/cli/src/services/service-config.ts` の `defaultPort()`）。4097 / 4098 は
  どこかで `service set` された値
- **設定ファイルの場所は `OPENCODE_CONFIG_DIR` に従う。** Orca のセッションでは
  `~/.orca-relay/opencode-overlays/<hash>/service.json` が読まれ、
  `~/.config/opencode/service.json` は使われない。Orca 内で `opencode service set` を
  試すとそちらが書き換わるので、Orca の外のシェルから設定する（[経緯](../research/agents/agent-config-generation-notes.md)）

### 生成されるもの

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

| キー | 中身 | 残すもの |
| --- | --- | --- |
| `model` | `default` 階層 | — （毎回書く） |
| `agents.<id>.model` | 割り当てた階層 | 割り当てを外したとき、値が階層のモデルなら消す。手で書いた別のモデル・他のキーは残す |
| `providers.<id>.settings` | `[provider.<id>]` の `profile` / `region` | 他のキー（`baseURL` など）と他のプロバイダ |
| `experimental.policies` | `provider.use` を `*` で deny、この PC のプロバイダだけ allow | [所有の規則](#配置済みの設定の所有) |

- **V1 形式の `agent` ではなく V2 形式の `agents` に書く。** `agent` だと
  `#variant` 付きの指定が黙って無視され、親のモデルで動く
  （[実測](../research/opencode/agent-models.md)）
- **policies はグローバル設定がプロジェクト設定に勝つ**ので、リポジトリの
  `.opencode/opencode.json` から別のプロバイダを有効にされない
  （[policies の優先順位](../research/opencode/permission/gaps.md#他の経路2026-09-23-追加実測)）
- Bedrock は `profile` か認証の環境変数が無いと**有効にならない**（region だけでは
  足りない。公式）。常駐サービスへシェルの `AWS_REGION` が渡る保証も無いので、
  `profile = "default"` と `region = "us-east-1"` を設定に書く

### 効かない使い方

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

**主エージェント（`build` / `plan` など）の `model` は、エージェントを選んだだけでは
使われない。** セッションのモデルは別に保存されていて、`--agent plan` で起動しても
既定モデルのまま動く（[実測](../research/opencode/agent-models.md)。公式の記述どおり）。
子エージェント（`explore` など）の `model` は効く。

主エージェントを重いモデルで動かしたいときは、`agent:` を指定したスラッシュコマンドを
経由させる（公式ではコマンドで選んだエージェントの `model` が呼び出し時のモデルに勝つ。
未実測）。

### 隔離起動（`ocs`）

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

`ocs` の既定モデルは `[opencode.sandbox] model_preference` が決め、ここの `default` は
使わない（通常版から引き継ぐのは `model` だけ）。エージェントごとの割り当ては、この PC の
プロバイダが `[opencode.sandbox] providers` にあるときだけ隔離版にも出す
（[隔離版の設定の書き出し方](sandbox/opencode-sandbox.md#エージェントとコマンド)）。
**Bedrock は `ocs` では使えない**
（コードから判断。実機では未確認）。境界の内側から `~/.aws` が読めず
（開けていない）、AWS の資格情報の環境変数も落とすため（`ocs` の `inner_env`）。
`[provider.amazon-bedrock] network_allow` は用意してあるが、`providers` には入れていない。

### 子エージェント

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

`[opencode.agents.<id>]` に V2 形式でエージェントを定義し、`opencode.json` の
`agents` へ出す。モデルは書かず、[`[opencode.model.agents]`](agent-model-assignment.md#モデルの割り当て) で
階層を割り当てる（PC ごとのプロバイダで ID が変わるため）。

| ID | 階層 | 役割 | 権限で塞ぐもの |
| --- | --- | --- | --- |
| `commit` | `routine` | 変更を読み、ファイル単位の論理単位ごとに対象とメッセージ全文（計画）を返す。提示・ステージ・コミットは親が行う | 編集・質問・子エージェントの起動・読み取り以外の shell（[コミットの確認](agent-config-generation.md#コミットの確認)） |
| `review` | `second_opinion` | 別系統のモデルで、設計案・差分・調査結果の欠陥を指摘する | 編集・shell・質問・子エージェントの起動 |
| `explore` | なし（組み込み） | 組み込みの探索役。今あるファイルを read / glob / grep / webfetch / websearch で探す。Git の履歴やコマンドが要る調査は親へ返す | 編集・shell・質問・子エージェントの起動 |
| `plan` | なし（組み込みの主エージェント） | 組み込みの計画役 | 計画ファイル（`~/.opencode/plan/*`）以外の編集。子は `explore` / `review` だけ。shell は deny を除いて確認（全体の allow を引き継がない） |

- **組み込みの `explore` / `plan` も宣言して制限を並べ直す。** OpenCode の規則は「基底 →
  組み込みエージェントの追加方針 → 全体の `permissions` → エージェントの `permissions`」の順に
  連結され、最後に一致したものが勝つ。全体の規則（`build` 向けの `.env.example` などの例外の
  allow、作業ツリーの外の edit の確認、`shell * ask` と shell の allow）が、組み込みの制限を
  上書きする。宣言しないと組み込みの制限が効かない（宣言しなかったときの不具合は
  [記録 N9](../research/agents/agent-config-generation-notes-2.md#記録-n9--組み込みエージェントを宣言しなかったときの不具合)、[調査記録](../research/opencode/permission/builtin-agent-override.md)、
  [CHG-0017](../change/closed/0017-builtin-agent-restrictions.md)）。`system` は書かず、組み込みの
  プロンプトを使う（plan モードの指示は利用者のメッセージに付いて渡され、宣言しても残る）
- **組み込みの方針を丸ごと写さない。** 足すのは deny と最小の allow だけ。`explore` の組み込みの
  `read *` の allow や `.env` の ask まで写すと、全体の秘密ファイルの deny を緩める
- **`restate_global_deny`**: エージェントに allow や ask を足すと、全体の deny より後ろに付くので
  全体の deny を上書きする（`plan` の計画ファイルの allow が、計画ディレクトリの中の `.env` などを
  許してしまう）。`restate_global_deny = ["edit", "shell"]` のように action 名を書くと、
  `generate.py` が全体の `permissions` のうちその action の deny を、全体での順のまま、
  エージェントの `permissions` の後ろへ写す。生成時だけのキーで `opencode.json` には出ない。
  書けるのは `[opencode.agents]` だけで、action は `read` / `edit` / `shell` / `subagent`。
  隔離版は隔離版の全体規則から写す
- `restate_global_deny` に `shell` を含むエージェントは、deny の前段停止の例外
  （`except_agents`）にしない。`plan` の `shell * ask` を理由に例外が付くと、前段停止が
  効かなくなる
- **元に戻すとき**は、宣言を消すと[所有の規則](#配置済みの設定の所有)で配備済みの
  `opencode.json` からも消える（組み込みと、宣言が残っている ID の場合。丸ごと消した自作の ID は残る）
- **`review` は shell を開けない。** `git diff` / `git status` も外部の diff
  ドライバや fsmonitor を通じてコードを実行しうる
  （[allow リスト監査](../research/opencode/permission/allow-list-audit.md)）。
  差分は親が依頼文に含めて渡す
- 書けるキーは `description`（必須）/ `mode` / `system` / `permissions` / `steps` /
  `hidden` / `color` / `disabled`、生成時だけのキーとして `restate_global_deny`。`model` と
  V1 形式のキー（`permission` など）は `apply` を止める。V1 の `[opencode.agent]` と同じ ID も止める
- `system` は組み込みの基底プロンプトを**置き換える**（公式）。`AGENTS.md` や
  スキルの一覧は引き続き足される
- `permissions` は全体の規則の後ろに付き、後勝ちで効く。効果は `allow` / `ask` / `deny`。
  隔離版で全体から捨てた `ask` も、エージェントの規則で戻せる
- 宣言したキーの差し替え・外したキーの削除・残すものは[所有の規則](#配置済みの設定の所有)が正本
- 隔離起動（`ocs`）にも同じ定義が出る。通常版の `opencode.json` からは引き継がず、
  `common.toml` から作る（[隔離版の設定の書き出し方](sandbox/opencode-sandbox.md#エージェントとコマンド)）

### 配置済みの設定の所有

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

`opencode.json` は OpenCode 自身や利用者も書くので、生成器は自分の持ち物だけを置き換え、
宣言から外したものは持ち物の範囲で消す（所有の規則。状態ファイルは持たない）。
比べた方式と実測は [CHG-0018](../change/closed/0018-opencode-policy-role-split.md) と
[調査記録](../research/opencode/agent-config-ownership.md)。

| 対象 | 生成器の持ち物 | 残すもの |
| --- | --- | --- |
| `permissions` | 全体（毎回置き換える） | — |
| `experimental.policies` | action が `permission` / `provider.use` の statement（毎回置き換え、末尾に書く） | ほかの action の statement と `experimental` のほかのキー |
| `agents.<id>`（V2） | 管理する ID の `description` / `mode` / `system` / `permissions` / `steps` / `hidden` / `color` / `disabled` | 生成器が書かないキー（`model` / `request` など）、管理しない ID |
| `agent.<id>`（V1） | 管理する ID の `description` / `mode` / `permission` / `prompt` / `color` / `hidden` / `disable` / `maxSteps` / `steps` / `tools` | 同上 |

- **管理する ID** は、`[opencode.agent]`（V1）と `[opencode.agents]`（V2）で宣言した ID と、
  既知の組み込み（`build` / `plan` / `general` / `explore` / `compaction` / `title` / `summary`。
  `generate.py` の `OPENCODE_BUILTIN_AGENTS`）。管理する ID では、持ち物のキーのうち今回
  宣言していないものを消す。宣言していない組み込みは、持ち物のキーを全部消す
- **宣言と逆の形式のエントリは消す。** V1 で宣言した ID の `agents.<id>`、V2 で宣言した ID の
  `agent.<id>`。同じ ID が両方にあると V2 が丸ごと勝ち、V1 の定義が黙って捨てられるため。
  中身が持ち物のキーだけ（V2 は割り当てを外した階層のモデルも含む）なら消し、それ以外の
  キーが残っていれば**消さずに `apply` を止め**、どのキーをどこへ移すかをエラーに出す
  （`model` は `[opencode.model.agents]` か、宣言した形式の側の `opencode.json` へ）
- **`experimental.policies` は `[opencode.model]` の有無に関係なく整える。** 書くものが
  無ければ持ち物の statement を消すだけで、`experimental` を新たに作らない
- **宣言から丸ごと消した自作の ID は撤去しない**（管理する ID から外れる）。消すときは
  `opencode.json` からも手で消す。割り当てた階層のモデルだけは[今までどおり](#生成されるもの)外れる
- `[opencode.model.agents]` には、`[opencode.agents]` で宣言した ID と組み込みだけを書ける。
  ほかの ID は `apply` を止める（モデルだけの定義は基底の全部許可で動くエージェントになる）
- `[opencode.agent]`（V1）に書けるキーは上の V1 の持ち物と `bypass` だけで、ほかは `apply` を止める
- **代償**: 管理する ID に手で書いた持ち物のキー（例: `plan.color`）と、手で書いた
  `permission` の policy は消える。要るなら `common.toml` に書く
- 試験は `test_generate_opencode_ownership.py`（手書きの設定・逆の形式・冪等・宣言を変えて
  戻したときに元の JSON に戻ること）

### 並列作業（`/fleet`）

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

Copilot CLI の `/fleet` に相当するもの。依頼を並列に動かせる作業に分け、
作業役の子エージェントを同時に起動して進める。仕組みは専用の機能ではなく、
**コマンドの指示文と、1 回の応答で `subagent` ツールを並べて呼ぶこと**で組んでいる
（Copilot の `/fleet` も取りまとめはプロンプトによる）。並べて呼んだ子は同時に走り、
全部が終わってから結果がそろって返るので、波の区切りが仕組みとして保たれる
（[実機確認](../research/opencode/fleet.md)）。

| 部品 | 置き場 | 中身 |
| --- | --- | --- |
| `/fleet` | `[opencode.commands.fleet]` → `opencode.json` の `commands` | 取りまとめの手順（分解 → 依存関係と担当ファイル → 波ごとに並べて起動 → 結果を確かめて次の波 → 検証してまとめる） |
| `fleet-worker` | `[opencode.agents.fleet-worker]`、階層 `worker` | 割り当てられた 1 つの作業を、担当ファイルの範囲で実装して確かめ、結果を返す |
| `bypass-fleet-worker` | `[opencode.agents.bypass-fleet-worker]`、階層 `worker` | `bypass` での作業役。指示と deny は `fleet-worker` と同じで、ほかは無確認（[bypass から呼べる子エージェント](#bypass-から呼べる子エージェント)） |

- **作業役は呼び出し元で決まる。** `bypass` からは `bypass-fleet-worker` だけ、
  `build` からは `fleet-worker` だけが `subagent` ツールの一覧に載る。指示文は一覧を見て
  使い分けさせる。どちらも載らない `plan` では、調査だけなら `explore` / `review` に分担し、
  実装を含むなら計画を示して止め、作業役を呼べるエージェントへの切り替えを利用者に頼む
  （拒否された作業を親の shell で肩代わりしない）
- **確認なしで進めたいときは `bypass` の上で使う。** `build` の上の `/fleet` は作業役が
  承認制なので確認が出る（[CHG-0017](../change/closed/0017-builtin-agent-restrictions.md) で対象外とした）
- 調査の振り分けは、今あるファイルの探索を `explore`、Git の履歴やコマンドが要る調査を
  作業役、第三者の検証を `review` にする（`explore` は shell を使えない）
- **取りまとめは今のセッションで動かす（`subagent = false`）。** 子エージェントは
  さらに子を起動できない（既定の入れ子は 1 段）。子にすると作業役を起動できない
- **作業役は同じ作業ツリーを共有する。** 衝突は、親が担当ファイルを重ねずに
  割り当てることで避ける。作業役には git の状態を変える操作（`add` / `commit` /
  `stash` / `checkout` / `switch` / `restore` / `reset`）を権限で禁じる
- **編集とシェルは全体の規則のまま。** 通常起動では作業役のシェルは確認が出る。
  無人の実行（`opencode run --auto`）では子セッションの確認に答えられず止まる
  （[commit エージェントの実機確認](../research/opencode/commit-review-agents.md)）。
  隔離起動（`ocs`）はシェルの既定が `allow` なので、個別の deny / ask に当たる操作以外は
  確認が出ない（[隔離版のエージェントとコマンド](sandbox/opencode-sandbox.md#エージェントとコマンド)）
- **作業役の `system` は、担当の範囲の外で起きることも確かめさせる**
  （[指示を足した前後の計測](../research/opencode/fleet-worker-instructions.md)）:
  - 既存の関数や振る舞いを変えたら、呼び出し元を grep で探して読み、壊れる所や
    直した誤りを前提にしている所が無いかを確かめて、報告の項目「呼び出し元への影響」に書く。
    担当外なので直さない。取りまとめ役はそれを受けて作業を切り直す（手順 5）
  - 確かめ用・比較用のファイルは作らない。要るときは作業ツリーの `.tmp/` の下に作って
    報告の前に消し、作業ツリーの外へは書かない。外への `write` は `edit` の確認になり、
    無人の実行では答える人がいないまま止まる
  - ファイルは read / glob / grep / edit / write ツールで読み書きし、確認方法のコマンドは
    渡された形のまま単独で、`workdir` を指定して実行する。`cat` / ヒアドキュメント / `cd`
    への誘導と、連結した読み取りの確認を減らすため。確認方法の `pytest` などは
    allow に無いので、実行するたびに確認が出る（任意コード実行になるので allow に載せていない）
- 1 つの波は 4 件までと指示している。子エージェントごとにモデルを呼ぶので、
  利用枠の消費は作業役の数だけ増える
- コマンドは、コマンド用のディレクトリではなく設定の `commands` に出す
  （スキルの置き場が走査されなかった実測は[記録 N11](../research/agents/agent-config-generation-notes-2.md#記録-n11--fleet-のコマンドの置き場)）
- `[opencode.commands.<name>]` に書けるキーは `template`（必須）/ `description` /
  `agent` / `subagent`。**`template` に「`!` + バッククォート」は書けない**
  （展開時にシェルとして権限の確認なしに実行されるため。`apply` を止める）

### 後勝ちの照合

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [pi のガード](guard/pi-guard.md)。

OpenCode は **最後に一致した規則が勝つ**。Claude の deny > ask > allow とは
逆なので、`generate.py` が `allow` → `ask` → `deny` の順に並べて同じ優先順位を
作る。並びが崩れると `git reset --hard` の deny を `git reset` の ask が
上書きしてしまうため、`test_effects_are_ordered_allow_then_ask_then_deny` で
固定している。

`common.toml` 側の書き方は Claude 向けと同じでよい (具体形を deny、一般形を
ask に置く)。
