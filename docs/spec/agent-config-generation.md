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
導入順と更新手順は [AI CLI の導入](cli-management.md#ai-cli-の導入)を参照。

## Copilot CLI の既定モデル

`[copilot] model` を `~/.copilot/settings.json` の `model` へ書きます。
apply のたびに上書きするため、TUI の `/model` で変えた既定値は次の apply で
戻ります。一時的に変えるときは `--model` を使います。キーが無ければ既存値に
触れません。

ID は `copilot help config` の候補一覧に無くても、API 側にあれば通ります
（1.0.87 で `claude-opus-5.5` は一覧に無いが `--model` で応答した）。書く前に
`copilot --model <ID> -p 'Reply with exactly: OK'` で確認します。

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
