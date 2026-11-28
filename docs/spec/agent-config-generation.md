# pi の設定の生成と所有権

pi の設定（`~/.pi/agent/`・`~/.cc-safety-net`・囲いの設定）を、このリポジトリがどう配り、何を利用者の持ち物として残すか。
pi は公式の既定に、人気の拡張（pi の package）だけを入れた構成（stock）で使う。旧 custom プロファイルと、pi 以外の AI CLI（Claude Code・Codex・Copilot CLI・Gemini CLI・OpenCode）の設定生成は撤去した
（[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md)）。

## ファイル構成

```text
home/.chezmoitemplates/
    pi-stock-packages                        入れる package（1 行に 1 つ、`npm:<名前>@<版>`。版を固定する）
    pi-permission-policy.json                権限の方針（permission-system の config.json の元データ）
    pi-mcp-servers.toml                      MCP サーバの宣言（`[[mcp]]`。chezmoi テンプレート）
    modify_pi_stock_settings.py.tmpl         settings.json の変換（packages・既定のツール・圧縮・子のモデル・シェル）
    modify_pi_permission_config.py.tmpl      permission-system の config.json の変換
    modify_json.py.tmpl                      generate.py を呼ぶ modify_ の共通ラッパー（Python 3.11 以上を選び直す）
    agent-instructions-stock.md              ~/.pi/agent/AGENTS.md の本文（ツール非依存の指示）
    agent-instructions-home.md               家の機（is-work でない）だけに足す節（開発中の Web サービスは tailnet だけに公開する）
    is-work                                  会社 PC かどうかの判定（検索 MCP の出し分け）
scripts/agents/
    generate.py                              pi-mcp-servers.toml から mcp.json を生成する（pi の MCP だけ）
    validate_mcp.py                          描画した pi-mcp-servers.toml の検査（pre-commit）
    validate_skills.py                       SKILL.md の frontmatter の検査（pre-commit）
home/dot_pi/agent/
    AGENTS.md.tmpl  keybindings.json  prompts/  themes/  agents/
    modify_settings.json.py.tmpl  modify_mcp.json.py.tmpl
    modify_compaction.json.py.tmpl  modify_pi-plan-mode.json.py.tmpl
    extensions/pi-permission-system/modify_config.json.py.tmpl    extensions/subagent/modify_config.json.py.tmpl
home/dot_cc-safety-net/rules/            cc-safety-net の規則
home/dot_config/pi-sandbox/              pib の囲いの設定（runner.toml）
home/dot_config/agents/                  検索の核と MCP サーバ（websearch/）、AgentCore のラッパー
home/dot_agents/skills/tailscale-serve/  tailnet への公開手順のスキル（家の機だけ。会社 PC は `.chezmoiignore.tmpl` で除外）
test/
    test_pi_stock_config.py  test_pi_subagents_config.py  test_pi_compaction_config.py
    test_pi_permission_decisions.py  test_pi_commands_doc.py  test_pi_theme.py  test_pi_sandbox_runner.py
    test_modify_legacy_cp932.py
    agents/test_mcp_servers.py  agents/test_modifier_wrappers.py
```

### コメントの書き分け

設定ファイル・テンプレート・スクリプトには **その行を編集するときに要る注記** だけを置く。
仕組み・判断基準・既知の不具合は `docs/spec/`、実測値と経過は `docs/research/` が正本で、ファイル側からは
`see docs/spec/<文書>.md#<見出し>` で参照する。

| 置き場所 | 内容 | 例 |
| --- | --- | --- |
| 設定・スクリプトのコメント | その値を足す/消すときの制約 | 「`gh` は `*pr create*` の形で書く（前置きのオプションを読み飛ばすため）」 |
| `docs/spec/` | なぜその方式か、upstream の不具合 | permission-system の既定は、設定が無いと全部 ask になる |
| `docs/research/` | 実測値、何が壊れたかの経過 | 子の権限の frontmatter の実測 |

- **同じ説明をコメントと `docs/` の両方に書かない**（更新時に必ず片方が古くなる）。
- コメントに残してよい例: 非自明な 1 行の意図、公式ドキュメントの URL、消すと壊れる理由の 1 文。
- `docs/` へ移すもの: 背景・比較・代替案・実測値・失敗談・「なぜ他の方法を採らなかったか」。

Python は 3.11 以上を前提とし、TOML は標準ライブラリ `tomllib` で読む（[ADR-0003](../adr/0003-require-python-311-for-agent-configuration.md)）。
`modify_` のラッパーは、Unix では `python3`、Windows では最新の Python 3 を選び直す。3.11 未満では `tomllib` の import が失敗するため、project の uv 環境や外部の `tomli` には依存しない。

### modify スクリプトの文字コード

Python の標準入出力は、Windows ではロケールのコードページ（日本語環境は cp932）が既定で、UTF-8 で話す chezmoi と食い違う（2026-11-20 に日本語 Windows の `chezmoi apply` で確認）。
`modify_*.py.tmpl` が `sys.stdin` を読み `sys.stdout` へ書くなら、`main()` の先頭（読み書きより前）で次の 2 行を呼んで UTF-8 に固定する。

```python
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
```

旧版が cp932 で書いた対象ファイルが残りうる 5 つ（`modify_settings`・`modify_compaction`・`modify_pi-plan-mode`・`pi-permission-system/modify_config`・`subagent/modify_config`）は、入力の固定の代わりに `read_stdin()`（bytes で読み、UTF-8 で読めなければ cp932 で読み直す）を使う。[旧版が書いた cp932 のファイルの移行](#旧版が書いた-cp932-のファイルの移行)を見る。新しい `modify_*.py.tmpl` は、上の 2 行でよい。

- **症状**: 出力に cp932 で書けない文字があると `UnicodeEncodeError: 'cp932' codec can't encode character '\u2014'` で apply が止まる。`settings.json` の出力は、調査の子の system prompt（`pi-agent-prompt-researcher`）に U+2014（EM DASH）を含むので、必ず当たる。cp932 で書ける文字（日本語など）だけの出力は、エラーにならず cp932 のバイト列を返して、chezmoi が UTF-8 として読み、文字化けする。入力側も同じで、UTF-8 の JSON を cp932 として読み誤る。
- **検査**: `scripts/lint_templates.py` が、`modify_*.py.tmpl`（描画できない `home/.chezmoitemplates/` の共有テンプレートを含む）の**ソース**を見て、`sys.stdin` / `sys.stdout` を text で使うのに、使う前の固定が無いものを落とす。`.buffer` 経由のバイト列の入出力（`modify_json.py.tmpl`）は対象外。`print()`・`input()` のように `sys.stdin` / `sys.stdout` を名指ししない入出力は見ない。新しい `modify_*.py.tmpl` を足すときは、同じ 2 行を置く。
- **実行で確かめない理由**: Windows の CI（`windows.yml`）は `PYTHONUTF8=1` で回す（[Windows の GitHub Actions](testing.md#windows-の-github-actions)）ので、この不具合は実行の試験では捕まらない。Linux では既定が UTF-8 で、cp932 を再現できるのは `PYTHONIOENCODING=cp932` を渡した子プロセスだけ。そこで固定の有無を静的に見る。
- **改行**: `reconfigure(encoding=...)` は改行の変換を変えない。Windows の text の標準出力は `\n` を `\r\n` にする（既存の挙動で、この規則の対象外）。

#### 旧版が書いた cp932 のファイルの移行

UTF-8 に固定する前（2026-11-20 より前）の日本語 Windows では、`modify_` が cp932 のバイト列を書いていた。そのファイルが対象ファイルに残っていると、固定後の `modify_` は UTF-8 として読めず、`chezmoi apply` / `chezmoi update` が `UnicodeDecodeError: 'utf-8' codec can't decode byte …` と `chezmoi: .pi/agent/….json: exit status 1` で止まる（2026-11-21 に確認。`compaction.json` と `pi-permission-system/config.json`。`--init` の有無に関係しない）。

- **対処（コード）**: 5 つの `modify_` は標準入力を bytes で読み、UTF-8 として読めなければ cp932 として読み直す（`read_stdin()`）。出力は UTF-8 で返すので、次の apply で対象ファイルが UTF-8 になる。cp932 でも読めないバイト列は、黙って壊さず `UnicodeDecodeError` で止める。
- **対処（手作業）**: コードを入れる前に止まった機は、対象ファイルを cp932 から UTF-8 へ 1 回だけ変換してもよい（UTF-8 のファイルを cp932 として読むと壊れるので、先に UTF-8 で読めるかを見る）。
- **Linux との関係**: Linux では標準入出力が UTF-8 なので、cp932 のファイルは作られていない。UTF-8 として読める入力は、読み方が text から bytes の復号に変わるだけで、結果（改行の扱いを含む）は今までと変わらない。
- **検査**: `test/test_modify_legacy_cp932.py` が、5 つの `modify_` を `PYTHONIOENCODING=cp932` の子プロセスで動かし、cp932 の入力が UTF-8 の同じ内容になること・UTF-8 の入力と同じ結果になること・壊れた JSON を作り直さず内容を保つこと（UTF-8 化と、text の標準入力と同じ改行の変換だけは行う。UTF-8 の BOM も保つ）・読めない入力で止まることを見る。
  ファイルの実体（機ごとの状態）は静的に見られないので、`lint_templates.py` には足していない（lint はソースの形だけを見る）。
- **撤去の条件**: 使っている全ての Windows 機で `chezmoi apply` が 1 回通り、対象ファイルが UTF-8 になったら、`read_stdin()` の cp932 の読み直しと試験を外す（利用者が判断する。他の Windows 機の有無は、この repo からは分からない）。

## pi の設定

### 設定の置き場（pi の標準の形と、機械ごとの上書き）

pi の設定は、1 か所にまとまっていない。これは pi の標準の形で、このリポジトリが散らしたわけではない（2026-11-15。pi 1.5.2 の `docs/settings.md`・`docs/extensions.md`）。

- **pi 本体**: `~/.pi/agent/settings.json`（全体）と、プロジェクトの `.pi/settings.json`。プロジェクトの設定が全体の設定を上書きする。
- **拡張**: `~/.pi/agent/extensions/`（全体）か、プロジェクトの `.pi/extensions/` に置く。拡張が自分の設定をどこに置くかは**拡張ごとの決め**で、pi 本体は規約を決めていない。実際の拡張は、`extensions/<拡張名>/config.json` の形を取る（`pi-permission-system`・`pi-permission-explain`・`ai-guard`）。
- **機械ごとの上書き**: chezmoi の管理外のファイルに置く。一覧は [マシン固有の設定の置き場](shell.md#マシン固有の設定の置き場)（pi に関するものは、`runner.local.toml`・`config.local.json`・`/permission-system`）。

### 配るもの

| 対象 | 配り方 |
| --- | --- |
| `~/.pi/agent/AGENTS.md` | `agent-instructions-stock.md`（ツール非依存の短い指示）。委譲の常設の指示を含む。**家の機（`is-work` が `false`）だけ**、末尾に `agent-instructions-home.md` を足す（開発中の Web サービスを tailnet だけに公開する指示と、複雑な不具合の修正が膠着したときの診断手順）。会社 PC には出さない。`AGENTS.md.tmpl` が出し分ける。`tailscale serve` の手順・WSL での扱いは、家の機だけに配るスキル `tailscale-serve`（[tailscale.md](tailscale.md)）。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#tailscale-の指示の経緯) |
| `~/.pi/agent/settings.json` | `modify_pi_stock_settings.py.tmpl`。`packages` を `pi-stock-packages` にし、`defaultTools` を `["+grep", "+find", "+ls"]`（pi の既定 read・bash・edit・write に読み取り専用の探索ツールを足す増分指定。plan mode の探索にも使う。利用者が `+`/`-` だけの増分指定にしたら保つ）にする。撤去した自作ハーネスの `extensions`・`skills` の項目は取り除く。`skills` には、Orca が入れたスキル 3 本の除外（`!computer-use`・`!orca-cli`・`!orchestration`）を毎回そろえる（利用者の他の項目は保つ。戻すときは `+skills/<名前>`。[手動起動と除外](skill-frontmatter.md#手動起動disable-model-invocation)）。テーマなど利用者のキーは保つ。起動モデルと子の既定配分は[プロファイルの説明](#pi-subagents-の設定)を参照。自宅の `enabledModels` は未設定なら `["github-copilot/*"]` を補う。これは起動・モデル循環の候補であり、別プロバイダの手動選択や Pi 本体のフォールバックを禁止しない。 |
| `~/.pi/agent/mcp.json` | `modify_mcp.json.py.tmpl` が `generate.py --target pi-mcp` で配る（下の「MCP 設定」） |
| `~/.pi/agent/extensions/pi-permission-system/config.json` | `modify_` で配る（下の「permission-system の設定」） |
| `~/.pi/agent/extensions/subagent/config.json`・`agents/` | pi-subagents の設定と agent 定義（下の「pi-subagents の設定」） |
| `~/.pi/agent/pi-plan-mode.json`・`compaction.json` | `modify_` で配る（下の「追加の 4 つの package」「圧縮の設定」） |
| `~/.pi/agent/prompts/`（`/fleet`・`/stepback`） | 静的なファイル。Unix だけ（[下](#プロンプトテンプレートfleetstepback)） |
| `~/.pi/agent/keybindings.json`・`themes/` | 静的なファイル（ファイルごとこのリポジトリの持ち物。手で足したキーは次の apply で消える） |
| `~/.cc-safety-net/` | cc-safety-net の規則（下の「cc-safety-net の規則」） |

撤去した旧 custom の配備（`~/.config/pi`・自作の拡張・`models.json`）は、`.chezmoiremove` が消す。

### permission-system の設定

stock の確認画面は package `@gotgenes/pi-permission-system`。設定ファイルが無いと**全部のツール呼び出しを ask にする**ので、
方針を `~/.pi/agent/extensions/pi-permission-system/config.json` へ配る。

- **消す範囲**: 撤去した自作の拡張のディレクトリだけを `.chezmoiremove` が消す。`.pi/agent/extensions` を丸ごと消さないので、`pi-permission-system/`・package 由来のもの・利用者が置いた拡張は残る。
- **配り方**: `modify_config.json.py.tmpl`（`modify_pi_stock_settings.py.tmpl` と同じ流儀）。リポジトリが持つのは `permission`・`commandEffects`・`shellTools` の自分の項目だけで、`permission`・`commandEffects` は毎回その値で置き換える。`yoloMode`・`debugLog`・`permissionReviewLog`・`doublePressToConfirm`・`promptTimeoutMs` など実行時の値は**既存のファイルの値を保つ**（無ければ拡張の既定: `yoloMode: false` など）。壊れた JSON はそのまま返す。
- **方針（元データは `home/.chezmoitemplates/pi-permission-policy.json`。2026-11-09 に「bash は ask が既定」から、YOLO を切る前提の「bash は allow が既定」へ変えた）**:
  - **運用は YOLO を切る前提**。YOLO が入っていると下の ask が全部自動承認になり、強制 ask は意味を持たない（下の「YOLO mode」）。リポジトリは `yoloMode` を配らないので、機械ごとに `/permission-system` で OFF にする。
  - **利用者の承認を、方針の根拠にしない（2026-11-11 の利用者の判断）**。承認は、内容を理解しないまま通ることがあり、防御としては数えない。ask は摩擦であって守る手段ではない。守るものは deny にする。許可を足すかどうかは、承認された件数ではなく、パスそのものの危険度で決める。プロジェクトの信頼（trust）も同じ種類の承認なので、プロジェクトの設定（`.pi/extensions/pi-permission-system/config.json`）で緩める許可は、利用者が自分のリポジトリにだけ置く。共通の方針（このファイル）には、全プロジェクトで要る公開のパスだけを置く。
  - **ディレクトリを根にした再帰への備え（2026-11-11）**: `grep -r`・`find` の再帰は、ゲートに中が見えない。**秘密のディレクトリの deny は、ディレクトリ自体の規則も併せて置く**。pi の公開ディレクトリの許可は `/*` だけ。**受容した限界**: `extensions/<名前>` を根にした再帰は `logs` の ask をすり抜ける。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#再帰への備えの根拠)。
  - 作業ツリーの中の `read`・`write`・`edit`・`grep`・`find`・`ls` は allow。作業ツリーの外（`external_directory`）は、**読み書きとも allow は `/tmp/*` だけ**、**読み取りだけ allow は下の許可リスト**、それ以外は ask。プロジェクトごとの事前許可（データセットの読み取りなど）は [プロジェクト単位でデータセットを読み取り専用にする](#プロジェクト単位でデータセットを読み取り専用にする)。
    - **読み取りの許可リスト**（2026-11-10）: `~/.pi/agent/` の公開ディレクトリ（`npm/`・`agents/`・`skills/` など）・`~/.agents/skills/`・`/tmp` 自体・Orca の貼り付け画像は**読み取りだけ** allow。`extensions/*/logs`・認証情報・`sessions/` は ask。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#読み取りの許可リストの経緯)。
    - **Orca の添付ファイル（`~/.orca/agent-session-attachments/*`）は、読み取りだけ allow**（2026-11-16）。書き込みは allow にしない。展開は `cat` で作業ツリーへ写してから行う。**受容した限界**: 添付の配下の symlink 経由で、リンク先の読み取りが通る。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#orca-の添付ファイル)。
    - **T3 Code の添付ファイル（`~/.t3/userdata/attachments/*`）も、読み取りだけ allow**（2026-11-19。利用者の指示）。T3 は、利用者が添付した画像・ファイルを作業ツリーの外のこの場所に置き、パスを指示に添える。読むたびに確認が出ていたため。書き込みは allow にしない。`~/.t3/userdata/` のそのほか（状態の DB など）は ask のまま。**受容した限界**: Orca の添付と同じく、配下の symlink 経由で、リンク先の読み取りが通る。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#t3-code-の-mcp-ツールと添付ファイル)。
    - **子エージェントの出力の読み取り（2026-11-11）**: `subagent-artifacts/` の `*_output.md` と `outputs/*` だけ allow（transcript・依頼文・セッションは ask）。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#子の出力の読み取り)。
    - **`external_directory_read` の並び順と、`..` を含む綴り（2026-11-18）**: **allow、`..` を含む綴りの ask（`*/../*`・`*/..`）、deny・ask の順**に並べる（後勝ち。試験で固定）。代償: 原形に `..` が残る綴りは ask になる（正規化したパスで書く）。**受容した限界**: 許可した場所の中の symlink は、リンク先が「既定の ask」の場所なら通る。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#並び順と--を含む綴り)。
    - **システム診断の読み取りの許可リスト（2026-11-11。OS の条件は付けない）**: `/var/log`・`/proc`・`/sys`・`/etc` の診断用のパスを、**ディレクトリではなく名前で**許可する。`btmp`・`auth.log`・`/proc/*/environ`・`/etc/shadow` など秘密が残りうるものは ask のまま。草案で、実在は未確認。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#システム診断の許可リスト)。
    - **deny は、開発に支障が出ない範囲で最大限まで（2026-11-15 の利用者の指示）**。安全側に倒して広く deny にすると、その開発が実質できなくなり、手作業を利用者に回すことになって、エージェントを使う意味が無い。守りたい害（秘密の流出・囲いの外での実行）を特定し、その害を生む操作だけを deny にする。決めかねて ask に残す、または広く deny にするのは、どちらも避ける。手順は [dotfiles-conventions の「権限ポリシーを変えるとき」](../../.agents/skills/dotfiles-conventions/SKILL.md#権限ポリシーを変えるとき)。確認件数の集計には `friction-review` を使う。
    - **systemd の unit（2026-11-15。決め直しを 3 回した）**: 読み取りは unit の種類の名前だけ allow。書き込みは `~/.config/systemd/user` が ask、`/etc/systemd/system` が deny。`enable`・`link` は ask、`--user` の `start` などは確認なし。**受容**: user unit に書くと任意のコードが動く。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#systemd-の-unit-の決め直し)。
    - **`commandEffects`（パス引数の向きの宣言。2026-11-10）**: `git` の `log`・`status`・`diff`・`show` と `python3` を読み取りと宣言する（`--output`・`-c`・`-m` が付くと外す）。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#commandeffects)。
    - **広く許可（`external_directory_read` の `*` を allow）にしない理由**: ① `path` の deny は 42 件（allow は 2 件）で、`.docker`・クラウドの認証などは `runner.toml` の `hide` と同じ集合として deny 済みだが、`.npmrc`・ブラウザのデータなど列挙にない場所は網羅していない。② 外部への送信は `curl` などを止めていない（bash の既定が allow）ので、読み取りと送信が連鎖しうる。③ 実測では、yolo を切った後の最初の 13 分間に出た確認 8 件が、すべて許可リストの範囲に収まった。広げる必要が実測で無い。
    - **`~/.pi/agent` と `watchdog_diff` の deny（2026-11-14）**: 権限の設定そのもの（`~/.pi/agent` 自体・`pi-permissions.jsonc`）と `watchdog_diff` は deny。見直しの条件: 上流が `--no-textconv` を付け、path 無しでも path の deny が効くようになったとき。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#pi-agent-と-watchdog_diff-の-deny)。
    - **広げたいとき**: 規則を 1 行足す（`~/src/*` など）か、確認画面の「このセッション中は許可」を使う。足したら、判定表に例を足して試験を回す。Windows の Temp を全体に広げるなら、`/mnt/c/Users/<名前>/AppData/Local/Temp/*` と `…/Temp` を足す（他のアプリの一時ファイルも読めるようになる）。
  - `bash` の既定は **allow**。止めるものだけを、後ろに書いた規則で決める（後勝ち）。判定は 2 つの拡張の組み合わせで、役割を分ける: **deny と強制 ask はこの方針（`pi-permission-system`。tree-sitter で複合コマンドを分解し、1 コマンドずつ前方一致で照合する）**、**破壊的な操作（`git reset --hard`・`rm -rf` の危険な対象・`find -delete` など）の意味解析は `cc-safety-net`**（[規則](#cc-safety-net-の規則)）。
    - **deny**: `sudo`・`git push`・スクリプトをシェルへ渡す形（`sh`・`bash`・`sh -s` など）、**秘密を取るコマンド**（`gh auth token`・`gh secret set|list`・`bw get|list|export`・`op read`・`op item get`・`vault read`・`vault kv get`・`chezmoi secret`）、環境変数の一覧（`printenv`・`env` の単独。`printenv <名前>` は許す）、**グローバルな環境変更**（`pip`・`pipx`・`uv tool install`・`npm -g`・`pnpm add -g`・`yarn global add`・`mise use -g`・`brew install`・`cargo`・`go`・`gem` の `install`）。プロジェクト内の変更（`uv add`・`uv pip install`・`npm install <pkg>`・`mise use <tool>`）は止めない。既知の限界: `npm install foo -g` のようにフラグが後ろにある形は前方一致で拾えない。`path` の deny はファイルの読み書きを止めるだけで、コマンド経由の取得は止めないので別に置く。**`rm -rf` の一律 deny は置かない**: 過去のコマンドの 2.0% を誤って止めていた。`cc-safety-net` が対象（作業ツリーの外・home・root・`.git`）で判定する。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#グローバルな環境変更の-deny)。
    - **`git flow … publish` は deny**（2026-11-18）: feature 枝のリモートへの push になるため。`git flow`・`git -C * flow`・`git-flow` の 3 つの前置きごとに、`<前置き> publish *` と `<前置き> * publish *` の 6 規則（末尾の `*` は、直前の空白ごと省略できるので、引数なしの形も当たる）。**bash の規則の末尾に置く**（後勝ち。前にある `git flow * finish*`・`git -C * config*` の ask が、枝名に `finish`・`config` を含む publish の deny を上書きしてしまうため。独立した監査で見つかった）。種別（`feature`・`release` など）は列挙しない（`-v` などの前置きや独自の種別も止める）。**受容した誤検知**: 引数のどこかに語として `publish` を含む `git flow` も deny になる（枝名が `publish` そのものの `start`・`update`・`finish`、`-m`・`-M` のメッセージの語など。`*` は引用符をまたぐため、引数の中身までは区別できない。枝名やメッセージの語を変える。理由文にも書いてある）。**受容した限界**: `git -c <鍵>=<値> flow …` の前置きは規則に当たらない。`env`・`bash -c` などのラッパーの後ろは、ラッパーの床の確認（YOLO を切っているとき ask）になる。
    - **`nohup`（2026-11-17。利用者の指示）**: `nohup *` を理由つきの deny にした（長い処理は `bg_run` へ誘導する。YOLO でも効く）。**受容した限界**: 別のラッパーの後ろ・`bash -c` の中・末尾の `&` だけの常駐は止めない。囲い（pib）の中では、バックグラウンドのジョブはコマンドの終了で消える。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#nohup-の-deny-の実測)。
    - **強制 ask**（YOLO を切ると、毎回確認が出る）: ① 外部への投稿・変更（`gh` の `pr`・`issue`・`workflow`・`variable`・`gist` の変更系、`gh repo fork|rename|archive|unarchive`、`chezmoi apply|update`）、② 公開・配布・統合（`git flow integrate`・`git flow feature|release|hotfix|bugfix|support finish` = `develop`・`main` へのマージ（2026-11-11。`-C` 付き・`git-flow` 形も。feature 同士のマージと `develop` から feature への取り込みは allow）・`gh pr merge`・`gh release create|edit|delete|upload`・`gh repo create|edit|delete`・`gh gist create`・各種 `publish`・`twine upload`・`gem push`・`docker push`）、③ 履歴・設定の改変（`git rebase|filter-branch|update-ref -d|reflog expire|worktree remove|remote add|remote set-url`。`git config` はここに無い（下の「`git config`」。2026-11-15 に deny へ移した）。`git worktree remove` は、パスが `.tmp/worktrees/` の下で、`--force`・`-f`・`..` を含まないときだけ allow（git 自身が、未コミットの変更がある worktree の削除を断る）。実際の分類の順序は「最後に当たった規則が勝つ」ので、allow の例外は ask の後ろに置く）、④ 外部送信・永続化（`scp`・`sftp`・`ssh`・`rsync`・`socat`・`ncat`・`nc`・`telnet`・`aws s3 cp|sync`・`gsutil cp`・`az storage blob upload`・`crontab`・`at`・`batch`・`systemctl` の変更系・`systemd-run`・`fdisk`・`parted`）。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#git-worktree-remove)。
    - **`git config`（2026-11-15。利用者の指示）**: 書き込みは **deny**、名乗りの鍵（`user.name`・`user.email`）だけ ask、読み取り（`--get`・`--list` など）は allow、否定オプション（`--no-*`）は deny。`-C` 付きは ask。**受容した限界**: `git -c`・`GIT_CONFIG_COUNT` などの前置きは規則に当たらない。値に `user.name`・`user.email` を含む別の鍵の書き込みは、deny でなく名乗りの ask に当たる（人が全文を見て判断する）。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#git-config-の-deny-の根拠)。
    - **サブコマンドの前に付くオプションを読み飛ばすため、規則を広げてある**: `gh` と `chezmoi` は `gh *pr create*`・`chezmoi *apply*` の形（`gh -R o/r pr create`・`chezmoi --force apply` を拾う）。`git` は `git -C <dir> <サブコマンド>` の形を別に足す（過去のコマンドの 3.4% が `git -C` を使う）。広げた分は、余分に ask が出ることはあっても、見逃しは減る。`git` の ask に `git *rebase*` のような広い形を使わないのは、コミットメッセージや `--grep` の語まで拾うため（試験で確認する）。
    - **`gh api` の書き込み**は、撤去したフルガードの `check_gh_api_mutation`（意味解析）を再現できないので、`-X`・`--method`・`-f`・`-F`・`--field`・`--raw-field`・`--input` を含む形を ask にする近似にした（GraphQL の読み取り `-f query=…` も ask になる）。`gh *api *…` の形で、前置きオプション付き（`gh -R o/r api … --method POST`）も ask（2026-11-18）。
    - **受容するもの**: 変数経由・インラインコードでの迂回は検出しない（ガードは意図的な迂回を保証しない）。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#bash-の規則の出典)。
  - `path`（全ツール・bash 共通）の deny: `.env`・`*.env.*`（`*.env.example` は allow）・`~/.ssh`・`~/.aws`・`~/.gnupg`・`~/.netrc`・`~/.config/gh`・`~/.config/agents/websearch-keys.json`（検索の鍵ファイル。Bitwarden から同期される）・`~/.config/sops/age`（age 秘密鍵）・`~/.config/Bitwarden CLI`（`bw` のデータ）・`~/.zsh_history`・`~/.bash_history`（直接打った秘密が残りうる。2026-11-22）・秘密鍵（`*.pem`・`*.key`・`id_rsa*` など）。**pi 自身の認証情報・設定（`~/.pi/agent/` の認証・信頼・モデル設定・MCP の設定、`ayu/` = pi-rewind のスナップショット）も deny**（2026-11-10）。利用者はいつも拒否するものなので、ask にせず deny にして確認で待たせない（理由をモデルへ返す）。`sessions/`・`extensions/*/logs` は、振り返りの分析で読むことがあるので ask のまま。ディレクトリ自体の deny も併せて置く（上の「再帰への備え」）。
  - **`path` の deny は、pib の囲いの `hide`（`runner.toml`）と同じ集合に保つ**（2026-11-12）。食い違いは `test_pi_sandbox_runner` が検出する。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#path-の-deny-と-hide)。
  - **`path_write`（書き込みだけの deny。読み取りは許す）**: ファイルの道具は囲いの外で動き、これらは次のコマンド・次の起動から効く（囲いが外れる・方針が緩む・拡張やランチャーのコードが実行される）ため、次を拒否する。
    - **`~/.pi/agent/` の、pi が読み込む・実行するもの**（`settings.json`・`AGENTS.md`・`extensions/`・`agents/`・`bin/`・`tmp/` など）を 1 つずつ deny にする（`sessions/` は除く。許可リスト型にしない）。**chezmoi が `~/.pi/agent` へ配るものは、すべて deny に入っていることを試験で固定する**。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#pi-agent-の-deny-の置き方)。
    - **`~/.config/pi-sandbox/`**（囲いの設定。runner はコマンドごとに読む）。
    - **囲いの中で読み取り専用に見せるもの（`runner.toml` の `visible.read`）**: `~/.local/bin/`・mise・uv など。**一致は `test_pi_sandbox_runner` が固定する**。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#囲いの読み取り専用の一覧)。
    - 変えるのは利用者（chezmoi・mise・uv）。シェルの起動ファイル（`~/.bashrc` など）はまだ対象にしていない（[限界](sandbox/pi-sandbox-runner.md#保証しないこと限界)）。
    - **この保護は既定の場所に固定**: `pib` は、設定の場所の環境変数が既定と違うと、制御ファイルがリンクで外を指していると、起動しない。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#囲いの保護の固定)。
  - **全 deny に理由をつける**（2026-11-11）: `deny` の値は `{ "action": "deny", "reason": "…" }` と書ける。理由は、拒否の文に付いてエージェントへ届く（「なぜ拒否され、代わりに何をすべきか」を読める）。すべての deny に理由がある（件数は書かない。試験 `test_every_deny_rule_carries_a_reason` が全件を検査する）。
    **ask には、理由を付ける仕組みが無い**（拡張の docs: 理由は deny の値にだけ書ける）。確認の画面には、コマンドとパスだけが出る。そのため、「子が絶対にやってはいけない」操作は、理由つきの deny にする（無人の確認は 5 分で拒否され、止まる）。人が在席して承認したい操作（`gh` の変更系・`git rebase` など）だけを、ask に残す。
  - `mcp` は ask（検索の `websearch`・`agentcore-websearch`・`webfetch` と、T3 Code の読み取り・PR/Issue/リンク参照・表示・閲覧・描画・整理・監視・新規スレッド起動・子の起動などの 52 本だけ allow。上の「MCP 設定」と [T3 Code の MCP ツールの権限](#t3-code-の-mcp-ツールの権限)）、`skill` は allow。入れる拡張の自分のツール（`todo`・`ask_user_question`・`subagent`・`subagents_enable`・`bg_wait`）は毎回の確認を出さないよう allow。**`tool_search`（pi 組み込み）も allow**（2026-11-23。利用者の指示）。宣言されていないツール（MCP の `deferred`・`codemode` など）を探して、次の呼び出しに宣言するだけで、実行はしない。宣言されたツールの呼び出しは、そのツールごとの規則（`mcp` は ask など）で判定されるので、allow にしても**呼び出しの権限は広がらない**。**受容した点**: 検索は権限の規則を参照せず、登録済みの `deferred`・`codemode` のツールを列挙し、一致したものの名前と説明の先頭行を、ツール結果の本文としてモデルへ返す（pi 1.5.2 `dist/extensions/tool-search/tool.js` の `searchAndLoad`。確かめ済み）。つまり、**呼び出しが deny のツールでも、`deferred`・`codemode` なら、説明（外部の内容。MCP サーバ由来）が確認なしにモデルへ届き、宣言もされ得る**（呼び出しは各ツールの規則で止まる）。この機が配る MCP の既定は `direct` だが、利用者が足したサーバや T3 Code のツール（91 本）は `deferred` になりうる。上のどれにも当たらないツール（`*`）は ask。**pi 組み込みの MCP が足す資源のツール**（2026-11-24。利用者の承認）は、`list_mcp_resources`・`list_mcp_resource_templates` だけ allow（読み取り専用。資源の名前・URI・説明を返し、本文は読まない）。`read_mcp_resource`（本文を読む）と `codemode`（スクリプトを走らせる）は ask のまま（判定表で固定）。**受容した点**: (1) `server` を省くと、資源を持つ全サーバ（有効かつ `hidden` でないもの）へ一覧を要求する（資源は `resources/list`、テンプレートは `resources/templates/list`）。指定すると、そのサーバの 1 ページだけを取る。`mcp` 面のサーバ単位の ask を通らない。(2) `cursor` は、そのサーバが出した値かを照合せず、モデルが指定した文字列が（前後の空白を除いて）そのまま対象サーバへ渡る（対象は構成済みのサーバに限られ、接続先は変わらない）。(3) 結果（資源の名前・URI・説明）はサーバ由来の信頼できない内容で、`readOnlyHint` はその信頼性を保証しない（プロンプトインジェクションの入力になりうる）。ファイル系のサーバが `file://` の URI を出すと、`path` の deny の対象のパスや存在が、本文を読まずにモデルへ届きうる（本文は `read_mcp_resource` の ask で止まる）。利用者が足した第三者サーバでも同じ。分類の根拠・出典は [research](../research/agents/permission-policy-rationale-2026-11.md#pi-組み込みの-mcp-が足すツールの分類2026-11-24)。
  - **`subagent_launch` は allow**（2026-11-09。当面の運用）。workflow の子の起動ごとの確認を出さないため。`gate`・`acceptance.verify` のシェルはこの時点で検査されないので、運用では使わない。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#subagent_launch)。
  - 子と親の連絡用のツール（`contact_supervisor`・`intercom`・`structured_output`・`subagent_command`）も allow。YOLO を切ると、規則の無いツールは `*` の ask になり、子が進捗を連絡するたびに確認が出るため。
  - 追加の 4 つの package のツール（下の「追加の 4 つの package」）: `bg_status`・`bg_kill`・`plan_mode_question`・`plan_mode_complete`・`goal_complete`・`goal_blocked`・`goal_wait` も allow（状態を記録するだけ、または読み取りのツール）。`bg_run` は allow にしない（`shellTools` で bash と同じ判定に通す）。
- **`shellTools`（マージ）**: `pi-permission-policy.json` の `shellTools`（`bg_run` の `commandArgument: command`・`workdirArgument: cwd`）を、既存の `shellTools` にマージする。リポジトリが持つキーだけをこの値にし、利用者が足した他のキーは保つ（`permission`・`commandEffects` は従来どおり置き換え）。
- **YOLO mode**: 拡張の `/permission-system` で ON / OFF できる。ON は ask を自動で承認するだけで、**明示の deny は YOLO でも効く**（上の deny・`path` の deny は残る）。**強制 ask は表現できない**（YOLO が全部 allow に戻す。`cc-safety-net` も ask にはできない）ので、強制 ask を使うなら YOLO を切る。切り替えた `yoloMode` は `chezmoi apply` で戻らない（上の「実行時の値は保つ」）。
  - **`/sandbox`（ローカルの拡張）は、囲いに合わせて YOLO も切り替える**（囲いあり = ON、囲いなし = OFF。[ADR-0040](../adr/0040-pi-sandbox-session-toggle.md)。仕様は [実行中の切り替え](sandbox/pi-sandbox-runner.md#実行中の切り替え)）。囲いの外の強制 ask は YOLO で働かなくなる。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#sandbox-と-yolo-の連動)。
  - **YOLO を切ると、規則に無くても ask になるもの**（拡張の `docs/configuration.md` の「Fail-closed behavior」）: `bash -c`・`eval`（中身を再解析しない）、`sudo`・`env`・`xargs`・`nohup`・`parallel`・`watch`・`flock`・`find -exec` など別のコマンドを実行する前置き（このうち `sudo`・`nohup` は、それぞれ先頭に置いた形が明示の deny に当たる。床はそれ以外の形に残る）（`time`・`timeout`・`nice`・`stdbuf`・`setsid` は中のコマンドで判定）、パースできないコマンド（例: heredoc と `2>&1` とパイプを同時に使う形）。YOLO が入っているときは、これらも自動承認されていた。確認画面の「このセッション中は許可」で、同じパターンは再質問されない。
- **確認で待たせない方針（2026-11-10）**: 確認（ask）が利用者待ちで自律稼働を止めるのを避ける。① **誰も答えない確認は 5 分で拒否して先へ進む**（`promptTimeoutMs: 300000`。初期値だけで、変えた値は apply で戻らない）。② **いつも拒否するものは ask にせず deny にする**（上の `path`）。③ 許可リストで、確認を出さない読み取りを増やす（上の `external_directory`）。④ エージェントの振る舞い（指示に追記）: 確認が出る操作を避ける（`cd` を絶対パスで書くのは上流の不具合の[一時対処](temporary-workarounds.md#pi-permission-system-の-cd-先の誤判定)）。拒否・誰も答えなかった操作は繰り返さず、他の作業を続けて、最後に「承認待ち」として一覧で報告する。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#確認で待たせない方針)。
- **承認待ちの通知（BEL）**: 確認ダイアログが開くとき、端末の BEL を鳴らす（`promptNotifications: ["bell"]`。初期値だけで、変えた値は apply で戻らない）。Zed の Terminal Threads や Orca が、フォーカス外の端末の BEL を通知にする。`ask_user_question`（rpiv-ask-user-question）も、質問を待つときに BEL を 1 回鳴らす（拡張の仕様）。**完了時の BEL は、評価した package（pi-notify 系）に無い**。
- **方針の変え方**: `pi-permission-policy.json` を編集して `chezmoi apply`（書式は拡張の docs の configuration.md。後に書いた規則が勝つので、全許可の `*` は先頭、例外は後ろに置く）。**変えたら、判定表（`test/agents/pi_stock/permission_cases.json`）に例を足して試験を回す**（[権限の方針の試験](#権限の方針の試験)）。`~/.pi/agent/extensions/pi-permission-system/config.json` を手で書き換えた `permission` は、次の apply でリポジトリの値へ戻る。
- bash のパターンは 1 コマンドずつ照合される（`curl … | sh` のような連結は書けない）。パイプ先の `sh`・`bash` を deny して防ぐ。

### cc-safety-net の規則

package `cc-safety-net` は、破壊的なコマンド（`git reset --hard`・`rm -rf` の危険な対象・`find -delete`）と秘密のパスへのアクセスを、コマンドを解析して止める（設定なしで動く。標準の水準）。リポジトリは次の 2 つを足す。配り先は `~/.cc-safety-net/rules/`。

- **`git push` を全て止める**（`home/dot_cc-safety-net/rules/dotfiles-guard/rulebook.json`）。`pi-permission-policy.json` の `git push*` は前方一致なので `git -C <dir> push` を読み飛ばせない。`cc-safety-net` は git の前置きオプション（`-C`・`-c`・`--git-dir` など）を読み飛ばしてサブコマンドを見るので、これらと、`env`・`xargs`・`bash -c`・`$(…)` 経由も止める。`git log --grep push` や `git commit -m 'fix push'` は止めない（試験で確認）。
  - 規則は `rulebook_version: 1` の形（`subcommand: "push"`・`block_args: ["push"]`。サブコマンド自身を必ず現れる引数にして、全ての push を止める）。`rulebook_version: 2` の `match.command_path` は `git -C <dir>` を読み飛ばせず、見逃すので使わない。
  - 止めるだけで、確認（ask）にはできない（`cc-safety-net` の仕様）。
- **`bg_run` を shell ツールとして宣言する**（`rule.json` の `command_tools`）。pi-background の `bg_run` は `cc-safety-net` が知らない shell ツールで、宣言しないと中のコマンドを解析しない（`cc-safety-net` の docs の記述。宣言前の挙動は実機で確かめていない）。**宣言した後は、実機で `bg_run` も block された**（2026-11-10。作業ツリーの中の使い捨てリポジトリで `git reset --hard` を、`bash` と `bg_run` のどちらでも止めた）。**試験の注意**: `/tmp` の一時リポジトリでは、`cc-safety-net` が「一時リポジトリの緩和」で `git reset --hard` を通す。最初の試験（2026-11-09。`/tmp` で実行されたのを「解析されない」と読んだ）はこの緩和に当たっていて無効だった。block を確かめる試験は、作業ツリーの中（`.tmp/` など）で行う。`pi-permission-system` は `shellTools` で `bg_run` にも効く。
- 配備した規則の確認は `cc-safety-net rule verify`（`$schema` を足すことがある）と `rule list`。規則を足すときは、rulebook に書いて、判定表に例を足す。

### 権限の方針の試験

`test/test_pi_permission_decisions.py` が、方針を**実際の判定エンジンに通して**、表 `test/agents/pi_stock/permission_cases.json`（コマンド → 判定）と照合する。規則の書き間違い・通常の作業を止める誤判定・危険な形の見逃しを、開発の段階で見つけるため。

- `pi-permission-system` の判定エンジンを、YOLO を切った状態で直接呼ぶ（`test/agents/pi_stock/permission_check.mjs`）。bash は複合コマンドの分解とラッパーの床（`<opaque-bash-wrapper>` など）を含む。`cc-safety-net` は `explain` に、リポジトリの規則を `CC_SAFETY_NET_HOME` で渡して通す。
- 方針の bash の規則は、表のどれかの例が当たること（当たらない規則は書き間違いか、表の不足）を検査する。
- プロジェクト単位の設定（下の節）が、グローバルの方針と合成されることも確かめる。
- **範囲外**: bash のトークンを `path` と `external_directory` へ投影するゲート（`cat <秘密のパス>` など。規則の評価だけは surface の表で見る）。エンジンの内部 API を直接呼ぶので、package の版を上げたときに壊れることがある（版は `pi-stock-packages` で固定）。pi の package が無い環境では skip する（skip は通過ではない）。
- **ゲートに見えない出力先**（2026-11-16）: bash のトークンの投影は、コマンドに**明示したパス**（引数とリダイレクト先）を取り出す。出力先が設定や既定で決まるコマンドは、推定しない。`git flow feature start x --worktree` は、`gitflow.worktreePath` の既定が作業ツリーの外（`../<repo>-worktrees/`）で、別の repo で実際に外へ作られた。判定表の `access` で確かめたのは、**外部パスの投影結果**だけである（`git worktree add /opt/wt/x` は外のパス 1 件が `unproven`、引数にパスが無い `git flow feature start x --worktree` と内部のパスの `git worktree add .tmp/worktrees/x` は、外部パスが 0 件）。`[]` は「外部パスとして出ない」の意味で、実ゲートで確認が出ないことまでは証明しない（実ゲートは判定表の範囲外）。対策は、パスを引数に出させることではなく、**設定の既定を作業ツリーの中にすること**（`home/dot_config/git/config.tmpl` の `[gitflow] worktreePath`。主 worktree のルート基準。[ブランチモデル](development.md#ブランチモデルai-pr--develop-auto-merge)）と、常設の指示で「出力先が既定で決まるコマンドは、実行前に確かめる」こと。`git flow * start` を「引数に `.tmp/` が無ければ deny」にする案は、この repo の通常の操作（引数にパスが無い）を止めるので採らない。

### プロジェクト単位でデータセットを読み取り専用にする

作業ツリーの外にあるデータセット（例: `/data/datasets`）を、**そのプロジェクトでだけ**、読み取りを確認なしにし、書き込みは確認（ask）のままにする手順。グローバルの方針は `/tmp/*` だけを事前許可している。前提は YOLO を切っていること（YOLO が入っていると ask は自動承認され、事前許可の意味がない）。

1. プロジェクトを、pi の信頼の確認で許可しておく。**未信頼のプロジェクトの設定は読まれない**（警告が出る。拡張の仕様。プロジェクトの設定でグローバルの方針を緩められないようにするため）。
2. プロジェクトの直下に `.pi/extensions/pi-permission-system/config.json` を作る。

   ```json
   {
     "permission": {
       "external_directory_read": { "/data/datasets/*": "allow" }
     }
   }
   ```

3. pi を起動し直す（または `/reload`）。

- **パターンの書き方**: 末尾の `/*` が必須。`*` はサブディレクトリを含めて一致する（`**` は書かない）。`/data/datasets` 自体（ディレクトリの一覧など）も許すなら、`"/data/datasets": "allow"` を足す。`~/datasets/*` のように `~` も使える。シンボリックリンクは、参照したパスと実体のどちらにも一致する（作業ツリー内のリンクが外を指す場合も、実体で「外」と判定される）。
- **読み取りだけ許し、書き込みは禁止にする**: `external_directory_write` に同じパターンを `deny` で足す。足さなければ、書き込みはグローバルの `ask` のまま。
- **bash からの読み取り**: `cat`・`head`・`tail`・`wc`・`rg`・`grep`・`ls`・`sed`・`awk`・`sort`・`diff`・`stat`・`find` などの読み取り専用のコマンドと、`read`・`grep`・`find`・`ls` のツールは、読み取りと分かるので許可される。`python train.py --data /data/datasets/x` のように**読み書きを判別できない**ものは、書き込みの面も見て ask になる。確認画面の「このセッション中は許可」で通すか、書き込みも許すなら `external_directory`（読みと書きの両方）を使う。
- **他の判定は変わらない**: `path` の deny（`.env`・秘密鍵など）は、この許可よりも優先して効く。
- 確認済み: グローバルの方針との合成（読みは許可・書きは ask・他の場所は ask）と書き込みの deny は `test_pi_permission_decisions.py` の表（`project`・`project_deny_write`）。bash 経由の判別は拡張の docs による（実機では未確認）。

### MCP 設定

- `~/.pi/agent/mcp.json` を `modify_mcp.json.py.tmpl`が配る。`[[mcp]]`（`clis` に `pi` を含むもの）から `mcpServers` を作る。仕様は [MCP サーバの設定](mcp-servers.md)。
- 宣言したサーバだけを更新し（`command` / `args`）、利用者が足したサーバと利用者のキーは保つ。壊れた JSON は触らない。何度流しても同じ結果。
- **package の一覧の変更**: `pi-web-access` を外した（家の検索は自作の MCP `websearch`）。`pi-mcp-adapter` は 2026-11-17 に、会社 PC からも外した（どの機も pi 組み込みの MCP。[理由](mcp-servers.md#pi-mcp-adapter-を使わない理由2026-11-17)）。評価は [記録](../research/agents/pi-stock-packages-evaluation-2026-11.md)。
- **permission**: `mcp` は `"*": "ask"` のまま、`websearch`・`agentcore-websearch`（サーバ名だけのルール）を allow。他の MCP は ask。 T3 Code のツールは、[別に決めている](#t3-code-の-mcp-ツールの権限)。
- **未確認**（実機）: permission-system は `mcp` に allow が 1 つでもあると `mcp_status` などの探索系を自動で allow にする、と docs にある。実挙動は未確認。

### T3 Code の MCP ツールの権限

2026-11-19（2026-11-21 に allow を 21 本から 39 本へ、2026-11-28 に T3 のツール拡充に合わせて 91 本中 allow 52 本・ask 39 本へ整理）。T3 Code の中で pi を動かすと、T3 が MCP のツール（91 本。pi では `mcp__t3-code__<名前>`）を足す。`mcp.json` に無いサーバなので、権限の判定は名前を最初の `__` で分け、`t3-code_<名前>`・`t3-code:<名前>`・`t3-code`・`<名前>`・完全名・`mcp_call` と、面全体の `mcp` の 7 つを照合する（拡張 42.0.0 の `createPiMcpToolTargets` と `normalizeMcpTargets`）。既定は ask（`"*": "ask"`）。

- **ツールごとに allow する**（`t3-code:<名前>`）。サーバ単位の `t3-code` の allow は、全ツールと将来の追加分まで通すので置かない（試験で固定）。名前単位の規則なので、**引数（対象のスレッド・URL・パス）は区別できない**。
- **allow は 52 本**。基準は、読み取り・PR/Issue/リンク参照・表示・ブラウザの閲覧・HTML の描画・元に戻せる整理・PR/背景監視・新規スレッド起動・自分の子の起動と取消（承認された件数は根拠にしない）。**外への送信は防がない**（下の「プロンプトインジェクションによる外部送信」。利用者がリスクを受容した）。
  - 読み取り・PR/Issue/リンク参照 25: `orchestrator_capabilities`・`task_status`・`t3_thread_list`・`t3_thread_search`・`t3_thread_read`・`t3_thread_wait`・`t3_worktree_list`・`t3_worktree_status`・`list_thread_pull_requests`・`read_pull_request_guide`・`t3_project_list`・`t3_project_read`・`t3_environment_read`・`t3_environment_links`・`list_scheduled_tasks`・`t3_preview_list`・`preview_status`・`t3_theme_read`・`device_list`・`pull_request_read`・`pull_request_list`・`ci_logs`・`list_issues`・`read_issue`・`list_thread_issues`
  - 表示だけ 1: `send_to_user`
  - ブラウザの付随操作 2: `preview_wait_for`（待つだけ）・`t3_preview_close`（このスレッドが持つタブを閉じるだけ）
  - **ブラウザの閲覧 7**（2026-11-21。利用者の指示は「ブラウザ操作は閲覧系は allow で、操作系は ask」という分類。どのツールを閲覧系に入れるかは実装者の判断で、`preview_resize`・`preview_set_appearance` を含めた）。性質で 3 つに分けて、記録する:
    - 閲覧: `preview_open`・`preview_navigate`（任意の URL を開く。開いた時点で、ページのスクリプトが動く）。`preview_open` の `profileId` の既定は利用者のプロファイルで、現在のタブを再利用できる。ログイン済みのページを読めるか、サーバ側のブラウザにログイン情報があるかは**未確認**（利用者は、これを受容して allow にした）。
    - 取得・保存: `preview_snapshot`（ページの状態・要素を返す。利用者が操作中のタブにも使える。画像を保存できる）・`preview_recording_start`・`preview_recording_stop`（録画のファイルへの、ローカルのパスを返す。最大 50 MiB）。
    - 表示状態の変更: `preview_resize`・`preview_set_appearance`。2026-11-19 に reviewer の指摘で ask に戻したが、実装者の判断で閲覧系に含めて戻した（利用者の個別の指定ではない）。開いたページのスクリプトを `resize`・`matchMedia` で動かし、通信につながりうるリスクは残る。
    - 操作系 3（`preview_act`・`preview_evaluate`・`preview_dialog`）は ask。
  - **HTML の描画 2**（同。利用者の指示は「描画のみでフォーム送信などを想定してないものであれば allow」。**この条件は強制されない**）: `html_preview`・`html_render`。モデルが書いた HTML は、外部へ要求を送れる（下の「T3 のソースで確かめたこと」と、「プロンプトインジェクションによる外部送信」）。ローカルの画像・`.html` の読み取りの範囲も、下に記録した。
  - **元に戻せる整理・監視 11**（2026-11-21・2026-11-28 更新。利用者の指示）: `t3_thread_update`・`t3_thread_organize`・`link_pull_request`・`link_pull_requests`・`unlink_pull_request`・`unlink_pull_requests`・`watch_pull_request`・`unwatch_pull_request`・`link_issue`・`unlink_issue`・`t3_background_wait`。`threadId` を指定すれば、**ほかのスレッドにも効く**（`t3_thread_organize` の `archive`・`settle` など）。`watch_pull_request` はツール定義上チェック・レビュー完了で自動起床させる監視設定のみで PR マージ等の外部変更は行わず、`unwatch_pull_request` で解除できる（T3 ソース未確認・利用者受容）。`link_issue` / `unlink_issue` はスレッドとの紐づけのみで Issue 本体は変えない。`t3_background_wait` は進行中作業の完了待ち状態を示すだけ。**戻せないもの**: `t3_thread_update` の改名は元のタイトルが失われる（事前に読めるので手で戻せる）。`link_pull_request` は PR のマージでスレッドを settle する副作用がある。
  - **新規スレッド起動・自分の子の起動と取消 4**（2026-11-21・2026-11-28 更新。利用者の指示）:
    - `t3_thread_launch`・`create_threads`: 新しいトップレベルスレッドを作成する（2026-11-28 にモバイルからの確認タイムアウト解消のため利用者承認で allow 化）。ツール定義上は既存スレッドの履歴や走行中ターンには触れず、起動先の権限モードは呼び手より広くならない（T3 ソース未確認・利用者受容）。**受容した点**: 新規スレッドの初回実行で API トークン消費が起き、また `workspaceStrategy` 省略時はプロジェクトルートに紐づく（誤起動しても既存スレッドを止めず、不要ならアーカイブ/削除で片付けられる）。
    - `delegate_task`: 子を起動する。**別プロバイダのモデルも指定でき**、親が組み立てた `task` の文字列が、選んだプロバイダへ渡る（親の履歴は自動では継がない。「秘密を書かない」は指示で、検査ではない）。子の実行モードは、親より広くできない（`resolveRuntimeMode`。`runtime_mode_escalation_denied`。既定は親のモードを継ぐ。継いだモードを委譲先が提供しなければ、提供する最も広いモードに下がる。明示したモードは、提供しなければ拒否される。このスレッドは `full-access`）。狭いモードは、人の承認で止まるだけで、読み取り専用ではない。子が pi の方針・`pib` の囲いを継ぐかは、**未確認**（継ぐものとして扱わない）。
    - `task_cancel`: **呼び手のスレッドが起動したタスクだけ**止められる（T3 のソース: `readTask` が `candidate.threadId === scope.thread.threadId` と `origin === "app_owned"` で絞り、無ければ `task_not_found`）。止める範囲は、そのタスクの子と、その下のすべてのタスク（子スレッドの後の実行・待ち行列・孫の委譲・PR の監視を含む）。停止の前に、子とその下のスレッドの実行モード・対話モードが、親より広くないかを検査する（`assertStoppable`）。
  - **確実とは言い切れないが、リスクを受容して allow にした例外 3 本**（2026-11-19。実装者の判断）:
    `t3_thread_read` は、子の最終結果を読むと「配信済み」になる（`task_status` も同じ）。任意のスレッドを読めるので、ほかのスレッドの子の結果を読んだとき、その親の完了の通知に影響するかが未確認。毎回使う読み取りで、ask にすると allow を足した意味が薄れるため残した。害は、通知が先に「配信済み」になる程度と見たが、裏付けは無い。最初の監査の reviewer は ask を勧めた。`t3_environment_read` は、返却項目と秘匿化が未確認（「identity と preferences の読み取り」という定義だけが根拠）。`send_to_user` は、Markdown が外部画像を取得するかが未確認（通常の返信と同じ表示の経路なら、新しい経路ではない）。いずれも、T3 側の改修後に確かめ、危ういと分かれば ask に戻す。
- **ask は 39 本**:
  - **既存スレッドへの送信・停止・変更 7**: `t3_thread_send`・`t3_thread_send_attachments`・`t3_thread_interrupt`・`t3_workflow_stop`・`t3_thread_transfer`・`t3_thread_configure`・`t3_queue`。**ほかのスレッドに触れる**（走行中のターンの中断・再開、待ち行列のメッセージの編集・取消、文脈への書き込み、モデルやプロバイダの変更）。名前単位の許可は対象のスレッドを区別できず、呼び手が `full-access` だと「呼び手より広い権限の相手へは送れない」歯止めも効かないため ask を維持する。
  - **GitHub 書き込み系（PR / Issue / CI 再実行） 9**: `pull_request_create`・`pull_request_update`・`pull_request_respond`・`pull_request_review`・`pull_request_merge`・`ci_rerun`・`create_issue`・`comment_on_issue`・`set_issue_state`。外部リポジトリへ書き込む操作のため、`gh` の書き込み系と同じく ask を維持する（このリポジトリの `develop` PR は専用入口 `scripts/ai_pr.py` 経由で行う）。
  - **スケジュール 3**（`schedule_task`・`delete_scheduled_task`・`run_scheduled_task_now`）、**設定・プロジェクト・環境リンクの変更 9**（`t3_project_create`・`t3_project_update`・`t3_project_delete`・`t3_project_clone`・`t3_environment_preferences_update`・`t3_theme_set`・`t3_environment_link`・`t3_environment_unlink`・`t3_worktree_handoff`）。`t3_environment_preferences_update` は全スレッドに効く常設の指示を書き換えられ、`t3_environment_link` / `unlink` は別マシン接続を変えるため ask を維持する。
  - **ブラウザの操作系 3**（利用者の指示）: `preview_act`（クリック・入力・アップロードなど）・`preview_evaluate`（ページでスクリプトを実行）・`preview_dialog`（ダイアログの承認・却下）。
  - **その他 8**（別途検討）: `request_secret`・`t3_pending_request`・`write_pull_request_guides`・`t3_attachment_prepare_upload`・`t3_attachment_discard`・`device_open`・`device_close`・`device_screenshot`。
- **T3 のソースで確かめたこと**（2026-11-21。利用者の fork の `apps/server`・`apps/web`。T3 の改修は入れていない前提で読んだ。読んだ範囲の記録で、全体の保証ではない）:
  - **`html_render`** は、利用者のローカルのブラウザの iframe で描く（`BrowserDocumentFrame.tsx` の `HtmlRenderDocument`。`sandbox="allow-scripts allow-forms"`。`allow-same-origin` が無いので、ページは opaque origin になり、T3 の画面の cookie・保存領域へ直接は触れない）。ページは T3 のサーバが `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-downloads` で配る（`http.ts`）。**`connect-src`・`img-src`・`form-action` の制限は無い**。外部の描画サービスへは委託しないが、描画の実行時に、ページが外部へ要求を送れる。
  - **`html_preview`** は、T3 のホストの headless Chrome で描く（`htmlRender/headlessChrome.ts`）。要求は `publicProxy` を通り、**ループバック・プライベート・リンクローカルなどの宛先（`10/8`・`172.16/12`・`192.168/16`・`127/8`・`169.254/16`・`100.64/10` など）を拒否する**（DNS の細工への備えを含む。この宛先制限は維持される）。公開の宛先へは届く。メインのフレームを固定し、ポップアップは禁止。全通信がこのプロキシを通るかは、読んでいない（上の宛先制限が効くのは、プロキシを経由する要求）。
  - **`preview_*`** のブラウザ: `apps/server/src/preview` を `proxy`・`blocklist`・`loopback` などで検索した範囲では、`publicProxy` のような宛先の制限は見つからなかった（開発サーバの確認が目的で、ローカルへ届く）。`t3_preview_list` の定義は、「自動化できるのは `runtime:'server'` のタブだけで、ほかは利用者のローカルのデスクトップのアプリにある」と述べる。実装は Playwright で Chrome を操作する（`preview/DesktopBrowserChannel.ts` の注釈）。サーバ側のタブとデスクトップ側のタブの経路の違いは、読んでいない。
  - **ページ本体の `path`**（`htmlRender/HtmlRender.ts` の `readPageFile`）: 絶対パスで、ネットワークのパスでなく、実体が `/\.html?$/i` に一致し（`.html`・`.htm`）、T3 内部のパスでなく、リンクをたどらずに開いて、ハードリンクが 1 つだけの通常のファイルで、サイズの上限以下のものに限る。
  - **埋め込まれるローカル画像**（同 `inlineLocalImages`。`html`・`path` どちらの入力にも `prepare` が適用される）: HTML 中の絶対パスの文字列で、拡張子が `png`・`jpg`・`jpeg`・`gif`・`webp`・`avif`・`svg`・`bmp`・`ico` のものを、ファイルの先頭のバイトで画像と確かめて（`isImageBytes`。確かめる形式は PNG・JPEG・GIF・ICO・BMP・WEBP・AVIF。拡張子の候補にある SVG の扱いは未確認。全部は読んでいない）、1 枚 10 MiB まで（事前の `stat` と、読み取り量の指定）を data URI に埋め込む。**`readPageFile` にある T3 内部のパス・ハードリンク・リンク先の検査は、この経路には無い**（`fileSystem.stat`・`stream` で読む）。T3 のサーバの権限で読める画像を、場所を絞らずに埋め込める。`html_render` の描画が同じ `prepare` を通るかは、未確認。pi の `path` の deny は、MCP の名前の判定には掛からない。
  - したがって、T3 が内容を外部へ送るのではないが、**モデルが書いた HTML や URL は、外部のホストへ要求を送れる**。
- **プロンプトインジェクションによる外部送信は、防がない（リスクを受容。2026-11-21。利用者の判断）**: ブラウザ・描画の 4 本（`preview_open`・`preview_navigate`・`html_preview`・`html_render`）は、モデルが書いた URL・HTML が、LLM プロバイダ以外の、各ツールから到達できるホストへ要求を送れる。悪意のあるページやファイルの指示に従ったモデルが、見た内容（会話・読んだファイル）を URL やフォームに載せて送る経路（プロンプトインジェクション）が成り立つ。利用者は、当初の条件（「描画のみでフォーム送信などを想定しないもの」）が強制されないこと、今回検討した追加の制限・監視が未実装であることを聞いたうえで、次のように述べ、4 本を allow に戻すことに「OK」と答えた（原文）: 「プロンプトインジェクション対策するとかなり制限することになる気がします。pi ハーネス側も対策するのを諦めました。」。
  - **受容した範囲**: 4 本を、家も仕事の機も allow にし、今回検討した直接送信（各ツールから到達できる、LLM プロバイダ以外のホストへの送信）への、追加の制限・監視は導入しない。既存の保護（`html_preview` の `publicProxy` の宛先制限、`pib` の囲いなど）は変更しない。これを、4 本の外へ広げた一般方針とは扱わない。
  - **変わらないもの**: 害を生む操作の deny（破壊的な操作など）と、秘密のファイル（`.env`・鍵・SSH の鍵など）の読み書きの deny（`permission.path`）は、プロンプトインジェクション対策とは別の理由（モデルの誤りを含む）で残す。この deny は、対象のファイル操作を、名前・パスの形で拒否する。環境変数、規則に一致しない秘密、T3 内部の読み取りや通信（`html_preview` の画像の埋め込みなど）は、この規則の対象外。外部送信の防止とは、結びつけない。
  - 利用者の発言（原文。T3 の責務の整理）: 「LLMプロバイダーが更にどこに渡すかはT3codeの責務外ですよね？ならT3側は問題なし。LLMプロバイダーの読み取り側を制限するのではなく、送信側を制限・監視する方針で。この方針だと？」。T3 の責務外かと尋ねたのは、LLM プロバイダから先の転送。
  - **見送った対策の候補**（未実施。効果は未検証。対象と、確かめる項目）は、`docs/research/agents/permission-policy-rationale-2026-11.md` の「見送った対策の候補」。
  - **通信の遮断**（`pib --offline`・`/sandbox offline`）は、T3 のツールに及ばない。YOLO では、ask も自動承認される。遮断が要る作業では、T3 のツールを使わない（対象のツールを無効化する、または deny にする）。
  - 未確認: 会社の方針が「T3 のブラウザ・描画」を禁じていないか（利用者が聞いた範囲は、内部の内容を外部へ送信しない、まで）。サーバ側のブラウザのプロファイルに、ログイン情報があるか。
- **注意**: T3 のツールは pi の囲い（sandbox）の外で動く。**deny にした MCP のツールは、モデルから隠れる**（対象のどれかに一致した最後の規則が deny なら隠す。拡張の `isToolFullyDenied`）ので、deny の理由に書いた案内は、モデルに届かない。
- 試験: 判定表の `t3_mcp`（91 本の分類）を、実ゲートの `normalizeInput`（対象の生成）と `evaluateAnyValue` に通して、規則が意図どおりに当たることを確かめる（駆動の `mcpTools`）。T3 のツールが増減したら、表と方針をそろえる。

### 追加の 4 つの package（background・plan mode・goal・rewind）

評価と決定は [評価の記録](../research/agents/pi-stock-packages-evaluation-2026-11.md)。いずれも `pi-stock-packages` で版を固定して参照する（コードは取り込まない。自作のコードも足さない）。表の `@narumitw/pi-btw` と `pi-show-token-rate` は後から足した 5 つ目・6 つ目（2026-11-09。見出しの「4 つ」は、他の節からの参照の見出しリンクを保つためそのままにした）。

| package | 役割 | 設定・permission |
| --- | --- | --- |
| `pi-background@0.4.2` | 背景シェル実行。`bg_run`・`bg_status`・`bg_kill`・`/bg`。bash が 120 秒を超えると自動で背景化し、終了で親を起こす | 設定項目は無い。`shellTools` に `bg_run`、`bg_status`・`bg_kill` は allow |
| `@narumitw/pi-plan-mode@0.60.0` | `/plan`。`tool_call` の block で読み取り専用にし、計画を保存・承認・実装する | `~/.pi/agent/pi-plan-mode.json`（下。stock だけ）。`plan_mode_question`・`plan_mode_complete` は allow |
| `@narumitw/pi-goal@0.55.0` | `/goal`。目的を自走で続ける。token 予算・自動応答数・無進捗の上限 | 既定のまま（`pi-goal.json` は配らない）。`goal_complete`・`goal_blocked`・`goal_wait` は allow |
| `@narumitw/pi-btw@0.63.5` | `/btw <質問>`。本体と別のスレッドで質問する（モデル・思考レベルは別に指定可）。ツールは登録せず、モデル呼び出しもツールなし。本体へは明示したときだけ戻せる | 既定のまま（`pi-btw.json` は配らない）。ツールを足さないので permission は不要 |
| `pi-show-token-rate@0.3.0` | ステータス行に TPS（ストリーム中は直近の窓の値）と TTFT を出す。コマンド `/token-rate` で表示を切り替える。ツールは登録しない。ファイル・ネットワーク・子プロセスを使わない | 設定ファイルは配らない（既定のまま）。permission は不要。自作の `speed` は stock では配らないので、ステータスの競合は無い |
| `@ayulab/pi-rewind@0.4.6` | `/rewind`・`/checkpoint`。ターンごとの作業ツリーのスナップショットを、別の bare repo に保存する（利用者の `.git` には書かない） | ツールを足さないので permission は不要 |

- **plan mode の設定**: `home/dot_pi/agent/modify_pi-plan-mode.json.py.tmpl` が `~/.pi/agent/pi-plan-mode.json` を配る。拡張が `/plan settings` で書き換えるので、既存のキーはすべて保ち、次の 2 つだけ無いときに補う。`defaultPlanTools` = `["read","bash","grep","find","ls","ask_user_question"]` に検索・取得 MCP の完全名 5 つ（`mcp__websearch__web_search`・`mcp__websearch__fetch_page`・`mcp__websearch__search_papers`・`mcp__agentcore_websearch__web_search_tool__WebSearch`・`mcp__webfetch__fetch`）を足したもの（許可リストは完全一致の名前だけ。この 5 つは [MCP の `pi_exposure = "direct"`](mcp-servers.md#pi_exposurepi-への見せ方) でモデルへ直接見せている。**既存の `defaultPlanTools` を持つファイルにも**、無い名前だけ末尾へ追記する（和集合。順序・利用者の名前は保つ。リストでない値は触らない）。`subagent` は入れない。子は別プロセスで plan mode の block が及ばないため）、`defaultPlanExportPath` = `.tmp/keep/plan/`（既定の `PLAN.md` で作業ツリーを汚さない）。拡張の側で `grep`・`find`・`ls` を使うには pi 本体の settings での有効化が要る（未実施）。
- **goal の運用**: 設定は拡張の既定（`continuationLimits.automaticTurns` = 25・`noProgressTurns` = 3・`rpc.enabled` = false・`retryUsageLimits` = false）。**`/goal` は必ず `--tokens` つきで使う**（例: `/goal --tokens 500k <目的>`）。**時間の上限は無い**ので、離席中は外側の `timeout` と合わせる。
- **限界**:
  - `bg_run` は、`cc-safety-net` の tool 名の既定（`bash`・`powershell` だけ）には入っていないが、`rule.json` の `command_tools` で宣言すれば解析される（[cc-safety-net の規則](#cc-safety-net-の規則)。宣言した状態で、`bg_run` 経由の `git reset --hard` が block されることを実機で確かめた）。`pi-permission-system` の deny・ask は `shellTools` 経由で効く。
  - pi-background の自動背景化は、pi 組み込みの bash のときだけ効く。**bash を置き換える拡張（サンドボックス系・`pi-patty-bg-tasks` など）を入れない**。入れると無効になる。pi を閉じると実行中の job は死ぬ。
  - `/goal` の完了は同じエージェントの**自己申告**（`goal_complete`）。独立した検証ではない。独立性が要るときは review の子を手順に入れる。
  - `pi-rewind` は **GPL-3.0**。npm で参照するだけで、このリポジトリにコードを取り込まない。戻せるのは作業ツリーのファイルだけ（`git commit`・ブランチ操作・push は戻らない）。
  - **`pi-rewind` の警告「Checkpoint failed: Command failed with exit code 1」（2026-11-10 に確認）**: `/reload` の直後のターンで出る。警告が出たターンは巻き戻しの地点にならないが、データは失われない。上流はアーカイブ済みで直る見込みはない。利用者が `/rewind` を使う予定なので拡張は残し、毎ターン出るようなら（変更の有無に依らず）外すか代わりを探す。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#pi-rewind-の警告の調査)。
  - **`pi-rewind` が戻せるのは、pi を起動した作業ツリーだけ**（README の「Nested repositories」）: 入れ子の git リポジトリは、外側のスナップショットから除外され、戻されない。
    このリポジトリの実装は `.tmp/worktrees/<名前>/`（入れ子の worktree）で行い、`.tmp/` は `.gitignore` の対象でもある。**本体（`develop`）から起動した pi の `/rewind` は、worktree の中の編集を戻さない**。worktree の編集を戻したいときは、その worktree のルートで pi を起動するか、git（細かいコミット）で戻す。
- **導入の条件（実機での確認。すべて未確認）**:
  - pi-rewind: worktree の中で `/rewind` して、`git status`・`git reflog`・`git stash list` が変わらないこと。
  - pi-background: 12 分のコマンドで、終了時に親が起きること。
  - pi-btw: `chezmoi apply` 後に pi 1.5.0 が package を取得して `/btw` が動くこと。Orca の端末での表示。`/plan`・`/goal` との共存。**質問と選んだ文脈は、選んだモデルの提供元へ送られる**（README の記述。未検証）。
  - pi-show-token-rate: `chezmoi apply` 後に pi 1.5.0 が package を取得してステータス行に出ること。Copilot 経由（reasoning がストリームに出ない場合）で数値が極端に過小にならないこと。Orca の端末での表示。他のステータス表示と競合しないこと。（すべて未確認）
  - plan と goal: permission-system との `tool_call` の実行順（plan mode が block する呼び出しで ask が先に出ないか）。

### 拡張の追加と削除

`home/.chezmoitemplates/pi-stock-packages` を編集して `chezmoi apply`（1 行に 1 つ、`npm:<名前>@<版>`）。
版を固定した npm の package は再取得されない。版を上げるときは書き換える。

### 自作の拡張の置き場

自作の拡張（[ADR-0031](../adr/0031-evaluate-existing-extensions-first.md) の例外の一覧にあるもの）は、先例（`pi-permission-explain`・`pi-sandbox-toggle`・`t3-usage-status`。2026-11-19 にここへ記録）に従う。

- **置き場**: `home/dot_pi/agent/local-packages/<名前>/`（配備先は `~/.pi/agent/local-packages/<名前>/`）。pi の package の形で、`package.json` の `pi.extensions` が実装の入口を指す（例: `./src/index.ts`）。本体が提供する依存は `dependencies` に入れず、使う場合は `peerDependencies`（`optional`）にする。
- **読み込み**: `pi-stock-packages` に `./local-packages/<名前>` を 1 行足す（`settings.json` からの相対パス）。OS を限るなら、その行だけをテンプレートの条件で囲み、`.chezmoiignore.tmpl` でも配備を除く（`pi-sandbox-toggle` は Linux だけ）。OS を問わない拡張（`t3-usage-status`）は無条件の 1 行にする。
- **配らないもの**: stock は、自作の拡張のコードを `~/.pi/agent/extensions/` へ配らない（そこにあるのは package の設定だけ）。
- **保護**: 配備先は `path_write` で deny（`~/.pi/agent/local-packages`。[判定表](#権限の方針の試験)）。囲いの外の pi 本体で実行されるコードなので、ファイルの道具で書き換えさせない。
- **試験の登録**: `test/test_<名前>.py` を作り、`scripts/verify.py` の `Rule` に `home/dot_pi/agent/local-packages/<名前>/**` を登録する。配線（`pi-stock-packages` の 1 行）は `test/test_pi_stock_config.py` の `LOCAL_PACKAGES` と配線の試験で固定する。

### Copilot Gemini の画像ガード

自宅・会社の標準 Pi で [`pi-copilot-image-guard`](../../home/dot_pi/agent/local-packages/pi-copilot-image-guard/README.md) を既定で読み込む。
対象は Copilot 経由の Neon・Carbon・Argon・Hydrogen・3.8 Flash。履歴の古い画像だけを送信用コピーから省き、現在ターンだけで上限を超えたら送信を止める。Sol・Claude・Google 直接 API・Bedrock、既定モデルの割り当ては変えない。

既存環境では `chezmoi apply ~/.pi/agent/local-packages/pi-copilot-image-guard ~/.pi/agent/settings.json` で配備し、Pi を開き直す。

**撤去条件**: Pi 本体・Copilot 側・代替拡張が、利用中の Pi と Copilot の経路で同等の画像対策を提供したら削除する。履歴のみの省略と、現在ターンだけでの超過時に画像を捨てずに止める挙動を先に確認する。撤去時は `pi-stock-packages` の登録、ローカル package、専用試験・検証規則を外す。配備済みのディレクトリは `.chezmoiremove` で削除する。

### Windows

pi 本体と設定（`~/.pi/agent/`）は Windows にも配る。`prompts/`（`/fleet`・`/stepback`）と、囲い（`pib`・`pi-sandbox-runner`）は Unix（Linux / WSL）だけ。
`~/.config/pi`（撤去した自作ハーネス）は、どの OS でも配らず、`.chezmoiremove` が配備済みを消す。除外を外す記述（`!.config/pi/`）を足してはならない:
ソースと削除が同じ対象を指すと、`chezmoi: .config/pi: inconsistent state` で apply が止まる（2026-11-11 に Windows の機で発生。試験 `test_ignore_never_unignores_config_pi`）。

試験は `test/test_pi_stock_config.py`（`chezmoi execute-template` で描画して確かめる。実機の apply は行わない）。

### テーマ（iceberg）

pi の配色テーマ `iceberg`（暗色）を配る。目的は配色の読みやすさ（タイトル・選択行・警告のコントラスト）を上げること。テーマは JSON の設定ファイルだけで、拡張（コード）は足さない。

- **配るファイル**: `home/dot_pi/agent/themes/iceberg.json`（配備先は `~/.pi/agent/themes/iceberg.json`）。組み込みの `dark.json` と同じキー構成（`colors` は全トークン）。`.chezmoiignore.tmpl` では除外しないので、custom / stock のどちらでも配られる。
- **選び方**: `/settings` の Theme で `iceberg` を選ぶ。または `~/.pi/agent/settings.json` に `"theme": "iceberg"` を書く。**リポジトリは `theme` を配らない**（利用者のキーなので、利用者が選ぶ）。
- **何を変えるか**: 配色だけ。**確認画面に枠や背景は付かない**（それは別の問題で、このテーマでは直せない）。
  - `text` は `#c6c8d1`。`muted` は Iceberg のグレー `#6b7089` では暗いので、`#9399b2` に明るくした。
  - `accent`（確認画面のタイトルと選択行）は暖色の橙 `#e2a478`、`warning`（規則に当たったコマンドの強調）は明るい橙 `#e9b189`、`error` は赤 `#e27878`、`success` は緑 `#b4be82`。
  - 背景系（選択行）は `#161821` より少し明るい暗色（`#272c42`）。
  - **会話・ツールのブロックの境界**（2026-11-10。小さい画面で、ブロックの境目が見えにくかったため）: 枠線は theme では引けない（pi の設定にも無い）ので、**背景の明るさの差と色相**で出す。**端末の背景は theme が決めない。** 最初の調整は iceberg の `#161821` だけを基準にしたが、実機（iPhone の Orca）のスクリーンショットの画素を測ると端末の背景は `#282c34` で、調整後の背景との比は 1.05〜1.17 しかなかった。そこで、**どちらの背景に対しても比 1.3 以上**になる、端末の背景より明るい色にした: ユーザーの入力 `#30436d`（青。`#282c34` に対して 1.43）・実行中 `#3a4052`（灰青。1.36）・成功 `#2d4d44`（緑。1.50）・失敗 `#643640`（赤。1.43）・拡張のメッセージ `#443a66`（紫。1.36）。ツールの見出し（`$ コマンド` の行）は `toolTitle` を青（`#9dbad9`）にし、出力 `toolOutput` は `#b8bdd2` にした（各背景で 4.5 以上）。本文は各背景で 5.9 以上。**`bg_run` の「Background $ …」の行と、pi-subagents の「async subagent」の表示は、背景を持たない**（画素が端末の背景と同じ `#282c34`）。拡張が自前の描画（`renderShell: "self"` 相当）で出すため、theme の背景のトークンが効かない。色は文字色（`accent`・`muted`）だけ。枠線や背景が要るなら、拡張の描画を差し替える必要があり、自作は最後の手段なので見送る。
  - **入力欄の枠は、思考の深さで色が変わる**（pi 本体の仕様。`thinking*`）。常用する `xhigh` がエラーの赤に見えないよう、寒色から暖色へ順に: `off` グレー `#6b7089` → `minimal` スレート `#7788a7`（グレーと青の中間）→ `low` 青 `#84a0c6` → `medium` シアン `#89b8c2` → `high` 紫 `#a093c7` → `xhigh` 明るい紫 `#ada0d3` → `max` 明るい橙 `#e9b189`。`xhigh` までは赤系を使わない。`high` と `xhigh` の差は小さい（同じ紫の明るさ違い）。枠としての見え方は実機で未確認。
- **出典**: [Iceberg](https://github.com/cocopon/vscode-iceberg-theme)（cocopon。MIT）の terminal の色（2026-11-10 取得）。パレットに無い色は、`muted`・`dimText` と、背景系の暗色（パレットの色を `#161821` と混ぜたもの）だけ。
- **コントラストの実測**（WCAG。背景 `#161821`。`test/test_pi_theme.py` が検査する）: `text` 10.6（要 7 以上）・`muted` 6.27・`accent` 8.27・`warning` 9.37・`error` 6.06・`success` 8.96・`mdLink` 8.17（いずれも要 4.5 以上）。`dim`（`#7a8099`）は 4.53。
- **未確認**: iPhone の Orca での見え方（ブロックの背景を変えた効果は、実機で見てから調整する）。`system` テーマ（端末のパレットから自動で作る既定）との比較。
- **戻し方**: `settings.json` の `theme` を消すか、`/settings` で `system` を選ぶ。
- 試験は `test/test_pi_theme.py`（pi 本体が無くても動く。組み込み `dark.json` が見つかるときだけ `colors` のキー集合の一致も見る。見つからなければ skip で、skip は通過ではなく未検査）。

### 圧縮の設定

方針と根拠は [記録](../research/agents/long-context-compaction-paper-2026-11.md)（70 万トークンで圧縮・指示だけを package で恒久設定・自作なし）。

- **package**: `npm:@thgilciffart/pi-compaction@0.3.1`（`pi-stock-packages`）。要約の指示の恒久設定だけに使う。
- **`~/.pi/agent/compaction.json`**: `home/dot_pi/agent/modify_compaction.json.py.tmpl`が配る。
  - `defaults.instructions`: 続きの作業のための brief を作る指示（日本語 10 項目）。リポジトリの値に**強制**する（変えたら apply で更新される）。
  - `defaults.onError`: `"default"`（無いときだけ補う。要約に失敗したら本体の既定で圧縮する）。
  - `auto`・`model`・`effort`・`style` は配らない（利用者が `/compaction-settings` で足したキーは保つ。`models` など他のキーも保つ）。壊れた JSON は触らない。何度流しても同じ結果。
- **`compaction.modelOverrides`（`~/.pi/agent/settings.json`）**: `modify_pi_stock_settings.py.tmpl` が、窓が約 100 万以上のモデル（`github-copilot/` の `claude-sonnet-5.5`・`claude-opus-5.5`・`claude-sonnet-5`・`gpt-6-sol`・`gpt-6.2-sol`・`gpt-5.3-codex`・`gemini-3.8-flash`・`gemini-4-carbon`、家の機に限り `gemini-4-neon`）に `reserveTokens = 300000` を、**無いときだけ**補う（利用者が別の値を書いていれば保つ。`compaction` の他のキーも保つ）。`reserveTokens` = 窓 − 発動点なので、窓が 100 万なら発動点は 70 万トークン（窓の 7 割）、1.1M の `gpt-6.2-sol` なら約 80 万になる。`gpt-6-sol` もカタログに実在するので残す。
- 試験は `test/test_pi_compaction_config.py`。

### プロンプトテンプレート（/fleet・/stepback）

`~/.pi/agent/prompts/fleet.md`・`stepback.md` を配る（Unix のみ。Windows は `.chezmoiignore.tmpl` で除外）。配る形は `home/dot_pi/agent/prompts/*.md`（静的なファイル）。

| コマンド | 文面 |
| --- | --- |
| `/stepback` | ツールに依らない |
| `/fleet` | pi-subagents の `subagent` ツールに合わせる |

- **`/fleet` の仕組み**: 専用の機能ではなく、指示文と `subagent` ツール。目的は**利用者の待ち時間を最小にする**こと。
  待ちを作る 3 つの原因（書き手どうしの衝突・前の作業の完了待ち・長い検査の待ち）への手順を、文面に書いてある（下の表）。
  リポジトリ固有の手順（AGENTS.md・skill）があれば、そちらを優先させる。

| 待ちの原因 | 文面の手順 |
| --- | --- |
| 書き手どうしの衝突 | 書き手 1 人につき、専用の枝と worktree を 1 つ（置き場はリポジトリの規則。既定は親セッションの cwd 配下の `.tmp/worktrees/<名前>/`。cwd の外は書き込みの確認で止まり、`git worktree remove` も `.tmp/worktrees/` の外は確認になる）。同じ作業ディレクトリに書き手を置かない。担当ファイルは重ねず、共有されやすいファイル（索引・登録表・lockfile・生成物）は担当を 1 つに決める |
| 取り込みの待ち | 親が統合用の枝を先に切り、作業の枝はそこから切る。完了した順に 1 件ずつ、親が検査してから履歴の残る形で merge する（波の終わりを待たない。`git rebase` は確認になるので使わない）。取り込む前に統合用の worktree が clean であることを確かめる。衝突解消後の最終差分は再検証する。実質的な変更が入れば、コミット前に再監査する。機械的でない衝突は `git merge --abort` で戻し、委譲できるなら担当の worker に戻す。設計判断が要るものは利用者に示す |
| 前の作業の完了待ち | 親がインターフェースとテストの期待値を先に契約に書く。先行の実体がなくても実装・検証できる部分だけ並列にする。実体が必要な作業は、前提が揃ってから起動する |
| 長い検査の待ち | 3 段（worker は担当に絞る → 親が完了ごとに再実行と安い登録チェック → 全体は統合用の枝で、コードの変更が止まってから 1 回だけ）。重い検査は `bg_run` で背景に出し、`wake_on` で失敗の行に反応し、待つ間は次の作業・取り込み・reviewer の監査を進める |
| そもそも分けるべきでない | 数分で終わる変更は親が実装する。分割できなくても条件に合う実装は `worker` 1 人に渡せる。読み取りには専用の worktree は不要。互いの結果を待たずに進められる調査だけを並列にする |

`subagent` の `worktree: true`（管理 worktree）は、小さく独立した使い捨ての作業だけに使う。変更が親の作業ツリーへ自動では入らず
（patch と handoff の記録が残る）、親の作業ツリーが清潔でないと起動できないため、統合用の枝で取り込む形にはなじまない。
採用するときは、親が handoff と patch を確認して統合用の枝へ適用する。再検査と必要な監査を済ませてからコミットする。
この方針は、このリポジトリの運用（`.agents/skills/feature-orchestration/`。F＝親が feature の worktree を作って `cwd` で渡す。
積み重ね＝前の枝の先頭から次の枝を切る）を、stock 一般へ書き直したもの。作業の一覧は `todo` に登録し、前提が満たされたものから
1 件ずつ起動する（上限 4 件）。

- **委譲の根拠**: pi-subagents は「利用者が依頼したときだけ」委譲を許す。`/fleet` の呼び出しも委譲の依頼として扱う。ただし、利用者が委譲を禁止した範囲では、起動条件や監査より禁止を優先する。別の規則で独立監査が必須なら、未監査のままコミットしない。
  挙動・設計・互換性・権限・安全に影響する変更は、数行でも親の再検証と独立監査を終えてからコミットする。
  統合用の枝への取り込みは親が行う。`push` と保護ブランチ（`develop`・`main`）への統合は利用者の指示があるまで禁じる。
- **試験**: `test/test_pi_stock_config.py`（上の手順の要点の語が残っている、文面に撤去した自作ハーネスの語が無い）、
  `test/test_pi_commands_doc.py`（[早見](pi-commands.md)と実物の一致）。
- **既存の機への反映**: `chezmoi apply`（`~/.pi/agent/prompts` だけに絞ってよい）。全体の `apply` は他のスクリプトも動かすので、絞る。

### 会社の Pi のモデルプロファイルを切り替える

会社の機では、Bedrock と Copilot のどちらを起動時に使うかを、chezmoi の設定で選ぶ。自宅ではこの設定を参照しない。

1. `chezmoi edit-config` で既存の `[data]` に `work_pi_profile = "copilot"` を追加する。Bedrock に戻すには `"bedrock"` にするか、キーを削除する。未指定なら Bedrock。不正な値では反映が止まる。
2. 利用者の端末で `chezmoi apply ~/.pi/agent/settings.json ~/.pi/agent/AGENTS.md` を実行する。
3. Pi では新しいセッション、T3 Code では新しいスレッドを開く。作業前に親のプロバイダ・モデル・思考レベルを確かめる。旧セッションを再開すると当時のモデルが復元される。

既定の親は、Bedrock が Sonnet 5.5 `medium`、Copilot が Gemini 4 Neon `medium`。同じプロバイダで選んだ親モデルや思考レベルは、旧既定の移行時を除いて保つ。`enabledModels` には選んだプロバイダの候補だけを残し、親モデルを先頭に置く。

- 別の会社プロファイルへ切り替えると、親モデル・思考レベル・候補を `settings.json` の `dotfilesWorkPiModels` に退避する。元に戻すと復元する。他のプロバイダや曖昧な候補も退避するが、会社の起動候補には入れない。
- 選択していない側の子モデルの既定は除き、個別に設定した割り当ては保つ。認証・履歴・検索 MCP は変えない。
- これはアクセス制御ではない。別プロバイダの手動選択や、選択先の利用可能なモデルがない場合の Pi のフォールバックは防がない。意図と異なるプロバイダで起動したら、作業を始めず認証と設定を確認する。

### pi-subagents の設定

子エージェントは package `pi-subagents`（nicobailon。`pi-stock-packages` で版固定）。評価は [評価の記録](../research/agents/pi-stock-packages-evaluation-2026-11.md) の「オーケストレーションの評価と決定」、運用は `.agents/skills/feature-orchestration/references/pi-subagents.md`。自作のコードは足さない（既存の `modify_` スクリプトと設定だけ）。複数形の `extensions/subagents/` は凍結した自作拡張で、ここの対象ではない。

- **`~/.pi/agent/extensions/subagent/config.json`**（単数形。）: `home/dot_pi/agent/extensions/subagent/modify_config.json.py.tmpl` が配る。
  - **`forceTopLevelAsync: true` は強制**（利用者が false にしても apply で戻る）。前景の子には親の拡張が載らず permission-system と cc-safety-net が効かないため。
  - 無いときだけ補う: `worktreeProvider: "native"` と、**取り払った上限**（2026-11-10。利用者の指示）: `maxActiveAsyncRunsPerSession: 0`（同時数。0 は無制限）・`maxSubagentDepth: 8`（入れ子の深さ。入れ子にするかは agent ごとの許可 `allowNestedSubagents` で決まる）・`maxSubagentSpawnsPerRun: 10000`（1 run の子の累計。0 は使えず、無視されて 64 になるので、大きな値）・`globalConcurrencyLimit: 1000`（1 run の同時数。正の整数のみ）・`maxSubagentSpawnsPerSession: 0`（セッションの累計。0 は無制限）・`parallel: { maxTasks: 64, concurrency: 16 }`（`tasks: […]` や chain の並列グループ。既定は 8 件・4 並列。キーごとに無いときだけ補う）。
    - 初期値の 4・1・32 のままなら、上限を外した値へ移す。**この 3 つの値を意図して選ぶことはできない**（apply のたびに戻る。別の値なら保つ）。
    - 値は pi-subagents の設定の検証（`src/shared/types.js`・`config.js`）に通る範囲（`reviewer` の監査で確認）。最大値の記載は文書に無い。実機の `subagent({ action: "doctor" })` で、反映後に読み込みが通ることを確かめる（**未確認**）。
    - 同時数の上限に当たったことは無い（2026-11-10 に 4 本を同時に回して、上限に達しなかった）。先に詰まりやすいのは、全件検査の CPU（`feature-orchestration` の落とし穴に記録。**推測**）と、親の確認の手間。
  - 利用者が足した他のキーは保つ。壊れた JSON は触らない。何度流しても同じ。
- **settings の `subagents.agentOverrides`**（`modify_pi_stock_settings.py.tmpl`）: 組み込みの `scout`（`read`・`grep`・`find`・`ls`・`contact_supervisor`）と `oracle`（`read`・`grep`・`find`・`ls`）の `tools` を読み取り専用に絞る（組み込みの既定は `bash`・`write` を持つ）。`reviewer`（読み取り専用）・`worker` は変えない。検索の子 `researcher`（`read`・`write`）・`evidence-auditor`（`read`）には、機の検索・取得の MCP を `mcp:websearch`（家）・`mcp:agentcore-websearch` と `mcp:webfetch`（会社 PC）で足し、組み込みの prompt の食い違いを直す `systemPrompt` を置く（[理由と会社 PC の設定](mcp-servers.md#子のエージェントへの検索-mcp-の渡し方)）。利用者が同じ役の `tools` を書いていれば保つ（無いときだけ補う）。`systemPrompt` だけは repo が管理し、毎回揃える。他の `subagents` のキー・他の役の上書きも保つ。
- **役割ごとのモデル**: 起動時の親と子の既定は、自宅 Copilot・会社 Bedrock・会社 Copilot の 3 プロファイルで異なる。会社では [`work_pi_profile`](#会社の-pi-のモデルプロファイルを切り替える) で選ぶ。表の `:` の後ろは思考の深さを示す。

  | 役割 | 自宅 Copilot (`github-copilot`) | 会社 Bedrock (`amazon-bedrock`) | 会社 Copilot (`github-copilot`) |
  | --- | --- | --- | --- |
  | 親（起動時） | `gemini-4-neon:medium` | `us.anthropic.claude-sonnet-5-5:medium` | `gemini-4-neon:medium` |
  | `scout` | `claude-sonnet-5.5:high` | `us.anthropic.claude-sonnet-5-5:low` | `claude-sonnet-5.5:medium` |
  | `researcher` | `gemini-4-neon:xhigh` | `us.anthropic.claude-sonnet-5-5:medium` | `gemini-4-neon:medium` |
  | `worker` | `gpt-6.2-sol:xhigh` | `us.anthropic.claude-sonnet-5-5:medium` | `gpt-6.2-sol:xhigh` |
  | `reviewer` | `claude-sonnet-5.5:high` | `us.openai.gpt-6.2-sol:high` | `claude-sonnet-5.5:high` |
  | `evidence-auditor` | `claude-sonnet-5.5:high` | `us.openai.gpt-6.2-sol:high` | `claude-sonnet-5.5:high` |
  | `oracle` | `gemini-4-carbon:high` | `us.openai.gpt-6.2-sol:high` | `claude-opus-5.5:medium` |
  | `delegate` | 設定なし（親のモデルを継ぐ） | 設定なし（親のモデルを継ぐ） | 設定なし（親のモデルを継ぐ） |

  子の設定先は `subagents.agentOverridesByProvider.<プロバイダ>.<役>.model`。`advisor` は `oracle` の別名で、設定には `oracle` を使う。生成元は [`modify_pi_stock_settings.py.tmpl`](../../home/.chezmoitemplates/modify_pi_stock_settings.py.tmpl) の `PROVIDER_AGENT_MODELS`、`HOME_COPILOT_MODELS`、`WORK_BEDROCK_MODELS`、`WORK_COPILOT_MODELS`。

  - **プロバイダの選択**: pi-subagents は起動時の `defaultProvider` ではなく、親が使っているモデルのプロバイダで子の設定を選ぶ。`/model` で親のプロバイダを変えても追従する。割り当てがなければ子は親のモデルを継ぐ。
  - **Bedrock の扱い**: 会社では選択したプロバイダだけに子の既定を生成する。自宅では Copilot が起動時の既定だが、手動選択に備えて Bedrock の子の設定も残す。自宅で Bedrock を使う場合、`reviewer`・`evidence-auditor`・`oracle` は Sol 6.1 `high`、他の役は会社 Bedrock と同じ。
  - **自宅の親の既定**: 親の設定がすべて無ければ Neon `medium` を置く。既存の Sol `high` または Sonnet `xhigh` は、候補とモデル別の思考レベルに個別指定がない場合だけ一度移す。旧既定と同じ明示指定は初回だけ区別できないが、その後で選び直した値は戻さない。
  - **会社 Copilot の旧既定**: Copilot を有効にした最初の反映で、親が旧既定の Sonnet 5.5 `medium` と一致すると Neon `medium` に移す。休眠プロファイルから復元した値も対象で、旧既定と同じ値を手動で選んだ設定はこの一度だけ区別できない。その後は Sonnet に戻しても再移行しない。
  - **子の既存値の移行**: 旧既定と一致するモデルだけを表の配分へ移し、それ以外の指定を保つ。自宅の `delegate` の旧既定は解除する。会社で Bedrock に切り替えると、Copilot の旧既定と移行・生成したモデルを除き、個別のモデル指定は残す。

  **Copilot の分担**: 親の Neon が利用者との要件整理を担い、複雑な設計は読み取り専用の `oracle` に相談する。会社の計画役は Opus、自宅は Carbon。Sol が実装し、Sonnet が別系統でレビュー・証拠監査する。

  常設指示は、親が Copilot を使い、複雑な計画を `oracle` に相談するときに `options.context: "fresh"` を求める。起動後にモデルを切り替えた場合も、実際の親のプロバイダで判断する。親の履歴を丸ごと渡さず、要件・制約・関係ファイルに絞る。

  既存の委譲条件と利用者の明示指定を優先し、`/plan` のモデルは自動で切り替えない。

  **選定の根拠**: [Neon の発表](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-neon/)は途中での指示修正への追従を報告している。[Anthropic の Advisor 資料](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool)は難しい判断と実行の分離を勧める。[FrontierCode 2.0](https://cognition.com/frontiercode)では Sol の実装費用が低い。実行環境が異なるため、Pi と Copilot での作業費用や品質は未測定。

  [Copilot の公式料金表](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing)では Sol は入力 272K トークン超で長文単価がかかる。実装の依頼は、確定した計画・差分・合格条件に絞る。モデル別の圧縮設定は変えない。

  **検証の範囲**: `test/test_pi_subagents_config.py` で 3 プロファイルの設定生成を検査する。会社 Bedrock の Sol 6.2 は Pi 1.6.0 のカタログと [AWS のモデルカード](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-2-sol.html) で確認した。会社の Pi でのツール・MCP 呼び出しと、自宅の割り当てによる品質改善は未検証。

  **見直し条件**: 計画を説明し直す回数、実装の手戻り、レビューでの見逃しを確認する。会社では再試行を含む合格 1 件あたりの費用も比較する。
- **agent 定義の写し**（`home/dot_pi/agent/agents/{worker,reviewer,scout,oracle,researcher,evidence-auditor}.md`。配備先は `~/.pi/agent/agents/`。）: 組み込みの agent を**そのまま写し**、frontmatter に `permission: { external_directory: deny }` だけを足した。
  - **理由（ADR-0031 の評価）**: 子が作業ツリーの外を読もうとすると、方針は確認（ask）になり、**親の画面へ転送される。離席中は誰も答えず、5 分止まる**（実例: 2026-11-10、`review` の worker が `cd ~/.pi/…` で 240 秒以上待った）。確認ではなく**即座の拒否**にしたい。agent ごとの `permission:` は、agent ファイルの frontmatter にしか書けない（settings の `agentOverrides` は `permission` を扱えない）。ほかの標準の手段は無い。
  - **実測**（2026-11-10。使い捨ての project agent で。審査ログの `permission_request.blocked`・`origin: project-agent` でも確認。記録は [権限の frontmatter の実測](../research/agents/subagent-permission-frontmatter-2026-11.md)。**user 配下に配備した写しでの実測は、反映後に一度確かめる（未確認）**）: `external_directory: deny` で、作業ツリーの外の `read` と bash のパス引数は即座に拒否された（`/etc/hostname`・`/etc`・`/tmp`・`~/.agents/skills/…`。pi 本体の `~/.pi/agent/npm/…` は読めた）。作業ツリーの中は通った。`skills: <名>` と `inheritSkills: false` で、子には指定した skill だけが見えた。
  - **書式の制約**: pi-subagents は `permission:` の値に `allow`・`ask`・`deny` の単一の値だけを許す。permission-system の docs にある入れ子の形（`external_directory:` の下にパターン）は、agent 定義が `Invalid agent definitions` になる。bash のルールも書けない。
  - **維持費と撤去条件**: 6 つの組み込みの prompt の写しを持つ（markdownlint は除外。`.markdownlint-cli2.jsonc`）。`pi-subagents` の版を上げたら、写し直す（試験 `test_agent_files_match_the_builtin_except_permission` が、パッケージの組み込みとの食い違いを検出する）。`agentOverrides` が `permission` を扱えるようになるか、子の既定の権限を設定で変えられるようになったら、写しをやめる。
  - 作業ツリーが worktree の子（`cwd` に feature の worktree）では、本体の `.tmp/` や共有の `~/.agents/skills` を読めない（引き継ぎは worktree の中のファイルで行う）。
- **常設の委譲の指示**: 自宅・会社で共通の [`agent-instructions-stock.md`](../../home/.chezmoitemplates/agent-instructions-stock.md) を `~/.pi/agent/AGENTS.md` に配る。利用者の依頼または適用される常設指示が起動の根拠であり、規模や複雑さだけでは起動しない。
  - コードの横断調査は `scout`、外部の一次資料の照合は `researcher` に任せる。問いが 1 件でも対象とする。単純な検索や資料 1 件の確認は親が行う。
  - 親は編集前に直接実装・単独委譲・並列委譲を決める。範囲と合格条件が固まり、引き継ぎと再検証に見合うなら、1 件でも `worker` に渡す。設計が固まった時点でも再判定する。
  - 書き手は worktree ごとに 1 人。並列にするのは、共有のインターフェースと検査の期待値が固まり、互いの結果を待たずに進められる作業だけとする。
  - 子は `async: true` で起動し、明示されない限り再委譲しない。親が検査を再実行する。挙動・設計・互換性・権限・安全に影響する変更は、差分の大きさを問わず、新しいコンテキストの読み取り専用 `reviewer` が監査する。実装者の自己評価は渡さない。
  - 起動条件は指示であり、hook による強制ではない。`authorityPolicy` は危険操作の確認用である。採用理由と観測方法は [ADR-0043](../adr/0043-delegate-bounded-implementation-to-a-single-worker.md) を参照する。
- **複雑な不具合の膠着時の診断**（`agent-instructions-home.md`。家の機だけ）: 膠着の判断は親モデルが行う。Watchdog による検知や閾値の強制ではない。`options.agentScope: "user"` で同名のプロジェクト定義を選ばない。読み取り専用の役で、Astra でない Copilot モデルと確認できる場合に、新規コンテキストで 1 回だけ呼ぶ。親の会話を自動では引き継がせず、次の切り分け方を求める。Astra への自動切り替えはしない。
- **permission**（`pi-permission-policy.json`）: `subagent_supervisor` は allow、`subagent_launch`（workflow の子の起動ごとの確認）は **allow**（[上](#permission-system-の設定)。方針の実体と同じ）。`gate`・`acceptance.verify` のシェルは bash の規則の外なので使わない。
- 試験は `test/test_pi_subagents_config.py`（描画して確かめる。実機の apply は行わない）。
