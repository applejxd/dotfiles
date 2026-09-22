# AI CLI 統合 permission / hook 管理

Claude Code / Copilot CLI の permission (allow/deny/ask) と hook 登録を
**単一ソース** で管理し、`chezmoi apply` で両 CLI の設定ファイルへ自動展開する仕組み。
OpenCode V2 は hook を持たないので、同じソースから permission と MCP だけを生成する。
Gemini CLI は `GEMINI_MANAGED` で定義した一部設定だけを生成する。
`hooks` はOrcaなどの外部ツールが管理するため保持し、`common.toml` からは生成しない。

設計判断の根拠は次のADRを正本とする。

- [ADR-0001: 外部ツール設定との共存](../adr/0001-external-tool-config-coexistence.md)
- [ADR-0002: ループバックHTTPの承認範囲](../adr/0002-loopback-http-approval-scope.md)
- [ADR-0003: agent設定生成にPython 3.11以上を要求](../adr/0003-require-python-311-for-agent-configuration.md)
- [ADR-0004: hook判定軸](../adr/0004-hook-check-semantic-axis.md)
- [ADR-0005: エージェント設定を秘密として扱う](../adr/0005-agent-runtime-config-as-secret.md)
- [ADR-0006: 指示を減らし強制は機構へ寄せる](../adr/0006-instructions-to-mechanisms.md)
- [ADR-0007: filesystem ガードの機構境界](../adr/0007-filesystem-guard-boundary.md)

sandbox が **何を提供しているか** (採用していない機能も含む) の網羅は
[sandbox機能の包括調査](../research/agents/sandbox-capabilities.md) を参照。

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
    validate_common.py                       描画結果の TOML / スキーマ検査
home/.chezmoiscripts/
    300_windows/run_onchange_after_346_claude_mcp.ps1.tmpl  未登録の MCP を claude へ登録
    400_unix/run_onchange_after_410_claude_mcp.sh.tmpl      同上 (Unix)
home/dot_claude/
    modify_settings.json.py.tmpl             ~/.claude/settings.json を更新
home/dot_claude/hooks/
    executable_check_bash.py                 入出力とループのみ (fail-closed)
    lib/bashrules/                           bash コマンド検査ルールの本体
        __init__.py                          DENY / ASK の登録簿 (★評価順の正本)
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
    test_check_bash_decision.py              deny/ask 判定と rm root guard の test
    test_check_file_read.py                  ファイル読み取り遮断と glob 照合の test
    test_generate_copilot_plugins.py         enabledPlugins 生成 / 重複解消の unit test
    test_generate_hooks.py                   hook 生成 / 外部 hook 温存の unit test
    test_generate_opencode.py                OpenCode の permission / MCP 生成の test
    test_generate_updates.py                 CLI 自動更新停止 / 既存 env 保持
    test_generate_sandbox.py                 sandbox 設定生成の unit test
    test_herdr_integration.py                Herdr統合の生成・保持
    test_mcp_servers.py                      MCP の単一ソース化と 3 CLI への生成
    test_mise_agents.py                      Claude への MCP 登録スクリプト
    test_modifier_wrappers.py                modify_ ラッパーの end-to-end test
    test_redirect_tmp.py                     一時パス誘導の判定
    test_skill_frontmatter.py                SKILL.md frontmatter検証
```

`common.toml` は **chezmoi テンプレート**なので、ユーザ・OS による出し分けを
`{{ if }}` で書ける。生成側 (`generate.py` を呼ぶ modify\_ など) は
`includeTemplate "dot_config/agents/common.toml.tmpl"` で描画結果を受け取る
(`include` は描画しない。`includeTemplate` は `.chezmoitemplates/` に無ければ
source directory を探すので、配備用のテンプレートをそのまま共有できる)。

**配備済みファイルは使えない**。modify\_ が動く時点では `~/.config/agents/common.toml`
がまだ更新されておらず、`chezmoi diff` や部分適用でも当てにできない。

素の TOML ではなくなるため `check-toml` は効かない (ファイル名が `.toml` で
終わらないので対象外)。代わりに pre-commit の `common-toml-local` が
`scripts/agents/validate_common.py` を呼び、出し分けの両側を描画して
TOML として読めること・必須の deny リストが空でないこと・`[[mcp]]` が
スキーマに合うことを確認する。chezmoi が無い環境では skip せず失敗する。

### コメントの書き分け

`common.toml.tmpl` には **その行を編集するときに要る注記** だけを置く。
仕組み・判断基準・既知の不具合・実測値はこの文書が正本で、ファイル側からは
`see docs/spec/agent-permissions.md 「<見出し>」` で参照する。

| 置き場所 | 内容 | 例 |
| --- | --- | --- |
| `common.toml.tmpl` | その値を足す/消すときの制約 | 「`~/.cache` を read に書くと write が潰れる」 |
| この文書 | なぜその方式か、実測値、upstream の不具合 | bind-mount が 3239 件に展開される測定 |

経緯をファイル側に書くと、設定 386 行に対してコメントが 500 行を超えて
「値を探すのが難しいファイル」になる。実際そうなっていたので分離した。

Python runtime は 3.11 以上を前提とし、TOML は標準ライブラリ `tomllib` で読む。
Windows ではインストール済みの最新 Python 3 を選ぶ `py -3`、Unix では
`python3` を使用する。3.11 未満では `tomllib` import が失敗するため、
project の uv 環境や外部 `tomli` には依存しない。

`modify_private_*` のように `private_` を付けることで mode 600 を保持し、
`~/.copilot/settings.json` に含まれる `gho_xxx` トークンを保護している。

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
[[mcp]]
id = "deepwiki"
purpose = "GitHub リポジトリのドキュメントを検索する"
transport = "http"
url = "https://mcp.deepwiki.com/mcp"

{{- if not (regexMatch "(?i)(^|\\\\)applejxd$" .chezmoi.username) }}
[[mcp]]
id = "ddgs"
purpose = "DuckDuckGo で web 検索する"
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
全 CLI の状態の完全同期ではない。宣言から消したサーバは Copilot / Claude の
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

## 3 層構成

| 層 | 仕組み | 効く CLI |
| --- | --- | --- |
| 0. sandbox | Claude: `~/.claude/settings.json` の `sandbox.filesystem.denyRead/denyWrite`、Copilot: `~/.copilot/settings.json` の `sandbox.userPolicy.filesystem.deniedPaths` (どちらも generate.py が生成)。OS レベル (bwrap/Seatbelt) で強制されるパス単位の deny | **Claude + Copilot** |
| 1. permission リスト | `~/.claude/settings.json` の `permissions` (generate.py が生成) | **Claude のみ** |
| 2. hook | `check_bash.py` が同じリストを読んで deny / ask を返す | **Claude + Copilot** |

人が書くのは `common.toml` の `[bash] allow / ask / deny` と `[sandbox]` の
パス列だけ。そこから permission リストと sandbox 設定が生成され、hook も
同じ `[bash]` リストを読む。ルールを複数箇所に書く必要はない。

**なぜ複数層に配るのか**: hook は設定の読み込みに失敗しうる
(`~/.config/agents/__pycache__` 由来の import 失敗など、トラブルシュートに実例あり)。
permission リストは CLI 本体が評価するので、hook が落ちても Claude 側の deny は残る。
hook 自体も設定を読めないときは **fail-closed** で deny する。
sandbox はさらにその外側で OS が強制するため、hook や permission リストの
実装バグ・迂回パターンに関係なく該当パスへのアクセスを止められる
(ただし sandbox が対応できるのは「パスへのアクセス可否」のみで、コマンドの
意味を解釈する判定 (`check_secret_env_echo` 等) は代替できない)。

Copilot CLI の `permissions-config.json` は deny / ask を表現できない
(公式仕様) ため、Copilot 側の「コマンドの可否」の強制は hook が全面的に担う。
一方 sandbox は Copilot にもあり、`common.toml` の `[sandbox] deny` から
`merge_copilot_settings` が `sandbox.userPolicy.filesystem.deniedPaths` を
生成する (deny リストは両 CLI で共通。ただし Copilot はワイルドカードを
扱えないため、生成時に `*` を含む要素だけ落とす)。

### OpenCode V2 の扱い

OpenCode V2 に sandbox は無い。強制に使えるのは permission リストと
plugin の 2 つで、`common.toml` の意図はその範囲で表現する。
生成は `generate.py --target opencode-config`。

| 層 | OpenCode での状態 |
| --- | --- |
| 0. sandbox | **無い**。OS レベルの強制は効かない（[検討して不採用](../change/0002-opencode-ask-by-default.md)） |
| 1. permission リスト | `opencode.json` の `permissions`。**既定は `ask`** |
| 2. hook | plugin の `permission.evaluate` / `tool.execute.*`（`guide-plugin`） |

**permission と plugin は安全網であって境界ではない。** 実行前の文字列検査は
クォートと変数で、実行後の出力検査は `base64` ですり抜ける（実測）。

PostToolUse 系の hook (`format-file.sh` / `markdownlint.sh`) だけは、CLI 本体の
`formatter` 機能で等価な結果になる ([整形 (formatter)](#整形-formatter))。

この差から、Claude / Copilot 向けとは 3 点だけ扱いを変えている。

**`ask_hook_owned` を除外しない**: Claude では `rm` のような「hook が承認要否
まで判定する」コマンドを静的 `ask` から外す (静的 ask を出すと hook の
exemption がどのモードでも無効化されるため)。OpenCode には委譲先が無いので、
外すと素通りになる。そのため素の `ask` として出す。`rm` は毎回確認になる。

**deny の最終防衛線が permission リストしかない**: Claude では hook と sandbox
が同じ deny を別経路で強制するが、OpenCode では `permissions` が落ちれば
防御ごと消える。`opencode.json` 自身を `[file] claude_write_deny_globs` と
`[sandbox] claude_write_deny` に入れて、エージェントが自分の deny を
書き換えられないようにしてある。

**`~/.config/opencode/service.json` は秘密扱い**: background service の
認証 password が平文で入る。`[sandbox] deny` と読み取り deny の両方に入れる。

#### glob の記法差

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

`test_generate_opencode.py` が変換表と「生成物に `**` が残らないこと」を固定する。

#### 整形 (formatter)

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

#### OpenCode へ渡さないもの

| 渡さないもの | 理由 |
| --- | --- |
| `[web] allow_domains` / `deny_domains` | `webfetch` の resource は **URL 全体**で、`*` が `/` を跨ぐ。`*://*.example.com/*` は `https://evil.test/x.example.com/y` にも当たり、ドメイン許可を正しく書けない。過大な allowlist を出すより出さない方を選ぶ |
| `[file] claude_read_allow` | OpenCode は allow が既定 (`{action:"*", resource:"*", effect:"allow"}`)。同義の規則が増えるだけ |
| `[claude] mcp_deny` | Claude の `mcp__<server>__<tool>` と OpenCode の `<server>_<tool>` は別体系。機械変換すると実在しない名前を deny したまま気付けない |
| `[[hooks]]` | Claude の hook 契約とは別物。OpenCode 側は plugin で書く |
| `[sandbox]` | sandbox が無い (`claude_write_deny` の意図だけ `[file]` 側へ写している) |

#### 既定は `ask`

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

#### plugin 層 (`guide-plugin`)

`~/.config/opencode/guide-plugin/` に置く。判定表は `common.toml` の
`[[opencode.shell.guide]]` と `[opencode.ask_description]` から
`rules.json` として生成し、plugin は読むだけにする。

| 役割 | 実体 | 登録先 |
| --- | --- | --- |
| 誘導（deny + 代替案）と説明の生成 | `index.js` | `opencode.json` の `plugins` |
| 確認画面への説明表示（toast） | `tui.ts` | **`cli.json` の `plugins`** |

**登録先が分かれるのは仕様。** `opencode.json` に書いたディレクトリからは
TUI 側が読まれない。どちらも**絶対パスのディレクトリ**でないと解決されず、
`~` も単一ファイルも黙って無視される。

plugin が守る規約は 2 つ。

- **すでに `allow` のものには触らない。** `bypass` エージェントを壊さない
  （bypass は全 action が `allow` になるので、これが識別の代わりになる）
- **リダイレクトを含むコマンドは `allow` へ引き上げない**

**サーバ側 plugin を更新したら `opencode service restart` が要る。**
常駐サービスのプロセス内で動くため、`chezmoi apply` だけでは反映されない。
TUI 側は CLI プロセスなので再起動は不要。

#### 確認画面に出るコマンドの説明

60 文字以上のコマンドで確認が出るとき、安価なモデルが 1 行の日本語説明を
作り、toast で表示する。破壊的操作・外部送信・秘密への接触があれば
先頭に `⚠` が付く。

```toml
[opencode.ask_description]
models = ["amazon-bedrock/us.anthropic...", "github-copilot/claude-haiku-4.5", ...]
```

`models` は上から試し、使えたものを採用する。**Bedrock 未設定なら自動的に
Copilot へ落ちる**（catalog に無いものは通信せず飛ばす）。

**説明は判断の補助であって判定器ではない。** コマンド文字列は信頼できない
入力で、偽装は原理的に防げない。確認画面は常に生コマンドを表示するので、
そちらが一次情報。

モデル呼び出しが失敗・タイムアウトしても**確認は通常どおり出る**
（説明が付かないだけ）。

#### 後勝ちの照合

OpenCode は **最後に一致した規則が勝つ**。Claude の deny > ask > allow とは
逆なので、`generate.py` が `allow` → `ask` → `deny` の順に並べて同じ優先順位を
作る。並びが崩れると `git reset --hard` の deny を `git reset` の ask が
上書きしてしまうため、`test_effects_are_ordered_allow_then_ask_then_deny` で
固定している。

`common.toml` 側の書き方は Claude 向けと同じでよい (具体形を deny、一般形を
ask に置く)。

### Codex CLI / Gemini CLI の扱い

この 3 層は Claude Code / Copilot CLI 用で、`check_bash.py` も両 CLI しか
起動しない。Codex CLI と Gemini CLI は独自の宣言的な仕組みを持つので、
`common.toml` からは生成せず、同じ意図を手書きで並べている。

| CLI | 仕組み | ソース |
| --- | --- | --- |
| Codex CLI | `prefix_rule()` (Starlark) | `home/dot_codex/rules/*.rules` |
| Gemini CLI | policy rule (TOML) | `home/dot_gemini/policies/*.toml` |

そのため「必ず止めたい操作」を足すときは、`common.toml` だけでなく
この 2 箇所も更新する。経緯は
[ADR-0006](../adr/0006-instructions-to-mechanisms.md) を参照。

### sandbox 層 (`[sandbox]`)

> [!NOTE]
> `[sandbox]` が扱うのは**パスのポリシー**だけで、sandbox が起動できること自体は
> ホスト側の前提条件になる。Linux の bubblewrap backend は `bwrap` /
> `slirp4netns` / `unshare` / `nsenter` / `iptables` などを probe し、1 つでも
> 欠けると**起動を拒否して全ツールが失敗する**。症状と一覧は
> [トラブルシューティング](troubleshooting.md) の
> 「9. Linux で sandbox がコマンドを 1 つも実行できない」を参照。

#### なぜ既定が逆なのに揃えるのか

**既定は実際に逆向き**である。Claude は「read はほぼ全許可 + deny を引く」
ブラックリスト、Copilot は deny-by-default のホワイトリスト。
それでも揃えているのは次の理由による。

1. **Claude の既定が緩すぎる。** 公式が
   「この既定では `~/.aws/credentials` や `~/.ssh/` も読める」と明記している。
   何もしなければ Copilot より明確に緩くなり、
   「Copilot が家用で緩め、Claude が会社用で厳し目」という運用方針が逆転する
2. **ブラックリストは fail-open。** 列挙し忘れた秘密は黙って読める。
   ホワイトリストは fail-closed で、新しいツールが動かなくなる形で
   気付ける。**壊れ方が見える側**を選んでいる
3. **公式に支持された構成。** `denyRead: ["~/"]` + `allowRead` は
   Anthropic のドキュメントが例示している形で、回避策ではない

コストは `claude_read_allow` のパスを手で維持していること。
Copilot 側も `copilot_read_allow` で同じものを列挙する。以前は
`allowDevToolAccess` が自動で行っていたが、不具合のため切っている
([ADR-0008](../adr/0008-explicit-dev-tool-grants.md))。

> [!NOTE]
> 揃えているのは **filesystem だけ**。network は Copilot にドメイン単位の
> 制御が無く、`allowedUrls` も「プロンプトを省略する URL」であって制限では
> ないため、**実効ポリシーを揃えられない**。
> 層ごとの方式の違いは
> [sandbox機能の包括調査](../research/agents/sandbox-capabilities.md) を参照。

#### キー名の規則

`common.toml` のキーは **共有 = 無印 / CLI 固有 = CLI 名の接頭辞** で統一する
(`[[hooks]]` の `claude_event` / `copilot_event` と同じ規則)。

| キー | 効く CLI | 用途 |
| --- | --- | --- |
| `[sandbox] deny` | 両方 | whitelist の内側でも遮断する秘密情報 (read/write 両方) |
| `[sandbox] seccomp_apply_path` | 両方 | seccomp の適用バイナリ |
| `[sandbox] claude_read_allow` | Claude | whitelist に開ける読み取りの穴 |
| `[sandbox] claude_write_allow` | Claude | cwd + temp 以外に書き込みを許す場所 |
| `[sandbox] claude_write_deny` | Claude | read は許すが write を禁止する対象。`deny` に**追加**される |
| `[sandbox] claude_network_allow` | Claude | shell が実際に通信する先 (CDN 等) |
| `[sandbox] claude_network_strict` | Claude | 許可外ドメインを拒否する (v2.1.219+) |
| `[sandbox] copilot_read_allow` | Copilot | Copilot が読める場所 (whitelist の本体) |
| `[sandbox] copilot_write_allow` | Copilot | 同上の書き込み |
| `[sandbox] copilot_allow_dev_tool_access` | Copilot | 開発ツールの自動許可。`false` 固定 |
| `[file] claude_*` (5 キー) | Claude | `Read()` / `Edit()` の allow / ask / deny |
| `[bash] allow` / `ask` / `deny` | 両方 | ただし粒度が違う |

無印は「両 CLI に効く」を意味する。**片方にしか渡らない設定を無印で足しては
いけない。** 実際、`copilot_*` が生まれる前の `read_allow` / `write_allow` は
名前の上ではただの許可に見えて Claude にしか効いておらず、Copilot 側で
`uv run` が動かない原因になっていた。

キーを読み違えても `.get(key, [])` は静かに空リストを返すため、綴り間違いや
旧名の残りは **防御が黙って消える** 形で現れる。`generate.py` の
`validate_sandbox_keys()` が `[sandbox]` と `[file]` の未知キーを検出して
apply を止める。

#### 許可を足したくなったときの判断手順

「動かないので許可を足したい」は頻出する。**足す前に必ずこの順で判断する。**

##### Step 1. 本当に遮断されているのか確認する

`ENOENT` は「未許可」と「本当に無い」の区別がつかない。実効ポリシーで見る
(Copilot は `/sandbox policy`、Claude は `/sandbox` の Config タブ)。
`ls` が成功して 0 件なら **deny された空の tmpfs**。`Path.exists()` は
denied path でも真を返すので判定に使わない。

##### Step 2. 許可ではなく別の層で解けないか考える

| 症状 | 許可を足す前に |
| --- | --- |
| `/tmp` に書けない | `./.tmp` を使う (`redirect-tmp.py` が誘導している) |
| ホーム配下の秘密を読みたい | **足さない。** 値を伏せて渡す |
| 1 回だけ必要 | `claude --settings` / `--add-dir` |
| このプロジェクトだけ | 対話プロンプトで承認 (下記「このマシンだけで許可を足す」) |

##### Step 3. どちらの CLI で不足しているのかを切り分ける

ここが最重要。**両方で不足しているとは限らない。**

| 不足している側 | 典型的な原因 | 書く場所 |
| --- | --- | --- |
| Copilot だけ | ホーム外、または `copilot_read_allow` に未列挙 | `copilot_read_allow` / `copilot_write_allow` |
| Claude だけ | ホーム配下で `denyRead: ["~/"]` に掛かった | `claude_read_allow` / `claude_write_allow` |
| 両方 | 真に共通の要件 | それでも**両方のキーに書く**。無印キーは作らない |

判別のコツ: **ホームの外 (`/usr`, `/opt`, `/etc`) は Claude では既定で読める。**
Claude の `denyRead` は `~/` 配下しか塞いでいないため。
逆に Copilot は全体が whitelist なので、ホームの外も明示が要る。

実例 (`/usr/include`): Copilot は不可視、Claude は既定で読める
→ `copilot_read_allow` にだけ追加した。

##### Step 4. 粒度と権限を絞る

- **read で足りるなら read に留める。** 特に実行ファイルとヘッダは
  write を与えると、以後のビルド成果物へ任意コードを混ぜられる
- ディレクトリ全体ではなく、必要な部分木を指す
- Copilot は**ワイルドカード非対応・絶対パス限定**

##### Step 5. スコープを選ぶ

| 範囲 | 置き場 |
| --- | --- |
| 全マシンで必要 (ツールチェーン・システム領域) | `common.toml` |
| このマシンだけ (データセット置き場など) | `~/.config/agents/local.toml` |
| このプロジェクトだけ | 対話承認 / `[[copilot.locations]]` / `.claude/settings.local.json` |

##### Step 6. 根拠を書き、テストで固定する

`common.toml` のコメントに **実測値**と**何が壊れたか**を残す。
`test/agents/test_generate_sandbox.py` に、そのパスが期待どおりの権限で
生成されることと、**write を与えていない**ことを固定する。

> [!IMPORTANT]
> **禁止 (deny) をこの手順で足さないこと。** CLI 固有キーは許可の補償専用で、
> 禁止を置くと片方だけ無防備になる。遮断は `[sandbox] deny` (両 CLI) か
> hook で行う。境界は [ADR-0007](../adr/0007-filesystem-guard-boundary.md)。

#### Copilot が読み書きできる場所 (`copilot_read_allow` / `copilot_write_allow`)

Copilot の filesystem は deny-by-default なので、このリストが
**Copilot に見える範囲そのもの**になる。以前は `allowDevToolAccess` が
`PATH` 上のツールやキャッシュを自動で許可していたが、
**この自動付与は切ってある** ([ADR-0008](../adr/0008-explicit-dev-tool-grants.md))。

切った理由は 2 つ。

1. **取りこぼす。** 公式ドキュメントはキャッシュの扱いを
   "read-only for most locations, and read/write for selected writable locations"
   と書いており、**uv はこの選別から漏れていた**
2. **ユーザ指定を上書きする。** `readwritePaths` に書いたパスを自動付与の
   read-only が潰す (`github/copilot-cli#4846`)。しかも `/sandbox policy` は
   Read-write と表示するので、**表示からは気付けない**

実測 (Copilot CLI 1.0.84-5、dev-tool access が ON だった頃):

| パス | 実効権限 | 結果 |
| --- | --- | --- |
| `~/.cache/uv` | read-only (RW 指定しても) | `uv run` が lock を作れず EROFS |
| `~/.local/share/uv/python` | 不可視 | `.venv/bin/python` の実体を辿れない |
| `/usr/include` | 不可視 | C/C++/cgo のビルドが `fatal error: stdlib.h` で落ちる |
| `/usr/local` 配下 | 不可視 | ローカル導入のヘッダ・ライブラリ・CUDA を参照できない |

自動付与の粒度は直感と一致しなかった。実測 (Ubuntu) では
**ライブラリは見えるのにヘッダが見えない**。

```text
見える  : /usr/lib (136) /usr/lib/x86_64-linux-gnu (2864) /usr/bin (3083)
          /usr/share (336) /usr/libexec (135) /etc (277) 各種 pkgconfig
見えない: /usr/include /usr/local/* /usr/src /opt /sys /var/lib
```

現在のリストは `claude_read_allow` とほぼ同じ内容に、ホーム外を足した形になる。

```toml
copilot_read_allow = [
  "~/.local", "~/.cargo", "~/.rustup", "~/.nvm",
  "~/go", "~/.texlive",           # ツールチェーン
  "~/.config", "~/.gitconfig",    # ツールの設定 (秘密は deny で個別に塞ぐ)
  "/usr/include",                 # システムヘッダ
  "/usr/local",                   # include / lib / share / cuda をまとめて
  "/usr/src",                     # カーネルヘッダ (DKMS, CUDA ドライバ)
  "/opt",                         # サードパーティのツールチェーン
]
copilot_write_allow = [
  "~/.cache", "~/.npm", "~/.cargo/registry", "~/.local/state",
  "~/.local/share/uv/tools",      # uvx の一時環境
  "~/.config/chezmoi",            # chezmoi の永続 state (boltdb)
]
```

書き込みは**キャッシュ類だけ**。それ以外は read-only にする。書ければ
以後のビルド成果物へ任意コードを混ぜられる。
**存在しないパスを書いても害は無い** (Copilot は実在しないパスをポリシーから
落とし `/sandbox policy` の Notes に記載するだけ)。
Claude は `denyRead` が `~/` 配下だけなので `/usr` や `/opt` は元から読める。

> [!CAUTION]
> **同じパスを read と write の両方に書いてはいけない。**
> sandbox 実装は同一パスの RO/RW 競合を「最も制限的な意図」= RO へ解決する
> ため、**write 指定が無言で消える**。これが上記 2 の不具合の本体で、
> ユーザ指定どうしでも同じことが起きる。
> write 権限は read を含むので、書きたい場所は `copilot_write_allow` にだけ
> 書く (`~/.cache` `~/.npm` がこれに当たる)。
> `build_copilot_sandbox` が重複を検出して apply を止める。
>
> 親子関係 (`~/.local` と `~/.local/state`) は
> 「より具体的なパスが勝つ」規則で解決されるので問題ない。

書き込みを許す場所の選び方にも注意が要る。

> [!WARNING]
> **`~/.local/share/mise` を `copilot_write_allow` に入れてはいけない。**
> PATH 上の全ツールが書き換え可能になり、`git` や `python` を差し替えて
> 以後のコマンドを乗っ取る経路ができる。sandbox が防ごうとしている当のもの。
> read だけで `mise exec` は動く。
>
> 対して `~/.local/share/uv/tools` は write に入れてある。**PATH に載らず**
> `uvx <tool>` からしか使われないので質が違う。しかも `~/.cache/uv` が
> rw な時点で uvx 経由のコードは同じ経路で汚染できるため、リスクは増えない。
> RO のままだと `uvx` が一時環境を作れず、pre-commit の ruff / yamllint が
> `Read-only file system (os error 30) at ".../uv/tools/.tmpXXXX"` で落ちる。

判断の基準は **「PATH に載るか」**。載るものは read だけにする。

許可した領域の内側に秘密があるときは、`deny` に個別のパスを書けば
「より具体的なパスが勝つ」規則で遮断される。
`~/.config/chezmoi` は state (boltdb) のために write を与えているが、
同じディレクトリの age 秘密鍵は `deny` で塞いである。

#### `/sandbox policy` の表示は実効性を保証しない

上記 2 の不具合で分かったことだが、**`/sandbox policy` が Read-write と
表示していても、実際には read-only で bind されていることがある**。
sandbox 実装は同一パスに RO と RW が来たとき「最も制限的な意図」として
RO を採り、その解決は出所 (ユーザ指定 / 自動発見) を区別しない。

権限を疑ったときは表示ではなく mount を見る。

```bash
findmnt -T ~/.cache/uv -o TARGET,SOURCE,OPTIONS
```

#### PATH 上のディレクトリは read-only で固定される (dev-tool access が ON のとき)

> [!NOTE]
> この節は `copilot_allow_dev_tool_access = true` のときの挙動。
> 現在は `false` にしているので、この自動付与は起きない。
> 他マシンや既定設定でこの症状に当たったときのために残してある。

`allowDevToolAccess` は `PATH` に載っているディレクトリを **read-only で
bind-mount** する。公式の意図は
"a command needs to run `git`, not modify it" で、実行ファイルの置き場を
改竄から守るもの。**保護されるのは PATH に載っているディレクトリそのもの**で、
その親は関係ない。

| パス | 権限 | PATH に載っているか |
| --- | --- | --- |
| `~/.local/share/mise` | rw | ✗ |
| `~/.local/share/mise/installs` | rw | ✗ |
| `.../npm-markdownlint-cli2/0.22.1` | rw | ✗ |
| `.../npm-markdownlint-cli2/0.22.1/bin` | **r- (EROFS)** | ○ |
| `.../node/24.5.0/bin` | **r- (EROFS)** | ○ |

このため `mise install --force` は、使用中のツールの `bin/` を消そうとして
`Read-only file system (os error 30)` で失敗する。sandbox の外で
ディレクトリごと消してから入れ直すこと。

#### bind-mount は symlink を「実体」に置き換える

ディレクトリを bind-mount する副作用として、
**そのパスが symlink だとビューから消える**。bind-mount は symlink を辿った
先を貼るので、リンクそのものはマウント後の名前空間に存在しない。

mise はツールごとに `<tool>/latest` という symlink を作り、PATH には
`<tool>/latest/bin` を載せる。この結果:

```text
ホスト        : installs/node/{24.5.0, latest -> 24.5.0}
sandbox 内    : installs/node/{24.5.0}          ← latest が消える
PATH          : .../node/latest/bin             ← 解決できない
結果          : node: not found
```

`node` が消えると、shebang で node を呼ぶ npm 製ツール
(`markdownlint-cli2` など) が軒並み動かなくなる。`npx` も同じ理由で消える。
同じ現象は `/bin` `/lib` `/sbin` でも起きている。

**対処は親ディレクトリごと許可すること。** 親を許可した領域は bind-mount では
なく素通しになり、中の symlink はリンクのまま見える。実測でも
`/usr/local` を許可した後は `cuda -> /etc/alternatives/cuda` が
symlink として見えている。`copilot_read_allow` が
`~/.local/share/mise/installs` ではなく **`~/.local` ごと** 許可しているのは
この理由による。

> [!NOTE]
> 「symlink が一律に消える」わけではない。消えるのは
> **bind-mount の対象になったパス自身**だけ。

#### 機構の境界 (どこに書くか)

置き場所は **「誰が強制できるか」** で決める
([ADR-0007](../adr/0007-filesystem-guard-boundary.md))。

| 表現したいもの | 置き場所 | 効く CLI |
| --- | --- | --- |
| 絶対パス・ワイルドカード無しの遮断 | `[sandbox] deny` | 両方 (OS レベル) |
| glob / cwd 相対 / 意味論を含む遮断 | hook | 両方 |
| CLI ごとに書き方が違う**許可** | `claude_*` / `copilot_*` | 片方ずつ |

規則は 1 つだけ覚えればよい。

> **CLI 固有キーに「禁止」を置かない。** 許可にだけ使う。

許可の非対称は実効ポリシーを揃えるためのもので安全側に働くが、
禁止の非対称はそのまま穴になる。実際、`[file] claude_read_deny_globs` は
Claude の `Read()` deny にしかならず、**リポジトリ内に置かれた秘密ファイルが
Copilot からは読める**状態だった。現在は `check_file_read.py` が同じリストを
読んで Copilot 側を埋めている。

| 防御 | Claude | Copilot |
| --- | --- | --- |
| ホーム配下の秘密 | `[sandbox] deny` | 同左 |
| リポジトリ内の秘密 (glob) | `Read()` deny permission | `check_file_read.py` hook |
| bash 経由のアクセス | `check_bash.py` hook | 同左 |

`check_file_read.py` を Claude に付けないのは、permission が同じリストから
生成済みで防御が増えないうえ、**全ファイル読み取りに Python のプロセス起動が
乗る**ため (ADR-0004 の実測で hook 1 回あたり 110ms)。

#### プロジェクト側の設定で `deny` を打ち消せるか

**打ち消せない。** ただし層ごとに理由が違う。

| 層 | プロジェクト設定からの上書き | 根拠 |
| --- | --- | --- |
| sandbox | **不可** | Claude は配列がスコープをまたいで**結合**され削除手段が無い。Copilot はリポジトリ設定に `sandbox` を許していない |
| permission (Claude) | **不可** | 「deny → ask → allow の順に評価し、**最初に一致したものが結果を決める**」 |
| hook (`preToolUse`) | **不可** | 「**いずれかの hook が deny を返せばブロック**」 |

> [!WARNING]
> **`permissionRequest` は別物。** この event だけは
> 「後の hook 出力が前を上書きする」と定義され、読み込み順は
> policy → user → **project** → plugins。リポジトリ側の hook が user の決定を
> 上書きできる。このリポジトリが `preToolUse` しか使っていないのは意図的で、
> **`permissionRequest` に移してはいけない** (test で固定)。

#### 残る非対称

`claude_network_*` だけが残る。Copilot にドメイン単位の制御が無く
(`allowOutbound` の on/off だけ)、hook でも代替できない。

`[sandbox] deny` の実効性は実測済み。deny 配下のディレクトリは
**空の tmpfs として見える** (エントリ数 0) ので、`ls` は成功するが中身は
一切取れない。

両 CLI とも **whitelist (deny-by-default)** で揃えてある。Copilot は元から
その方式で、Claude は `denyRead` に `~/` を置き `allowRead` で穴を開けることで
同じ形にしている (公式ドキュメントに構成例あり)。書き込み側は両者とも元から
whitelist (cwd + セッション temp + 明示許可のみ)。

`common.toml` の `[sandbox]` に書くパスは、permission の `Read()`/`Edit()`
glob 記法とは **書式が異なる**:

- `~/` 始まりで home からの相対、`/` 始まりで絶対、無印/`./` はプロジェクト
  相対 (ただし **user 設定 `~/.claude/settings.json` では無印/`./` は
  `~/.claude` 基準になる**)。ホーム全体に効かせたいパターンは必ず `~/` を
  明示すること。
- `deny` (両 CLI 共通): whitelist の内側でも遮断する秘密情報。read/write 両方。
  公式に "Rules that you configure are always kept" とあり自動付与に勝つ。
- `claude_read_allow` (Claude のみ): whitelist に開ける読み取りの穴。
  ツールチェーン (`~/.local` `~/.cache` `~/.cargo` 等) と skill 置き場のみ。
- `claude_write_allow` (Claude のみ): cwd + temp 以外に書き込みを許す場所
  (パッケージマネージャのキャッシュ)。
- `claude_write_deny` (Claude のみ): read は許すが write を禁止する対象
  (hook/permission 設定の改竄防止、シェル起動ファイル、認証ファイル)。
- `.git/config` / `.git/hooks` はリポジトリ相対のパスなので `common.toml` には
  書けないが、**Claude sandbox の "Protected paths" が常時保護している**
  (`allowWrite` や `Edit` 許可ルールでも解除できない)。同じく cwd 配下の
  シェル起動ファイル・`.gitconfig`・`.claude/**`・`.mcp.json`、および
  `~/.claude` のほとんどと `~/.claude.json` も自動で write 保護される。
  Copilot 側は cwd 外に書けないこと自体が保護になる。
  hook の `check_guard_tampering` は、sandbox の外で動く操作
  (承認済みの unsandboxed コマンドなど) 向けの二重化として残す。

#### なぜ Claude 専用キーが残るのか (whitelist に揃えた後も)

モデルを揃えても、次の 2 点は **機構の差**として残るため Copilot には渡さない:

| キー | Copilot に渡さない理由 |
| --- | --- |
| `claude_read_allow` / `claude_write_allow` | Copilot は同じ役割を `copilot_read_allow` / `copilot_write_allow` が担う。内容はほぼ同じだが、ホーム外 (`/usr` `/opt`) の扱いが違う (Claude は `denyRead` が `~/` 配下だけなので元から読める) ので別キーにしてある |
| `claude_write_deny` | Copilot は cwd の外に**そもそも書けない**ので、改竄防止の deny を足す意味が無い |

つまり「Claude 専用」は *方針の差ではなく実装の差*。両者の**実効ポリシーは
揃っている**必要がある。

> [!IMPORTANT]
> 運用方針は Copilot が家用で緩め、Claude が会社用で厳し目。
> `claude_read_allow` を安易に広げると **Claude の方が緩くなり方針が逆転する**。
> 実測した Copilot の実効ポリシーには `$HOME` 配下の作業ディレクトリ許可は
> 無く、skill も `~/.agents/skills` と `~/.claude/skills` だけが出る。
> そのため `claude_read_allow` にも `~/src` のような他リポジトリや、
> AI CLI の設定ディレクトリ全体 (`~/.claude` 等) を入れない
> (`test_read_allow_does_not_open_other_repositories` 他で固定)。
> 作業中のプロジェクトは cwd として自動許可されるので不要。
> 別ディレクトリが要るときは `claude --add-dir <path>`、恒久的に必要なら
> `~/.config/agents/local.toml` を使う。

`~/.config` は丸ごと開けているため、その中の秘密 (`sops/age`,
`gh/hosts.yml`, `Bitwarden CLI`) は `deny` で個別に塞いでいる
(`test_secret_config_dirs_are_denied_even_though_config_is_allowed`)。

#### なぜ広い名前マッチを deny に置かないか

Claude の Linux sandbox は **deny 対象の各パスに `/dev/null` を bind-mount
する**実装。そのため `~/**/*secret*` のような名前マッチを deny に書くと
展開結果の数だけ mount が必要になる。実測 (この環境の `$HOME`):

| パターン | 展開数 |
| --- | ---: |
| `~/**/*secret*` | 1316 |
| `~/**/*credential*` | 1103 |
| `~/**/*.pem` | 473 |
| `~/**/*password*` | 285 |
| **deny 全体** | **3239** |

コマンド 1 回ごとに 3239 個の bind-mount は実用に耐えない。さらに deny 対象が
**symlink を経由すると bwrap のセットアップごと失敗**し、全 sandbox コマンドが
動かなくなる既知の不具合がある ([anthropics/claude-code#45451][cc-45451])。
whitelist なら deny は `~/` の 1 本で済み、どちらの問題も起きない。
この不変条件は `test_deny_has_no_broad_name_globs` で固定している。

[cc-45451]: https://github.com/anthropics/claude-code/issues/45451

#### symlink の扱い

sandbox は **symlink で許可範囲を広げることも deny を回避することもできない**。
bwrap は mount namespace で隔離するため、許可されていないパスは sandbox 内に
存在せず、そこへ張った symlink を辿っても `ENOENT` になる。macOS の Seatbelt も
解決後のパスで判定する。Copilot も tool permission 層について
"The match resolves symlinks and `.`/`..` segments" と明記している。

→ 大きなデータセット等を使わせたい場合は、プロジェクト配下に symlink を張る
のではなく **実パス (`/data1` 等) を明示的に許可**すること。利便性のための
symlink は張ってもよいが、許可は実パスに与える必要がある。

sandbox は `sandbox.enabled = true` のみを設定し、`autoAllowBashIfSandboxed`
等の承認モードには触れない。既存の承認フロー (`permissions.defaultMode`) は
変えず、sandbox は純粋に追加の防御層として働く (副作用を最小化するため)。

### ネットワーク層 (`[web]` → `sandbox.network`)

ファイル層と違い、**ネットワークは両 CLI で足並みを揃えられない**。

| | Claude | Copilot |
| --- | --- | --- |
| 粒度 | **ドメイン単位** (`allowedDomains` / `deniedDomains`) | **on/off のみ** (`allowOutbound` / `allowLocalNetwork`) |
| 強制方法 | sandbox 外のプロキシ。全サブプロセスに適用 | OS レベル |
| 許可外の扱い | **承認プロンプト** (既定) | 単純に不可 |

`common.toml` の `[web] allow_domains` (WebFetch 用のドキュメントサイト) と
`[sandbox] network_allow` (shell が実際に通信する CDN 等) を合算したものが
Claude の `sandbox.network.allowedDomains` になり、`deny_domains` は
`deniedDomains` に反映される。2 つに分けているのは役割が違うため:
前者を増やすと WebFetch の自動承認が広がり、後者を増やすと shell の通信先が
広がる (`test_network_allow_is_disjoint_from_web_allow_domains` で混在を検出)。

なお Claude は `WebFetch(domain:...)` の許可ルールからも sandbox の allowlist を
組み立てるため前者は実質二重だが、permission 側の記法が変わっても sandbox の
許可が崩れないよう明示的に出している。

> [!WARNING]
> **sandbox に効く wildcard は先頭の `*.` と単独の `*` だけ**。
> `example.*` のように他の位置に置いた wildcard は `WebFetch` には効くが
> sandbox 側は無視するため、穴が開いたつもりで開いていない状態になる
> (`test_web_wildcards_are_sandbox_compatible` で固定)。

#### ネットワークも whitelist にしてある (Claude のみ)

`[sandbox] network_strict = true` から `sandbox.network.strictAllowlist` を
立てており、**許可外ドメインへの接続は拒否される** (Claude Code v2.1.219 以降が
必要)。これが無いと許可外は拒否ではなく**承認プロンプト**になる。

許可漏れがあっても即座に破綻はしない。sandbox 内で接続が失敗し、
「sandbox 外での再実行」を求める承認プロンプトに落ちるだけなので、
足りないドメインが判明したら `claude_network_allow` に追記すればよい。

**Copilot 側は outbound が全ドメイン許可のまま**で、これは変えられない
(ドメイン単位の設定が存在しないため)。`allowedUrls` は公式に
"URLs or domains allowed without prompting" とあるとおり**承認プロンプトの
省略リスト**であって通信制限ではなく、sandbox 内の `curl` は任意のホストへ
到達できる。結果としてネットワークは Claude (会社用・厳しめ) と
Copilot (家用・緩め) で非対称なままになるが、これは運用方針とは一致している。

#### 認証情報を sandbox 側で落とす (`sandbox.credentials`)

Claude Code v2.1.187 以降では `sandbox.credentials` で、sandbox 内の
環境変数を unset する (`deny`) か、値を伏せたままツールを動かす (`mask`)
ことができる。`check_secret_env_echo` や `check_gh_token_exposure` の一部を
肩代わりできるが、`mask` は TLS 終端 (`network.tlsTerminate`) を要求し
プロキシに平文を見せることになるため、導入は別途検討する (現在は未使用)。

#### WSL2 での抜け穴 (seccomp フィルタ)

WSL2 では Windows バイナリ (`cmd.exe`, `/mnt/c/...`) の起動が Unix domain
socket 経由になるため、**seccomp フィルタが無いと sandbox から脱出できる**
(公式: "the optional seccomp filter has to be installed to block the socket
in the first place")。未導入だと Claude は
`[Sandbox Linux] apply-seccomp binary not available - unix socket blocking
disabled.` を出す。

このリポジトリでは **mise で導入し、パスを settings.json で教える**方式を
取っている。`npm install -g` は `[bash] deny` で禁止しているため使わない。

- `home/dot_config/mise/config.toml.tmpl` の
  `"npm:@anthropic-ai/sandbox-runtime"` が本体を入れる。
- `common.toml` の `[sandbox] seccomp_apply_path` が導入先を指し、
  `generate.py` が `sandbox.seccomp.applyPath` を生成する。

> [!IMPORTANT]
> **mise に書くだけでは効かない。** Claude が `apply-seccomp` を自動検出するのは
> npm のグローバル領域だけである:
>
> - npm グローバル prefix (`npm -g config get prefix`) 配下の `lib/node_modules`
> - `/usr/lib` / `/usr/local/lib` / `/opt/homebrew/lib` の `node_modules`
>
> mise の `npm:` バックエンドはパッケージを
> `~/.local/share/mise/installs/npm-.../` へ**隔離**するため、上記のどこにも
> 現れない (実機で npm prefix 配下の `@anthropic-ai/` が空のままになることを
> 確認済み)。そこで公式が用意している代替手段
> 「copy `vendor/seccomp/*` from sandbox-runtime and set
> `sandbox.seccomp.bpfPath` and `applyPath` in settings.json」を使い、
> **コピーの代わりに mise の導入先を直接指している**。

`seccomp_apply_path` の `{arch}` は `generate.py` が `x64` / `arm64` に
置換する。バージョン更新に追従するよう mise の `latest` エイリアスを経由し、
**パスが実在するときだけ**設定を出力する (未導入のマシンや非対応
アーキテクチャでは設定が出ず、Claude は従来どおり自動検出に戻るだけ)。

導入後は `/sandbox` の Dependencies タブに不足が出ていないことを確認する。

#### sandbox に移せないネットワーク系チェック

以下は「どのドメインに繋ぐか」では表現できないため hook に残す:

| チェック | 残す理由 |
| --- | --- |
| `check_reverse_shell` | `/dev/tcp`・`nc -e`・待ち受けソケット。ドメイン許可の話ではない |
| `check_pipe_to_shell` | `curl \| sh` は**許可済みドメイン**でも成立する |
| `check_curl_file_send` | 許可済みドメインへの外部送信は sandbox では止まらない |
| `check_pip_redirect` | uv に統一するという**ポリシー**であってセキュリティではない |
| `check_gh_api_*` | GitHub API の意味解釈が必要 |

逆に `check_http_dangerous_output` (`curl` でシェル起動ファイルを上書き) は
下記の Protected paths と `denyWrite` で**完全に冗長**になっている。

### このマシンだけで許可を足す (chezmoi 管理に影響を与えない)

データセット置き場 (`/data1`) や外部マウントなど、**このマシンでしか意味が
無いパス**を共有の `common.toml` に書きたくない場合の手段。共有設定を汚さず、
`chezmoi diff` にも出ない方法が CLI ごとに用意してある。

> [!IMPORTANT]
> `~/.claude/settings.json` の `sandbox` キーを直接編集しても無駄。
> `chezmoi apply` のたびに `generate.py` が丸ごと生成し直すため上書きされる。
> `~/.copilot/settings.json` も `deniedPaths` だけは同様に再生成される。

#### 1. `~/.config/agents/local.toml` (両 CLI・マシン全体)

`generate.py` は起動時にこのファイルがあれば読み、**追記だけ**を共有設定へ
マージする。chezmoi の管理対象ではないので `chezmoi apply` でも消えず、
`chezmoi diff` にも現れない。

```toml
# ~/.config/agents/local.toml (chezmoi 管理外・このマシン専用)
[sandbox]
claude_read_allow   = ["/data1", "/data2"]   # データセットは read-only で十分
claude_write_allow  = ["/data1/outputs"]     # 書き出し先だけ read-write
copilot_read_allow  = ["/data1", "/data2"]   # Copilot にも要るなら両方書く
copilot_write_allow = ["/data1/outputs"]
deny                = ["/data1/private"]     # 許可した中の一部を塞ぐことも可能

# このマシンの「この案件でだけ」開きたいもの (Copilot)
[[copilot.locations]]
path = "~/src/some-project"
allowed_directories = ["/data1/some-project"]
```

- 反映させるには `chezmoi apply` を実行する (生成時に読まれる)。
- `[sandbox]` で追記できるのは `deny` / `claude_read_allow` /
  `claude_write_allow` / `claude_write_deny` / `copilot_read_allow` /
  `copilot_write_allow` のみ。**共有設定のエントリを消したり緩めたりはできない**
  (`sandbox.enabled = false` のようなキーは無視される)。
- `[[copilot.locations]]` で追記できるのは `path` / `approvals` /
  `allowed_directories`。同じ `path` が共有側にもあれば **union** される。
- **CLI 名の接頭辞を省略できない。** 無印の `read_allow` を書いても黙って
  無視されるため、`generate.py` が stderr に警告を出す。
- パスは実在している必要がある。存在しないパスは bwrap の bind-mount が
  失敗する要因になる。
- `AGENTS_LOCAL_CONFIG` 環境変数でファイルの場所を差し替えられる (テスト用)。
- `~/.config/agents` は `claude_write_deny` に入っているため、**sandbox 内の
  コマンドからは書けない**。エージェントがここに許可を書き足して自分の
  権限を広げることはできない。

#### 2. `.claude/settings.local.json` (Claude・プロジェクト単位)

Claude の設定スコープは上から managed → `claude --settings` →
`.claude/settings.local.json` (project local) → `.claude/settings.json`
(shared project) → `~/.claude/settings.json` (user) の 5 段。
**`sandbox.filesystem` の配列はスコープをまたいでマージされる**
(上書きではなく結合) ので、project local に穴だけ書けばよい。
このファイルは Claude 自身が global gitignore に追加するためコミットされない。

```json
{ "sandbox": { "filesystem": { "allowRead": ["/data1"] } } }
```

user スコープに `settings.local.json` は**存在しない**。マシン全体に効かせたい
場合は 1 の `local.toml` を使うこと。

#### 3. `[[copilot.locations]] allowed_directories` (Copilot・プロジェクト単位)

Copilot には **作業ディレクトリごと**の追加許可がある。`common.toml` に書くと
`~/.copilot/permissions-config.json` の `locations.<path>.allowed_directories`
へ展開され、そのプロジェクトで作業しているときだけ適用される。

```toml
[[copilot.locations]]
path = "~/src/some-project"
allowed_directories = ["/data1/some-project"]
```

location キーは **Git ルート** (リポジトリ外なら正規化した cwd)。
絶対パスのみで、公式仕様が「適用時に実在すること」を要求するため
`generate.py` が存在しないパスを落とす。**deny は書けない**
(`permissions-config.json` は deny / ask 非対応)。

案件固有のものは共有設定を汚さないよう、`common.toml` ではなく
chezmoi 管理外の `~/.config/agents/local.toml` に同じ書式で書く
(同じ `path` は union される)。

> [!IMPORTANT]
> **設定の実体はプロジェクトの外 (`~/.copilot/`) にある。**
> リポジトリの中に置いて共有することは**できない**。
> Copilot のリポジトリ設定が受け付けるキーは公式に列挙されており、
> `sandbox` も `permissions-config.json` の `locations` も含まれない。
> 許されているのは `deniedUrls` / `disabledMcpServers` のように
> **union で追加するだけ・削除できない** = 締める方向のキーに限られる。

#### 4. 対話プロンプトで承認する (Copilot・プロジェクト単位・設定不要)

**実は一番手軽なのはこれ。** Copilot はディレクトリやツールの承認を
`~/.copilot/permissions-config.json` へ**自分で保存する**。公式に
「When you approve a tool or grant access to a directory for the current
location, the CLI records the decision here」とある。

> [!IMPORTANT]
> このファイルは CLI が書き込むため、`generate.py` は **location 単位で
> union** する (全置換しない)。以前は全置換していたため、
> **`chezmoi apply` のたびに対話承認が消えて同じプロンプトが再発する**
> 不具合があった。承認を取り消したいときは CLI を終了してから手で消す。

#### 5. `/sandbox config` の TUI (Copilot・マシン全体)

Copilot は `readonlyPaths` / `readwritePaths` を **`generate.py` が触らない**
設計なので、TUI で足した許可はそのまま残る (`chezmoi apply` でも消えない)。
`deniedPaths` だけが共有の `deny` から再生成される。

#### 6. 一時的に 1 セッションだけ

- Claude: `claude --settings '{"sandbox":{"filesystem":{"allowRead":["/data1"]}}}'`
- Copilot: `--add-dir` で作業ディレクトリを足す

> [!NOTE]
> どの方法でも **symlink は許可の手段にならない**。プロジェクト配下に
> `/data1` へのリンクを張っても、許可は実パスに与える必要がある (後述)。

#### まとめ: どれを使うか

| 効かせたい範囲 | Claude | Copilot |
| --- | --- | --- |
| **このプロジェクトだけ (まず試す)** | プロンプトで「don't ask again」→ `.claude/settings.local.json` | **プロンプトで承認** → `permissions-config.json` に自動保存 |
| このプロジェクトだけ (共有したい) | `.claude/settings.json` **(リポジトリ内・コミット)** | **不可** |
| このプロジェクトだけ (設定で明示) | `.claude/settings.local.json` | `local.toml` の `[[copilot.locations]]` |
| このマシン全体 | `local.toml` の `[sandbox]` | 同左 |
| 全マシン (共有) | `common.toml` の `claude_*` | `common.toml` の `copilot_*` |
| 1 セッションだけ | `claude --settings` | `--add-dir` |

**まず対話プロンプトで承認すれば足りることが多い。** 設定ファイルを書く必要が
あるのは「無人実行で聞かれたくない」「複数マシンへ配りたい」場合に限られる。

リポジトリの中に許可を置けるのは Claude だけ。Copilot はプロジェクト単位の
スコープを持つが、設定ファイルの実体は常にリポジトリの外にある。

> [!WARNING]
> **Claude の `.claude/settings.json` はコミット対象の共有ファイル**で、
> 公式に「In a git repository, commit it so teammates get it」とある。
> `sandbox.filesystem` の配列はスコープをまたいで結合されるので、
> **信頼していないリポジトリを clone しただけで自分の sandbox が広がりうる**。
> 緩和は `--setting-sources` で project スコープを除外する (v2.1.246+) か、
> managed settings の `allowManagedReadPathsOnly`。
> Copilot はリポジトリ設定に `sandbox` を許していないためこの経路が無い。

### Copilot の sandbox は Claude と別物

Copilot の sandbox 設定は `~/.copilot/settings.json` の `sandbox` キーに入る。
スキーマは公式ドキュメントに記載が無く、実機で `/sandbox` の TUI を操作して
確認したもの (Copilot CLI 1.0.84-5):

```jsonc
"sandbox": {
  "enabled": true,
  "allowBypass": true,          // sandbox 外での実行を都度承認で許可
  "allowDevToolAccess": false,  // 自動許可。ADR-0008 により無効化
  "addCurrentWorkingDirectory": true,
  "sandboxMcpServers": true,
  "sandboxLspServers": true,
  "auth": { "git": true, "gh": true },
  "userPolicy": {
    "filesystem": {
      "readwritePaths": [], "readonlyPaths": [], "deniedPaths": []
    },
    "network": { "allowOutbound": true, "allowLocalNetwork": true }
  }
}
```

Claude との差で特に重要なもの:

- **既定のモデルが逆だった**。Claude の既定は「read 全許可 → deny を引く」
  ブラックリストだが、Copilot は **deny-by-default のホワイトリスト**
  (公式: "The sandbox is deny-by-default: unless a path is explicitly
  granted, a command cannot use it")。
  → このリポジトリでは Claude 側を `denyRead: ["~/"]` + `allowRead` で
  whitelist 化し、**両者のモデルを揃えてある**。
  → Copilot は cwd の外への書き込みがそもそもできないので、
  `claude_write_deny` (改竄防止) に相当する設定は**渡していない**。
- **`claude_read_allow` / `claude_write_allow` を Copilot に渡してはいけない**。
  Copilot 側は `copilot_read_allow` / `copilot_write_allow` が同じ役割を担う。
  内容はほぼ同じだが、ホーム外の扱いと write の範囲が違うため
  生成側が参照するキーを取り違えないことをテストで固定している
  (`test_copilot_sandbox_reads_only_the_copilot_keys`)。
- **ワイルドカード非対応・絶対パス限定** (公式ドキュメントに明記)。
  `deny` に書いた `~/**/.env` のようなパターンは Copilot 側では
  自動的に除外される (`build_copilot_sandbox` が `*` を含む要素を落とす)。
- **`deniedPaths` に read/write の区別が無い**。Claude の
  `denyWrite` 相当 (「改竄防止のため書き込みだけ止めたい」) を
  ここに書くと **read も止まり通常の開発作業が壊れる**:
  `~/.gitconfig` を入れると git が user 情報や include を読めず全 git 操作が
  失敗し、`~/.copilot/hooks` や `~/.config/agents` を入れると hook 自体が
  読めなくなる。よって共通の `deny` には
  **「純粋な秘密情報で、通常の開発で読む必要が無いもの」だけ**を置き、
  write のみ止めたいものは `claude_write_deny` (Claude 専用) に分ける
  (この不変条件は `test_copilot_deny_excludes_read_required_files` で固定)。
- `readonlyPaths` は Claude の `denyWrite` とは**別物**。前者は
  deny-by-default のホワイトリストへの「read 権限の付与」(足し算) で、
  後者は「write 権限の剥奪」(引き算)。ただし重なった場合は
  **より具体的なパスが勝ち、ユーザーが明示した規則は自動付与より優先される**
  ため、広い read/write 付与の内側を `readonlyPaths` で書き込み禁止にする
  使い方はできる (公式の例: `/project` は writable だが
  `/project/secrets` を read-only にするとそこだけ保護される)。
  リポジトリ内の秘密ディレクトリを守りたい場合はこれが使える。
- `~/.ssh` を denied にすると git over SSH は使えなくなるが、
  `auth.git` / `auth.gh` が GitHub 向けトークンを注入するため
  HTTPS 経由の `git` / `gh` は sandbox 内でも動作する。
- sandbox の適用範囲はプロセスによって強度が違う。shell コマンドや
  `grep`/`glob` (ripgrep) は **OS が強制**するが、CLI 内蔵の read/edit
  ツールは同じポリシーを**ソフトウェア的に自己チェックするだけ**
  (OS のバックストップが無い)。リモート MCP には適用されない。

`generate.py` が管理するのは `enabled`・`allowDevToolAccess`・
`userPolicy.filesystem` の 3 リスト。`network` / `allowBypass` / `auth`
といった挙動設定には触れない (家用の緩い運用を壊さないため)。
`readwritePaths` / `readonlyPaths` は `/sandbox config` の TUI から足した分と
`common.toml` の分を **union** する (生成側が手作業の追加を消さない)。

#### 実測した既定の許可範囲 (WSL2, chezmoi リポジトリを cwd として `/sandbox policy`)

```text
System (read-only):  /etc /usr/bin /usr/lib /usr/lib32 /usr/lib64 /usr/libexec
                     /usr/sbin /usr/share /run/NetworkManager /run/systemd/resolve
                     /mnt/wsl/resolv.conf
System (read-write): $TMPDIR
Working directory:   <cwd> (read-write)
Current session:     ~/.copilot/session-state/<id>/files (read-write)
Copilot home:        ~/.copilot/logs (read-only)
Personal skill roots: ~/.agents/skills ~/.claude/skills (read-only)
Network:             Outbound allowed / Local network blocked
Dev-tool access:     Detected tools: python (パスはレポートに出力されない)
```

ここから分かること:

- **`$HOME` 直下は一切許可されていない**。`~/.gitconfig` `~/.bashrc`
  `~/.ssh` などは設定を足さなくても既定で触れない。
  `~/.copilot` も `logs` だけが read-only で、`hooks` や `settings.json` は
  許可対象外 = **改竄不能**。
- したがって Copilot 側では `deny` の大半が多重防御 (冗長) であり、
  実際に効くのは `allowDevToolAccess` が拾う可能性のある
  `~/.npmrc` / `~/.pypirc` / `~/.config/gh/hosts.yml` あたり。ただし
  **cwd を `$HOME` にして起動すると home 全体が read-write になる**ため、
  その場合の保険として残してある
  (公式: "Rules that you configure are always kept" なので自動付与に勝つ)。
- `$TMPDIR` が read-write で許可される。このリポジトリでは zsh 側で
  `TMPDIR` をリポジトリ直下 `.tmp` に向けているため
  (`home/dot_zshenv` の `_tmpdir_repo_local_update`)、
  sandbox の一時領域もリポジトリ内に収まる。
- 設定変更は **セッション開始時に読まれる**。`chezmoi apply` 後は
  Copilot を起動し直さないと `/sandbox policy` に反映されない。
- **存在しないパスの deny ルールは黙って無効化される**。実測では
  `~/.netrc` / `~/.npmrc` / `~/.pypirc` が未作成だったため
  設定した 10 件のうち 7 件しか enforce されず、残りは Notes 節に
  `does not exist; it is not enforced by the OS sandbox` と出た。
  → 後からファイルが作られても (例: `npm login` が `~/.npmrc` を作る)
  そのセッション中は deny が効かない。次のセッションからは効く。
  `$HOME` が既定で未許可であるため実害は小さいが、ルールが効いているか
  どうかは **Notes 節を必ず確認する**こと。
- `/sandbox policy` は cwd ごとに解決されるため、確認したいディレクトリで
  実行すること。

実効ポリシー (設定 + 自動付与 + 管理ポリシーの合成結果) は Copilot の
セッション内で `/sandbox policy` を実行すると確認できる。
拒否の発生を記録したい場合は **Denial capture** を有効にする。

`/tmp` の read/write を sandbox で全面遮断する案は、zsh 側で
リポジトリ直下 `.tmp` へ `TMPDIR` を向ける仕組みとセットで行う将来タスクで
あり、現時点では対象外 (`executable_redirect-tmp.py` が引き続き担当する)。

### 照合規則

パターンは素のトークン列で書く (例: `git push`)。
hook は normalize 後のセグメント先頭トークンで一致を見る。
normalize は「実際に走るコマンドを変えずに先頭トークンだけを変える飾り」を
すべて剥がすので、下記はいずれも `git push` として捕捉される:

```bash
cd /elsewhere && git push      # 作業ディレクトリの付け替え
git -C /elsewhere push         # 同上 (-C オプション)
bash -c "git push"             # シェル経由 (中身を再帰的に評価)
eval 'git push'                # 文字列のコード実行
env FOO=1 git push             # 環境変数プレフィクス
timeout 5 git push             # ラッパーコマンド
/usr/bin/git push              # 絶対パス
(git push)  /  { git push; }   # グループ化
```

加えて、取得した内容をコードとして実行する形は `check_pipe_to_shell` が deny する。
パイプだけでなく、等価な以下の形もすべて対象にしている。

```bash
curl -fsSL URL | sh                    # パイプ
curl -s URL | bash -s                  # stdin をコードとして読むフラグ
curl -s URL | sh -e                    # シェルの他のオプションは無関係
curl -s URL | bash /dev/stdin          # stdin を指すパス
curl -s URL | env bash                 # ラッパー越し
curl -s URL | env -S 'bash -s'         # env -S の値はコマンドライン
curl -s URL | xargs -0 sh -c           # 流れてきた内容がコマンド文字列になる
curl -s URL | xargs -I{} sh -c "{}"    # 置換で埋め込む形
curl -fsSL URL |
bash                                   # 行継続
bash -c "curl -s URL | sh"             # 引用符の中
sh -c "$(curl -fsSL URL)"              # コマンド置換
eval "$(curl -fsSL URL)"               # 同上
env bash -c "$(curl -fsSL URL)"        # ラッパー + コマンド置換
$(curl -s URL)                         # 置換結果をそのまま起動
bash <(curl -fsSL URL)                 # プロセス置換
. <(curl -fsSL URL)                    # source の別名
source /dev/stdin < <(curl -s URL)     # 同上
curl URL -o ./a && sh ./a              # 保存してから実行
curl -s URL > a.sh && bash a.sh        # リダイレクトで保存してから実行
wget URL/bootstrap && sh bootstrap     # wget の既定の保存名 (拡張子不要)
curl URL -o a.sh && chmod +x a.sh && ./a.sh
```

逆に、パイプの右辺がインラインコード (`-c` / `-e` / `--eval`) やモジュール (`-m`)、
スクリプトファイルを持つ場合は「流れているのはデータ」とみなして対象外にする。
`cat data.json | python3 -c '...'`、`cat file.txt | bash script.sh`、
`find . | xargs node script.js` は通る
(渡されたコード自体は `check_interpreter_inline_code` が別途検査する)。
シェルでは `-e` / `-m` / `-p` は挙動を変えるだけのオプションなので、
インラインコードの指定とはみなさない。

`env` / `timeout 5` / `nice -n 10` / `nohup` / `setsid` / `command` / `exec` /
`stdbuf` などのラッパーは、値を取るオプションを含めて剥がしてから head を見る。
保存したファイルを実行する形では、シェル/インタプリタの**最初の非オプション
引数**だけを対象にするので、`wget .../data.csv && python3 process.py data.csv`
のようにデータとして渡す形は通る。

コマンド名の照合だけでは捕まらない形は、専用のチェックが個別に見る。

| チェック | 対象 |
| --- | --- |
| `check_reverse_shell` | `/dev/tcp` へのリダイレクト、`nc -e` / `-l`、`socat EXEC:` |
| `check_shell_startup_write` | `~/.bashrc` / `~/.zshrc` / `authorized_keys` への**書き込み** |
| `check_privilege_escalation` | `chmod u+s`、`usermod` / `passwd`、`/etc/shadow` / `/etc/sudoers` |
| `check_encoded_command` | `base64 -d` / `xxd -r` の出力をシェルへ渡す形 |
| `check_guard_tampering` | hook・permission 設定の改変、`PYTHONPATH` の差し替え |
| `check_git_config_write` | `alias.*` / `core.hooksPath` / `credential.*` などの書き込み |
| `check_block_device_write` | `dd of=/dev/sda` |
| `check_secret_env_echo` | 秘密の環境変数を**出力先へ流す**形 |

`git -C <dir> <sub>` は normalize が `git <sub>` に畳むため、専用のチェックは持たない。
以前あった部分一致の判定は `git -C sub show HEAD -- config/app.yml` のような
読み取りまで deny する誤検知しか生まなかったため廃止した。

### 読み取りと書き込みを区別する

パスが引数に現れるだけでは書き込みではない。`_write_targets()` が
書き込み先だけを抽出し、`check_shell_startup_write` と
`check_privilege_escalation` はその結果に対して判定する。

- リダイレクト先 (`> f` / `>> f`)、`dd of=`
- `cp` / `mv` / `install` / `ln` / `rsync` は**最終引数**のみ
- `tee` / `truncate` / `shred` / `rm` / `chmod` / `chown` / `touch` などは全引数
- `sed` は `-i` があるときだけ

これにより `cp ~/.bashrc ./backup/` (複製元が起動ファイル) は通り、
`cp evil ~/.bashrc` は deny になる。
ただしインラインコード (`python3 -c "open('~/.bashrc','a')..."`) は読み書きの
区別が静的に付かないため、起動ファイルのパスを参照している時点で deny する。
`/etc` も同様に、読み取り自体が機密な `shadow` / `sudoers` は常に deny、
world-readable な `passwd` / `group` は書き込み先のときだけ deny とする。

### センシティブパスの判定を 2 段に分ける

| 段 | 根拠 | 例 |
| --- | --- | --- |
| 確実な証拠 | 完全一致の名前・拡張子・ディレクトリ | `.env`, `id_rsa*`, `credentials`, `*.pem`, `.ssh/`, `.aws/`, `.gnupg/`, `/etc/shadow` |
| 語彙ヒューリスティック | basename に `secret` / `password` / `credential` / `api_key` などを含む、`secrets/` 配下 | `db-password.yaml`, `secrets/prod.yaml` |

語彙ヒューリスティックには 2 つの例外を置く。

1. **ソースコードの拡張子** (`.py` / `.go` / `.ts` / `.rs` / `.java` など) は対象外。
   `src/secrets.py` や `internal/credentials.go` は「秘密を扱うコード」であって
   秘密そのものではない
2. **列挙するだけのコマンド** (`ls` / `tree` / `find` / `fd`) は対象外。
   中身を読まないため、`ls tests/fixtures/secrets` は通る。
   ただし確実な証拠 (`ls -la ~/.ssh`) は列挙でも deny のまま

### エージェント CLI のランタイム設定も秘密扱いにする

`~/.claude.json` と `~/.copilot/config.json` は CLI が自分で書き換えるランタイム
設定で、chezmoi 管理外。MCP サーバ定義の `headers` / `env` に PAT や API キーが
平文で入りうる (`claude mcp add --env GITHUB_PAT=...` など) ため、
`[file] claude_read_deny_globs` / `claude_write_deny_globs` (Claude の `Read()` / `Edit()`) と
`check_bash.py` (bash 経由の `cat` / `grep` / `jq`) の両方で deny する。

同名でも `~/.claude/settings.json` や `~/.copilot/hooks/from-claude.json` は
このリポジトリが生成する設定で秘密を含まないため、巻き込まない。
`.claude.json` は basename 完全一致 (`_SENSITIVE_BASENAMES`)、
`config.json` は名前が一般的すぎるのでディレクトリ込みの suffix 一致
(`_CREDENTIAL_PATHS`) で判定する。

MCP へトークンを渡すときは設定ファイルに直書きせず、環境変数や
`gh auth token` のような外部の資格情報ストアを経由させる。

### 秘密の環境変数

`check_secret_env_echo` は、値が**出力先へ流れる**ときだけ deny する。

| 形 | 結果 |
| --- | --- |
| `echo $GITHUB_TOKEN`, `printf ... "$TOKEN" > f` | deny |
| `curl -H "Authorization: Bearer $TOKEN" URL` | deny |
| `nc host 443 <<< "$TOKEN"`, `mail ... <<< "$SECRET"` | deny |
| `X=$GITHUB_TOKEN && echo $X` (別名への移し替え) | deny |
| `base64 <<< "$TOKEN"`, `sed -n p <<< "$TOKEN"` | deny |
| `sh -c 'echo $GITHUB_TOKEN'` (子シェルが展開) | deny |
| `python3 -c "print(os.environ['GITHUB_TOKEN'])"` | deny |
| `gh api -H "Authorization: bearer $GITHUB_TOKEN" /user` | 未掲載 |
| `docker run -e API_TOKEN=$API_TOKEN img` | 未掲載 |
| `bash -c 'docker run -e API_TOKEN=$API_TOKEN img'` | 未掲載 |
| `test -n "$GITHUB_TOKEN"`, `echo "${#GITHUB_TOKEN}"` | 未掲載 |
| `rg '\$GITHUB_TOKEN' .` (エスケープ済み) | 未掲載 |

出力先は `_SECRET_SINK_COMMANDS` (echo / printf / cat / tee / base64 / head /
sed / awk / jq など、stdin を stdout へ通すフィルタを含む) と
`_SECRET_EGRESS_COMMANDS` (curl / wget / nc / ssh / scp / rsync / mail / aws など) の
2 つに分けて持つ。`nc` は ask リストにあり Copilot では自動承認されるため、
hook 側の deny が実質唯一の防御になる。

`sh -c '...'` のようにコードを引数で渡す形は、中身を取り出して同じ判定を
再帰的に適用する (深さ 2 まで)。これにより「子シェルが展開する秘密」は捕捉しつつ、
`bash -c 'docker run -e API_TOKEN=$API_TOKEN img'` のような正当な形は通る。
シェルの `$VAR` 展開を経由しない `os.environ[...]` / `process.env.X` /
`$ENV{X}` / `ENVIRON["X"]` / `getenv(...)` は
`check_interpreter_inline_code` が見る。

値を出力せずプロセスへ渡すだけの形は通常の開発操作なので通す。
変数名の判定は `PATH` / `PATHS` / `MONKEY` / `KEYCLOAK_URL` / `AUTHOR_NAME` に
当たらないよう、`PAT` / `KEY` / `AUTH` は単語境界付きで照合する。

`cd <dir> && <cmd> <relpath>` のように作業ディレクトリを移してから相対パスで触る形は、
パスを結合した変種を作ってパス系のチェックだけ再適用する。

heredoc の本文は、実行される形 (`bash <<'EOF'` / `python3 - <<'PY'`) のときだけ
検査する。`cat <<'EOF' > note.md` のようにファイルへ書くだけの本文は
検査対象から外すので、ドキュメントにコマンド例を書いても誤検知しない。

評価順は **deny → ask → allow**。より具体的なパターンを deny に置けば、
一般形を ask にできる。

```toml
ask  = ["git reset"]          # index を戻すだけなら承認で実行
deny = ["git reset --hard"]   # 作業ツリーを壊す形だけ拒否
```

### deny と ask の使い分け

| 分類 | 例 | 置き場所 |
| --- | --- | --- |
| 承認の余地なく禁止 | `sudo`, `git push`, `git reset --hard`, `git rebase`, `gh pr merge` | `deny` |
| 外部への漏洩・システム変更 | `ssh`, `telnet`, `npm install -g`, DB クライアント | `deny` |
| 規約違反 | `pip` / `pip3` (uv / uvx を使う) | `deny` + hook の `check_pip_redirect` |
| 壊滅的な削除 | `rm -rf /`, `rm -rf ~`, `rm -rf /etc` | `check_rm_root_guard` (hard-deny) |
| コンテナ経由の権限昇格 | `docker run --privileged`, `-v /:/host`, docker socket | `check_docker_host_escape` (hard-deny) |
| プロジェクト外への変更 | `mise use -g`, `cmake --install`, `gcc -o /usr/local/bin/x` | `ask` |
| 提案 → 承認 → 実行 | `rm`, `git clean`, `git commit`, `docker rm`, `gh pr create` | `ask` |
| **LLM 判定へ委譲** | `npx`, `uvx`, `pipx run`, `python -c`, `npm install`, `mv` | **未掲載** |
| 用途で危険度が変わる | `nc` (疎通確認は `ask`、`-e` / `-l` は hook が deny) | `ask` + hook |
| サブコマンドで分ける | `systemctl status` は許可、`systemctl enable` は `deny` | 用途ごとに列挙 |
| 自動承認 | `git status`, `grep -n`, `uv sync` | `allow` |
| GitHub 読み取り | `gh pr list`, `gh issue view`, `gh search code`, REST GET | **未掲載** |

### `rm` の承認範囲

`rm` は ask に載せたままだが、**workspace 内だと確証できる削除だけ**は承認を省いて
auto / assisted の判定へ委ねる (`_ASK_EXEMPTIONS`)。
`rm -rf node_modules` / `build` / `.venv` のような再生成可能な成果物の削除で
毎回止まると、承認が形骸化するため。

> [!CAUTION]
> この委譲を成立させるには、`rm` を **Claude の `permissions.ask` に出してはいけない**。
> Claude の explicit ask は[どのモードでも自動承認されない](https://code.claude.com/docs/en/permission-modes)
> (`bypassPermissions` を含む)。PreToolUse hook の `allow` も v2.1.77 以降は
> ask を上書きしない。hook が黙っても静的 ask が残っていれば auto で必ず
> プロンプトが出て、上表の「未掲載」が実機では ask になる。
>
> そのため `[bash]` に `ask_hook_owned` を置き、generate.py はこのリストの
> コマンドを静的 ask から除外する。hook 側は `bash.ask` を丸ごと policy として
> 読むので、`ask` への掲載はそのまま必要。
>
> 代償として、hook が起動に失敗した場合は静的 ask の保険が無くなり auto の
> classifier 頼りになる。deny 側 (`check_rm_root_guard`) も hook 内なので、
> 壊滅的ターゲットの防御はもともと hook の可用性に依存している。
>
> Copilot は `permissions-config.json` が allow 専用 (`tool_approvals` /
> `allowed_directories`) で ask を持たないため、この分岐の影響を受けない。
>
> 整合性は `test_check_bash_decision.py` の
> `test_hook_owned_ask_is_not_emitted_as_a_static_claude_rule` が
> `_ASK_EXEMPTIONS` と突き合わせて固定する。

| 形 | 結果 |
| --- | --- |
| `rm -rf node_modules`, `rm -f *.pyc`, `rm src/old.py` | 未掲載 |
| `rm -rf .` / `./` / `*` / `./*` / `**` (作業ディレクトリ全体) | deny |
| `rm -rf .git`, `.git/objects`, `.git/refs` | deny |
| `rm -rf /`, `~`, `/etc`, `../../x` | deny |
| `rm -rf ../other-repo`, `~/Documents`, `/var/tmp/build` | ask |
| `rm -rf $BUILD_DIR`, `"$OUT"/*`, `$(cat targets.txt)` | ask |
| `cd /elsewhere && rm -rf data` | ask |
| `rm -rf .tmp`, `<workspace>/.tmp/run-1`, `find ./.tmp -delete` | 未掲載 (scratch 免除) |

免除の条件は次を**すべて**満たすこと。1 つでも欠ければ従来どおり ask にする。

- PreToolUse payload の `cwd` が取れ、絶対パスである (取れなければ fail-closed)
- コマンド全体に基点を変えるもの (`cd` / `pushd` / `popd` / `chdir`) が現れない。
  `normalize()` は `cd X && Y` を `Y` に畳むため、正規化後だけを見ると
  相対パスが workspace 内に見えてしまう。元の文字列を単語境界で判定するので
  `\cd` や `cd$IFS/x`、`bash -c "cd /x && rm -rf y"` も捕捉する
- `xargs` を含まない (対象が標準入力から来ると静的に読めない)
- 対象に `$` / `` ` `` / `~` / `{` / `}` が含まれない (展開が解決できない)
- 対象が絶対パスでない、`..` を成分に含まない
- ドット始まりの成分に glob を含まない (`.g*t` は `.git` に届く)
- 対象が glob だけのトークンでない (`*` / `**` は範囲が読めない)
- `cwd` を基準に解決した先が workspace の内側
- realpath で解決しても workspace の内側に留まる。途中の成分が symlink だと
  文字列比較だけでは外へ抜けるため、両方を見る。比較は workspace 側も
  realpath に揃えるので、workspace 自体が symlink 配下にあっても誤判定しない

deny 側は `check_rm_root_guard` が担う。作業ディレクトリ全体と `.git` 配下を
追加したのは、**workspace 内でも取り返しがつかない**ためである
(git 管理外・未コミットのファイルは復旧できず、`.git/objects` を消せば
リポジトリ自体が復旧不能になる)。
`.git` は `.g*t` のようなドット始まりの glob と `{.git,build}` の
ブレース展開も対象にする。
`.` は `find . -delete` のような探索起点としては正当なので、
判定は `rm` 側にだけ置き `_is_catastrophic_rm_target` には入れない。

### 使い捨てディレクトリ (`./.tmp`) の削除

`redirect-tmp.py` が `/tmp` の代わりに誘導する `./.tmp` は「いつ消えてもよい」
前提の置き場なので、ここだけは上の条件を緩めて承認を省く
(`_rm_targets_scratch_only` / `_find_targets_scratch_only`)。

workspace 免除との違いは 2 点だけ。

- **絶対パスを受け付ける** (`rm -rf <workspace>/.tmp/run-1`)。
  解決先が `.tmp` の内側だと確証できれば、範囲は workspace 免除より狭い
- **`find` の削除も免除する** (`find ./.tmp -delete`,
  `find ./.tmp -type f -exec rm {} +`)。
  探索起点がすべて `.tmp` 配下で、`-exec` に渡す引数が `{}` だけのときに限る

次はいずれも従来どおり ask にする。

- 対象に scratch の外が 1 つでも混ざる (`rm -rf .tmp /etc/hosts`)
- `..` を成分に含む (`rm -rf .tmp/../src`)
- `cd` / `pushd` で基点が変わる、`xargs` で対象が標準入力から来る
- `$` / `` ` `` / `~` / `{` / `}` を含む (`rm -rf $PWD/.tmp`)
- symlink が workspace の外を指している。`.tmp` 配下のリンクだけでなく、
  `.tmp` 自身が外を向いている場合も弾く (realpath で判定する)。
  **相対指定と絶対指定で判定は同じ**。workspace 免除が scratch 免除より
  先に成立するため、realpath 検査は両方に入れてある
- `find` の探索起点を省略した形 (`find -delete` は cwd 全体が対象)

`.git` の hard-deny は免除より先に評価されるので、`rm -rf .tmp/.git` は
引き続き deny になる。

免除が落ちて ask になったときは、`check_policy_ask` が通る書き方を
メッセージに添える (`rm -rf .tmp/<名前>` の形にする、`cd` や変数展開と
混ぜない)。常時読み込まれる個人用カスタム指示に書くと毎ターン
コンテキストを消費するため、**止めた時点のメッセージで誘導する**方を採った。

なお `ask` は Copilot CLI では自動承認されるため、この緩和が実際に効くのは
Claude Code だけである。逆に言うと、deny へ上げた 2 つは
**Copilot でこれまで素通りしていた**ものを止めるようになった。

### 「未掲載」という 4 つ目の選択肢

両 CLI には LLM が安全性を判定するモードがある。

| | Claude Code | Copilot CLI |
| --- | --- | --- |
| 手動 | `default`（別名 `manual`） | `manual` |
| **LLM 判定** | **`auto`**（classifier という別モデルが審査） | **`assisted`**（LLM safety check） |
| 全許可 | `bypassPermissions` | `allow-all` |

**`ask` に載せるとこのモードに到達しない。**
Claude Code は「explicit ask rule に一致するツールは、`bypassPermissions` を含む
どのモードでも自動承認しない」と明記している。hook が返す `ask` も同様に
プロンプトを最低保証する。**ただしこれが成立するのは Claude Code だけで、
Copilot CLI では hook の `ask` が自動承認される**（後述の `git commit` の説明を参照）。

したがって「LLM の判断に任せたい」コマンドは、`allow` ではなく
**どのリストにも載せない**のが正しい。`allow` に入れると手動モードでも
無条件に通ってしまい、かえって緩くなる。

| 状態 | Claude auto | Copilot assisted |
| --- | --- | --- |
| `allow` | 無条件実行 | 無条件実行 |
| `ask` | プロンプト | プロンプト |
| **未掲載** | **classifier が判断** | **safety check が判断** |

未掲載にしても hook の個別 deny チェックは効く。
`uvx ruff format .` は通るが `uvx pip install x` は deny、
`python -c 'print(1)'` は通るが `python -c "os.system('git push')"` は deny になる。

`gh` も全て allow から外している。Copilot の `permissions-config.json` は
`gh pr list` のような allow を先頭トークン `gh` に丸めるため、1件でも置くと
未列挙の mutation まで assisted を迂回してしまう。読み取り系は未掲載、
既知の mutation は ask / deny、`gh api` は hook の意味解析に委ねる。

| `gh` の分類 | 例 | 結果 |
| --- | --- | --- |
| 読み取り CLI | `issue/pr/release/repo` の list/view、`gh search`、`gh status` | 未掲載 |
| REST API 読み取り | 既定 GET、明示 GET / HEAD | 未掲載 |
| GraphQL 読み取り | inline の `query` / `{ ... }` | 未掲載 |
| API mutation | POST / PUT / PATCH / DELETE、暗黙 POST、GraphQL mutation | ask |
| API 判定不能 | query 未指定、file / stdin query、動的 method | ask |
| 秘密情報 | `auth token`, `auth status --show-token`, sensitive file payload | deny |

`gh api -f/-F` は通常は暗黙に POST へ切り替わる。ただし
`--method GET` を明示した場合は query parameter として扱うため未掲載にする。
GraphQL は読み取り query でも HTTP POST を使うので、method ではなく operation
本文を検査する。静的に安全性を確認できない場合は fail-open にせず ask へ倒す。

`git commit` の確認点は commit skill が持つ。skill は `git add -- <files>` と
`git commit ...` を別々のコマンドとして実行し、commit の直前に対象ファイルと
コミットメッセージを提示して承認を得る。ステージは取り消せるので `git add` は
未掲載のままにし、確認はコミットメッセージを読む1回に絞る。compound command に
しないのは、Claude Code の native permission も Codex の rules も `&&` の後半を
再評価しないためで、単独実行にすれば CLI 側の強制もコミットに効く。

なお **Copilot CLI 1.0.53 以降は hook の `ask` が機能しない**。TUI が permission
dialog を数十 ms 表示しただけで自動承認する既知バグ
([github/copilot-cli#3590](https://github.com/github/copilot-cli/issues/3590), OPEN)
があるため。実測では hook 由来の permission 90 件のうち 79 件が
`outcome=auto_approved` / `source=assisted_approval` で中央値 58ms (min 6ms /
max 99ms) に解決され、人間が応答した 11 件は中央値 23.5 秒だった。
`deny` はこのバグの影響を受けず正常にブロックする。

このため skill 側では CLI を判別せず、どの CLI でも同じ文面で明示確認する。
skill は呼び出したときしか読まれないため、Copilot 側は常時読み込まれる
`~/.copilot/copilot-instructions.md` にも同じ規則を置いて二重化している
（Claude Code / Codex は機械的強制があるので置かない）:

| CLI | 機械的強制 | 実際の確認点 |
| --- | --- | --- |
| Claude Code | hook / permission の ask | skill の明示確認 + ask プロンプト |
| Copilot CLI | なし (#3590 で自動承認される) | skill と copilot-instructions.md の指示 |
| Codex CLI | `git.rules` の prompt | skill の明示確認 + prompt |

Copilot 側のバグが修正されても skill の明示確認は残す。目的が
「実行の可否」ではなく「コミットメッセージの確認」であり、CLI 依存の
分岐を持たない方が文面を1つに保てるため。

`curl` / `wget` も allow には置かず、読み取りと通常ダウンロードを未掲載にする。
HTTP method と payload option は hook が transfer ごとに解析するため、
`curl --next` で複数 request を連結した場合も、1件でも mutation があれば ask になる。

| `curl` / `wget` の分類 | 例 | 結果 |
| --- | --- | --- |
| GET / HEAD | `curl URL`, `curl -I URL`, `wget URL`, `wget --spider URL` | 未掲載 |
| query parameter | `curl -G -d q=test URL` | 未掲載 |
| 通常ダウンロード | `curl -o file URL`, `wget -O file URL` | 未掲載 |
| HTTP mutation | `curl -X POST`, `curl -d`, `wget --method=PUT` | ask |
| upload / body | `curl -T file`, `curl -F file=@x`, `wget --post-file=x` | ask |
| ループバック宛の mutation | `curl -X POST http://localhost:8000/api` | 未掲載 |
| 判定不能 | config file、動的 method、option 値欠損 | ask |
| 取得結果の直接実行 | `curl URL \| sh`, `wget -qO- URL \| bash` | deny |
| 秘密情報の送信 | sensitive file payload、`$TOKEN` の header/body 展開 | deny |
| 永続化先の上書き | `curl -o ~/.bashrc`, `wget -O ~/.ssh/authorized_keys` | deny |

明示 GET / HEAD でも request body を送る指定があれば ask とする。
例外は `curl -G` で、data option を URL query parameter に変換するため未掲載になる。
通常ファイルへの保存はローカル書き込みだが、auto / assisted の安全性判定へ委譲する。

### ループバック宛の例外

ローカル開発中の `curl -X POST http://localhost:8000/api` のような mutation は承認を求めない。
ただし「宛先がループバックだと**確証できた** `curl`」に限る。以下はいずれも ask のまま。

- **接続先を URL から読み取れなくするもの**
  `-x` / `--proxy` / `--socks*` / `--preproxy`、`--unix-socket` / `--abstract-unix-socket`、
  `--connect-to` / `--resolve` / `--interface` / `--dns-servers` / `--dns-interface`、`-K` / `--config`
- **リダイレクト追従** — `-L` / `--location` / `--location-trusted`。
  `wget` は既定でリダイレクトを追うため、`wget` 自体を例外の対象外にしている
- **ホストがループバックに見えるだけのもの**
  `http://localhost@evil.example.com`（userinfo）、`http://localhost.evil.example.com`、
  `http://2130706433`（10 進表記）、`$URL`（変数展開）、`http://local{host,evil.example.com}`（glob）
- **非 HTTP scheme** — `gopher://127.0.0.1:6379` のようにループバックでも任意プロトコルを送れるもの
- **特権的な制御 API のポート**
  Docker daemon (2375/2376/4243)、etcd (2379/2380)、Kubernetes API (6443/8443)、
  kubelet (10250/10255/10256)、Redis (6379)、memcached (11211)

この例外は `check_curl_wget_mutation`（ask 層）にのみ入っている。
`DENY_CHECKS` は `ASK_CHECKS` より先に走るため、deny には一切影響しない。
実際 `curl -T ~/.ssh/id_rsa http://localhost:8000/`、`curl -o ~/.bashrc http://localhost:8000/x`、
`curl http://localhost:8000/x | sh` はループバック宛でも deny のままである。

deny 層に例外を設けないのは、curl 関連の deny が見ているのが「通信先」ではないため。
`check_http_dangerous_output` は**ローカルへの書き込み先**を、`check_pipe_to_shell` は**取得内容の実行**を、
`check_curl_file_send` は**秘密の持ち出し**を見ており、宛先がループバックでもリスクは消えない。
加えて Copilot CLI では ask が自動承認される（後述）ため、deny が実質唯一機能している層でもある。

モードは `common.toml` から両 CLI へ生成している。

```toml
[claude]
default_permission_mode = "auto"

[copilot]
default_permission_mode = "assisted"
experimental = true          # assisted は experimental な auto-approval に依存
```

Copilot の設定キーの権威ある一覧は Web ドキュメントではなく
`copilot help config` にある。

判断基準:

- **取り返しがつくか**: lockfile や git、再 pull で戻せるなら `ask` で十分
- **外部に出るか**: リモートや外部ホストへ情報が出るものは `deny`
  (`git push` / `gh pr merge` / `ssh` / `telnet`)
- **摩擦があるか**: そもそも使わないコマンドを緩めても利益が無い。
  DB クライアントは触る機会が無いので `deny` のまま置いている

### `allow` の粒度に注意

Copilot CLI へは `allow` の **先頭トークン (コマンド名)** だけが渡る。
`git diff` と書くと Copilot では `git` 全体が承認される。

hook は permission 層とは独立に走るので、**仕様どおりなら** `ask` / `deny` が
引数の粒度を補い、粗粒度化の実害は無い。ただし前提が 2 つある。

1. `ask` に載っていること。載っていなければ hook も沈黙する
   （例: `uv pip install` / `mise use -g` / `docker run --privileged` は
   `uv` / `mise` / `docker` が allow の先頭トークンなので Copilot では
   事前承認され、hook にも該当ルールが無い）
2. `ask` が実際に止まること。現状 Copilot は hook の `ask` を自動承認する
   既知バグがあり (github/copilot-cli#3590, OPEN)、実測 (1.0.84-2) でも
   `git config --get user.name` が確認無しで実行された

| hook の判定 | Claude | Copilot (仕様) | Copilot (現状) |
| --- | --- | --- | --- |
| `deny` | 止まる | 止まる | 止まる |
| `ask` | プロンプトが出る | プロンプトが出る | **素通り** (#3590) |
| 未掲載 / `allow` | 素通り | 素通り | 素通り |

`allow` にコマンドを足すときは、そのコマンド名で始まる**破壊的な形が
`ask` / `deny` に載っているか**を確認する。載せずに allow だけ足すと、
Copilot ではそのコマンドが丸ごと無防備になる。

### `ask` に載せるかどうかの判断軸

**影響範囲がプロジェクト内で完結するか**で決める。

| 影響範囲 | 扱い | 例 |
| --- | --- | --- |
| プロジェクト内で完結 | **未掲載** (LLM 判定に委ねる) | `uv add` / `uv remove` / `uv pip install` / `uv sync` / `mise install` / `mise use` (ローカル) / `cmake --build` / `gcc -o build/x` |
| ホームやシステムに残る | `ask` | `uv tool install` / `uv python install` / `uv self update` / `mise use -g` / `mise settings set` / `mise self-update` / `cmake --install` / `gcc -o /usr/local/bin/x` |
| 外部に見える / 認証情報が残る | `ask` | `docker login` / `docker push` / `gh pr create` |
| ツール自身を置き換える | `deny` | `uv self update` / `mise self-update` / `mise implode` / `rustup self update` / `chezmoi upgrade` / `npm install -g` |
| root 相当を得られる | `deny` | `sudo` / `docker run --privileged` / `docker run -v /:/host` |

ツールチェーンの更新を `ask` ではなく `deny` にするのは、影響が全プロジェクトに
及ぶうえ、戻すには元のバージョンを知っている必要があり実質不可逆だから。
エージェントが実行する正当な理由も無い。
対象がツール自身ではないもの (`uv tool upgrade ruff`、`uv python install`) は
プロジェクト外だが復旧可能なので `ask` に留める。

venv や lockfile はプロジェクトを捨てれば消えるので、承認を挟む価値が
承認疲れに見合わない。逆にホームやシステムへ出るものは、
セッションが終わっても残るので確認する。

### `mise` は common.toml に書けない

`command_policy` は `mise` を runner として扱い、`normalize()` が先頭の
`mise` を落とす (`mise settings set x` → `settings set x`)。そのため
`[bash] ask` に `mise ...` と書いても**一致しない**。mise の判定は
`check_global_env_mutation` で行う。
`test_mise_patterns_are_not_written_in_common_toml` が再発を防ぐ。
`mise self-update` / `mise implode` は `check_tool_self_update` が deny する。

フラグの位置が自由なもの (`mise use -g`、`cmake --build --target install`、
`gcc -o <path>`、`docker run --privileged`) も前方一致では取りこぼすので、
同じく hook 側で判定する。

作業ディレクトリを付け替える `-C` 形式は `allow` に入れない。
permission を回避する既知のバイパス形式であり、対策を用意している意図と矛盾する。

`allow` の先頭トークンと衝突する `ask` / `deny` エントリ（例: `git diff` を
allow に置くと Copilot では `git push` まで承認される）は、
`test_shadowed_entries_are_enforced_by_hook` が hook 側で意図した判定を返すことを
機械的に検査する。ここが落ちたら Copilot ではそのコマンドが無条件に通る。
ただしこの検査が保証するのは **hook の判定まで**で、Copilot が `ask` を
自動承認する分は埋められない。隠れるエントリのうち実際に止まるのは `deny` だけ。

`gh` は衝突を hook で補うのではなく、allow から完全に外して
`test_copilot_permissions_do_not_broadly_allow_gh` で再発を防ぐ。

### 無人実行時に `ask` がどうなるか

| 実行環境 | `ask` の結果 |
| --- | --- |
| Claude 対話 (`default`) | プロンプトが出る |
| Claude `auto` | プロンプトが出る (classifier の暗黙 approve を封じる) |
| Claude `bypassPermissions` | プロンプトが出る |
| Claude `dontAsk` | 自動拒否 |
| Claude `-p` (非対話) | プロンプト不能。auto では当該操作をスキップして継続 |
| Copilot cloud agent | `deny` 扱い |

→ 無人実行では必ず安全側に倒れるため、**`deny` を `ask` に緩めても無人時のリスクは
増えない**。対話時だけ「自分で手を動かす」手間が減る。

### credential 系 glob は部分一致にしない

`[file.read_deny_globs]` / `[file.write_deny_globs]` に `**/*key*` のような
部分一致 glob を書くと、正当なファイルまで巻き込む。実例:

```text
home/AppData/Roaming/Keyhac/extension/fakeymacs/keyhac.bat
home/AppData/Roaming/Keyhac/.../key_bindings.org
home/AppData/Roaming/Keyhac/.../keymap_layer.drawio
```

いずれも chezmoi 管理下でエージェントが編集する必要がある。
一般的にも `tokenizer.py` / `keyboard.ts` / `monkey.md` などを誤検知する。

→ `**/*.key` / `**/*_key` / `**/id_*` / `**/*.pem` / `**/.ssh/**` のように
**拡張子・接尾辞・既知のファイル名で具体的に**書く。
`test_check_bash_decision.py` が「正当なファイルが deny されないこと」と
「秘密ファイルが確実に deny されること」の両方を検査している。

### `[web]` の allow_domains は制限ではない

`common.toml` の `[web] allow_domains` は `generate.py` が
`WebFetch(domain:...)` として **`permissions.allow` にだけ**展開する。
つまり「このドメインは自動承認する」という意味であって、
**リストに無いドメインを拒否する仕組みではない**。
未掲載のドメインは `default_permission_mode`（現在 `auto`）の判定に落ち、
classifier が通せば取得できる。

| 生成先 | 反映されるキー | 効果 |
| --- | --- | --- |
| `~/.claude/settings.json` | `permissions.allow` | 自動承認のみ。deny 側へは出力されない |
| `~/.copilot/settings.json` | `allowedUrls` / deny | Copilot は `deny_domains` も反映できる |
| `~/.config/opencode/opencode.json` | (出力しない) | resource が URL 全体で、ドメイン許可を正しく書けない ([OpenCode へ渡さないもの](#opencode-へ渡さないもの)) |

Claude には「許可した以外を拒否する」表現手段が無い。
`permissions.deny` に素の `WebFetch` を置くと **全 WebFetch が止まる**
（deny が allow に優先するため、個別 allow で抜くこともできない）。
ホワイトリスト運用にしたい場合は hook で URL を検査する必要がある。

## hooks の単一ソース化

`[[hooks]]` に 1 度書けば、両 CLI の設定ファイルへ展開される。

| 生成先 | 生成方法 | 使うフィールド |
| --- | --- | --- |
| `~/.claude/settings.json` の `hooks` | `modify_settings.json.py.tmpl` → `--target claude-settings` | `claude_event` / `claude_matcher` / `timeout_sec` |
| `~/.copilot/hooks/from-claude.json` | `from-claude.json.tmpl` の `output` → `--target copilot-hooks` | `copilot_event` / `copilot_matcher` / `timeout_sec` |

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
  `~/.claude/hooks/` 配下を起動しているエントリだけを差し替える (後述)
- CLI UI で手動追加した hook も `~/.claude/hooks/` を指していなければ残るが、
  再現性が無いので `common.toml` に転記すること
- `*_event` を空にすればその CLI には出力されない
- `*_matcher` を省略すると `matcher` キー自体が出力されない (= 全マッチ)。
  `Stop` / `UserPromptSubmit` など matcher 非対応イベントでは省略すること

### bash 検査ルールの足し方

`check_bash.py` は入出力とループだけを持ち、判定は
`~/.claude/hooks/lib/bashrules/` にある。足す場所は 3 段階で選ぶ。

| やりたいこと | 編集する場所 | Python |
| --- | --- | --- |
| コマンド名の前方一致で許可 / 禁止 | `common.toml` の `[bash]` | 不要 |
| 守る名前・検査するオプションを足す | `bashrules/tables.toml` | 不要 |
| 上記で表せない判定 | `bashrules/*.py` + `__init__.py` | 必要 |

Python を書く場合は、内容に合うモジュールへ
`check_xxx(cmd: str) -> str | None` を定義し (拒否理由の文字列を返し、
問題なければ `None`)、`bashrules/__init__.py` の `DENY_CHECKS` か
`ASK_CHECKS` に 1 行足す。

| モジュール | 担当 |
| --- | --- |
| `rules_exec.py` | 任意コード実行 (`curl \| sh`、`python -c`、リバースシェル) |
| `rules_guard.py` | 防御機構・環境の改変 (hook、起動ファイル、権限昇格) |
| `rules_files.py` | ファイルの読み書き・持ち出し |
| `sensitive.py` | 秘密情報の検出 |
| `http.py` / `ghapi.py` | `curl` / `wget` / `gh api` の字句解析 |
| `rm.py` / `docker.py` | 削除 / コンテナ |
| `policy.py` | `common.toml` の deny / ask 照合 |
| `_shared.py` | 共通ユーティリティ (正規化・パス判定) |

★`__init__.py` のリストは**順序に意味がある**。先に一致したものがユーザーへ
のメッセージを決めるため、具体的な代替案を出せるルールを汎用のものより前に
置く。`check_policy_loaded` が先頭なのは fail-closed のため。

### 外部ツールとの共存 (Orca / herdr)

Orca は `~/.claude/settings.json` と `~/.gemini/settings.json` の `hooks` へ
直接エントリを注入する。`permissions` が chezmoi の専有領域なのに対し、
`hooks` は**共有領域**である。generate.py が `hooks` を全置換していた頃は
`chezmoi apply` のたびに Orca の 12 エントリが消えていた
(`SessionStart` / `UserPromptSubmit` / `SubagentStart` などは**イベントキーごと**)。

現在の `merge_claude_hooks()` は次の規則で動く。

| 判定 | 扱い |
| --- | --- |
| コマンドが `~/.claude/hooks/` を起動している (ホームの表記と引用は問わない) | chezmoi の生成物。除去して `common.toml` から再生成 |
| それ以外 | 外部由来。そのまま温存 |

パス基準で所有権を判定できるのは、`~/.claude/hooks/` 配下が
`home/dot_claude/hooks/` として**このリポジトリの管理下にある**ため。
逆に言えば、このディレクトリにスクリプトを置いて `settings.json` へ手で
登録しても、`common.toml` に転記していなければ次の apply で消える
（`common.toml` を単一の真実とするための意図的な挙動）。

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
| `~/.codex/config.toml` | 書き込み無し | `chezmoi-managed:start/end` マーカー間のみ |

Orca 本体が生成する実体 (`~/.orca/`, `~/.orca-wsl/`, `~/.orca-relay/`,
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

## common.toml の編集ルール

- 編集後は `chezmoi apply` で `~/.claude/settings.json` 等に反映される
- CLI UI で「Always allow」を押した場合は、その項目を common.toml に転記する
  (転記しないと次回 apply で消える。これは意図的な強制で、dotfiles を単一の
  真実とする方針)
- `[bash] deny` は hook が hard-block し、Claude では permission でも拒否される
- `[bash] ask` は hook が `ask` を返す。承認すればそのまま実行される
  (Copilot CLI では hook の `ask` が自動承認される既知バグがある。前述)
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

## Claude Code permission リストの既知バグ

下記は 2026-05 時点で open。hook 側の normalize で必ず防ぐべき理由。

| Issue | 概要 |
| --- | --- |
| [#59498](https://github.com/anthropics/claude-code/issues/59498) | `cd /elsewhere && git push` が `Bash(git push:*)` ask/deny を bypass |
| [#59006](https://github.com/anthropics/claude-code/issues/59006) | `git -C /path commit` が `Bash(git commit *)` deny を bypass |
| [#20085](https://github.com/anthropics/claude-code/issues/20085) | compound 命令 (`a && b`) が個別評価されない |
| [#52419](https://github.com/anthropics/claude-code/issues/52419) | VS Code 拡張の auto-attach が `.claudeignore` / deny を bypass |

`test/agents/test_command_policy.py` の `test_real_bug_*` ケースで、これらの
bypass パターンを hook が確実に block することを保証している。

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

## 動作確認手順

### unit test

```bash
uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q
```

hook は `AGENTS_CONFIG_DIR` で agents 設定ディレクトリを差し替えられるので、
`~/.config` へ apply する前でもリポジトリの `common.toml` に対してテストできる。

### dry-run

```bash
chezmoi diff ~/.claude/settings.json
chezmoi diff ~/.copilot/hooks/from-claude.json
chezmoi diff ~/.copilot/settings.json
chezmoi diff ~/.copilot/permissions-config.json

# 生成結果だけ見たいとき
chezmoi cat ~/.copilot/hooks/from-claude.json
```

### apply 後の hook 動作確認

```bash
# 正常コマンド (PASS)
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git status"}}' \
  | python3 ~/.claude/hooks/check_bash.py

# critical: cd && bypass を block
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cd /elsewhere && git push"}}' \
  | python3 ~/.claude/hooks/check_bash.py
# -> stdout に permissionDecision: deny の JSON が出力される

# format-file: Claude 形式 (file_path) / Copilot 形式 (path) の両方で動く
echo '{"tool_input":{"path":"/path/to/foo.py"}}' | bash ~/.claude/hooks/format-file.sh
```

## 新環境セットアップ

1. `chezmoi init --apply <repo>` で全ファイルが配置される
2. `~/.config/agents/common.toml` を編集して必要な項目を追加
3. `chezmoi apply` で両 CLI 設定が再生成される

なお初回 apply 時、Claude Code が未起動なら `~/.claude/settings.json` は存在しない。
chezmoi modify_ スクリプトは空 stdin を受けると空オブジェクトとして扱い、common.toml
ベースの最小 settings.json (permissions + hooks) を生成する。

## トラブルシュート

| 症状 | 対応 |
| --- | --- |
| apply 後 Claude が `permissions` / `hooks` を読まない | Claude Code は起動時に settings.json を読むので再起動 |
| Copilot CLI で hook の deny が効かない | `~/.copilot/hooks/from-claude.json` が apply されているか確認。`copilot --log-level debug` で hook がロードされているか確認 |
| `~/.config/agents/command_policy.py` が読めない・壊れている | hook が fail-closed で全 bash を拒否する。`~/.config/agents/__pycache__/` を削除して `chezmoi apply` をやり直す |
| common.toml の編集が反映されない | `chezmoi diff` で差分を確認 → `chezmoi apply` |
| `chezmoi diff` が全て「new file」になる | **AI CLI の sandbox 内で実行している**。`~/` が不可視で展開先が空に見えるため。sandbox 外のシェルで実行する |
| `chezmoi` が `chezmoistate.boltdb: read-only file system` で落ちる | `~/.config/chezmoi` が write 許可に入っているか確認 (`copilot_write_allow` / `claude_write_allow`) |
| `uvx` が `os error 30 at ".../uv/tools/.tmpXXXX"` で落ちる | `~/.local/share/uv/tools` が write 許可に入っているか確認 |
