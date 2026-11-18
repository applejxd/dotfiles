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

## pi の設定

### 設定の置き場（pi の標準の形と、機械ごとの上書き）

pi の設定は、1 か所にまとまっていない。これは pi の標準の形で、このリポジトリが散らしたわけではない（2026-11-15。pi 1.5.2 の `docs/settings.md`・`docs/extensions.md`）。

- **pi 本体**: `~/.pi/agent/settings.json`（全体）と、プロジェクトの `.pi/settings.json`。プロジェクトの設定が全体の設定を上書きする。
- **拡張**: `~/.pi/agent/extensions/`（全体）か、プロジェクトの `.pi/extensions/` に置く。拡張が自分の設定をどこに置くかは**拡張ごとの決め**で、pi 本体は規約を決めていない。実際の拡張は、`extensions/<拡張名>/config.json` の形を取る（`pi-permission-system`・`pi-permission-explain`・`ai-guard`）。
- **機械ごとの上書き**: chezmoi の管理外のファイルに置く。一覧は [マシン固有の設定の置き場](shell.md#マシン固有の設定の置き場)（pi に関するものは、`runner.local.toml`・`config.local.json`・`/permission-system`）。

### 配るもの

| 対象 | 配り方 |
| --- | --- |
| `~/.pi/agent/AGENTS.md` | `agent-instructions-stock.md`（ツール非依存の短い指示）。委譲の常設の指示を含む。**家の機（`is-work` が `false`）だけ**、末尾に `agent-instructions-home.md` を足す（開発中の Web サービスは、Tailscale が使えるなら tailnet だけに公開する。`funnel` は利用者が明示したときだけ）。会社 PC には出さない。`AGENTS.md.tmpl` が出し分ける。`tailscale serve` の手順・WSL での扱いは、家の機だけに配るスキル `tailscale-serve`（[tailscale.md](tailscale.md)）。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#tailscale-の指示の経緯) |
| `~/.pi/agent/settings.json` | `modify_pi_stock_settings.py.tmpl`。`packages` を `pi-stock-packages` にし、`defaultTools` を `["+grep", "+find", "+ls"]`（pi の既定 read・bash・edit・write に読み取り専用の探索ツールを足す増分指定。plan mode の探索にも使う。利用者が `+`/`-` だけの増分指定にしたら保つ）にする。撤去した自作ハーネスの `extensions`・`skills` の項目は取り除く。`skills` には、Orca が入れたスキル 3 本の除外（`!computer-use`・`!orca-cli`・`!orchestration`）を毎回そろえる（利用者の他の項目は保つ。戻すときは `+skills/<名前>`。[手動起動と除外](skill-frontmatter.md#手動起動disable-model-invocation)）。テーマ・既定のモデルなど利用者のキーは触らない **家の機（`is-work` でない）は、`enabledModels` を `["github-copilot/*"]` にする**（2026-11-16。利用者の指示。利用者がすでに `enabledModels` を書いていれば保つ。会社 PC は触らない）。家で AWS CLI の API 検証のために Bedrock の認証情報（`AWS_PROFILE`・`~/.aws`・`AWS_BEARER_TOKEN_BEDROCK` など）を置いても、**pi が Bedrock のモデルで無意識に起動しない**ため。pi は環境変数などの認証情報で Bedrock を使えるようにし（`docs/providers.md`）、`defaultProvider` が無い・Copilot が使えないとき、起動時の選択が別のプロバイダへ落ちうる。`enabledModels` は「起動時の選択とモデルの切り替え（Ctrl+P）の対象」なので（`docs/settings.md`）、Bedrock を外せば、そこへ落ちない。`/model` で明示して選ぶのは妨げない。家で他のプロバイダも使うときは、`settings.json` の `enabledModels` にパターンを足す（利用者の値は保たれる）。AWS CLI 自体は、エージェントからも普通に使える（制限しない）。 |
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
  - `path`（全ツール・bash 共通）の deny: `.env`・`*.env.*`（`*.env.example` は allow）・`~/.ssh`・`~/.aws`・`~/.gnupg`・`~/.netrc`・`~/.config/gh`・`~/.config/agents/websearch-keys.json`（検索の鍵ファイル。Bitwarden から同期される）・秘密鍵（`*.pem`・`*.key`・`id_rsa*` など）。**pi 自身の認証情報・設定（`~/.pi/agent/` の認証・信頼・モデル設定・MCP の設定、`ayu/` = pi-rewind のスナップショット）も deny**（2026-11-10）。利用者はいつも拒否するものなので、ask にせず deny にして確認で待たせない（理由をモデルへ返す）。`sessions/`・`extensions/*/logs` は、振り返りの分析で読むことがあるので ask のまま。ディレクトリ自体の deny も併せて置く（上の「再帰への備え」）。
  - **`path` の deny は、pib の囲いの `hide`（`runner.toml`）と同じ集合に保つ**（2026-11-12）。食い違いは `test_pi_sandbox_runner` が検出する。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#path-の-deny-と-hide)。
  - **`path_write`（書き込みだけの deny。読み取りは許す）**: ファイルの道具は囲いの外で動き、これらは次のコマンド・次の起動から効く（囲いが外れる・方針が緩む・拡張やランチャーのコードが実行される）ため、次を拒否する。
    - **`~/.pi/agent/` の、pi が読み込む・実行するもの**（`settings.json`・`AGENTS.md`・`extensions/`・`agents/`・`bin/`・`tmp/` など）を 1 つずつ deny にする（`sessions/` は除く。許可リスト型にしない）。**chezmoi が `~/.pi/agent` へ配るものは、すべて deny に入っていることを試験で固定する**。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#pi-agent-の-deny-の置き方)。
    - **`~/.config/pi-sandbox/`**（囲いの設定。runner はコマンドごとに読む）。
    - **囲いの中で読み取り専用に見せるもの（`runner.toml` の `visible.read`）**: `~/.local/bin/`・mise・uv など。**一致は `test_pi_sandbox_runner` が固定する**。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#囲いの読み取り専用の一覧)。
    - 変えるのは利用者（chezmoi・mise・uv）。シェルの起動ファイル（`~/.bashrc` など）はまだ対象にしていない（[限界](sandbox/pi-sandbox-runner.md#保証しないこと限界)）。
    - **この保護は既定の場所に固定**: `pib` は、設定の場所の環境変数が既定と違うと、制御ファイルがリンクで外を指していると、起動しない。 経緯・実測は [research](../research/agents/permission-policy-rationale-2026-11.md#囲いの保護の固定)。
  - **全 deny に理由をつける**（2026-11-11）: `deny` の値は `{ "action": "deny", "reason": "…" }` と書ける。理由は、拒否の文に付いてエージェントへ届く（「なぜ拒否され、代わりに何をすべきか」を読める）。すべての deny に理由がある（件数は書かない。試験 `test_every_deny_rule_carries_a_reason` が全件を検査する）。
    **ask には、理由を付ける仕組みが無い**（拡張の docs: 理由は deny の値にだけ書ける）。確認の画面には、コマンドとパスだけが出る。そのため、「子が絶対にやってはいけない」操作は、理由つきの deny にする（無人の確認は 5 分で拒否され、止まる）。人が在席して承認したい操作（`gh` の変更系・`git rebase` など）だけを、ask に残す。
  - `mcp` は ask（検索の `websearch`・`agentcore-websearch` だけ allow。上の「MCP 設定」）、`skill` は allow。入れる拡張の自分のツール（`todo`・`ask_user_question`・`subagent`・`subagents_enable`・`bg_wait`）は毎回の確認を出さないよう allow。上のどれにも当たらないツール（`*`）は ask。
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
- **ゲートに見えない出力先**（2026-11-16）: bash のトークンの投影は、コマンドに**明示したパス**（引数とリダイレクト先）を取り出す。出力先が設定や既定で決まるコマンドは、推定しない。`git flow feature start x --worktree` は、`gitflow.worktreePath` の既定が作業ツリーの外（`../<repo>-worktrees/`）で、別の repo で実際に外へ作られた。判定表の `access` で確かめたのは、**外部パスの投影結果**だけである（`git worktree add /opt/wt/x` は外のパス 1 件が `unproven`、引数にパスが無い `git flow feature start x --worktree` と内部のパスの `git worktree add .tmp/worktrees/x` は、外部パスが 0 件）。`[]` は「外部パスとして出ない」の意味で、実ゲートで確認が出ないことまでは証明しない（実ゲートは判定表の範囲外）。対策は、パスを引数に出させることではなく、**設定の既定を作業ツリーの中にすること**（`home/dot_config/git/config.tmpl` の `[gitflow] worktreePath`。主 worktree のルート基準。[ブランチモデル](development.md#ブランチモデルgitflow-lite)）と、常設の指示で「出力先が既定で決まるコマンドは、実行前に確かめる」こと。`git flow * start` を「引数に `.tmp/` が無ければ deny」にする案は、この repo の通常の操作（引数にパスが無い）を止めるので採らない。

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
- **permission**: `mcp` は `"*": "ask"` のまま、`websearch`・`agentcore-websearch`（サーバ名だけのルール）を allow。他の MCP は ask。
- **未確認**（実機）: permission-system は `mcp` に allow が 1 つでもあると `mcp_status` などの探索系を自動で allow にする、と docs にある。実挙動は未確認。

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
- **`compaction.modelOverrides`（`~/.pi/agent/settings.json`）**: `modify_pi_stock_settings.py.tmpl` が、窓が 100 万のモデル（`github-copilot/` の `claude-sonnet-5.5`・`claude-opus-5.5`・`claude-sonnet-5`・`gpt-6-sol`・`gpt-5.3-codex`・`gemini-3.8-flash`）に `reserveTokens = 300000` を、**無いときだけ**補う（利用者が別の値を書いていれば保つ。`compaction` の他のキーも保つ）。`reserveTokens` = 窓 − 発動点なので、発動点は 70 万トークン（窓の 7 割）。
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
| 取り込みの待ち | 親が統合用の枝を先に切り、作業の枝はそこから切る。完了した順に 1 件ずつ、親が検査してから履歴の残る形で merge する（波の終わりを待たない。`git rebase` は確認になるので使わない）。取り込む前に統合用の worktree が clean であることを確かめる。衝突は、機械的なものは親がその場で解き、それ以外は `git merge --abort` で戻してから、その作業の worker に統合用の枝を取り込ませて直させる（`resume`）。設計に関わるものは利用者に示す。他の作業は止めない |
| 前の作業の完了待ち | 作業間の境界（ファイル名・署名・データ形式）を、親が契約に先に書く。依存する作業も契約に対して同時に実装させ、「後続」にするのは実体が無いと進められないときだけ。実体に載る後続は、前の枝の先頭から枝を切って始める（見込み実装） |
| 長い検査の待ち | 3 段（worker は担当に絞る → 親が完了ごとに再実行と安い登録チェック → 全体は統合用の枝で、コードの変更が止まってから 1 回だけ）。重い検査は `bg_run` で背景に出し、`wake_on` で失敗の行に反応し、待つ間は次の作業・取り込み・reviewer の監査を進める |
| そもそも分けるべきでない | 直列でも数分で終わる、または担当ファイルが重なる依頼は、分けずに自分で進める。読むだけの作業は worktree を作らず並列にする |

`subagent` の `worktree: true`（管理 worktree）は、小さく独立した使い捨ての作業だけに使う。変更が親の作業ツリーへ自動では入らず
（patch と handoff の記録が残る）、親の作業ツリーが清潔でないと起動できないため、統合用の枝で取り込む形にはなじまない。
採用するときは、親が handoff と patch を確認して統合用の枝へ適用・コミットし、再検査する。
この方針は、このリポジトリの運用（`.agents/skills/feature-orchestration/`。F＝親が feature の worktree を作って `cwd` で渡す。
積み重ね＝前の枝の先頭から次の枝を切る）を、stock 一般へ書き直したもの。作業の一覧は `todo` に登録し、前提が満たされたものから
1 件ずつ起動する（上限 4 件）。

- **委譲の根拠**: pi-subagents は「利用者が依頼したときだけ」委譲を許す。`/fleet` の呼び出しを、その依頼として扱う旨を文面に書いてある。
  worker の担当の枝へのコミットと、親による統合用の枝への取り込みは許可し、`push` と保護ブランチ（`develop`・`main`）への統合は
  利用者の指示があるまで禁じている。
- **試験**: `test/test_pi_stock_config.py`（上の手順の要点の語が残っている、文面に撤去した自作ハーネスの語が無い）、
  `test/test_pi_commands_doc.py`（[早見](pi-commands.md)と実物の一致）。
- **既存の機への反映**: `chezmoi apply`（`~/.pi/agent/prompts` だけに絞ってよい）。全体の `apply` は他のスクリプトも動かすので、絞る。

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
- **役割ごとのモデル**（`modify_pi_stock_settings.py.tmpl` の `PROVIDER_AGENT_MODELS`。`subagents.agentOverridesByProvider.<プロバイダ>.<名>.model`。`:` の後ろは思考の深さ）: 以前の Copilot / Bedrock のカタログ（`common.toml.tmpl` の `[pi.model.tier.*]`・役割ごとのモデル）に合わせる。pi-subagents が、**親のセッションのモデルのプロバイダごとに層を重ねる**（`/model` で替えても追従する。apply 時の `defaultProvider` には依らない）ので、両方の表を常に置く。知らないプロバイダの子は、親のモデルを継ぐ。利用者が書いた `model` は保つ。

  | 役割 | github-copilot | amazon-bedrock | 理由 |
  | --- | --- | --- | --- |
  | `worker` | `claude-sonnet-5.5:medium` | `us.anthropic.claude-sonnet-5-5:medium` | 実装は medium で足りる（opus と合格率が同じで sonnet が速い） |
  | `reviewer`・`evidence-auditor` | `gpt-6.1-sol:high` | `us.openai.gpt-6.1-sol:high` | 実装（Claude）と**別系統**にして、独立した目で見る（second_opinion） |
  | `oracle` | `gpt-6.1-sol:high` | `us.openai.gpt-6.1-sol:high` | 二番目の意見。**親・worker の Claude と別系統**にし（同じモデルの自己点検はほとんど効かず、評価役は同系統の出力を好むため。根拠）、`reviewer` と同じにする。Bedrock の Opus 5.5 は、カタログでは plan 役の既定で、ほかは明示の指示のときだけ。自律に起動する子には使わない（高価）。`context: fork` で親の会話を引き継ぐので、別モデルでは読み込みの再利用が効かない（少し高い） |
  | `scout` | `claude-sonnet-5.5:low` | `us.anthropic.claude-sonnet-5-5:low` | 速い調査（**新しい判断**。カタログに階層が無い。`explore` は計測が要るとされていた） |
  | `researcher` | `claude-sonnet-5.5:medium` | `us.anthropic.claude-sonnet-5-5:medium` | 調査の合成（**新しい判断**。カタログに階層が無い） |

  Haiku は使わない（利用者の方針。担当外の編集・書式崩れの実測）。Bedrock の `gpt-6.1-sol`・`opus-5-5` は `verified=false`（会社の機での pi のツール呼び出しは未確認）。`delegate` は設定せず、親のモデルを継ぐ。
- **agent 定義の写し**（`home/dot_pi/agent/agents/{worker,reviewer,scout,oracle,researcher,evidence-auditor}.md`。配備先は `~/.pi/agent/agents/`。）: 組み込みの agent を**そのまま写し**、frontmatter に `permission: { external_directory: deny }` だけを足した。
  - **理由（ADR-0031 の評価）**: 子が作業ツリーの外を読もうとすると、方針は確認（ask）になり、**親の画面へ転送される。離席中は誰も答えず、5 分止まる**（実例: 2026-11-10、`review` の worker が `cd ~/.pi/…` で 240 秒以上待った）。確認ではなく**即座の拒否**にしたい。agent ごとの `permission:` は、agent ファイルの frontmatter にしか書けない（settings の `agentOverrides` は `permission` を扱えない）。ほかの標準の手段は無い。
  - **実測**（2026-11-10。使い捨ての project agent で。審査ログの `permission_request.blocked`・`origin: project-agent` でも確認。記録は [権限の frontmatter の実測](../research/agents/subagent-permission-frontmatter-2026-11.md)。**user 配下に配備した写しでの実測は、反映後に一度確かめる（未確認）**）: `external_directory: deny` で、作業ツリーの外の `read` と bash のパス引数は即座に拒否された（`/etc/hostname`・`/etc`・`/tmp`・`~/.agents/skills/…`。pi 本体の `~/.pi/agent/npm/…` は読めた）。作業ツリーの中は通った。`skills: <名>` と `inheritSkills: false` で、子には指定した skill だけが見えた。
  - **書式の制約**: pi-subagents は `permission:` の値に `allow`・`ask`・`deny` の単一の値だけを許す。permission-system の docs にある入れ子の形（`external_directory:` の下にパターン）は、agent 定義が `Invalid agent definitions` になる。bash のルールも書けない。
  - **維持費と撤去条件**: 6 つの組み込みの prompt の写しを持つ（markdownlint は除外。`.markdownlint-cli2.jsonc`）。`pi-subagents` の版を上げたら、写し直す（試験 `test_agent_files_match_the_builtin_except_permission` が、パッケージの組み込みとの食い違いを検出する）。`agentOverrides` が `permission` を扱えるようになるか、子の既定の権限を設定で変えられるようになったら、写しをやめる。
  - 作業ツリーが worktree の子（`cwd` に feature の worktree）では、本体の `.tmp/` や共有の `~/.agents/skills` を読めない（引き継ぎは worktree の中のファイルで行う）。
- **常設の委譲の指示**（`agent-instructions-stock.md` の「委譲（サブエージェント）」。配備先は `~/.pi/agent/AGENTS.md`）: `pi-subagents` は、利用者が今回の依頼または**適用される利用者・プロジェクトの指示**で委譲を求めたときだけ子を起動する（規模・複雑さ・専門の agent があることは授権にならない。`skills/pi-subagents/SKILL.md`）。そのため、委譲してよい場面（調査の並列・実装後の `reviewer` の監査・独立した実装の並列・判断が分かれるときの `oracle`）と作法（`async: true`・親が再検証・承認が要る操作は任せない）を、利用者の常設の指示として書いた。授権のための設定項目は無い（`authorityPolicy` は危険操作の確認の設定で、起動の授権ではない）。
- **permission**（`pi-permission-policy.json`）: `subagent_supervisor` は allow、`subagent_launch`（workflow の子の起動ごとの確認）は **allow**（[上](#permission-system-の設定)。方針の実体と同じ）。`gate`・`acceptance.verify` のシェルは bash の規則の外なので使わない。
- 試験は `test/test_pi_subagents_config.py`（描画して確かめる。実機の apply は行わない）。
