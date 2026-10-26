# AI CLI 設定の生成と所有権

`common.toml` をどう書き、`generate.py` などがそれを各 CLI の設定ファイルへ
どう展開するか (どのキーを置き換え、どれを合算・保持するか) をまとめる。
全体像は [AI CLI 統合 permission / hook 管理](agent-permissions.md)、
判定の中身は [コマンド・ファイルの判定](guard/agent-command-policy.md)、
sandbox は [sandbox (Claude Code / Copilot CLI)](sandbox/agent-sandbox.md) を参照。

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
home/dot_claude/hooks/                       Python 版の判定器。Claude / Copilot への登録は撤去済みで
                                             実行時は呼ばれず、TS の判定器の正解データの書き出し元
                                             (オラクル) として残る ([CHG-0035](../change/0035-retire-python-judge-oracle.md))
    executable_check_bash.py                 入出力とループのみ (fail-closed)
    executable_decide.py                     判定 API (decide) の入口
    lib/policy_loader.py                     command_policy の import と設定ディレクトリの解決
    lib/bashrules/                           bash コマンド検査ルールの本体
        __init__.py                          DENY / ASK の登録簿 (評価順の正本)
        tables.py                            判定の表 (pi/harness/judge/tables.toml) の読み込み
        _shared.py                           共通ユーティリティ・ポリシー層の参照
        policy.py                            common.toml の deny / ask を照合
        sensitive.py  http.py  ghapi.py      関心事ごとの判定
        rm.py  docker.py                     同上
        rules_exec.py  rules_guard.py        同上
        rules_files.py                       同上
    executable_check_file_read.py            ファイル読み取りを遮断 (fail-closed。判定器側)
    executable_redirect-tmp.py               /tmp 利用を ./.tmp へ誘導 (判定器側)
    executable_markdownlint.sh               Markdown の lint (pi のフルガードが edit / write の後に呼ぶ)
    executable_format-file.sh                拡張子別のフォーマッタ実行 (同上)
home/dot_copilot/
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

経緯をファイル側に書くと値を探しにくくなるので分離した
（[経緯](../research/agents/agent-config-generation-notes.md)）。

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
  [`allow` の粒度に注意](guard/agent-command-policy.md#allow-の粒度に注意))
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
[[mcp]]
id = "agentcore-websearch"
purpose = "AgentCore Web Search で web 検索する (Gateway の URL がある機だけ)"
clis = [{{ if eq (includeTemplate "is-work" .) "true" }}"claude", "opencode", "pi"{{ else }}"pi"{{ end }}]
requires_env = "AGENTCORE_GATEWAY_URL"
transport = "stdio"
command = "uv"
args = [
  "run", "--no-project", "--quiet",
  '{{ .chezmoi.homeDir }}/.config/agents/agentcore_websearch_mcp.py',
  "--service", "bedrock-agentcore", "--region", "us-east-1", "--disable-telemetry",
]
```

| CLI | 生成先 | 生成する仕組み |
| --- | --- | --- |
| Copilot CLI | `~/.copilot/mcp-config.json` | `generate.py --target copilot-mcp` |
| OpenCode V2 | `~/.config/opencode/opencode.json` の `mcp.servers` | `generate.py --target opencode-config` |
| Codex CLI | `~/.codex/config.toml` の `mcp_servers` | `modify_config.toml` が `fromToml` で描画 |
| Claude Code | `~/.claude.json` | `400_unix/410` (Unix) と `300_windows/346` (Windows) が `claude mcp add-json` で登録 |
| pi（Unix・Windows） | `~/.config/pi/harness/rules.json` の `mcp` | `generate.py --target pi-harness`。フルガードが起動のたびに `registerMcpServer` で登録する（[pi のガード](guard/pi-guard.md#mcp)。`mcp.json` へ書く経路は無い。[経緯](../research/agents/agent-config-generation-notes.md)） |

Gemini CLI と Antigravity は使わないため対象外。既存の定義はそのまま残す。

**`[[mcp]]` の任意のキー `exposure`（pi だけに効く）**: モデルへのツールの見せ方で、`direct` / `codemode` / `deferred` / `hidden`（不正な値は生成が止まる）。
**省略すると pi には `direct` を出す。** pi 本体の既定は `codemode` だが、`pis` は `-ne` で組み込みの `codemode` / `tool_search` を外すので、
既定のままだとツールがモデルから呼べない（[実測 E6](../research/agents/pi-extension-under-harness.md#記録-e6--2026-10-11)）。
`direct` はツール定義が常駐する（1 ツールで数十トークン）ので、大きいサーバを足すときは、そのサーバだけ `deferred` などに変えて試す。
他の CLI の定義には `exposure` を混ぜない。`pis` では MCP のツールは役割の既定（実装役は確認）になる。

`agentcore-websearch` は全機に配る（使うかは実行時に決まる。下の「AgentCore Web Search」。`deepwiki` は外した。[経緯](../research/agents/agent-config-generation-notes.md)）。
`[[mcp]]` が 1 つも無いと `mcp` キー自体が生えないので、参照側は `hasKey` で受けること（`missingkey=error` で描画が止まる）。
deepwiki の代わりの OSS 調査は `oss-research` スキル（インストール済みの実体・配布物・
版を固定したソースに直接当たる）、GitHub の操作は github MCP を使わず
`github-operations` スキル（gh CLI）が担う。

**入れる CLI を絞るには `clis` を書く。** 省略すると 5 つ全部に入る。
`agentcore-websearch` は、会社 PC（`is-work`）では `clis = ["claude", "opencode", "pi"]`、個人の機では `["pi"]` にしてある
（家で、動かない MCP を Claude Code・OpenCode に登録しないため。Copilot は内蔵の web 検索があり、Codex は使わない）。書ける値は `claude` /
`copilot` / `opencode` / `codex` / `pi` で、それ以外を書くと apply が止まる。

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
`.chezmoitemplates/is-work` で、`agentcore-websearch` を入れる CLI の一覧を切り替える
（[会社 PC の判定](#会社-pc-の判定)）。

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
| 対象 | **全機に配る**（会社 PC で Copilot を使うので、`llm-provider` では切らない）。使うかは実行時に決まる（下の「使えない機」）。`clis` は会社 PC が `claude` / `opencode` / `pi`、個人の機が `pi` |
| リージョン | `us-east-1`（`[provider.amazon-bedrock]` と揃える） |
| Gateway の URL | アカウント固有なのでソースに書かず、環境変数 `AGENTCORE_GATEWAY_URL` から読む |
| 認証 | AWS の既定の認証情報（`AWS_PROFILE` / `~/.aws`）。API キーは無い |
| proxy の版 | `mcp-proxy-for-aws-cli` をラッパーの `PROXY` で固定。依存まで固定した CLI 用の配布物 |
| OpenCode 内蔵の検索 | `[opencode] websearch = false` で消す（v2.0.14 で、設定するとツール一覧から消えることを確認） |

**使えない機（家など、URL も AWS の認証も無い機）**: 失敗させず、**ツールの無い空の MCP サーバ**になる（ラッパーが stdio で `initialize` / `tools/list` などに空で答える）。
起動の失敗が毎回の通知になるのを避け、「家で設定されても、認証しなければ何も起きない」を実現する。空になるのは、`AGENTCORE_GATEWAY_URL` が無い・`https://` でないとき、
pi のサンドボックスの内側（`PI_HARNESS_BOUNDARY=1`。内側では AWS の認証情報を使えない）のとき。
Unix の pi のフルガードは、`[[mcp]]` の `requires_env`（`AGENTCORE_GATEWAY_URL`）が空の機では、そもそも登録しない（プロセスも起動しない）。
**`pis` の内側で AgentCore を使うには、ブローカーでの中継が要る**（Bedrock のブローカー（段 U7b）の後。[CHG-0037](../change/0037-pis-usability-and-telemetry.md)）。
それまで、会社 PC の `pis` の内側では使えない（境界なしの `pi` か、Windows の素の `pi` では使える）。**未確認**: 起動失敗時の pi の挙動、Windows の `uvx`、内側の環境変数に `PI_HARNESS_BOUNDARY` が伝わるか。

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

#### 制約のある環境の機での設定

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

## pi と共有する設定（`[opencode.*]` に書き、pi も読む）

`common.toml` の `[opencode.*]` に書くキーのうち、**pi も読むもの**（`[pis.broker]`・`[pi.confirm]`・モデルの割り当て・スキルのスクリプト・作業ツリーの外の読み取り・コミットの確認など）の生成の仕様。pi の正本は `[pi]` / `[pis]`。

> OpenCode だけが使う設定（plugin 層・bypass から呼べる子エージェント・キーバインド・隔離起動 `ocs` など。保留中のレガシーで、撤去予定。CHG-0020 段 6 は保留中）は [OpenCode 向けの設定の生成](opencode-config-generation.md) へ移した。3 層との対応と Claude / Copilot との扱いの差は [OpenCode V2 の扱い](agent-permissions.md#opencode-v2-の扱い)。

### Copilot ブローカーの設定（`[pis.broker]`）

`common.toml.tmpl` の `[pis.broker]`（`copilot` は `off` / `auto` / `http://127.0.0.1:<port>`。`github` 系は [GitHub ブローカー](sandbox/fence-boundary.md#github-ブローカーpis-のみ)）は、
`build_pi_harness` が `rules.json` の `broker.copilot` へ出し、`pis` が起動時に読む。
未知のキーは拒否、省略時は `off`。値の厳密な検証（URL の形）は起動時に `pi.py` が行う。
意味と振る舞いは [fence-boundary.md](sandbox/fence-boundary.md#copilot-ブローカーpis-のみ)。

### 確認表の設定（`[pi.confirm]`）

`common.toml.tmpl` の `[pi.confirm]`（`bash`: 前方一致の文字列の配列、`checks`: 確認に格上げする検査の名前、`timeout_seconds`: 確認の待ち時間、既定 300）は、
`pi_confirm`（`generate.py`）が検証して `rules.json` の `judge.common.pi.confirm` へ出す。`checks` の各要素は `judge/checks.ts` の ask の検査の名前に実在すること
（生成時に検証）、`timeout_seconds` は 10〜3600 の整数、未知のキーは拒否、省略すると空の表。意味と振る舞いは [pi-decide.md の confirm](guard/pi-decide.md#confirm)。

### pi と共有する節

次の 5 つは `[pi]` が正本で、pi のフルガードの判定器と OpenCode の生成の両方が読む（移行の計画は
[CHG-0020](../change/0020-pi-migration.md)）。

| `[pi]` の節 | 中身 | OpenCode での位置 |
| --- | --- | --- |
| `[pi.shell] allow` | 無確認で実行してよい shell コマンド（[既定は `ask`](opencode-config-generation.md#既定は-ask)） | `[opencode.shell] allow` |
| `[pi.redact]` | shell 出力の伏字化（[shell 出力の伏字化](opencode-config-generation.md#shell-出力の伏字化)） | `[opencode.redact]` |
| `[pi.external_read]` | 作業ツリーの外で確認なしに読める場所（[作業ツリーの外の読み取り](#作業ツリーの外の読み取り)） | `[opencode.external_read]` |
| `[pi.skill_scripts]` | 確認なしに実行できるスキルのスクリプト（[スキルのスクリプト](#スキルのスクリプト)） | `[opencode.skill_scripts]` |
| `[[pi.guide]]` | 誘導（[判定 API の誘導](guard/pi-decide.md#誘導)） | `[[opencode.shell.guide]]` の `pi = "<id>"` の位置 |

- `generate.py` は `common.toml` を読んだ直後（`load_common`）に、`[pi]` の値を OpenCode の位置へ写す
  （`resolve_pi_shared`）。OpenCode の生成の処理は写した後の位置を読むので、出力は写す前と同じ
- **OpenCode 側に同じキーを書くと生成を止める。** 2 か所に書くとどちらが効くか分からなくなる
- OpenCode を撤去するとき（CHG-0020 の段 6）に、写す処理ごと消す
- `[[pi.guide]]` は、OpenCode 側の一覧の `pi = "<id>"` を中身に置き換える（並びの位置は OpenCode 側が決める）。
  無い id や、`pi` と一緒に他のキーを書いたものは生成を止める
- 試験は `test_pi_shared.py`。描画した `common.toml` の `[opencode]` に 4 つが残っていないことも固定する

> OpenCode 専用の設定（plugin 層・bypass から呼べる子エージェント・キーバインド・隔離起動 `ocs` など）は [OpenCode 向けの設定の生成](opencode-config-generation.md) へ移した。この節には、pi と共有する設定だけが残っている。

### deny の例外（`.env.example` など）

`.env.*` は deny（read / edit とも。`.env` と同じ）にし、サンプルの `.env.example` /
`.env.sample` / `.env.template` だけを `[[file.deny_exceptions]]` で例外にする。
**例外は対の deny glob とセットで宣言する**（`deny` に `read_deny_globs` /
`write_deny_globs` の項目と同じ文字列、`except` に例外の glob）。例外は**その deny にだけ**
効き、`.ssh/**` や `*secret*` など別の deny に当たるパスは、例外に当たっても deny のまま
（`~/.ssh/.env.example` は deny、`app/.env.example` は allow、`app/.env.local` は deny）。
`deny` が deny の一覧に無いと生成を止める（対の相手が無い例外は黙って効かないため）。

| CLI | 例外の表現 |
| --- | --- |
| OpenCode | 例外のある deny を deny の先頭に出し、**その直後**に例外の allow を置く。後勝ちなので、後ろの別の deny が例外に勝つ（`test_deny_exceptions_sit_right_after_their_paired_deny` / `test_dotenv_variants_are_denied_except_examples`）。例外の allow はそれより前の ask（作業ツリー外の edit の確認など）も潰すので、**ask と例外の交差を ask として直後に戻す**（`~/.claude/skills/*` の ask と `*/.env.example` から `~/.claude/skills/*/.env.example` など。`wildcard_intersection`。`*` が 2 個以上・`?` を含むなど交差を作れない形は生成を止める）。隔離版（`ocs`）の規則の整理でも、開けた場所の edit の ask として残す |
| OpenCode の guide plugin | `rules.json` の `read_deny_except`（`{deny: [正規表現], except: [正規表現]}`）。`grep` / `glob` の結果フィルタと shell 出力の伏字化は、**対の deny に当たったときだけ**例外を適用し、ほかの deny に当たれば伏せる。壊れていれば例外なし（厳しい側） |
| Copilot | `check_file_read.py` が `command_policy.matches_read_deny` で同じ意味に判定する。Windows では deny も例外も大小文字を区別せずに照合する（guide plugin の `pathRegExp` と同じ。POSIX は区別する）。例外の定義が壊れていれば hook が拒否する（fail-closed） |
| Claude | **表現できない**。deny 優先で例外を書けないので `.env.example` なども deny のまま（`**/.env.*`）。例外の定義は読まない |

- Bash hook（`bashrules/sensitive.py`）は `.env.<接尾辞>`（`.env.local` 以外）を元から
  サンプル扱いにしていて、`cat .env.example` は止まらない。変更していない
- `bypass` は `ask` を `allow` にするので、`ask` のままだと `.env.local` などが
  通ってしまう。`.env.*` を deny にした理由（[ADR-0014](../adr/0014-bypass-as-ask-upgrade.md)）

### 作業ツリーの外の読み取り

作業ツリーの外のパスを `read` / `grep` / `glob` / `edit` で触ると、OpenCode は
その前に `external_directory`（resource は触ったファイルのディレクトリ + `/*`）を
確かめる。既定は `ask` なので、スキルの参照ファイルや隣のリポジトリを読むたびに
確認が出ていた。shell の作業ディレクトリ（`workdir`）が外にあるときも同じ確認が立つ。

次の場所だけ `external_directory` を `allow` にする。

| 出所 | 場所 |
| --- | --- |
| `[pi.external_read] paths` | スキルの置き場（`~/.claude/skills`・`~/.agents/skills`・`~/.config/opencode/skills`） |
| `[opencode.sandbox] work_read` | 隔離版が読める作業場所（`~/src`・`~/worktrees`・`~/papers`・`~/.local/share/chezmoi`） |

作業場所は隔離版の `work_read` をそのまま使い、二重に並べない
（`opencode_external_read_dirs`）。

- **同じ場所の `edit` は `ask` に戻す。** `external_directory` は read と edit の
  両方の前段なので、allow だけ置くと既定の `{*, *, allow}` で作業ツリーの外へ
  確認なしに書ける
- **`read` の allow は足さない**（deny の例外を除く。[上](#deny-の例外envexample-など)）。
  `read` は既定で allow なので要らず、足すと OpenCode の既定の `*.env` の `ask` を上書きしてしまう
- 規則は `[file]` 由来の read / edit の規則より**前**に置く。秘密のパスの deny
  （`read_deny_globs` / `write_deny_globs`）が後勝ちで効き続ける
- 作業ツリーの中のパスは resource が相対パスになるので、`~/.local/share/chezmoi/*`
  の `edit` の `ask` は、このリポジトリで作業するときの編集には当たらない
  （絶対パスで渡しても相対に直る）
- 隔離版（`ocs`）も既定は `ask` なので同じ規則を出す。`~/` 始まりの read / edit の
  規則は隔離版では捨てるが、この `edit` の `ask` だけは残す
  （捨てると、以前は `external_directory` の確認が止めていた edit が確認なしになる）

実測は [作業ツリーの外の読み取りとスキルのスクリプト](../research/opencode/permission/external-read-and-skill-scripts.md)。

### スキルのスクリプト

スキルが手順に書いたスクリプト（`sdd-docs` の `lint_docs.py` と、状態を読むだけの `docs_state.py status` など）は shell の
既定の `ask` に当たり、呼ぶたびに確認が出ていた。`external_directory` の確認は
出ない（shell は引数に書いた外のパスから外部ディレクトリを推定しなかった。
`ls <外のパス>` でも同じ。実測）。
`[pi.skill_scripts] allow` に載せたスクリプトだけを allow にする
（`opencode_skill_script_rules`）。

```toml
[pi.skill_scripts]
runners = { py = ["python3"], sh = ["bash"] }

[[pi.skill_scripts.allow]]
script = "~/.config/opencode/skills/checkpoint/scripts/checkpoint.py"
subcommands = ["paths", "lint", "read"]
```

| 書き方 | 生成する規則 |
| --- | --- |
| `script` だけ | `<runner> <script> *` を allow、`<runner> <script> *>*` と `*<*` を deny |
| `subcommands` | 上の `<script>` の後ろにサブコマンドを足した形を、サブコマンドごとに出す |
| `exact` | `<runner> <script> <引数>` を**完全一致**で allow（`*` を付けない） |

- **スキルの置き場の中に限る。** `script` が `[pi.external_read] paths` の外か
  `..` を含むと `generate.py` が `apply` を止める。拡張子に対応する `runners` が
  無いときも止める
- shell の resource は生のコマンド文字列で `~` を展開しない。`~/` の形と、展開した
  絶対パスの形の両方を出す。引用符で囲んだパスや、パスを変数に入れた形
  （`S=…; python3 "$S/x.py"`）には当たらず、確認が出る。スキル側は
  `python3 <パス>` とそのまま書く（`sdd-docs` / `checkpoint` の `SKILL.md`。
  `test_skill_docs_call_their_scripts_in_the_allowed_form` が固定する）
- **リダイレクトは deny。** 前方一致の allow はリダイレクトを含む形にも当たり、
  `wc *` と同じく任意書き込みの手段になる。`2>&1` も止まる（止まったら付けずに
  呼び直せばよい）。静的 deny のままだとモデルには `Permission denied: shell` しか
  返らないので、同じ範囲を `deny_guide` にも出し、`redirect_message` の説明付きで
  前段で止める（[前段停止](guard/opencode-guard.md#opencode-の-deny-の説明前段停止)）。
  前段は静的 deny より広く止めない: `exact` の形・`subcommands` に無い形・引用符付き・
  `&` を挟む形（`&>`）は前段で見送り、静的 deny か確認に任せる
- **runner に `uv run --no-project python` を使わない。** 作業ツリーの
  `.python-version` に実行ファイルのパスが書いてあると、それを起動する（実測）。
  `python3` は uv の設定探索を通らないが、`PATH` の解決（mise の shim・venv）で
  作業ツリーに従う余地はある（OpenCode の shell での解決先は未確認）。
  `--no-config` や Python の明示で避けられた実測もあり、uv 一般が危険という意味ではない
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
- **away-shift。** `away_guard.py` の `init` / `check` / `log` / `status` / `sleep` / `snapshot` と `preflight.py` を載せた（`preflight.py` は渡された文字列を判定器へ渡すだけで実行しない。コードを読んで確認）。
  `snapshot` は、リポジトリの作業用コピーを `work/src/` へ作る（追跡と ignored でない未追跡。`[file] read_deny_globs` に当たるもの・リンク・サブモジュール・容量超過は除外し、一覧が読めなければ拒否する）。**隔離ではない**（[CHG-0030](../change/0030-away-shift-on-pi.md)）。
  書き込みは `.tmp/away-shift/` の中に閉じる（run_id の検査、リンクの拒否、`--note-file` は `work/` 直下のみ。`test_away_guard.py` が固定）。
  待機は `sleep <秒>`（1〜7200 の整数。何も読み書きしない）を許可し、生の `sleep` は `[pi.shell] allow` に足さない（OpenCode の全体許可へ複写され、`sleep … > ファイル` が書き込み経路になるため）。
  `skill_scripts` は `shell_allow` を持つ探索・レビュー役からも到達するが、書き込み先が閉じているので受け入れる。読み取り専用と説明している役割に書き込みの例外ができることを今回受け入れる。許可の期待値は `test_decide.py` の `test_away_shift_scripts_allow_only_the_listed_subcommands` が固定している。実際の pis（TS 版）での挙動は未確認

### shell ツールの環境変数

値の正本は `common.toml` の `[agent_env]`（`GIT_TERMINAL_PROMPT` / `GIT_EDITOR` / `GCM_INTERACTIVE`）。
AI CLI のシェルへ**未設定のときだけ**入れる。空文字を明示した変数は設定済みとして空のまま残す。

| 変数 | 防ぐもの |
| --- | --- |
| `GIT_TERMINAL_PROMPT=0` | TTY が付く経路での資格情報の入力待ち |
| `GIT_EDITOR=false` | `-m` 無しの `git commit`・`rebase -i` などのエディタ起動待ち |
| `GCM_INTERACTIVE=never` | Git Credential Manager の対話（GCM が無ければ無害） |

配り先:

| CLI | 方法 |
| --- | --- |
| OpenCode | 生成器が `rules.json` の `agent_env` に出し、`index.js` が `shell.create.before` で `??=` により入れる。`ocs` の `inner_env` には足さない（隔離版の内側も同じ `index.js` を読む） |
| Copilot CLI | 起動関数（shellrc / PowerShell。Windows は `try/finally` の関数）が `[agent_env]` をテンプレートで直接読む |
| Claude Code | 保留。再開時に `CLAUDE_ENV_FILE` と比較する（`settings.json` の `env` は上書きで不適） |

- 生成器は、キーが `^[A-Z_][A-Z0-9_]*$` でない・値が文字列でないとき生成を止める。
  `[agent_env]` が無ければ空の辞書を出す。`index.js` は `agent_env` が文字列の辞書でなければ何も入れない
- 起動関数で入れた値は、AI CLI の `!` で人が実行したコマンドにも入る（許容）
- 入れないもの: `GIT_SSH_COMMAND`（git 設定の SSH 指定と衝突）、`EDITOR=true`（成功の偽装）、
  `GIT_SEQUENCE_EDITOR`
- plugin のロード失敗（fail-open）や `rules.json` が全部無効で `index.js` を載せない設定では OpenCode 側は効かない
- 実測は [E1](../research/agents/noninteractive-git-env.md)。試験は `test_guide_shell_env.py`

### `git commit` の件名と本文

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
- **`git add -- <パス…> && git commit …` の連結形も抜き出す。** commit スキルは分けて実行するが、
  モデルが連結形で書いたときも表示できるようにしている。追加するパスを
  `追加: …` の 1 行で出す。scanner が分けた `resources` は 2 つになるので、`tui.ts` は配列のまま、
  `index.js` は生のコマンドを渡す。連結は引用符の外の `&&` で分け、前が `git add -- <パス 1 つ以上>`、
  後ろが単純な `git commit …` のときだけ抜き出す（[CHG-0013](../change/closed/0013-commit-agent-as-planner.md)）
- 表示は本体の確認画面と同じ要求を選ぶ（自分と子のセッションの保留の先頭。子の
  セッションを開いているときは出さない）。コミットは親が行うので、確認は親の画面に出る
  （[コミットの確認](#コミットの確認)）
- **抜き出せない形は従来のモデルの説明へ倒す。** 上の連結形を除く引用符の外の `;` `&&` `|` `>`
  改行（別のコマンドが続き、確認画面で切れた部分に隠れうる）、`$` や `` ` ``（実行時に
  展開される）、`-F` / `-C` / `--fixup` など `-m` 以外からメッセージを取るもの、
  `FOO=1 git commit` や `git -c … commit`、`git add -A` / `git add .` などパス指定でない `add`
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

### モデルの割り当て

PC ごとにモデルのプロバイダを 1 つに決め、既定モデル・エージェントごとのモデル・
接続設定・他のプロバイダの禁止を `opencode.json` へ出す。
新しいモデルが出たときなどに割り当てを見直す手順は
[モデルの割り当ての見直し](model-lineup-review.md)にある。

#### 会社 PC の判定

`.chezmoitemplates/is-work` が `apply` のたびに決める（`"true"` / `"false"`）。**LLM のプロバイダ（`llm-provider`）とは別の軸**で、
「検索語などを AWS の外へ出してよい個人用の機か」を表す。会社 PC で Copilot を使うようになっても、個人専用の配布が会社の機へ入らないようにするため。

| 条件（上から順に評価） | `is-work` |
| --- | --- |
| `chezmoi.toml` の `[data]` に `work` がある | その値（`true` / `false`） |
| ユーザー名が `applejxd`（`DOMAIN\applejxd` も含む、大小無視） | `false`（個人用） |
| それ以外 | `true`（会社 PC） |

- **`is-work` で切るもの**: `web-search` と `imozuru` のスキルの配布と許可規則（検索語を外へ出さない）、GitHub の認証の出どころ（個人は `gh auth token`、会社 PC は権限を絞った PAT のファイル）、`agentcore-websearch` を入れる CLI の一覧
- **`llm-provider` で切るもの**: Copilot ブローカー、Envoy の取得、OpenCode のプロバイダ、`[pis.network]` の既定
- **AgentCore 自体は、どちらでも切らない。** 使うかは実行時（URL の有無）で決まる。判定を誤っても、認証が無ければ何も起きない
- 勤務先の具体はリポジトリに書かない。判定の根拠は個人のユーザー名だけで、自動の判定が合わない機は `[data] work` で上書きする（`chezmoi update` は `init` を呼ばないので、`[data]` は `init` 時にしか変わらない。上書きが要るのは例外）

#### プロバイダの判定

`.chezmoitemplates/llm-provider` が `apply` のたびに決める。

| 条件（上から順に評価） | プロバイダ |
| --- | --- |
| `chezmoi.toml` の `[data]` に `llm_provider` がある | その値 |
| ユーザー名が `applejxd`（`DOMAIN\applejxd` も含む、大小無視） | `github-copilot`（個人用） |
| それ以外 | `amazon-bedrock`（制約のある環境用） |

判定の前提は「個人機のユーザーは `applejxd`、制約のある環境の機は別名で AWS CLI にログイン
している」こと。どちらでもない PC では OpenCode を使わない。

- **gh のログイン状態は見ない。** 制約のある環境の機でも `gh auth login` していることがあり、
  見分けに使えない。OpenCode の Copilot 接続も `gh` とは別で、`/connect` が要る
- **`~/.aws` の有無も見ない。** 個人機にも `~/.aws` ディレクトリだけ存在する
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
| `default` | 主エージェントの既定 | `claude-sonnet-5.5` | `us.anthropic.claude-sonnet-5-5` |
| `routine` | 決まった形の短い作業 | `claude-sonnet-5.5#medium` | `us.anthropic.claude-sonnet-5-5#low` |
| `worker` | 実装などを任せる作業役 | `claude-sonnet-5.5#medium` | `us.anthropic.claude-sonnet-5-5#medium` |
| `deep` | 難しい判断・設計 | `claude-sonnet-5.5#high` | `us.anthropic.claude-opus-5-5#high` |
| `second_opinion` | 別系統のモデルでの確かめ | `gpt-6-astra` | `us.openai.gpt-6-sol` |

Copilot の `default`・`deep` は Sonnet 5.5、`second_opinion` は OpenCode の階層では Astra のままで、
pi の Copilot は `[pi.model.tier.github-copilot]` で Sol に上書きしている（Opus と Astra が制限されたため）。`deep` の `xhigh` は Sonnet で通る確認が取れていないので `high` にした。Bedrock の階層は全部 `us.`
（`global.` は使わない）。`us.` 無しの ID は `ask_description` の候補の最後のフォールバック
（`amazon-bedrock/anthropic.claude-haiku-5-5`）だけで、推論プロファイルが無い環境で取りこぼさないための意図的なもの。

割り当て（`[opencode.model.agents]`）は `commit = "routine"`・`review = "second_opinion"`・
`fleet-worker = "worker"`。

- **`routine` と `worker` は今は同じモデルだが、分けておく。** 名前は用途なので、
  どちらかの計測結果が変わったときに片方だけ差し替えられる
- **`routine`（`commit`）は Sonnet 5.5。** haiku ではコミットメッセージの書式が崩れ、Sonnet 5.5 でそろう。effort では差が出なかった
- **`worker`（`fleet-worker`）も Sonnet 5.5。** 実装課題で Opus 5.5 と合格率に差が無く、速い。haiku は難しめの課題で不合格が多く、担当外にファイルを残す。
  Bedrock の値は Copilot で近似した判断で、Bedrock 上では未確認
- 比較の数値と根拠は[経緯](../research/agents/agent-config-generation-notes.md)と[階層のモデルの計測](../research/opencode/tier-models.md)
- **effort はプロバイダの予算で分ける。** Copilot（使い放題）は質と待ち時間で選び、`routine` も
  `worker` も `medium`。Bedrock（予算が有限）は、effort で差が出なかった `routine` を `low` にして
  費用を削り、`worker` は `medium`。公開のベンチマークでも、effort の差は難しいコーディングの課題で
  1 段あたり 1〜3 ポイント程度（[階層のモデルの計測](../research/opencode/tier-models.md)の追記）。
  Bedrock の Sonnet 5.5 に effort を付けられることは、利用者が確かめた
- **`deep` は計測していない**（機械的に採点できる課題が作れないため、opus の上位の effort のまま）
- **Bedrock の `default` は Sonnet 5.5 のまま。** Opus 5.5 の `low` が候補だが未比較（[経緯](../research/agents/agent-config-generation-notes.md)）
- `default` を割り当てに使わないのは、Copilot の `default` はバリアントが付けられず
  （下記）ほかの階層と推論の強さが変わるのと、既定モデルを変えたときに子エージェントまで
  変わらないようにするため。Bedrock では今は `routine` / `worker` と同じモデルで、effort だけが違う

```toml
[opencode.model.agents]
explore = "worker"      # 例
```

- **どのプロバイダにも同じ階層名をそろえる**（`test_every_provider_defines_the_same_tiers`）
- ID は [models.dev](https://models.dev) の一覧か TUI の `/models` で実在を確かめてから
  書く。Bedrock の `us.` はクロスリージョン推論プロファイル (米国のリージョン内。以前の `global.` は使わない)
- **`default` に `#variant` は付けられない。** 既定の `model` はバリアントを
  保持しない（公式）。付けると `apply` を止める
  - Copilot の `default` に推論の強さを持たせる手段は無かった（2 回目以降の呼び出しで送られない。
    [実測 記録 E2](../research/opencode/agent-models.md#記録-e2--2026-09-28-既定モデルに推論の強さを持たせられるか)）
  - そのため Copilot の `default` はバリアントなし（強さは Copilot 側の既定。
    どの強さかは未確認）。high で動かしたいセッションは TUI でバリアントを選ぶ
- 未知の階層・プロバイダ、`[opencode.agent]`（V1 形式）にあるエージェントへの
  割り当ても `apply` を止める。後者は V1 の `agent` と V2 の `agents` に同じ ID が
  並んだときの結合順を確かめていないため
  - 改名前の階層名（`light` / `standard` / `heavy`）で割り当てても、未知の階層として止まる。
    エラーには定義済みの階層名が並ぶ
- 宣言も組み込みでもない ID への割り当ても止める（[所有の規則](opencode-config-generation.md#配置済みの設定の所有)）

### コミットの確認

差分を読む作業は安いモデルの子（`commit`）に任せ、**承認は会話で行う**
（[CHG-0015](../change/closed/0015-commit-planner-with-chat-approval.md)）。

0. `docs/change/` があるリポジトリでは、親が今回の変更に関わる活動中の案件を判断し、
   `sdd-docs` の A2（案件の更新）を検査まで済ませる。編集の前に、その案件ファイルの既存の差分だけは
   親が見る（利用者の書きかけを上書きしないため）。結果は承認時の提示の直前に 1〜2 行で示す
   （更新しなかったときも「不要（理由）」と書く）。更新した案件は、それが記録する変更と同じコミットに含める
1. 親が `commit` を呼ぶ。子は commit スキルの手順 2 として差分を読み、ファイル単位の論理単位ごとに
   対象のパスとメッセージ全文（計画）を返す。ステージもコミットもしない
2. 親は計画の全文をスキルの「承認時の提示」の形で返答に示し、**利用者の承認を待って返答を終える**
3. 承認されたら、親がスキルの手順 3〜6 で単位ごとに `git add -- <パス>` と `git commit -m '<件名>' -m '<本文>'` を
   別々に実行する。差分は読み直さず、`git status --short` と `git diff --cached --name-only` で対象を確かめる

- **承認の場を会話にする理由。** 会話で承認を求める形では、全文を示さないと承認を求められないので、
  抜けがあっても利用者の目に見える。照合の仕組みは置かない
  （確認画面を承認の場にした案と照合の仕組みの案を退けた経緯は[記録 N10](../research/agents/agent-config-generation-notes-2.md#記録-n10--コミットの確認で採らなかった案)）
- 親がこの流れを知る手段は、`commit` の `description`（親の `subagent` ツールの一覧に出る）と commit スキル。
  スキルの手順 4 の既定（提示して承認を得る）をそのまま使い、上書きの指示は出さない
- 承認の操作は、通常起動と `ocs` で 2 回（会話と `git commit` の確認画面）、`bypass` で 1 回（会話）
- **docs の反映をコミットの前に置く理由。** コミットの後に促すと docs だけのコミットが続き、
  承認が 2 回になる。判断を親に置くのは、案件に書く経緯（決めたこと・見送ったこと）が差分に
  現れず、差分だけを読む子には書けないため。子に「docs 未反映」を検出させる保険は入れていない
  （親が飛ばすと提示の前の 1 行が欠けるので、利用者の目に見える。理由は上の記録 N10）
- **ADR・仕様・調査記録（B）は対象外。** 判断が重く、頼まれずに増やさない
- **git の pre-commit hook や plugin の `git commit` 直前のゲートには置かない**（理由は上の記録 N10）

**子の権限**（後勝ち）:

| 順 | 効果 | 規則 | 理由 |
| --- | --- | --- | --- |
| 1 | `deny` | `edit` / `subagent` / `question` の `*` | 編集・子エージェントの起動・質問をさせない |
| 1 | `deny` | shell の `*` | 読み取り以外をさせない。隔離起動はシェルの既定が `allow` なので、列挙ではなく全体で塞ぐ |
| 2 | `allow` | `git status *`・`git diff *`・`git log *`・`git branch --show-current`・`git rev-parse --show-toplevel` | 状況の把握。commit スキルが教える形そのまま |
| 3 | `deny` | `*>*`・`*--output*` | allow の形に付けたファイルへの書き出し |

- **全体の規則は変えない。** 全体の `allow` から `git diff` / `git status` を外した判断
  （[allow リスト監査](../research/opencode/permission/allow-list-audit.md)）はそのままで、素の形を確認なしで
  通すのは `commit` の中だけ。`commit` の中では、リポジトリの設定の fsmonitor・外部 diff・textconv が
  確認なしで起動しうる（clone では運ばれず、`.git/config` の書き換えは別に塞いである）

**親の `git commit` の確認**（安全網）:

| 起動の仕方 | 確認 | 仕組み |
| --- | --- | --- |
| 通常起動 | 出る | 全体の `git commit *` の `ask`（`[bash] ask`） |
| `bypass` | 出ない | `ask` を `allow` に引き上げる。利用者が確認を省くと選んだ起動 |
| 隔離起動（`ocs`） | 出る | `drop_shell` で `git commit` の `ask` を捨てない |

- **オプションを前に置いた `git -c … commit` は guide 規則で止める。** 隔離起動はシェルの既定が
  `allow` なので、`git commit *` の `ask` に当たらない形は確認も hook も無しで通る。
  コミットメッセージの中に同じ形の文字列があると誤って止める（承知の割り切り）
- **確認画面には件名と本文を抜き出して出す**（[`git commit` の件名と本文](#git-commit-の件名と本文)）
- **残る穴**: 親が承認を待たずにコミットへ進むと、`bypass` では止まらない。静的な照合なので、
  引用符や変数で書き換えた形（`g"it" commit` など）はすり抜ける
  （[静的パターンの回避](../research/opencode/permission/shell-allow-and-plugin-gate.md)）。
  確認で「常に許可」を選ぶと `git commit *` がプロジェクトに保存され、以後は確認なしでコミットする

## hooks の単一ソース化

**Claude / Copilot への hook の登録は撤去した（[ADR-0017](../adr/0017-pi-only-and-ts-judge.md)）。**
`[[hooks]]` は、pi のフルガードが edit / write の後に呼ぶスクリプト（`post_edit = true`。整形と markdownlint）だけを持つ。
判定の hook（`check_bash.py`・`redirect-tmp.py`・`check_file_read.py`）の判定は TS の判定器（`pi/harness/judge`）が担い、`[retired_hooks].scripts` に載せた。
Python 版のファイルは `home/dot_claude/hooks/` に残るが、登録されず実行時は呼ばれない（正解データの書き出し元。[CHG-0035](../change/0035-retire-python-judge-oracle.md)）。

| 生成先 | 生成方法 | 扱い |
| --- | --- | --- |
| `~/.claude/settings.json` の `hooks` | `modify_settings.json.py.tmpl` → `--target claude-settings` | 登録は空。`retired_hooks` に載せたスクリプトの古い登録を外し、外部ツール（Orca など）の hook は残す |
| `~/.copilot/hooks/from-claude.json` | （撤去。`--target copilot-hooks` は無い） | 配備済みのファイルは `.chezmoiremove` で消す |

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
  （Copilot の hooks 生成は撤去済み。[記録](../research/agents/agent-config-generation-notes.md)）
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
ディレクトリで判定すると herdr の hook を apply のたびに消してしまう
（[経緯](../research/testing/docker-cold-start-fixes.md#6-2-回目の-apply-でも-claudesettingsjson-の差分が消えない2026-09-27)）。

`[retired_hooks].scripts` は撤去した hook の名前で、`settings.json` に残った
古い登録を消すためにある。一覧は git 履歴から作った
（`block-dangerous-commands.sh` / `update-adr-on-stop.py` / checkpoint の 3 本）。
**hook を撤去したらここへ足す。** 足し忘れると古い登録が外部の hook として残る。
名前の直後が引用符・空白・末尾でない場合（`check_bash.py.bak` など）は一致させない。

逆に言えば、このディレクトリにスクリプトを置いて `settings.json` へ手で
登録しても、`common.toml` に転記していなければ外部の hook として残り続ける。

herdr の hook は `common.toml` から生成せず、herdr 自身が `run_after_140` / `343` で毎回導入し直す
（理由は[記録](../research/agents/agent-config-generation-notes.md)）。

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

> 旧 Claude hook の記録。登録は撤去済み（[記録](../research/agents/agent-config-generation-notes.md)）。

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
`example-skills` は中身が完全に同一**（17 スキルが一致。[実測](../research/agents/agent-config-generation-notes.md)）。両方有効にすると全スキルが二重に登録される。

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
