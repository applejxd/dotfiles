# AI CLI 設定の生成と所有権

`common.toml` をどう書き、`generate.py` などがそれを各 CLI の設定ファイルへ
どう展開するか (どのキーを置き換え、どれを合算・保持するか) をまとめる。
全体像は [AI CLI 統合 permission / hook 管理](agent-permissions.md)、
判定の中身は [コマンド・ファイルの判定](agent-command-policy.md)、
sandbox は [sandbox (Claude Code / Copilot CLI)](agent-sandbox.md) を参照。

## ファイル構成

```text
home/dot_config/agents/
    common.toml.tmpl                         単一ソース (permissions + hooks + MCP)
                                             chezmoi テンプレート。ユーザ・OS の
                                             出し分けはここに書く
    command_policy.py                        hook が import する normalizer / matcher
                                             (deny / ask リストの loader も兼ねる)
scripts/agents/
    generate.py                              modify_ / .tmpl から呼ばれる変換器
    hooks.py                                 hook 登録の生成と外部 hook との所有権付きマージ
    validate_common.py                       描画結果の TOML / スキーマ検査
home/.chezmoiscripts/
    300_windows/run_onchange_after_346_claude_mcp.ps1.tmpl  未登録の MCP を claude へ登録
    400_unix/run_onchange_after_410_claude_mcp.sh.tmpl      同上 (Unix)
home/dot_claude/
    modify_settings.json.py.tmpl             ~/.claude/settings.json を更新
home/dot_claude/hooks/
    executable_check_bash.py                 入出力とループのみ (fail-closed)
    lib/policy_loader.py                     command_policy の import と設定ディレクトリの解決
    lib/bashrules/                           bash コマンド検査ルールの本体
        __init__.py                          DENY / ASK の登録簿 (評価順の正本)
        tables.toml                          検査に使うデータ (Python 不要で編集可)
        tables.py                            tables.toml の読み込み
        _shared.py                           共通ユーティリティ・ポリシー層の参照
        policy.py                            common.toml の deny / ask を照合
        sensitive.py  http.py  ghapi.py      関心事ごとの判定
        rm.py  docker.py                     同上
        rules_exec.py  rules_guard.py        同上
        rules_files.py                       同上
    executable_check_file_read.py            Copilot のファイル読み取りを遮断 (fail-closed)
    executable_redirect-tmp.py               /tmp 利用を ./.tmp へ誘導
    executable_markdownlint.sh               Markdown の lint
    executable_format-file.sh                拡張子別のフォーマッタ実行
home/dot_copilot/
    hooks/modify_from-claude.json.py.tmpl    ~/.copilot/hooks/from-claude.json を生成
    modify_private_settings.json.py.tmpl     ~/.copilot/settings.json を更新
    modify_private_permissions-config.json.py.tmpl
    modify_mcp-config.json.py.tmpl           ~/.copilot/mcp-config.json を更新
home/dot_codex/
    modify_config.toml                       ~/.codex/config.toml の管理ブロックを描画
home/dot_gemini/
    modify_settings.json.py.tmpl             ~/.gemini/settings.json を更新
home/dot_config/opencode/
    modify_opencode.json.py.tmpl             ~/.config/opencode/opencode.json を更新
    AGENTS.md.tmpl                           global 指示 (共有テンプレートを include)
test/agents/
    agents_common.py                         描画した common.toml をテストへ渡す
    test_command_policy.py                   shell normalize / match の unit test
    check_bash_hook.py                       check_bash の判定テストが共有する run_hook など
    test_check_bash_config.py                設定・生成物と hook の対応、指示ファイル、fail-closed
    test_check_bash_file_ops.py              rm・scratch・symlink・root / .git の保護
    test_check_bash_http_github.py           curl / wget / gh、ループバック、取得コードの実行
    test_check_bash_sensitive.py             秘密ファイル・秘密の環境変数・持ち出し
    test_check_bash_shell.py                 ask / deny の照合、ラッパー、shell 構文、間接実行
    test_check_file_read.py                  ファイル読み取り遮断と glob 照合の test
    test_claude_mcp_registration.py          Claude への MCP 登録スクリプト (Unix)
    test_generate_copilot_plugins.py         enabledPlugins 生成 / 重複解消の unit test
    test_generate_hooks.py                   hook 生成 / 外部 hook 温存の unit test
    test_generate_opencode.py                OpenCode の permission / MCP 生成の test
    test_generate_updates.py                 CLI 自動更新停止 / 既存 env 保持
    test_generate_sandbox.py                 sandbox 設定生成の unit test
    test_herdr_integration.py                Herdr統合の生成・保持
    test_mcp_servers.py                      MCP の単一ソース化と 3 CLI への生成
    test_modifier_wrappers.py                modify_ ラッパーの end-to-end test
    test_redirect_tmp.py                     一時パス誘導の判定
    test_skill_frontmatter.py                SKILL.md frontmatter検証
```

`common.toml` は **chezmoi テンプレート**なので、ユーザ・OS による出し分けを
`{{ if }}` で書ける。生成側 (`generate.py` を呼ぶ modify\_ など) は
`includeTemplate "dot_config/agents/common.toml.tmpl"` で描画結果を受け取る
(`include` は描画しない。`includeTemplate` は `.chezmoitemplates/` に無ければ
source directory を探すので、配備用のテンプレートをそのまま共有できる)。

**配置先のファイルは使えない**。modify\_ が動く時点では `~/.config/agents/common.toml`
がまだ更新されておらず、`chezmoi diff` や部分適用でも当てにできない。

素の TOML ではなくなるため `check-toml` は効かない (ファイル名が `.toml` で
終わらないので対象外)。代わりに pre-commit の `common-toml-local` が
`scripts/agents/validate_common.py` を呼び、出し分けの両側を描画して
TOML として読めること・必須の deny リストが空でないこと・`[[mcp]]` が
スキーマに合うことを確認する。chezmoi が無い環境では skip せず失敗する。

### コメントの書き分け

`common.toml.tmpl` には **その行を編集するときに要る注記** だけを置く。
仕組み・判断基準・既知の不具合は `docs/spec/agent-*.md`
([入口](agent-permissions.md#文書の構成)と分割先)、実測値と経過は
`docs/research/` が正本で、ファイル側からは
`see docs/spec/<文書>.md 「<見出し>」` で参照する。

| 置き場所 | 内容 | 例 |
| --- | --- | --- |
| `common.toml.tmpl` | その値を足す/消すときの制約 | 「`~/.cache` を read に書くと write が潰れる」 |
| `docs/spec/agent-*.md` | なぜその方式か、upstream の不具合 | 名前マッチの deny は展開数だけ bind-mount が要る |
| `docs/research/` | 実測値、何が壊れたかの経過 | bind-mount が 3239 件に展開された測定 |

経緯をファイル側に書くと、設定 386 行に対してコメントが 500 行を超えて
「値を探すのが難しいファイル」になる。実際そうなっていたので分離した。

Python runtime は 3.11 以上を前提とし、TOML は標準ライブラリ `tomllib` で読む。
Windows ではインストール済みの最新 Python 3 を選ぶ `py -3`、Unix では
`python3` を使用する。3.11 未満では `tomllib` import が失敗するため、
project の uv 環境や外部 `tomli` には依存しない。

`modify_private_*` のように `private_` を付けることで mode 600 を保持し、
`~/.copilot/settings.json` に含まれる `gho_xxx` トークンを保護している。

## common.toml の編集ルール

- 編集後は `chezmoi apply` で `~/.claude/settings.json` 等に反映される
- CLI UI で「Always allow」を押した場合は、その項目を common.toml に転記する
  (転記しないと次回 apply で消える。これは意図的な強制で、dotfiles を単一の
  真実とする方針)
- `[bash] deny` は hook が hard-block し、Claude では permission でも拒否される
- `[bash] ask` は hook が `ask` を返す。承認すればそのまま実行される
  (Copilot CLI では hook の `ask` が自動承認される既知バグがある。
  [`allow` の粒度に注意](agent-command-policy.md#allow-の粒度に注意))
- `[bash] allow` の先頭トークンだけが Copilot の承認済みコマンド名になる
  (Copilot は deny / ask を表現できないため、強制は hook が担う)
- `[file.write_ask_globs]` / `[file.write_deny_globs]` は Claude の
  **`Edit(path)`** rule として展開される。Claude Code v2.1.210 で
  `Write(path)` / `NotebookEdit(path)` / `Glob(path)` の permission rule は
  deprecated になり (起動時警告)、代替として `Edit(path)` / `Read(path)` が
  案内されている
  ([CHANGELOG v2.1.210](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md))。
  なお `Write` ツール自体は現役なので、hooks の `matcher` に書く `Write` は
  引き続き有効 (`MultiEdit` は v2.0 系で削除済みなので不要)

## CLI 本体の更新

Claude Code / Copilot CLI 本体は各社公式のインストーラーで導入します。
apply のたびに勝手な版へ動かないよう、CLI 自身の自動更新は停止します。

| `common.toml` | 生成先 |
| --- | --- |
| `[claude] auto_update = false` | `~/.claude/settings.json` の `env.DISABLE_AUTOUPDATER = "1"` |
| `[copilot] auto_update = false` | `~/.copilot/settings.json` の `autoUpdate = false` |
| `[opencode] auto_update = false` | `~/.config/opencode/opencode.json` の `update = "disable"` |

Claude の既存 `env` はこのキーだけを上書きし、それ以外の環境変数を保持します。
どちらも共通設定にキーがなければ既存値には触れません。
`DISABLE_AUTOUPDATER` はバックグラウンド更新のみを止めるため、更新したいときは
明示的に `claude update` などを実行します。
導入順と更新手順は [AI CLI の導入](structure.md#ai-cli-の導入)を参照。

## MCP サーバ

MCP サーバの定義も `common.toml` の `[[mcp]]` が単一ソース。同じサーバを
CLI ごとに書くと、URL を変えたときに片方だけ古いまま残る。

```toml
{{- if not (regexMatch "(?i)(^|\\\\)applejxd$" .chezmoi.username) }}
[[mcp]]
id = "ddgs"
purpose = "DuckDuckGo で web 検索する"
clis = ["claude"]
transport = "stdio"
command = "uvx"
args = ["--from", "ddgs[mcp]", "ddgs", "mcp"]
{{- end }}
```

| CLI | 生成先 | 生成する仕組み |
| --- | --- | --- |
| Copilot CLI | `~/.copilot/mcp-config.json` | `generate.py --target copilot-mcp` |
| OpenCode V2 | `~/.config/opencode/opencode.json` の `mcp.servers` | `generate.py --target opencode-config` |
| Codex CLI | `~/.codex/config.toml` の `mcp_servers` | `modify_config.toml` が `fromToml` で描画 |
| Claude Code | `~/.claude.json` | `400_unix/410` (Unix) と `300_windows/346` (Windows) が `claude mcp add-json` で登録 |

Gemini CLI と Antigravity は使わないため対象外。既存の定義はそのまま残す。

**applejxd では `[[mcp]]` が 0 件になる。** `deepwiki` は 2026-09-25 に外し、
`ddgs` は元から対象外のため。`[[mcp]]` が 1 つも無いと `mcp` キー自体が生えない
ので、参照側は `hasKey` で受けること（`missingkey=error` で描画が止まる）。

**入れる CLI を絞るには `clis` を書く。** 省略すると 4 つ全部に入る。`ddgs` は
`clis = ["claude"]` にしてあり、Claude Code にだけ入る（Copilot は内蔵の
web 検索があり、OpenCode / Codex では使わない）。書ける値は `claude` /
`copilot` / `opencode` / `codex` で、それ以外を書くと apply が止まる。

その結果、**Copilot / OpenCode / Codex 向けのサーバは現在 0 件**である。
Codex の重複宣言ガードは `[[mcp]]` が 1 つ以上ないと発火しないので、試験だけ
合成したソースで確かめている。

**宣言を消しても Copilot / OpenCode / Claude の生成先からは消えない。**
`merge_copilot_mcp` / `merge_opencode_mcp` は宣言されたサーバを足す・更新するだけで、
消えたサーバを刈らない (Claude も未登録のものを追加するだけ)。既に生成された
設定から取り除くには各 CLI の削除コマンドを使う。例外は Codex で、
`modify_config.toml` が管理ブロックごと描き直すので宣言から消せば消える。

**transport 名の違い**: OpenCode は `http` を `remote`、`stdio` を `local` と呼び、
`command` は実行ファイルと引数を **1 本の配列**で書く (Copilot は `command` と
`args` に分かれる)。`generate.py` が `[[mcp]]` から各形式へ変換する。

**Claude だけ生成ではない理由**: user scope の定義先である `~/.claude.json` は
MCP の `headers` / `env` に秘密が入りうるため chezmoi 管理外にしている
([ADR-0005](../adr/0005-agent-runtime-config-as-secret.md))。
そのためファイルを書かず、`[[mcp]]` のうち **未登録のものだけ** を CLI 経由で
追加する。既に同名のサーバがあれば触らないので、手元で差し替えた定義は残る。
`run_onchange_` なので `[[mcp]]` を増やすと次の `chezmoi apply` で登録される。
`add-json` を使うのは、http と stdio を同じ経路で登録できるため。

**適用範囲の非対称性**: この仕組みが揃えるのは「配布する既定値」であって、
全 CLI の状態の完全同期ではない。宣言から消したサーバは Copilot / OpenCode / Claude の
手元設定からは消えない (Codex は管理ブロックごと再生成するので消える)。
`chezmoi apply --exclude=scripts` や `chezmoi diff` では Claude の登録だけが
走らない点も同じ理由による。

**Codex の衝突**: 管理ブロックの外に同名の `[mcp_servers.<id>]` があると
TOML の重複宣言になり、Codex が設定ファイル全体を読めなくなる。黙って壊さない
よう、`modify_config.toml` が衝突を検出して `apply` を止める。

**ユーザ・OS による出し分け**: `common.toml` 側のテンプレートに書く。生成側
3 つは展開後の表だけを見るので、条件の解釈は 1 か所で済む。上の例では
`applejxd` に `ddgs` を入れない (Copilot CLI 内蔵の web 検索を使うため)。

**transport**: `http` は `url`、`stdio` は `command` / `args` を書く。
`stdio` のサーバは `uvx` から起動する形にしておくと、本体を別途入れずに済み、
`mise reshim` の要否やバックエンドの破損に左右されない。MCP サーバは sandbox
内で動く (Copilot は `sandboxMcpServers: true`) が、`uvx` が使う `~/.cache/uv`
と `~/.local/share/uv/tools` は書き込み許可済みで、`pypi.org` /
`files.pythonhosted.org` も許可済みなので追加設定は要らない。

**生成側が触らないもの**: Copilot の `headers` / `env` / `tools`、OpenCode の
`headers` / `environment` / `oauth`、および common.toml に無いサーバは既存値の
まま残す。前者は秘密、最後は公開範囲の設定で、どれも `common.toml` が持たない
情報だから。

未対応の transport・重複 id・不正な id・transport に無いキー (typo) は
`generate.py` が `apply` を止める。トークンは `common.toml` に書かず、
環境変数参照として各 CLI 側で設定する。

## OpenCode V2 の設定

通常起動の OpenCode V2 で permission と plugin をどう生成するか。
3 層との対応と Claude / Copilot との扱いの差は
[OpenCode V2 の扱い](agent-permissions.md#opencode-v2-の扱い) を参照。

### glob の記法差

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

| 渡さないもの | 理由 |
| --- | --- |
| `[web] allow_domains` / `deny_domains` | `webfetch` の resource は **URL 全体**で、`*` が `/` を跨ぐ。`*://*.example.com/*` は `https://evil.test/x.example.com/y` にも当たり、ドメイン許可を正しく書けない。過大な allowlist を出すより出さない方を選ぶ |
| `[file] claude_read_allow` | OpenCode は allow が既定 (`{action:"*", resource:"*", effect:"allow"}`)。同義の規則が増えるだけ |
| `[claude] mcp_deny` | Claude の `mcp__<server>__<tool>` と OpenCode の `<server>_<tool>` は別体系。機械変換すると実在しない名前を deny したまま気付けない |
| `[[hooks]]` | Claude の hook 契約とは別物。OpenCode 側は plugin で書く |
| `[sandbox]` | 通常起動に sandbox が無い (`claude_write_deny` の意図だけ `[file]` 側へ写している)。隔離起動 `ocs` は `[opencode.sandbox]` と `[sandbox] shell_network_allow` を使う ([OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md)) |

### 既定は `ask`

`permissions` の先頭に `{action:"shell", resource:"*", effect:"ask"}` を置き、
**未掲載のコマンドが無条件に通らないようにしてある**。shell の `allow` は
`[opencode.shell]` に書いた 5 件だけで、`[bash]` とは共用しない
（`[bash]` は 3 CLI 共通のため、触ると効果の切り分けができなくなる）。

allow の基準は副作用なし・冪等・**任意コード実行を含まない**こと。
`git diff` / `git status` は `.git/config` 経由で任意コマンドを起動できる
ため載せない。

**allow に載せたコマンドは任意ファイル書き込みの手段にもなる。** scanner が
リダイレクトを分割せず resource に残すので、`wc -l f.txt > path` が `wc *`
に前方一致する。allow は最小に保つ以外の守り方が無い。

### bypass から呼べる子エージェント

`bypass` のセッションから、同じく全部 allow の子エージェント `bypass-worker` を
サブエージェントとして起動できる。**ほかのエージェント（`build` など）からは起動できない。**

```toml
[opencode.agent.bypass-worker]
mode = "subagent"
permission = { "*" = "allow", task = "deny" }   # task は V2 の subagent
```

- `generate.py` は、全部 allow（`permission = "allow"` か `"*" = "allow"`）で
  サブエージェントとして使えるエージェントごとに、全体の `permissions` の**最後**へ
  `{ action: "subagent", resource: "<名前>", effect: "deny" }` を足す
  （`opencode_subagent_guards`）
- エージェントの規則は全体の規則の後ろに付き、最後に一致した規則が勝つ。
  `bypass` の `*` の allow だけがこの deny を上書きする
- `bypass-worker` 自身は `task = "deny"` なので、さらに子を起動できない
  （入れ子にならない）
- 「Always allow」で保存した承認は、設定の deny を上書きしない
- `bypass` と同じく、秘密ファイルの読み取り禁止も外れる。誘導の plugin も
  エージェント名で素通りさせる（下の plugin 層）

実測（build からは `Permission denied: subagent`、bypass からは起動できる、
子からの入れ子は不可）は
[Bypass モードの調査 6 章](../research/opencode/permission/bypass-agent.md#6-bypass-からだけ呼べる子エージェント2026-09-28)。

### plugin 層 (`guide-plugin`)

`~/.config/opencode/guide-plugin/` に置く。判定表は `common.toml` の
`[[opencode.shell.guide]]`・`[opencode.redact]`・`[opencode.ask_description]`・
`[file] read_deny_globs` から `rules.json` として生成し、plugin は読むだけにする。
`index.js` はこのどれかが有効なら、`tui.ts` は `ask_description` が有効な
ときだけ登録する（`generate.py` の `opencode_guide_server_needed` /
`opencode_guide_tui_needed`）。

| 役割 | 実体 | 登録先 |
| --- | --- | --- |
| 誘導（deny + 代替案）と説明の生成 | `index.js` | `opencode.json` の `plugins` |
| `grep` / `glob` の結果フィルタ | `index.js` | 同上 |
| shell 出力の伏字化 | `index.js` | 同上 |
| 確認画面への説明表示（toast） | `tui.ts` | **`cli.json` の `plugins`** |

隔離起動（`ocs`）は `cli.json` を渡さないので `tui.ts` は読まれない。
説明の生成だけでは隔離版の設定に `index.js` を載せない。

**登録先が分かれるのは仕様。** `opencode.json` に書いたディレクトリからは
TUI 側が読まれない。どちらも**絶対パスのディレクトリ**でないと解決されず、
`~` も単一ファイルも黙って無視される。

**`cli.json` は Orca セッションでは読まれない。** `OPENCODE_CONFIG_DIR` が
overlay を指すためで、パス指定の環境変数は存在しない。`shellenv.sh` が
`OPENCODE_CLI_CONFIG_CONTENT` へ本文を流し込んで補う。TUI plugin と
[キーバインド](#キーバインド)の両方がこれに依存する。

plugin が守る規約は 2 つ。

- **`bypass` エージェントには触らない。** 全部止めたいときの逃げ道を壊さない。
  判定は**エージェント名**で行う（`permission.evaluate` に `agent` が載ることを
  実測。[hook の呼ばれ方](../research/opencode/permission/hook-order.md)）。
  名前は permission が全部 allow（`"allow"` か `"*" = "allow"`）のエージェントから生成するので、
  `common.toml` が単一ソースのまま保たれる
- **`effect` では見分けない。** `allow` で判定すると
  `cd x && git log`（`git log` が静的 allow）のように、allow を含む呼び出しまで
  誘導が素通りする
- **リダイレクトを含むコマンドは `allow` へ引き上げない**

`bypass` は**誘導も結果フィルタも両方**素通りする。規則ごとに効かせ分ける
ことも技術的には可能だが採らない。誘導が誤爆したときの逃げ道を残すほうが
重要で、`bypass` は「秘密を読むために一時的に全部外す」用途も兼ねるため。

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
| 内容の形（`[[opencode.redact.rule]]`） | 出力本文 | 当たった範囲だけを `[伏字:名前]` に替える |
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

### 後勝ちの照合

OpenCode は **最後に一致した規則が勝つ**。Claude の deny > ask > allow とは
逆なので、`generate.py` が `allow` → `ask` → `deny` の順に並べて同じ優先順位を
作る。並びが崩れると `git reset --hard` の deny を `git reset` の ask が
上書きしてしまうため、`test_effects_are_ordered_allow_then_ask_then_deny` で
固定している。

`common.toml` 側の書き方は Claude 向けと同じでよい (具体形を deny、一般形を
ask に置く)。

## hooks の単一ソース化

`[[hooks]]` に 1 度書けば、Claude Code と Copilot CLI の設定ファイルへ展開される。

| 生成先 | 生成方法 | 使うフィールド |
| --- | --- | --- |
| `~/.claude/settings.json` の `hooks` | `modify_settings.json.py.tmpl` → `--target claude-settings` | `claude_event` / `claude_matcher` / `timeout_sec` |
| `~/.copilot/hooks/from-claude.json` | `home/dot_copilot/hooks/modify_from-claude.json.py.tmpl` → `--target copilot-hooks` | `copilot_event` / `copilot_matcher` / `timeout_sec` |

- hook スクリプトの実体は `~/.claude/hooks/` に 1 つだけ置き、Copilot からも
  同じファイルを呼ぶ
- Copilot の起動キーは Windows では `powershell`、Linux / macOS / WSL では
  `bash`。パスの表記と引用は起動キーごとに変える

  | 生成先フィールド | パス | 引用 |
  | --- | --- | --- |
  | Claude の `command` | 絶対パス | `"..."` |
  | Copilot の `bash` | `$HOME/...` | `"..."` |
  | Copilot の `powershell` | 絶対パス | `'...'` (`'` は `''` へ) |

  Windows で `$HOME` を使わないのは、PowerShell の `$HOME` が
  `HOMEDRIVE`+`HOMEPATH` 由来で chezmoi の `~` (`%USERPROFILE%`) と一致しない
  ことがあるため ([structure.md](structure.md))。生成は `chezmoi apply` 時に
  対象マシン上で走るので、絶対パスは必ずそのマシンのホームを指す。
  `powershell` を単一引用符にするのは、値が `-Command` へ渡された場合に
  二重引用符が外側の引用と衝突しうるため。
  Windows の Python hook は bytecode を生成せず日本語 JSON を壊さない
  `py -3 -B -X utf8` で起動する。
  反映・切り分け手順は [Windows の hook 起動](../../home/dot_copilot/README.md#windows-の-hook-起動)
  を参照
- `hooks` キーは Orca などの**外部ツールも追記する共有領域**なので、apply では
  このリポジトリの hook スクリプトを起動しているエントリだけを差し替える (後述)
- CLI UI で手動追加した hook も、このリポジトリのスクリプトを指していなければ
  残るが、再現性が無いので `common.toml` に転記すること
- `*_event` を空にすればその CLI には出力されない
- `*_matcher` を省略すると `matcher` キー自体が出力されない (= 全マッチ)。
  `Stop` / `UserPromptSubmit` など matcher 非対応イベントでは省略すること

### 外部ツールとの共存 (Orca / herdr)

Orca は `~/.claude/settings.json` と `~/.gemini/settings.json` の `hooks` へ
直接エントリを注入する。`permissions` が chezmoi の専有領域なのに対し、
`hooks` は**共有領域**である。generate.py が `hooks` を全置換していた頃は
`chezmoi apply` のたびに Orca の 12 エントリが消えていた
(`SessionStart` / `UserPromptSubmit` / `SubagentStart` などは**イベントキーごと**)。

現在の `merge_claude_hooks()` は次の規則で動く。

| 判定 | 扱い |
| --- | --- |
| コマンドが `~/.claude/hooks/<名前>` を起動し、`<名前>` が `[[hooks]].script` か `[retired_hooks].scripts` にある (ホームの表記と引用は問わない) | chezmoi の生成物。除去して `common.toml` から再生成 |
| それ以外 | 外部由来。そのまま温存 |

**ディレクトリではなくスクリプト名で所有権を決める。** `~/.claude/hooks/` は
共有ディレクトリで、herdr（`herdr integration install claude`）も
`herdr-agent-state.sh` をここに置き、`SessionStart` に登録する。
以前はディレクトリで判定していたので、apply のたびに herdr の hook を消し、
直後の `run_after_140_herdr_integration` が足し直していた。2 回 apply しても
`settings.json` が安定せず、その間は hook が無い状態になる
（[Docker の検証で発覚](../research/testing/docker-cold-start-fixes.md#6-2-回目の-apply-でも-claudesettingsjson-の差分が消えない2026-09-27)）。

`[retired_hooks].scripts` は撤去した hook の名前で、`settings.json` に残った
古い登録を消すためにある。一覧は git 履歴から作った
（`block-dangerous-commands.sh` / `update-adr-on-stop.py` / checkpoint の 3 本）。
**hook を撤去したらここへ足す。** 足し忘れると古い登録が外部の hook として残る。
名前の直後が引用符・空白・末尾でない場合（`check_bash.py.bak` など）は一致させない。

逆に言えば、このディレクトリにスクリプトを置いて `settings.json` へ手で
登録しても、`common.toml` に転記していなければ外部の hook として残り続ける。

herdr の hook を `common.toml` から生成する案は採らない。herdr の版や OS ごとに
スクリプト名・引数・起動形式が変わり、それを追従する責任まで負うことになるため。
herdr 自身が `run_after_140` / `343` で毎回導入し直す今の方式のほうが、
`mise upgrade herdr` 後の追従や登録の消失からの復旧も兼ねられる。

- 絞り込みは**エントリ単位ではなくコマンド単位**。1 エントリの `hooks` リストに
  管理対象と外部由来が混在していても、外部由来だけが残る
- 削除するのは「全コマンドが自分の生成物だと確認できたエントリ」だけ。
  解釈できない形（リストでない、`hooks` リストを持たない等）は将来のスキーマ
  変更や未知のツールの書き込みでありうるので**そのまま残す**。
  ただし chezmoi も生成するイベント（`PreToolUse` など）で値がリスト以外だった
  場合は結合できないため生成物を優先する（Claude のスキーマ上リスト以外は
  元々無効。完全に温存されるのは管理外イベントのみ）
- 出力順は「管理エントリ → 外部エントリ」で、既存ファイルの並びと一致するため
  差分が出ない。2 回適用しても結果は変わらない (冪等)

他の CLI は元から衝突しない。

| 設定ファイル | Orca の書き込み方 | chezmoi の管理方式 |
| --- | --- | --- |
| `~/.claude/settings.json` | `hooks` へ注入 | 管理エントリのみ差し替え |
| `~/.gemini/settings.json` | `hooks` へ注入 | `GEMINI_MANAGED` の枝だけ上書き |
| `~/.copilot/hooks/orca.json` | 専用ファイルを新規作成 | `from-claude.json` のみ生成 |
| `~/.codex/config.toml` | 書き込み無し | `chezmoi-managed:start/end`（トップレベルのキー）と `chezmoi-managed:tables:start/end`（テーブル）のマーカー間のみ |

Orca 本体が作るファイル (`~/.orca/`, `~/.orca-wsl/`, `~/.orca-relay/`,
`~/.local/share/orca/`, `~/.local/bin/orca-ide`, `~/orca/`) と、`npx skills` が
管理する skill ストア (`~/.agents/`) は chezmoi では追跡しない。
マシン固有のパスやバージョンを埋め込んでおり、Orca 自身が更新機構を持つため。
`home/.chezmoiignore.tmpl` に列挙してあるので `chezmoi add` も拒否される。

### matcher の書き分け (共通化してはいけない)

| CLI | 意味論 | 書き方 |
| --- | --- | --- |
| Claude Code | tool 名の完全一致を `\|` で OR 連結 | `Edit\|Write` |
| Copilot CLI | `^(?:pattern)$` として anchored される | `^(Edit\|Write\|edit\|create)$` |

Copilot は PascalCase イベント名で書くと Claude の tool 名 (`Edit` / `Write` …)
で照合するため、両方の名前を列挙する。

### Claude Code のイベント名・timeout の注意 (2026-08 時点の公式 docs 準拠)

- `TaskCompleted` は実在するが、`TaskCreate` ツール経由のタスク完了時にのみ発火する。
  「ターン終了時」に 1 回だけ動かしたい hook は `Stop` を使う
  (`Stop` = "When Claude finishes responding"、cadence は "once per turn")
- `SubagentStop` は `Stop` とは独立。サブエージェント終了も拾いたいなら両方に登録する
- `timeout` キーの単位は秒。`command` 型 hook のデフォルトは **600 秒**と長いため、
  `timeout_sec` を明示している (Copilot 側のキー名は `timeoutSec`)

## Copilot CLI の制約 (実機確認済)

- `~/.copilot/permissions-config.json` は **対話モードでのみロード** される。
  `copilot -p` (非対話モード) では一切無視される。
- `tool_approvals` の `kind: "commands"` の `commandIdentifiers` は
  **command 名の完全一致** のみで、`shell(git:*)` のような glob パターンの
  永続化サポートは未確証。よって本仕組みでは `[bash.allow]` の first token を
  ユニーク化して `commandIdentifiers` に集約する粗粒度方式を採用している。
- `kind: "write"` は MCP write tool 用で、shell tool (`touch`/`rm` 等) には
  効かない。
- `~/.copilot/settings.json` の `copilotTokens` / `loggedInUsers` /
  `installedPlugins` 等は Copilot 自動管理なので、generate.py はキー名
  ホワイトリスト方式で温存する。

### プラグイン (skill) の重複に注意

`anthropic-agent-skills` マーケットプレイスの **`document-skills` と
`example-skills` は中身が完全に同一** (実測: `skills/` 配下の差分は実行時
生成物の `__pycache__` のみで、`pptx` / `docx` / `pdf` / `xlsx` など 17 スキルが
一致)。両方有効にすると全スキルが二重に登録される。

`common.toml` の `[copilot.enabled_plugins]` でどちらを残すかを宣言し、
`merge_copilot_settings` が `settings.json` の `enabledPlugins` へ反映する。
**書いたキーだけを上書き**し、ここに無いプラグインはユーザーの設定を残す
(マーケットプレイスから別途入れたものを消さないため)。

なお個別スキル単位の無効化はできず、プラグインごとの on/off しかない。
`pptx` だけを外すことはできないので、`document-skills` を落とすと
`docx` / `pdf` / `xlsx` なども一緒に消える点に注意。

自前の `powerpoint-studio` スキル (`home/dot_claude/skills/`) は
プラグインの `pptx` と**競合しない**。前者は新規作成・大幅改稿の専用で、
description に「単なる .pptx のテキスト抽出や軽微な一語置換には使わない」と
明示してあり、抽出・軽微修正は後者が担当する。
