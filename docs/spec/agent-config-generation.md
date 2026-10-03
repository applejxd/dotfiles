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
    modify_private_service.json.py.tmpl      ~/.config/opencode/service.json の port だけ更新 (Windows のみ)
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

## Copilot CLI の既定モデル

`[copilot] model` を `~/.copilot/settings.json` の `model` へ書きます。
apply のたびに上書きするため、TUI の `/model` で変えた既定値は次の apply で
戻ります。一時的に変えるときは `--model` を使います。キーが無ければ既存値に
触れません。

ID は `copilot help config` の候補一覧に無くても、API 側にあれば通ります
（1.0.87 で `claude-opus-5.5` は一覧に無いが `--model` で応答した）。書く前に
`copilot --model <ID> -p 'Reply with exactly: OK'` で確認します。

## MCP サーバ

MCP サーバの定義も `common.toml` の `[[mcp]]` が単一ソース。同じサーバを
CLI ごとに書くと、URL を変えたときに片方だけ古いまま残る。

```toml
{{- if eq (includeTemplate "llm-provider" .) "amazon-bedrock" }}
[[mcp]]
id = "agentcore-websearch"
purpose = "Bedrock AgentCore Web Search で web 検索する"
clis = ["claude", "opencode"]
transport = "stdio"
command = "uv"
args = [
  "run", "--no-project", "--quiet",
  '{{ .chezmoi.homeDir }}/.config/agents/agentcore_websearch_mcp.py',
  "--service", "bedrock-agentcore", "--region", "us-east-1", "--disable-telemetry",
]
{{- end }}
```

| CLI | 生成先 | 生成する仕組み |
| --- | --- | --- |
| Copilot CLI | `~/.copilot/mcp-config.json` | `generate.py --target copilot-mcp` |
| OpenCode V2 | `~/.config/opencode/opencode.json` の `mcp.servers` | `generate.py --target opencode-config` |
| Codex CLI | `~/.codex/config.toml` の `mcp_servers` | `modify_config.toml` が `fromToml` で描画 |
| Claude Code | `~/.claude.json` | `400_unix/410` (Unix) と `300_windows/346` (Windows) が `claude mcp add-json` で登録 |

Gemini CLI と Antigravity は使わないため対象外。既存の定義はそのまま残す。

**Copilot の PC（applejxd）では `[[mcp]]` が 0 件になる。** `deepwiki` は 2026-09-25 に外し、
`agentcore-websearch` は Bedrock の PC だけに出すため。`[[mcp]]` が 1 つも無いと `mcp` キー自体が生えない
ので、参照側は `hasKey` で受けること（`missingkey=error` で描画が止まる）。
deepwiki の代わりの OSS 調査は `oss-research` スキル（インストール済みの実体・配布物・
版を固定したソースに直接当たる）、GitHub の操作は github MCP を使わず
`github-operations` スキル（gh CLI）が担う。

**入れる CLI を絞るには `clis` を書く。** 省略すると 4 つ全部に入る。
`agentcore-websearch` は `clis = ["claude", "opencode"]` にしてある（Copilot は内蔵の
web 検索があり、Codex は使わない）。書ける値は `claude` /
`copilot` / `opencode` / `codex` で、それ以外を書くと apply が止まる。

その結果、**Copilot / Codex 向けのサーバは現在 0 件**である。
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
`.chezmoitemplates/llm-provider` が `amazon-bedrock` を返す PC にだけ
`agentcore-websearch` を出す（Copilot の PC は Copilot CLI 内蔵の web 検索を使う）。

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

### AgentCore Web Search

Bedrock の PC で web 検索を提供する MCP サーバ。Claude Code の内蔵 `WebSearch` は
Anthropic 側のサーバ機能で、Bedrock 経由では使えない
（[Claude Code on Amazon Bedrock](https://code.claude.com/docs/en/amazon-bedrock)）。
OpenCode V2 の内蔵 `websearch` は Exa / Tavily などの別契約が要る。
そこで、AWS 内で完結する AgentCore Web Search を両方に入れる
（[公式ドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html)）。

```text
Claude Code / OpenCode
  └─ stdio ─ ~/.config/agents/agentcore_websearch_mcp.py
               └─ uvx mcp-proxy-for-aws-cli (手元の AWS 認証情報で SigV4 署名)
                    └─ HTTPS ─ AgentCore Gateway ─ Web Search コネクタ
```

| 項目 | 決めたこと |
| --- | --- |
| 対象 | `llm-provider` が `amazon-bedrock` の PC。`clis = ["claude", "opencode"]` |
| リージョン | `us-east-1`（`[provider.amazon-bedrock]` と揃える） |
| Gateway の URL | アカウント固有なのでソースに書かず、環境変数 `AGENTCORE_GATEWAY_URL` から読む |
| 認証 | AWS の既定の認証情報（`AWS_PROFILE` / `~/.aws`）。API キーは無い |
| proxy の版 | `mcp-proxy-for-aws-cli` をラッパーの `PROXY` で固定。依存まで固定した CLI 用の配布物 |
| OpenCode 内蔵の検索 | `[opencode] websearch = false` で消す（v2.0.14 で、設定するとツール一覧から消えることを確認） |

**ラッパーを挟む理由**: proxy は Gateway の URL を位置引数でしか受け取らない。
MCP の定義に URL を書かずに済ませるには、環境変数から読んで渡す層が要る。
ラッパーは Python で書き、`uv run` から起動する（Windows に `python3` が無いため）。
MCP クライアントは `~` を展開しないので、ラッパーのパスは `.chezmoi.homeDir` から絶対パスにする。

**`ocs`（隔離版 OpenCode）では使えない。** Bedrock 自体が `ocs` から届かないのと同じ理由で、
境界が `~/.aws` も Gateway のドメインも開けていない。

#### AWS 側の準備（アカウントごとに 1 回）

リポジトリには CloudFormation を置かない。AWS 公式のサンプル
[aws-samples/sample-agentcore-websearch-agent-skill](https://github.com/aws-samples/sample-agentcore-websearch-agent-skill)
の `cfn/agentcore-websearch.yaml` で、次の 3 つをまとめて作れる。

| リソース | 中身 |
| --- | --- |
| Gateway | 受け付けの認証は `AWS_IAM` |
| Target | `connectorId: "web-search"` のコネクタ |
| サービスロール | Gateway が引き受ける。`bedrock-agentcore:InvokeWebSearch` を持つ |

```bash
aws cloudformation deploy --region us-east-1 --stack-name agentcore-websearch \
  --template-file cfn/agentcore-websearch.yaml --capabilities CAPABILITY_IAM
aws cloudformation describe-stacks --region us-east-1 --stack-name agentcore-websearch \
  --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" --output text
```

サンプルは本番向けではないと明記している。使う前に権限の範囲を見直す。
使う人の IAM には、作った Gateway の ARN に対する
`bedrock-agentcore:InvokeGateway` を付ける。

#### 業務 PC での設定

1. 上で得た URL をシェルの初期化ファイル（リポジトリ管理外）に書く:
   `export AGENTCORE_GATEWAY_URL='https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp'`。
   Windows はユーザー環境変数に設定する
2. `chezmoi apply` で Claude Code へ登録し、OpenCode の設定を生成する
3. 以前の `ddgs` は宣言から消しても登録が残るので、1 回だけ `claude mcp remove ddgs -s user` を実行する
4. 確認: Claude Code の `/mcp` で `agentcore-websearch` が connected になり、`WebSearch` ツールが 1 つ見えること

URL が未設定だとラッパーは理由を stderr に出して終了する（MCP クライアント側では接続失敗として見える）。

#### 料金と制約

- 検索 1,000 回あたり $7。Gateway の呼び出しなどは別に課金される
  （[料金](https://aws.amazon.com/bedrock/agentcore/pricing)）
- `query` は 200 文字以内、`maxResults` は 1〜25（既定 10）
- 返るのは関連部分の抜粋・URL・タイトル・公開日。本文が要るときは `webfetch` と組み合わせる
- 利用条件として、結果を表示するときは出典リンクを残す
- Target 単位でドメインの許可・除外リストを強制できる（エージェント側から解除できない）

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
`[opencode.shell]` に書いた 5 件と、下のスキルのスクリプトだけで、`[bash]` とは共用しない
（`[bash]` は 3 CLI 共通のため、触ると効果の切り分けができなくなる）。

allow の基準は副作用なし・冪等・**任意コード実行を含まない**こと。
`git diff` / `git status` は `.git/config` 経由で任意コマンドを起動できる
ため載せない。

**allow に載せたコマンドは任意ファイル書き込みの手段にもなる。** scanner が
リダイレクトを分割せず resource に残すので、`wc -l f.txt > path` が `wc *`
に前方一致する。allow は最小に保つ以外の守り方が無い。

スキルのスクリプトの allow は `[opencode.skill_scripts]` から出す
（[スキルのスクリプト](#スキルのスクリプト)）。

### 作業ツリーの外の読み取り

作業ツリーの外のパスを `read` / `grep` / `glob` / `edit` で触ると、OpenCode は
その前に `external_directory`（resource は触ったファイルのディレクトリ + `/*`）を
確かめる。既定は `ask` なので、スキルの参照ファイルや隣のリポジトリを読むたびに
確認が出ていた。shell の作業ディレクトリ（`workdir`）が外にあるときも同じ確認が立つ。

次の場所だけ `external_directory` を `allow` にする。

| 出所 | 場所 |
| --- | --- |
| `[opencode.external_read] paths` | スキルの置き場（`~/.claude/skills`・`~/.agents/skills`・`~/.config/opencode/skills`） |
| `[opencode.sandbox] work_read` | 隔離版が読める作業場所（`~/src`・`~/worktrees`・`~/papers`・`~/.local/share/chezmoi`） |

作業場所は隔離版の `work_read` をそのまま使い、二重に並べない
（`opencode_external_read_dirs`）。

- **同じ場所の `edit` は `ask` に戻す。** `external_directory` は read と edit の
  両方の前段なので、allow だけ置くと既定の `{*, *, allow}` で作業ツリーの外へ
  確認なしに書ける
- **`read` の allow は足さない。** `read` は既定で allow なので要らず、足すと
  OpenCode の既定の `*.env` の `ask` を上書きしてしまう
- 規則は `[file]` 由来の read / edit の規則より**前**に置く。秘密のパスの deny
  （`read_deny_globs` / `write_deny_globs`）が後勝ちで効き続ける
- 作業ツリーの中のパスは resource が相対パスになるので、`~/.local/share/chezmoi/*`
  の `edit` の `ask` は、このリポジトリで作業するときの編集には当たらない
  （絶対パスで渡しても相対に直る。実測）
- 隔離版（`ocs`）も既定は `ask` なので同じ規則を出す。`~/` 始まりの read / edit の
  規則は隔離版では捨てるが、この `edit` の `ask` だけは残す
  （捨てると、以前は `external_directory` の確認が止めていた edit が確認なしになる）

実測は [作業ツリーの外の読み取りとスキルのスクリプト](../research/opencode/permission/external-read-and-skill-scripts.md)。

### スキルのスクリプト

スキルが手順に書いたスクリプト（`sdd-docs` の `lint_docs.py` など）は shell の
既定の `ask` に当たり、呼ぶたびに確認が出ていた。`external_directory` の確認は
出ない（shell は引数に書いた外のパスから外部ディレクトリを推定しなかった。
`ls <外のパス>` でも同じ。実測）。
`[opencode.skill_scripts] allow` に載せたスクリプトだけを allow にする
（`opencode_skill_script_rules`）。

```toml
[opencode.skill_scripts]
runners = { py = ["python3"], sh = ["bash"] }

[[opencode.skill_scripts.allow]]
script = "~/.config/opencode/skills/checkpoint/scripts/checkpoint.py"
subcommands = ["paths", "lint", "read"]
```

| 書き方 | 生成する規則 |
| --- | --- |
| `script` だけ | `<runner> <script> *` を allow、`<runner> <script> *>*` と `*<*` を deny |
| `subcommands` | 上の `<script>` の後ろにサブコマンドを足した形を、サブコマンドごとに出す |
| `exact` | `<runner> <script> <引数>` を**完全一致**で allow（`*` を付けない） |

- **スキルの置き場の中に限る。** `script` が `[opencode.external_read] paths` の外か
  `..` を含むと `generate.py` が `apply` を止める。拡張子に対応する `runners` が
  無いときも止める
- shell の resource は生のコマンド文字列で `~` を展開しない。`~/` の形と、展開した
  絶対パスの形の両方を出す。引用符で囲んだパスや、パスを変数に入れた形
  （`S=…; python3 "$S/x.py"`）には当たらず、確認が出る。スキル側は
  `python3 <パス>` とそのまま書く（`sdd-docs` / `checkpoint` の `SKILL.md`。
  `test_skill_docs_call_their_scripts_in_the_allowed_form` が固定する）
- **リダイレクトは deny。** 前方一致の allow はリダイレクトを含む形にも当たり、
  `wc *` と同じく任意書き込みの手段になる。`2>&1` も止まる（止まったら付けずに
  呼び直せばよい）
- **runner に `uv run --no-project python` を使わない。** 作業ツリーの
  `.python-version` に実行ファイルのパスが書いてあると、それを起動する（実測）。
  `python3` は `PATH` の python を使い、作業ツリーの設定を読まない
- **引数で書き込み先や実行するものを決められる形は載せない。** 引数の中身は
  静的な照合では検査できない。`--save <パス>` を `ask` で外そうとしても、
  `'--'save`・`$X`・argparse の省略形（`--sa`）で当たらなくなる（実測）。
  `check_refs.py` は `--save` / `--baseline` のパスを省けるようにし
  （既定はリポジトリのルートの `.tmp/refs-before.txt`）、その形だけを `exact` で
  通す。`checkpoint.py` の `write`（標準入力を引数のパスへ書く）は載せない
- **スクリプトがリポジトリの設定からコマンドを起動しないこと。** `git ls-files` や
  `git check-ignore` は `.git/config` の `core.fsmonitor` を起動する（実測。
  `git status` / `git diff` を shell の allow に載せない理由と同じ）。
  `check_refs.py` と `checkpoint.py` は git を `-c core.fsmonitor=false` 付きで呼ぶ
- コマンド置換（`$(…)` / `` `…` ``）は scanner が中のコマンドを別の resource として
  取り出し、それぞれ照合する。中身が allow でなければ全体が確認になる（実測）。
  変数代入を前に付けた形（`FOO=1 python3 …`）は resource に代入が残り、当たらない
- 隔離版は shell の既定が `allow` なので、この規則を出さない（残すとリダイレクトの
  deny で拒否が増えるだけ）
- 載せてよいかの判断は、引数で書き込み先・実行するもの・送り先を決められないか、
  リポジトリの設定（`.git/config`・`.python-version` など）からコマンドを起動しないか。
  足すときは `test_skill_script_allow_is_not_widened_silently` も更新する

### bypass から呼べる子エージェント

`bypass` のセッションから、同じく全部 allow の子エージェント `bypass-worker`（汎用）と
`bypass-fleet-worker`（`/fleet` の作業役）をサブエージェントとして起動できる。
**ほかのエージェント（`build` など）からは起動できない。** 逆に `bypass` からは、
承認制の子のうち役割が重なる `general` と `fleet-worker` を起動できない。

```toml
[opencode.agent.bypass]
permission = { "*" = "allow", task = { "*" = "allow", general = "deny", fleet-worker = "deny" } }

[opencode.agent.bypass-worker]
mode = "subagent"
permission = { "*" = "allow", task = "deny" }   # task は V2 の subagent

[opencode.agents.bypass-fleet-worker]
mode = "subagent"
system_from = "fleet-worker"
permissions = [
  { action = "*", resource = "*", effect = "allow" },   # 先頭の全 allow が「bypass 専用」の印
  { action = "subagent", resource = "*", effect = "deny" },
  # ... fleet-worker と同じ deny (git の状態を変える操作・question)
]
```

| 呼び出し元 | 起動できる子 |
| --- | --- |
| `bypass` | `bypass-worker`・`bypass-fleet-worker`・`explore`・`review`・`commit` |
| `build` など | `general`・`fleet-worker`・`explore`・`review`・`commit` |

- **`bypass` から承認制の子を外す理由。** `general` / `fleet-worker` は `bypass` から
  起動しても自分の規則で動くので、編集やシェルのたびに確認が出て無確認の前提が崩れる。
  モデルは説明の広い `general` を選びがちでもある。`explore` / `review` は読むだけで
  確認がほぼ出ず、`commit` は確認付きでコミットしたいときの経路として残す
- **deny した子は `subagent` ツールの一覧から消える**（実測）。`/fleet` の指示文は
  「一覧に `bypass-fleet-worker` があればそれ、無ければ `fleet-worker`」で使い分けさせる
- `bypass-fleet-worker` は、`/fleet` の作業役を `bypass` でも無確認で動かすためのもの。
  `system` は `system_from` で `fleet-worker` から写し（`generate.py` が生成時に展開し、
  `opencode.json` には `system` だけを出す。写し元は `system` を直接持つ
  `[opencode.agents]` に限る）、deny は `fleet-worker` と同じものを全 allow の後ろに並べる
  （最後に一致した規則が勝つ）。deny がそろっているかは
  `test_bypass_fleet_worker_keeps_every_fleet_worker_deny` が突き合わせる
- `generate.py` は、全部 allow で
  サブエージェントとして使えるエージェント（`mode` が `subagent` / `all`）ごとに、
  全体の `permissions` の**最後**へ `{ action: "subagent", resource: "<名前>", effect: "deny" }`
  を足す（`opencode_subagent_guards`）。全部 allow とは、V1 の `permission` が `"allow"` か
  `"*" = "allow"` を含むマップ、または V2 の `permissions` の**先頭**が
  `{ action = "*", resource = "*", effect = "allow" }` のもの（`_grants_everything`）。
  数える対象は `common.toml` の `[opencode.agent]` と `[opencode.agents]` の宣言だけで、
  `rules.json` の `guarded_subagents` にも同じ名前を出す（`opencode_guarded_subagents`）。
  全部 allow のエージェントは `bypass_agents` にも入り、誘導の plugin を素通りする
- エージェントの規則は全体の規則の後ろに付き、最後に一致した規則が勝つ。
  `bypass` の `*` の allow はこの deny を上書きする
- **全体の deny だけでは足りない。** `common.toml` に無いエージェント（手で足した
  `build` の上書きや別名のもの）の `permission` は `merge_opencode_agents` が残す。
  そこに `task = "allow"` などがあると、同じ理屈で deny が上書きされる。
  こうした個別の上書きは利用者の責任で、`generate.py` は各エージェントへ deny を
  差し込まない（[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md) の非目的）。
  下の guide plugin の検査は、上書きされた後の effect でも止める
- guide plugin でも起動元を検査する（二重の検査）。`rules.json` の
  `guarded_subagents` に名前を出し、`permission.evaluate` の `action` が `subagent`、
  `resources` がこの一覧に当たり、`agent` が `bypass_agents` に無ければ effect を
  `deny` にする。`agent` が載らない場合も deny（安全側）。`common.toml` に無い
  全部 allow のエージェントも `bypass_agents` に入らないので止まる。
  plugin は一覧が空でなければ登録される（`opencode_guide_server_needed`）。
  プロジェクトの `opencode.json` のように `generate.py` が触らない設定は、こちらだけが守る。
  `rules.json` が読めないときの扱いは[下](#rulesjson-が使えないとき)
- 設定の deny に当たった呼び出しは hook が発火しないので、plugin は deny を
  緩める側には回らない（[Bypass モードの調査 5 章](../research/opencode/permission/bypass-agent.md#5-plugin-は-bypass-を貫通する段階-2-の前提)）
- `bypass` は `mode = "primary"` を明示する。`mode` を宣言しないと既存設定の
  `mode`（`all` / `subagent`）が残り、`bypass` を子として起動できてしまう
  （`build` → `bypass` → `bypass-worker`）。全部 allow のエージェントは `common.toml` で
  `mode` を必ず宣言する（`test_all_allow_agents_in_common_declare_their_mode`）
- `bypass-worker` / `bypass-fleet-worker` 自身は子の起動が deny なので、さらに子を起動できない
  （入れ子にならない）
- 「Always allow」で保存した承認は、設定の deny を上書きしない
- `bypass` と同じく、秘密ファイルの読み取り禁止も外れる。誘導の plugin も
  エージェント名で素通りさせる（下の plugin 層）
- 隔離起動（`ocs`）でも、全体の deny と guide plugin の検査の両方が効く
  （[隔離版の設定の書き出し方](opencode-sandbox.md#エージェントとコマンド)）

実測（全体の deny だけで build からは `Permission denied: subagent`、bypass からは
起動できる、子からの入れ子は不可。build に個別の `task = "allow"` があると全体の deny は
上書きされ、plugin の deny でも、個別の規則の最後に置いた deny でも止まる）は
[Bypass モードの調査 6 章](../research/opencode/permission/bypass-agent.md#6-bypass-からだけ呼べる子エージェント2026-09-28)。
`bypass` から `general` / `fleet-worker` を外した構成と `bypass-fleet-worker` の実測は
同じ調査の [7 章](../research/opencode/permission/bypass-agent.md#7-bypass-の子の入れ替え2026-09-30)。

### plugin 層 (`guide-plugin`)

`~/.config/opencode/guide-plugin/` に置く。判定表は `common.toml` の
`[[opencode.shell.guide]]`・`[opencode.redact]`・`[opencode.ask_description]`・
`[file] read_deny_globs`・`[opencode.agent]`・`[opencode.agents]` から `rules.json` として生成し、plugin は読むだけにする。
`index.js` はこのどれかが有効なら、`tui.ts` は `ask_description` が有効な
ときだけ登録する（`generate.py` の `opencode_guide_server_needed` /
`opencode_guide_tui_needed`）。

| 役割 | 実体 | 登録先 |
| --- | --- | --- |
| 誘導（deny + 代替案）と説明の生成 | `index.js` | `opencode.json` の `plugins` |
| `grep` / `glob` の結果フィルタ | `index.js` | 同上 |
| shell 出力の伏字化 | `index.js` | 同上 |
| 全部 allow の子エージェントの起動元の検査（[上](#bypass-から呼べる子エージェント)） | `index.js` | 同上 |
| 確認画面への説明表示（toast） | `tui.ts` | **`cli.json` の `plugins`** |
| `git commit` の件名と本文の表示（[下](#git-commit-の件名と本文)） | `tui.ts` と `commit-message.js` | 同上 |

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

#### shell ツールの環境変数（git を入力待ちにさせない）

`index.js` は `shell.create.before` で、シェルツールの子プロセスへ次を**未設定のときだけ**
（`??=`）入れる。人の対話シェルには届かない。

| 変数 | 防ぐもの |
| --- | --- |
| `GIT_TERMINAL_PROMPT=0` | TTY が付く経路での資格情報の入力待ち |
| `GIT_EDITOR=false` | `-m` 無しの `git commit`・`rebase -i` などのエディタ起動待ち |
| `GCM_INTERACTIVE=never` | Git Credential Manager の対話（GCM が無ければ無害） |

- 値は `index.js` の `NONINTERACTIVE_ENV` 1 か所。`ocs` の `inner_env` には足さない
  （隔離版の内側も同じ `index.js` を読む）。空文字は設定済みとして残す
- 入れないもの: `GIT_SSH_COMMAND`（git 設定の SSH 指定と衝突）、`EDITOR=true`（成功の偽装）、
  `GIT_SEQUENCE_EDITOR`
- plugin のロード失敗（fail-open）や `rules.json` が全部無効で `index.js` を載せない設定では効かない
- 実測は [E1](../research/agents/noninteractive-git-env.md)。試験は `test_guide_shell_env.py`

#### `rules.json` が使えないとき

plugin のロード（モジュールの評価と `setup`）が例外で失敗すると、OpenCode は
plugin 無しで続ける（fail-open。[plugin API の実測 6 章](../research/opencode/plugin/api-probe.md#6-失敗時の挙動最重要)）。
そのため `index.js` は `rules.json` の読み込みと正規表現のコンパイルを節ごとに
例外から切り離し、ロード自体は必ず通す。壊れた節は `console.error` に記録し、
節ごとに次のように倒す。hook の中の例外は fail-closed なので、そちらは切り離さない。

| 壊れたもの | 扱い | 理由 |
| --- | --- | --- |
| ファイルが無い・JSON でない・オブジェクトでない | 下の全部の節が「壊れた」扱い | — |
| `guarded_subagents` / `bypass_agents` が無い・文字列の配列でない | 子エージェントの起動元を検査しない（止めずに警告） | 一覧が無いと守る子も `bypass` も分からない。全部止めると普段の作業ごと止まる（[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md)） |
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

#### `git commit` の件名と本文

`git commit` の確認ではモデルを呼ばず、コマンドから抜き出した件名と本文を
**確認画面のすぐ上**（TUI のスロット `session.composer.top`）に出す。確認画面は
コマンドを数行で切るので、長いコミットメッセージは本文の途中までしか見えない。
全画面（`ctrl+f`）にしにくいスマホからでも件名を読めるようにする。

```toml
[opencode.ask_description.commit]
enabled = true
line_width = 72   # 本文 1 行の桁数の上限（全角は 2 桁）
max_lines = 8     # 本文の行数の上限
```

```text
feat(opencode): git commit の確認に件名と本文を抜き出して出す   ← 件名（切らない）
- Motivation: git commit の確認画面はコマンドを数行し…          ← 本文（1 行ずつ切る）
- Change: guide plugin がコマンドから件名と本文を抜き…
引数: --allow-empty                                            ← -m 以外の引数
┃  △ Permission required
┃  $ git commit --allow-empty -m 'feat(opencode): …
```

- 件名は 1 つ目の `-m` の 1 行目、本文はそれ以降（`-m` の間の空行は詰める）。
  件名は切らずに折り返す。本文の各行は `line_width` と端末の幅の狭いほうで切る
  （折り返すと狭い画面で行数が倍になり、確認画面のボタンを押し出す）
- `-m` 以外の引数（パス指定やオプション）も 1 行で出す。何がコミットされるかに関わる
- 表示は本体の確認画面と同じ要求を選ぶ（自分と子のセッションの保留の先頭。子の
  セッションを開いているときは出さない）。`commit` エージェントは子で動くが、確認は
  親の画面に出る
- **抜き出せない形は従来のモデルの説明へ倒す。** 引用符の外の `;` `&&` `|` `>` 改行
  （別のコマンドが続き、確認画面で切れた部分に隠れうる）、`$` や `` ` ``（実行時に
  展開される）、`-F` / `-C` / `--fixup` など `-m` 以外からメッセージを取るもの、
  `FOO=1 git commit` や `git -c … commit`
- `index.js` は抜き出せる `git commit` ではモデルを呼ばない（`tui.ts` と同じ
  `commit-message.js` で判定する）。`commit-message.js` を読めなくても `index.js` の
  ロードは通し、従来どおり説明を作る
- スロットの無い版（`2.0.12`）では、同じ内容を toast で出す
- 抜き出しは sh の単語分割の一部を真似たもので、**判定器ではない**。確認画面の
  生コマンドが一次情報であることは変わらない
- 隔離起動（`ocs`）でも出る。モデルを呼ばないので、説明の生成を止める
  `OCS_ISOLATED` の対象にしない（`OCS_ISOLATED=1` と隔離版と同じ形の設定で確認。
  境界の中での表示は未確認）
- 試験は `test/agents/test_guide_commit_preview.py`。実機の画面（45 桁と 100 桁）は
  [ask 画面の調査 12 章](../research/opencode/plugin/ask-description.md#12-v2014-の再確認確認画面のすぐ上に出せる2026-09-30)

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

### 常駐サービスのポート

Windows の常駐サービスだけ `port = 4098` にする（`common.toml` の `[opencode.service]`。
Windows で描画したときだけ現れる）。`merge_opencode_service()` が
`~/.config/opencode/service.json` の `port` だけを書き、`password` などは残す。
Windows 以外では `.chezmoiignore.tmpl` がこのファイルを外し、OpenCode に任せる。

**理由**: 2026-10-02 に WSL と Windows の OpenCode（v2.0.14）がどちらも 127.0.0.1 の
4097 番を常駐サービスに使っていた。WSL と Windows が localhost を共有する構成では、
先に起きた側がポートを握り、もう一方は `Managed service port 4097 ... is already in use`
を繰り返したのち `Timed out waiting for the background service to start` で止まる
（Windows 側の `opencode.exe serve --service` が親の終了後も残っていた）。

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
  試すとそちらが書き換わる（2026-10-02、検証のつもりで `XDG_CONFIG_HOME` だけ
  差し替えて `set port 4098` を実行し、WSL 側も 4098 になって Windows と衝突した。
  `opencode service unset port` で戻した）

### モデルの割り当て

PC ごとにモデルのプロバイダを 1 つに決め、既定モデル・エージェントごとのモデル・
接続設定・他のプロバイダの禁止を `opencode.json` へ出す。
新しいモデルが出たときなどに割り当てを見直す手順は
[モデルの割り当ての見直し](model-lineup-review.md)にある。

#### プロバイダの判定

`.chezmoitemplates/llm-provider` が `apply` のたびに決める。

| 条件（上から順に評価） | プロバイダ |
| --- | --- |
| `chezmoi.toml` の `[data]` に `llm_provider` がある | その値 |
| ユーザー名が `applejxd`（`DOMAIN\applejxd` も含む、大小無視） | `github-copilot`（私用） |
| それ以外 | `amazon-bedrock`（業務用） |

判定の前提は「私用 PC のユーザーは `applejxd`、業務 PC は別名で AWS CLI にログイン
している」こと。どちらでもない PC では OpenCode を使わない。

- **gh のログイン状態は見ない。** 業務 PC でも `gh auth login` していることがあり、
  見分けに使えない。OpenCode の Copilot 接続も `gh` とは別で、`/connect` が要る
- **`~/.aws` の有無も見ない。** 私用 PC にも `~/.aws` ディレクトリだけ存在する
  ことがある（この PC で確認）
- `[data]` ではなくテンプレートで判定するのは、`chezmoi update` が `init` を
  呼ばないため（[CHG-0008](../change/closed/0008-raspi-branching.md)）。
  `[data]` の `llm_provider` は判定を覆したいときの逃げ道

#### 階層

`[opencode.model.tier.<プロバイダ>]` に**階層名 → モデル ID** を書き、エージェントは
階層名で指す。PC が変わってもエージェントの割り当てを書き直さずに済む。
**階層名はモデルの大小ではなく用途で付ける。** どのモデルを当てるかは計測で変わるが、
エージェントがどの用途かは変わらないので、当てるモデルを変えても名前と割り当てはそのまま使える。

| 階層 | 用途 | Copilot | Bedrock |
| --- | --- | --- | --- |
| `default` | 主エージェントの既定 | `claude-opus-5.5` | `global.anthropic.claude-sonnet-5-5` |
| `routine` | 決まった形の短い作業 | `claude-sonnet-5.5#medium` | `global.anthropic.claude-sonnet-5-5#low` |
| `worker` | 実装などを任せる作業役 | `claude-sonnet-5.5#medium` | `global.anthropic.claude-sonnet-5-5#medium` |
| `deep` | 難しい判断・設計 | `claude-opus-5.5#xhigh` | `global.anthropic.claude-opus-5-5#high` |
| `second_opinion` | 別系統のモデルでの確かめ | `gpt-6-astra` | `global.openai.gpt-6-sol` |

割り当て（`[opencode.model.agents]`）は `commit = "routine"`・`review = "second_opinion"`・
`fleet-worker = "worker"`。

- **`routine` と `worker` は今は同じモデルだが、分けておく。** 名前は用途なので、
  どちらかの計測結果が変わったときに片方だけ差し替えられる
- **`routine`（`commit`）は Sonnet 5.5。** `commit` を haiku で動かすとメッセージの書式が崩れ、
  `claude-sonnet-5` ではそろった（[記録 E4 / E5](../research/opencode/commit-review-agents.md)）。
  Copilot の `claude-sonnet-5.5#medium` は `claude-opus-5.5#medium` と同等にコミット・書式がそろい、
  速く単価も半分で、`claude-sonnet-5` より `git commit` 以外の確認が少なかった（記録 E6）。
  effort を low / high にしても、コミット・書式・確認に差は無かった
  （[階層のモデルの計測](../research/opencode/tier-models.md)）
- **`worker`（`fleet-worker`）も Sonnet 5.5。** 小さな実装・バグ修正・リファクタリングなどの
  課題では、`claude-opus-5.5` と `claude-sonnet-5.5` の low / medium / high の合格率に差が無く、
  sonnet の medium は opus の medium の約 2/3 の時間で終わった。`claude-haiku-4.5` は
  難しめの課題で 0/4、担当外にファイルを残し、手数が多いぶん Bedrock の単価での試算も
  sonnet 5.5 より高かった（[階層のモデルの計測](../research/opencode/tier-models.md)）。
  Bedrock の値は Copilot で近似した判断で、Bedrock 上では未確認
- **effort はプロバイダの予算で分ける。** Copilot（使い放題）は質と待ち時間で選び、`routine` も
  `worker` も `medium`。Bedrock（予算が有限）は、effort で差が出なかった `routine` を `low` にして
  費用を削り、`worker` は `medium`。公開のベンチマークでも、effort の差は難しいコーディングの課題で
  1 段あたり 1〜3 ポイント程度（[階層のモデルの計測](../research/opencode/tier-models.md)の追記）。
  Bedrock の Sonnet 5.5 に effort を付けられることは、利用者が確かめた
- **`deep` は計測していない。** 良し悪しを機械的に採点できる課題を作れないため、
  opus の上位の effort のまま
- **Bedrock の `default` は Sonnet 5.5 のまま（再考の候補あり）。** 上位モデルを低い effort で
  使うほうが、仕事 1 件あたりの費用で得になる場合がある（公式の資料）ので、Opus 5.5 の `low` を
  候補として記録した。同じ条件での比較が無く、主エージェントに effort を付けられるかも未確認
  （[階層のモデルの計測](../research/opencode/tier-models.md)の追記）
- `default` を割り当てに使わないのは、Copilot の `default` はバリアントが付けられず
  （下記）ほかの階層と推論の強さが変わるのと、既定モデルを変えたときに子エージェントまで
  変わらないようにするため。Bedrock では今は `routine` / `worker` と同じモデルで、effort だけが違う

```toml
[opencode.model.agents]
explore = "worker"      # 例
```

- **どのプロバイダにも同じ階層名をそろえる**（`test_every_provider_defines_the_same_tiers`）
- ID は [models.dev](https://models.dev) の一覧か TUI の `/models` で実在を確かめてから
  書く。Bedrock の `global.` はクロスリージョン推論プロファイル
- **`default` に `#variant` は付けられない。** 既定の `model` はバリアントを
  保持しない（公式）。付けると `apply` を止める
  - Copilot の `default` を「Opus 5.5 の high」にしたかったが、手段が無かった。
    モデル単位の `settings.reasoningEffort`・別名モデル・`context` hook の
    どれで入れても、効くのは 1 回目の呼び出しだけで、ツール結果を受けた 2 回目
    以降（`/v1/messages`）では推論の強さが送られない
    （[実測 記録 E2](../research/opencode/agent-models.md#記録-e2--2026-09-28-既定モデルに推論の強さを持たせられるか)）
  - そのため Copilot の `default` はバリアントなし（強さは Copilot 側の既定。
    どの強さかは未確認）。high で動かしたいセッションは TUI でバリアントを選ぶ
- 未知の階層・プロバイダ、`[opencode.agent]`（V1 形式）にあるエージェントへの
  割り当ても `apply` を止める。後者は V1 の `agent` と V2 の `agents` に同じ ID が
  並んだときの結合順を確かめていないため
  - 改名前の階層名（`light` / `standard` / `heavy`）で割り当てても、未知の階層として止まる。
    エラーには定義済みの階層名が並ぶ

#### 生成されるもの

| キー | 中身 | 残すもの |
| --- | --- | --- |
| `model` | `default` 階層 | — （毎回書く） |
| `agents.<id>.model` | 割り当てた階層 | 割り当てを外したとき、値が階層のモデルなら消す。手で書いた別のモデル・他のキーは残す |
| `providers.<id>.settings` | `[provider.<id>]` の `profile` / `region` | 他のキー（`baseURL` など）と他のプロバイダ |
| `experimental.policies` | `provider.use` を `*` で deny、この PC のプロバイダだけ allow | `provider.use` 以外の文と、`experimental` の他のキー |

- **V1 形式の `agent` ではなく V2 形式の `agents` に書く。** `agent` だと
  `#variant` 付きの指定が黙って無視され、親のモデルで動く
  （[実測](../research/opencode/agent-models.md)）
- **policies はグローバル設定がプロジェクト設定に勝つ**ので、リポジトリの
  `.opencode/opencode.json` から別のプロバイダを有効にされない
  （[policies の優先順位](../research/opencode/permission/gaps.md#他の経路2026-09-23-追加実測)）
- Bedrock は `profile` か認証の環境変数が無いと**有効にならない**（region だけでは
  足りない。公式）。常駐サービスへシェルの `AWS_REGION` が渡る保証も無いので、
  `profile = "default"` と `region = "us-east-1"` を設定に書く

#### 効かない使い方

**主エージェント（`build` / `plan` など）の `model` は、エージェントを選んだだけでは
使われない。** セッションのモデルは別に保存されていて、`--agent plan` で起動しても
既定モデルのまま動く（[実測](../research/opencode/agent-models.md)。公式の記述どおり）。
子エージェント（`explore` など）の `model` は効く。

主エージェントを重いモデルで動かしたいときは、`agent:` を指定したスラッシュコマンドを
経由させる（公式ではコマンドで選んだエージェントの `model` が呼び出し時のモデルに勝つ。
未実測）。

#### 隔離起動（`ocs`）

`ocs` の既定モデルは `[opencode.sandbox] model_preference` が決め、ここの `default` は
使わない（通常版から引き継ぐのは `model` だけ）。エージェントごとの割り当ては、この PC の
プロバイダが `[opencode.sandbox] providers` にあるときだけ隔離版にも出す
（[隔離版の設定の書き出し方](opencode-sandbox.md#エージェントとコマンド)）。
**Bedrock は `ocs` では使えない**
（コードから判断。実機では未確認）。境界の内側から `~/.aws` が読めず
（開けていない）、AWS の資格情報の環境変数も落とすため（`ocs` の `inner_env`）。
`[provider.amazon-bedrock] network_allow` は用意してあるが、`providers` には入れていない。

### 子エージェント

`[opencode.agents.<id>]` に V2 形式でエージェントを定義し、`opencode.json` の
`agents` へ出す。モデルは書かず、[`[opencode.model.agents]`](#モデルの割り当て) で
階層を割り当てる（PC ごとのプロバイダで ID が変わるため）。

| ID | 階層 | 役割 | 権限で塞ぐもの |
| --- | --- | --- | --- |
| `commit` | `routine` | 変更を論理単位に分け、パスを指定してステージし、単位ごとにコミットする。`git commit` は権限の確認（`ask`）を通す | 編集・質問・子エージェントの起動・作業ツリーを戻す git・リダイレクトと `--output`・`git commit` の検証の回避や `-a` / `--amend`（下記） |
| `review` | `second_opinion` | 別系統のモデルで、設計案・差分・調査結果の欠陥を指摘する | 編集・shell・質問・子エージェントの起動 |

- **`commit` は `git commit` の確認を承認の場にしてコミットする。** 質問のツールは
  使えないが、`git commit *` を `ask` にしているので、コミットの前に確認が出る
  （確認で「常に許可」を選んだプロジェクトでは出ない。下記）。
  commit スキルの「コミット前の承認」はこの確認で満たす（`system` がそう定め、スキルの
  手順 4 がその上書きを認める）。確認が拒否されたらそれ以降はコミットせず、ステージ内容・
  メッセージ・残りの単位の案を返して終わる。狙いは、差分を読む重い作業を安いモデルへ移し、
  親の文脈を節約すること
- **`commit` には確認画面が見えない。** ツール結果に承認の痕跡が残らないため、`system` で
  確認の有無を推測して報告することを禁じている。また shell は 1 回の応答で 1 つだけ呼ばせる。
  同じ応答に並べた呼び出しは前の完了を待たずに走り、コミット後の確かめがコミットの途中で
  走った（[記録 E7](../research/opencode/commit-review-agents.md#記録-e7--2026-10-02)）
- **`review` は shell を開けない。** `git diff` / `git status` も外部の diff
  ドライバや fsmonitor を通じてコードを実行しうる
  （[allow リスト監査](../research/opencode/permission/allow-list-audit.md)）。
  差分は親が依頼文に含めて渡す
- 書けるキーは `description`（必須）/ `mode` / `system` / `permissions` / `steps` /
  `hidden` / `color` / `disabled`。`model` と V1 形式のキー（`permission` など）は
  `apply` を止める。V1 の `[opencode.agent]` と同じ ID も止める
- `system` は組み込みの基底プロンプトを**置き換える**（公式）。`AGENTS.md` や
  スキルの一覧は引き続き足される
- `permissions` は全体の規則の後ろに付き、後勝ちで効く。効果は `allow` / `ask` / `deny`。
  隔離版で全体から捨てた `git commit` の `ask` も、`commit` の中では戻る
- 宣言したキーだけを差し替え、他のキーと他のエージェントは残す
- 隔離起動（`ocs`）にも同じ定義が出る。通常版の `opencode.json` からは引き継がず、
  `common.toml` から作る（[隔離版の設定の書き出し方](opencode-sandbox.md#エージェントとコマンド)）

#### `commit` の権限

素の `git status` / `git diff` / `git log` とパス指定のステージだけを `allow` にし、
`git commit` 本体は `ask` にする。目的は**うっかりの防止**で、意図的な迂回への耐性は求めない。
通常起動でも隔離起動（`ocs`）でも同じ規則が効く（[実機確認](../research/opencode/commit-review-agents.md)の記録 E2 / E4）。

| 順 | 効果 | 規則 | 理由 |
| --- | --- | --- | --- |
| 1 | `deny` | `edit` / `subagent` / `question` の `*` | 編集・子エージェントの起動・質問をさせない |
| 1 | `deny` | `git checkout *` / `git reset *` / `git stash *` / `git clean *` | 作業ツリーと index を戻させない |
| 2 | `allow` | `git status *`・`git diff *`・`git log *`・`git branch --show-current`・`git rev-parse --show-toplevel` | 状況の把握。commit スキルが教える形そのまま（ルートは承認時の提示でリポジトリ名に使う） |
| 2 | `allow` | `git add -- *` | `--` の後ろはパスだけになる |
| 2 | `allow` | `git restore --staged -- *` | ステージの取り消し。作業ツリーは戻さない |
| 3 | `deny` | `*>*`・`*--output*` | allow の形に付けたファイルへの書き出し |
| 4 | `ask` | `git commit *` | 承認の場。3 の `deny` より後ろなので、メッセージに `>` を含んでも確認に回る |
| 5 | `deny` | `* --no-verify*`・`git commit -n*`・`git commit -a*`・`git commit --all*`・`git commit --amend*`・`git commit * --amend*`・`git -* commit *` | 検証の回避・無関係な変更の混入・既存コミットの書き換え・オプションを前に置いた形 |

- **作法はスキル、実行環境の仕組みはエージェントが持つ。** 分け方・メッセージの書式・
  コマンドの形は commit スキルに従わせ、`system` には OpenCode の中でだけ要ること
  （確認が承認の場になること・read / glob / grep ツールで読むこと・`-m` を重ねてヒアドキュメントと
  `-F` を使わないこと・連結とリダイレクトをしないこと・拒否と hook の失敗での止まり方）だけを書く。
  allow の形はスキルが教える素の形に合わせてあり、`test_skill_forms_are_allowed_or_asked_in_the_commit_agent`
  が固定している
- **スキルの承認の原則は変えない。** 既定は「提示して承認を得る」のまま（Copilot は hook の
  `ask` を自動承認するので、環境の確認を当てにしない）。呼び出し元の指示が `git commit` の
  確認を承認の場と定めたときだけ、それに従う（手順 4 の冒頭）。この上書きを手順 4 の後ろに
  置いた版では、`claude-haiku-4.5` は提示して返るだけでコミットしなかった（記録 E4）
- **メッセージは、任せる前に利用者へ全文を見せる。** 確認画面はメッセージが長いと途中で切れ、
  スマホなどでは全画面（`ctrl+f`）にしにくい。親は任せる前にメッセージ全文を利用者に示して
  承認を得て、承認済みの全文を渡す。`commit` は渡された全文を一字も変えずに使い、確認画面では
  件名の一致だけを見ればよい。渡されなかった単位だけ、スキルに従って自分で作る
  （スキルの手順 4 とエージェントの `system` に同じ趣旨がある）
- **`claude-haiku-4.5` では書式が崩れやすいので、`commit` には使わない。** コミットまでは 9/10 で
  進むが、本文の `- Motivation:` / `- Change:` / `- Impact:` は 17 件中 2 件にとどまった（記録 E4）。
  `routine` 階層の Sonnet を当てる。Copilot の PC は `claude-sonnet-5.5#medium` で、10/10 がコミットし、
  3 行は 16 件中 15 件、`git commit` 以外の確認と誘導は 0 回。承認済みの全文を渡した 3 回は
  4 件とも一字も変わらなかった（記録 E6）。Bedrock の PC も `claude-sonnet-5-5` にした（Copilot の
  Sonnet 5.5 で近似した判断で、Bedrock 上では未確認）。1 世代前の `claude-sonnet-5` では 10/10 がコミットし、
  3 行は 14 件中 14 件そろった（記録 E5 / E6）。
  `claude-sonnet-5` では、`system` に「確かめも 1 つずつ」「`cd` ではなく `workdir`」を足した後、`cd … &&` の誘導は
  1 回の依頼あたり 1.7 回から 0 回、`git status --short; echo ---; git log …` のような連結による
  `git commit` 以外の確認は 0.8 回から 0.3 回に減った（記録 E6）
- **全体の規則は変えない。** 全体の `allow` から `git diff` / `git status` を外した判断
  （[allow リスト監査](../research/opencode/permission/allow-list-audit.md)）はそのままで、
  素の形を確認なしで通すのは `commit` の中だけ。`git add -A` / `git add .` / `git switch` /
  `git rm` はエージェントの規則に当たらず全体の規則に落ちる（通常起動は `ask`、隔離起動は `allow`）。
  `git restore`（`--staged --` 以外）と `git push` は全体の `deny` で止まる
- **接頭辞（`git -c core.fsmonitor=false -c core.hooksPath=/dev/null` と `--no-ext-diff --no-textconv`）は
  付けない。** 以前はこの接頭辞の形だけを allow にしていた（記録 E2 / E3）。やめた理由:
  - 接頭辞が止めるリポジトリの設定（fsmonitor・外部 diff・textconv・index の更新で走る hook）は
    `.git/config` か `~/.gitconfig` にしか書けず、clone では運ばれない
  - エージェントによる `.git/config` の書き換えは別に塞いである（通常起動は `edit` の `deny`、
    隔離起動は境界）
  - `git commit` では確認の後にリポジトリの hook を走らせており、コミットの時点でその設定は
    既に信頼している
  - 接頭辞はモデルの取り違え（記録 E3）を生み、スキルの形とも合わない
- **受け入れたこと**: `commit` の中では、`git status` / `git diff` がリポジトリの設定の
  fsmonitor・外部 diff・textconv・`post-index-change` hook を確認なしで起動しうる。
  `git diff --no-index` でリポジトリの外のファイルを読むこともできる
- `git -* commit *` の `deny` は隔離起動のために要る。隔離版の全体の規則はシェルの既定が
  `allow` なので、これが無いと `git -c core.hooksPath=/dev/null commit …` が確認も hook も
  無しで通る
- `git restore *` の `deny` はエージェントに置かない。置くと後ろの `restore --staged -- *` の
  `allow` と順序で競うだけで、素の `git restore` は全体の `deny` で止まる
- `--amend` は `deny` にした。直前のコミットは利用者のものかもしれず、hook の失敗で
  やり直すときも新しいコミットで足りる
- **残る穴**:
  - clean フィルタ（`filter.<driver>.clean`）は `diff` / `add` で走り、`status` でも index の
    更新時に走りうる（接頭辞を付けていたときも止めるオプションは無かった）
  - `git add -- .` はパス指定の形なので `allow` に当たり、まとめてステージできる。
    確認に出るのは `git commit` のメッセージだけなので、混入はスキルの指示と確認の目視に頼る
  - 静的な照合なので、引用符や変数で書き換えた形（`g"it" commit` など）は照合を
    すり抜ける（[静的パターンの回避](../research/opencode/permission/shell-allow-and-plugin-gate.md)）
  - 確認で「常に許可」を選ぶと `git commit *` がプロジェクトに保存され、以後は
    確認なしでコミットする（保存した承認は `ask` を `allow` に変えるが、`deny` は
    上書きしない。実測）
  - メッセージの中に空白に続けて `--no-verify` や `--amend` を書いたコミットも `deny` になる
- **無人の実行では `git commit` で止まる。** `opencode run --auto` は子セッションの
  確認を自動承認しないので、`commit` は allow の形の操作を終えたところで確認を待ち続ける
  （記録 E2）。TUI で子セッションの確認が表に出るかは未確認

### 並列作業（`/fleet`）

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
  ほかからは `fleet-worker` だけが `subagent` ツールの一覧に載る。指示文は一覧を見て
  使い分けさせる
- **取りまとめは今のセッションで動かす（`subagent = false`）。** 子エージェントは
  さらに子を起動できない（既定の入れ子は 1 段）。子にすると作業役を起動できない
- **作業役は同じ作業ツリーを共有する。** 衝突は、親が担当ファイルを重ねずに
  割り当てることで避ける。作業役には git の状態を変える操作（`add` / `commit` /
  `stash` / `checkout` / `switch` / `restore` / `reset`）を権限で禁じる
- **編集とシェルは全体の規則のまま。** 通常起動では作業役のシェルは確認が出る。
  無人の実行（`opencode run --auto`）では子セッションの確認に答えられず止まる
  （[commit エージェントの実機確認](../research/opencode/commit-review-agents.md)）。
  隔離起動（`ocs`）はシェルの既定が `allow` なので、個別の deny / ask に当たる操作以外は
  確認が出ない（[隔離版のエージェントとコマンド](opencode-sandbox.md#エージェントとコマンド)）
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
- コマンドは、コマンド用のディレクトリではなく設定の `commands` に出す。
  スキルでは `~/.config/opencode/skills` が実際には走査されなかった実測があり
  （[文脈の引き継ぎ](checkpoint.md)）、同じ置き場の扱いを当てにしない
- `[opencode.commands.<name>]` に書けるキーは `template`（必須）/ `description` /
  `agent` / `subagent`。**`template` に「`!` + バッククォート」は書けない**
  （展開時にシェルとして権限の確認なしに実行されるため。`apply` を止める）

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
