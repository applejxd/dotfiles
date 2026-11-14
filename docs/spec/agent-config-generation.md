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
    is-work                                  会社 PC かどうかの判定（検索 MCP・adapter の出し分け）
scripts/agents/
    generate.py                              pi-mcp-servers.toml から mcp.json・mcp-adapter.json を生成する（pi の MCP だけ）
    validate_mcp.py                          描画した pi-mcp-servers.toml の検査（pre-commit）
    validate_skills.py                       SKILL.md の frontmatter の検査（pre-commit）
home/dot_pi/agent/
    AGENTS.md.tmpl  keybindings.json  prompts/  themes/  agents/
    modify_settings.json.py.tmpl  modify_mcp.json.py.tmpl  modify_mcp-adapter.json.py.tmpl
    modify_compaction.json.py.tmpl  modify_pi-plan-mode.json.py.tmpl
    extensions/pi-permission-system/modify_config.json.py.tmpl    extensions/subagent/modify_config.json.py.tmpl
home/dot_cc-safety-net/rules/            cc-safety-net の規則
home/dot_config/pi-sandbox/              pib の囲いの設定（runner.toml）
home/dot_config/agents/                  検索の核と MCP サーバ（websearch/）、AgentCore のラッパー
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

### 配るもの

| 対象 | 配り方 |
| --- | --- |
| `~/.pi/agent/AGENTS.md` | `agent-instructions-stock.md`（ツール非依存の短い指示）。委譲の常設の指示を含む |
| `~/.pi/agent/settings.json` | `modify_pi_stock_settings.py.tmpl`。`packages` を `pi-stock-packages` にし、`defaultTools` を `["+grep", "+find", "+ls"]`（pi の既定 read・bash・edit・write に読み取り専用の探索ツールを足す増分指定。plan mode の探索にも使う。利用者が `+`/`-` だけの増分指定にしたら保つ）にする。撤去した自作ハーネスの `extensions`・`skills` の項目は取り除く。テーマ・既定のモデルなど利用者のキーは触らない |
| `~/.pi/agent/mcp.json` | `modify_mcp.json.py.tmpl` が `generate.py --target pi-mcp` で配る（下の「MCP 設定」） |
| `~/.pi/agent/mcp-adapter.json` | 会社 PC（`is-work`）だけ。`generate.py --target pi-mcp-adapter` |
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
  - **ディレクトリを根にした再帰への備え（2026-11-11）**: ゲートが見るのはパスのトークンだけで、`grep -r`・`find` の再帰は中を見ない（根のトークンが読み取りと投影されるだけ。判定エンジンで確認）。`~/.ssh/*` のように `/*` だけの規則は、ディレクトリ自体（`ls ~/.ssh`・`grep -r x ~/.ssh`）に一致せず、`path` は allow のまま外のフォルダの確認（ask）へ落ちる。そのため、**秘密のディレクトリの deny は、ディレクトリ自体の規則も併せて置く**（`~/.ssh`・`~/.aws`・`~/.gnupg`・`~/.config/gh`・`~/.pi/agent/ayu`）。読み取りの許可リストのうち、pi の公開ディレクトリ（`npm`・`install`・`agents`・`git`・`prompts`・`skills`・`themes`）には、ディレクトリ自体の allow を**追加しない**（`/*` の規則だけを置く。既存の `~/.agents/skills` と `/tmp` の根の allow は、別の判断（2026-11-10）で残っている）。根の allow は、根の直下に置かれた `.env`・鍵のように `path` の deny に当たる名前のファイルへ、根を起点にした再帰が確認なしで届くため（2026-11-11 の監査の指摘。実在は未確認）。`ls ~/.pi/agent/agents` のようなディレクトリ自体への確認は残るが、減る確認は実績で数件なので受け入れる（判定表に、根が ask のままである例を置いている）。根拠の再集計（YOLO を切った後の確認 92 件）: 外のフォルダ 73 件（79%）・bash 19 件。許可リストを足した後も、ディレクトリ自体の確認（`extensions` 3 件・`agents` 2 件）が出ていた。**既知の限界（受容）**: `extensions/<名前>` を根にした再帰は `extensions/*` の allow に当たり、`logs` の ask をすり抜ける。許可したディレクトリの下に `.env`・鍵が置かれても、根を起点にした再帰では `path` の deny に当たらない。pi の公開ディレクトリについて許可するのは、秘密を置かない前提の中身（`/*`）だけで、配下に秘密が無いことの確認は取れていない（運用の条件）。
  - 作業ツリーの中の `read`・`write`・`edit`・`grep`・`find`・`ls` は allow。作業ツリーの外（`external_directory`）は、**読み書きとも allow は `/tmp/*` だけ**、**読み取りだけ allow は下の許可リスト**、それ以外は ask。プロジェクトごとの事前許可（データセットの読み取りなど）は [プロジェクト単位でデータセットを読み取り専用にする](#プロジェクト単位でデータセットを読み取り専用にする)。
    - **読み取りの許可リスト**（2026-11-10。承認の手間を下げるため最優先で足した）: pi 自身のディレクトリ（`~/.pi/agent/` の `npm/`・`install/`・`extensions/`・`agents/`・`git/`・`prompts/`・`skills/`・`themes/`、`AGENTS.md`・`settings.json`）と、skill の置き場 `~/.agents/skills/`（2026-11-10。自作 skill の `references/`・`scripts/` を読むたびに確認が出ていた。**読み取りだけ**で、書き込みは ask のまま。配備先は `chezmoi apply` で元に戻り、skill の手順書を黙って書き換えられると次回以降の指示が変わりうるため）と、`/tmp` 自体（`cd /tmp`・`ls /tmp` で確認が出ていた。`/tmp/*` はディレクトリ自体に一致しない。読み取りだけで、書き込みは ask）と、Orca の貼り付け画像（Windows の Temp の `orca-paste-*`）。拡張が `read`・`grep`・`find`・`ls` のツールにだけ自動許可する「基盤のパス」と同じ範囲を、bash にも広げた形。**`extensions/*/logs` だけは ask のまま**（レビューログにはコマンドの文字列が残り、秘密が混ざりうるため。拡張も、ここは自動許可しない設計）。`~/.pi/agent/` の認証情報・`models.json`・`mcp.json`・`sessions/` は許可リストに無く、ask のまま。
    - **子エージェントの出力の読み取り（2026-11-11）**: 子の結果が長いと、完了の通知に `~/.pi/agent/sessions/<プロジェクト>/subagent-artifacts/…` のパスが付く。親がこれを読むたびに確認が出ていた（承認しないと 5 分で拒否される）。**`*_output.md`（子の最終の出力）と `outputs/*`（保存された出力）の読み取りだけ**を allow にした（`~/.pi/agent/sessions/*/subagent-artifacts/*_output.md`・`.../outputs/*`）。`*_transcript.jsonl`（子の全やり取り）・`*_input.md`（依頼文）・セッション自体（`*.jsonl`）は、これまでどおり ask（広く許可しない。実機で `outputs/<id>/context.md` のような深い階層にも `*` が届くことを、判定表で確かめた）。
    - **システム診断の読み取りの許可リスト（2026-11-11。Linux / WSL の一覧。OS の条件は付けない）**: `/var/log` のような診断で読むパスを、先に許可しておく。許可の根拠は、承認の履歴ではなく、パスそのものの危険度。**ディレクトリではなく名前で許可する**（ゲートはトークンだけを見るので、`/var/log/*` のような広い許可は `btmp` などへ再帰で届く）。許可: ログ（`/var/log/` の `syslog`・`kern.log`・`dmesg`・`boot.log`・`dpkg.log` と、その回転 `*.<n>`）、`/proc`（`cpuinfo`・`meminfo`・`loadavg`・`uptime`・`version`・`mounts`・`net/*`、`sys/` の `vm/*`・`fs/*`・`kernel/` の `hostname`・`osrelease`・`ostype`・`version`・`pid_max`・`threads-max`、プロセスごとの `status`・`stat`・`limits`・`io`・`cgroup`）、`/sys`（**葉の名前だけ**: `class/net/*/` の `address`・`operstate`・`mtu`・`speed`・`carrier`・`statistics/*`、`block/*/` の `size`・`stat`・`queue/*`、`class/block/*/size`、`class/thermal/*/` の `temp`・`type`、`class/hwmon/*/` の `name`・`temp*_input`・`fan*_input`、`class/power_supply/*/` の `capacity`・`status`・`online`・`type`、`devices/system/cpu` の `online`・`offline`・`possible`・`present`・`cpu*/topology/*`・`cpu*/cpufreq/*`、`devices/system/node` の `online`・`node*/meminfo`、`fs/cgroup/*`、`kernel/mm/*`。sysfs は symlink（`device`・`subsystem`・`driver` など）で別の枝へ辿れ、判定は「書いたままの別名」と「解決した実体」の**どちらかに一致した最後の規則**で決まる（拡張の `evaluateAnyValue`。source で確認）。木全体の allow は、別名経由で `iscsi_session/…/password` に届くので置かない）、`/etc`（`os-release`・`lsb-release`・`hostname`・`hosts`・`resolv.conf`・`wsl.conf`・`passwd`・`group`・`timezone`）、導入済みのものの参照（`/usr/share/doc`・`/usr/share/man`・`/usr/include`・`/var/lib/dpkg/status`）、WSL（`/mnt/wslg/*.log`）。**許可しない（ask のまま）**: `btmp`・`wtmp`・`lastlog`・`auth.log`・`secure`・`cloud-init*`（誤入力のパスワードや生成された鍵が残りうる）、`/proc/*/environ`・`mem`・`kcore`、`/etc/shadow`・`gshadow`・`sudoers`・`ssh/ssh_host_*`・`apt/auth.conf*`・`NetworkManager/system-connections/*`・`wireguard/*`・`openvpn/*`、`/var/lib/docker`・`/run/user`、`/sys/kernel/debug`、`/sys/class/iscsi_session`（CHAP の `password`・`password_in`。`/sys/class/*`・`/sys/devices/*`・`/sys/bus/*` の包括許可はこれを含むので置かない）、`/var/log/apt/*`（`history.log` のコマンドラインにプロキシの認証が残りうる。`term.log` は導入スクリプトの出力）、`/etc/fstab`（CIFS の `password=`）・`/etc/apt/sources.list*`（URL に認証を書ける）・`/etc/sysctl*`・`/proc/sys/net/*`（`tcp_fastopen_key`・`stable_secret` など秘密値）。`/proc/*/status` などの `*` は貪欲なので、`/proc/<pid>/root/…` 経由で同名のファイル（`status` など）に届く。そこで `/proc/*/root/*`・`/proc/*/cwd/*`・`/proc/*/fd/*`（開いているディレクトリへの経路）を ask に戻す（後勝ち。判定表に例）。ディレクトリ自体（`/var/log`・`/proc`・`/etc` など）の allow は置かないので、`ls /var/log` は確認になる（`ls /var/log/syslog /var/log/syslog.*` の形なら通る）。OS の条件は付けない（macOS には `/proc`・`/sys` などが無く、`/etc/hosts`・`passwd`・`group` は同じ種類のファイルなので害は無い。macOS 固有のパスは後から足す）。末尾だけの `*` は、`sources.list.d` のようなディレクトリ自体に一致するので、完全名と `.*` で書く。この一覧は知識（FHS・systemd・WSL）に基づく草案で、この機械に実在するかは確認していない。足りないパスは、確認で足す。
    - **`commandEffects`（パス引数の向きの宣言。2026-11-10）**: `git` の `log`・`status`・`diff`・`show`（`--output` が付くと外す）と、`python3` を読み取りと宣言する。skill のスクリプトの実行（`python3 ~/.agents/skills/<名前>/scripts/*.py`）は、宣言が無いと向きを証明できず（unproven）、書き込み側の ask になる（実測 2 件）。**`python3 -c`・`-m` が付くと宣言を外す**（`-m venv` などが書くため。読み取りと書き込みの両方を調べる）。宣言しても、許可リストの外のパスは読み取りの ask のまま。python3 のスクリプトが自分で書く先は検査できない（インラインコードの迂回と同じく受容する）。向きの表は `permission_cases.json` の `access`（`test_bash_path_effects_match_the_table`）。
    - **広く許可（`external_directory_read` の `*` を allow）にしない理由**: ① `path` の deny は 14 件で、秘密の置き場（pi の認証情報、`.npmrc`、`.docker`、クラウドの認証、ブラウザのデータなど）を網羅していない。② 外部への送信は `curl` などを止めていない（bash の既定が allow）ので、読み取りと送信が連鎖しうる。③ 実測では、yolo を切った後の最初の 13 分間に出た確認 8 件が、すべて許可リストの範囲に収まった。広げる必要が実測で無い。
    - **`watchdog_diff` の allow と `~/.pi/agent` の deny（2026-11-14）**: `watchdog_diff` は読み取り専用（git diff と未追跡の一覧だけで、書き込み・通信なし）だが、ツール単位の許可に無く既定の ask になっていた。`read`・`grep` と同じく allow にした。`~/.pi/agent` 自体と `~/.pi/agent/pi-permissions.jsonc` は許可リストに当たらず ask だったので、deny を明示した（権限の設定そのものの元データはこのリポジトリ。子や離席中は ask で 5 分止まらず即座に拒否される）。
    - **広げたいとき**: 規則を 1 行足す（`~/src/*` など）か、確認画面の「このセッション中は許可」を使う。足したら、判定表に例を足して試験を回す。Windows の Temp を全体に広げるなら、`/mnt/c/Users/<名前>/AppData/Local/Temp/*` と `…/Temp` を足す（他のアプリの一時ファイルも読めるようになる）。
  - `bash` の既定は **allow**。止めるものだけを、後ろに書いた規則で決める（後勝ち）。判定は 2 つの拡張の組み合わせで、役割を分ける: **deny と強制 ask はこの方針（`pi-permission-system`。tree-sitter で複合コマンドを分解し、1 コマンドずつ前方一致で照合する）**、**破壊的な操作（`git reset --hard`・`rm -rf` の危険な対象・`find -delete` など）の意味解析は `cc-safety-net`**（[規則](#cc-safety-net-の規則)）。
    - **deny**: `sudo`・`git push`・スクリプトをシェルへ渡す形（`sh`・`bash`・`sh -s` など）、**秘密を取るコマンド**（`gh auth token`・`gh secret set|list`・`bw get|list|export`・`op read`・`op item get`・`vault read`・`vault kv get`・`chezmoi secret`）、環境変数の一覧（`printenv`・`env` の単独。`printenv <名前>` は許す）、**グローバルな環境変更**（`pip`・`pipx`・`uv tool install`・`npm -g`・`pnpm add -g`・`yarn global add`・`mise use -g`・`brew install`・`cargo`・`go`・`gem` の `install`）。グローバルな変更は確認（ask）にせず deny にする（離席中に利用者を待って止まらないため）。deny の `reason` がブロックのメッセージに付くので、`uv add`・`uvx`・`npx`・プロジェクト内の `mise use` など正しい手段へエージェントが自分で切り替えられる（常用ツールの追加は利用者へ依頼）。プロジェクト内の変更（`uv add`・`uv pip install`・`npm install <pkg>`・`mise use <tool>`）は止めない。既知の限界: `npm install foo -g` のようにフラグが後ろにある形は前方一致で拾えない。`path` の deny はファイルの読み書きを止めるだけで、コマンド経由の取得は止めないので別に置く。**`rm -rf` の一律 deny は置かない**: 過去のコマンドの 2.0% を誤って止めていた。`cc-safety-net` が対象（作業ツリーの外・home・root・`.git`）で判定する。
    - **強制 ask**（YOLO を切ると、毎回確認が出る）: ① 外部への投稿・変更（`gh` の `pr`・`issue`・`workflow`・`variable`・`gist` の変更系、`gh repo fork|rename|archive|unarchive`、`chezmoi apply|update`）、② 公開・配布・統合（`git flow integrate`・`git flow feature|release|hotfix|bugfix|support finish` = `develop`・`main` へのマージ（2026-11-11。`-C` 付き・`git-flow` 形も。feature 同士のマージと `develop` から feature への取り込みは allow）・`gh pr merge`・`gh release create|edit|delete|upload`・`gh repo create|edit|delete`・`gh gist create`・各種 `publish`・`twine upload`・`gem push`・`docker push`）、③ 履歴・設定の改変（`git rebase|config|filter-branch|update-ref -d|reflog expire|worktree remove|remote add|remote set-url`。`git config --get|--list|-l` だけは allow。`git worktree remove` も、パスが `.tmp/worktrees/` の下で、`--force`・`-f`・`..` を含まないときだけ allow （git 自身が、未コミットの変更がある worktree の削除を断り、枝は残る。`--force` は cc-safety-net も拒否する。消えるのは ignored のファイルだけ。2026-11-10）。実際の分類の順序は「最後に当たった規則が勝つ」ので、allow の例外は ask の後ろに置く）、④ 外部送信・永続化（`scp`・`sftp`・`ssh`・`rsync`・`socat`・`ncat`・`nc`・`telnet`・`aws s3 cp|sync`・`gsutil cp`・`az storage blob upload`・`crontab`・`at`・`batch`・`systemctl` の変更系・`systemd-run`・`fdisk`・`parted`）。
    - **サブコマンドの前に付くオプションを読み飛ばすため、規則を広げてある**: `gh` と `chezmoi` は `gh *pr create*`・`chezmoi *apply*` の形（`gh -R o/r pr create`・`chezmoi --force apply` を拾う）。`git` は `git -C <dir> <サブコマンド>` の形を別に足す（過去のコマンドの 3.4% が `git -C` を使う）。広げた分は、余分に ask が出ることはあっても、見逃しは減る。`git` の ask に `git *rebase*` のような広い形を使わないのは、コミットメッセージや `--grep` の語まで拾うため（試験で確認する）。
    - **`gh api` の書き込み**は、撤去したフルガードの `check_gh_api_mutation`（意味解析）を再現できないので、`-X`・`--method`・`-f`・`-F`・`--field`・`--raw-field`・`--input` を含む形を ask にする近似にした（GraphQL の読み取り `-f query=…` も ask になる）。
    - 出典は、撤去したフルガードの deny・confirm の一覧から利用者が選んだもの（2026-11-09）。`git reset --hard`・`git stash drop`・`git branch -D`・`git clean -f`・`mkfs` などは `cc-safety-net` が既に止めるので足さない（[評価の記録](../research/agents/pi-stock-packages-evaluation-2026-11.md)）。
    - **受容するもの**: 変数経由（`cmd=push; git $cmd`）・インラインコード（`python -c`・heredoc の中のスクリプト）での迂回は検出しない。ガードは意図的な迂回を保証しない（ガードの範囲）。撤去したフルガードの判定器はこれらを検出したが、インラインコードから外部コマンドを実行する形を一律に deny するため、過去のコマンドの 1.3% を誤って止めた。判定器を自作して載せる案は、この誤判定と維持費で見送った。
  - `path`（全ツール・bash 共通）の deny: `.env`・`*.env.*`（`*.env.example` は allow）・`~/.ssh`・`~/.aws`・`~/.gnupg`・`~/.netrc`・`~/.config/gh`・`~/.config/agents/websearch-keys.json`（検索の鍵ファイル。Bitwarden から同期される）・秘密鍵（`*.pem`・`*.key`・`id_rsa*` など）。**pi 自身の認証情報・設定（`~/.pi/agent/` の認証・信頼・モデル設定・MCP の設定、`ayu/` = pi-rewind のスナップショット）も deny**（2026-11-10）。利用者はいつも拒否するものなので、ask にせず deny にして確認で待たせない（理由をモデルへ返す）。`sessions/`・`extensions/*/logs` は、振り返りの分析で読むことがあるので ask のまま。ディレクトリ自体の deny も併せて置く（上の「再帰への備え」）。
  - **`path` の deny は、pib の囲いの `hide`（`runner.toml`）と同じ集合に保つ**（2026-11-12）。`~/.config/gcloud`・`~/.docker`・`~/.kube`・`~/.azure`・`~/.password-store`、`~/.git-credentials`・`~/.config/git/credentials`・`~/.pypirc`・`~/.vault-token`、Hugging Face のトークン、`~/.pi/agent/oauth.json` も deny。囲いの中で隠しても、囲いの外で動く `read` ツールで読めてしまうため（YOLO は ask を自動で許可するので、確認にも頼れない）。食い違いは `test_pi_sandbox_runner` が検出する。
  - **`path_write`（書き込みだけの deny。読み取りは許す）**: ファイルの道具は囲いの外で動き、これらは次のコマンド・次の起動から効く（囲いが外れる・方針が緩む・拡張やランチャーのコードが実行される）ため、次を拒否する。
    - **`~/.pi/agent/` の、pi が読み込む・実行するもの**: `settings.json`（`shellPath`）・`AGENTS.md`・`extensions/`（権限の設定を含む）・`agents/`・`npm/`・`install/`・`prompts/`・`skills/`・`themes/`・`missions/`・`permission-mode/`・`pi-subagents/`・各拡張の設定（`compaction.json` など）・**`bin/`**（pi のランチャー `pi` と、pi が管理する `fd`・`rg`。**`PATH` の先頭**で、`find`・`grep` はこれを `shellPath` を通さず直接起動する）・`git/`（git の package）・**`tmp/`**（`-e` で指定した一時 package の置き場 `tmp/extensions`。更新に失敗するとキャッシュを再利用するので、置かれたコードが次の `pi -e` で実行される）。**許可リスト型（`~/.pi/agent/*` を deny して `sessions/*` だけ allow）にはしない**: 方向別の規則は共通の `path` の後ろに足されるので、後ろの allow が `*.env` の deny やリンク先の保護を上書きしてしまう（再監査の指摘）。そのため、`sessions/`（子エージェントの成果物。実ログでは、ファイルの道具が書いていたのはここだけ）を除いて、1 つずつ deny を置く。**chezmoi が `~/.pi/agent` へ配るものは、すべて deny に入っていることを試験で固定する**（新しく配るものを足し忘れない）。
    - **`~/.config/pi-sandbox/`**（囲いの設定。runner はコマンドごとに読む）。
    - **囲いの中で読み取り専用に見せるものすべて（`runner.toml` の `visible.read`）**: `~/.local/bin/`（pib の部品を含む）・`~/.local/share/mise`・`~/.local/share/uv`・`~/.config/mise`・`~/.config/uv`・`~/.gitconfig` と git の設定・`~/.cargo`・`~/.rustup`。囲いが読み取り専用にしているのは、書き換えられると囲いが外れるから（例: mise・uv が管理するツールや、`~/.local/bin` のランチャーは、ホストで後から実行される。runner 自身は、システムの `/usr/bin/python3 -I -S` で動かすので、mise の Python には依らない）。**この一致は `test_pi_sandbox_runner` が固定する**。
    - 変えるのは利用者（chezmoi・mise・uv）。シェルの起動ファイル（`~/.bashrc` など）はまだ対象にしていない（[限界](sandbox/pi-sandbox-runner.md#保証しないこと限界)）。
    - **この保護は既定の場所に固定**: `pib` は、`PI_CODING_AGENT_DIR`・`PI_SANDBOX_RUNNER_CONFIG`・`XDG_CONFIG_HOME` が既定と違うと起動しない。制御ファイル（runner・`pib-shell`・`runner.toml`・`runner.local.toml`・`~/.pi/agent/settings.json`・管理済みの `bin/fd`・`bin/rg`・`bin/pi`）と、その置き場のディレクトリがリンクで既定の位置の外を指していても起動しない（拒否は名前に付くので、リンク先を直接指されると効かない）。
  - **全 deny に理由をつける**（2026-11-11）: `deny` の値は `{ "action": "deny", "reason": "…" }` と書ける。理由は、拒否の文に付いてエージェントへ届く（「なぜ拒否され、代わりに何をすべきか」を読める）。`path` の deny 25 件・`bash` の deny 42 件・`skill` の deny 1 件のすべてに、理由がある（試験 `test_every_deny_rule_carries_a_reason`）。
    **ask には、理由を付ける仕組みが無い**（拡張の docs: 理由は deny の値にだけ書ける）。確認の画面には、コマンドとパスだけが出る。そのため、「子が絶対にやってはいけない」操作は、理由つきの deny にする（無人の確認は 5 分で拒否され、止まる）。人が在席して承認したい操作（`gh` の変更系・`git rebase` など）だけを、ask に残す。
  - `mcp` は ask（検索の `websearch`・`agentcore-websearch` だけ allow。上の「MCP 設定」）、`skill` は allow。入れる拡張の自分のツール（`todo`・`ask_user_question`・`subagent`・`subagents_enable`・`bg_wait`）は毎回の確認を出さないよう allow。上のどれにも当たらないツール（`*`）は ask。
  - **`subagent_launch` は allow**（2026-11-09。当面の運用）。これは pi-subagents が、ワークフロー（`workflow`・`chain`・`tasks` で複数の子を組み合わせて起動する形）で子を起動する直前に出す入れ子の呼び出しで、ask のままだと子ごとに確認が出る。子の終了後に走る `gate`・`acceptance.verify` のシェルコマンドも載るが、**この呼び出しの時点では bash の規則で検査されない**（pi-subagents の docs `workflows.md`。この拡張が `commands` を検査するかは未確認）。運用では `gate`・`acceptance.verify` を使わない（[feature-orchestration の運用](../../.agents/skills/feature-orchestration/references/pi-subagents.md)）ので、実害は出にくい。`ask` へ戻せば、毎回その内容を見られる。
  - 子と親の連絡用のツール（`contact_supervisor`・`intercom`・`structured_output`・`subagent_command`）も allow。YOLO を切ると、規則の無いツールは `*` の ask になり、子が進捗を連絡するたびに確認が出るため。
  - 追加の 4 つの package のツール（下の「追加の 4 つの package」）: `bg_status`・`bg_kill`・`plan_mode_question`・`plan_mode_complete`・`goal_complete`・`goal_blocked`・`goal_wait` も allow（状態を記録するだけ、または読み取りのツール）。`bg_run` は allow にしない（`shellTools` で bash と同じ判定に通す）。
- **`shellTools`（マージ）**: `pi-permission-policy.json` の `shellTools`（`bg_run` の `commandArgument: command`・`workdirArgument: cwd`）を、既存の `shellTools` にマージする。リポジトリが持つキーだけをこの値にし、利用者が足した他のキーは保つ（`permission`・`commandEffects` は従来どおり置き換え）。
- **YOLO mode**: 拡張の `/permission-system` で ON / OFF できる。ON は ask を自動で承認するだけで、**明示の deny は YOLO でも効く**（上の deny・`path` の deny は残る）。**強制 ask は表現できない**（YOLO が全部 allow に戻す。`cc-safety-net` も ask にはできない）ので、強制 ask を使うなら YOLO を切る。切り替えた `yoloMode` は `chezmoi apply` で戻らない（上の「実行時の値は保つ」）。
  - **YOLO を切ると、規則に無くても ask になるもの**（拡張の `docs/configuration.md` の「Fail-closed behavior」）: `bash -c`・`eval`（中身を再解析しない）、`sudo`・`env`・`xargs`・`nohup`・`parallel`・`watch`・`flock`・`find -exec` など別のコマンドを実行する前置き（`time`・`timeout`・`nice`・`stdbuf`・`setsid` は中のコマンドで判定）、パースできないコマンド（例: heredoc と `2>&1` とパイプを同時に使う形）。YOLO が入っているときは、これらも自動承認されていた。確認画面の「このセッション中は許可」で、同じパターンは再質問されない。
- **確認で待たせない方針（2026-11-10）**: 確認（ask）が利用者待ちで自律稼働を止めるのを避ける。① **誰も答えない確認は 5 分で拒否して先へ進む**（`promptTimeoutMs: 300000`。2 分では焦るため 5 分にした。初期値だけで、変えた値は apply で戻らない。拒否しても承認にはならない。モデルには「誰も答えなかった」と伝わるので、他の作業を続けられる。答え始めると（キーを押すと）時計は止まる。拡張の docs の「Unanswered prompts」）。② **いつも拒否するものは ask にせず deny にする**（上の `path`）。③ 許可リストで、確認を出さない読み取りを増やす（上の `external_directory`）。④ エージェントの振る舞い（指示に追記）: 確認が出る操作を避ける（`cd` を絶対パスで書くのは上流の不具合の[一時対処](temporary-workarounds.md#pi-permission-system-の-cd-先の誤判定)）。拒否・誰も答えなかった操作は繰り返さず、他の作業を続けて、最後に「承認待ち」として一覧で報告する。**実測**（yolo を切って約 1 時間、レビューログ）: 確認 16 件のうち 13 件が作業ツリー外の読み取り（pi 自身のファイルを bash で読んだもの）、強制 ask は 1 件（`chezmoi apply`）、床（`bash -c` など）は 0 件。頑度はエージェントの読み方と許可の不足が原因だった。
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

### プロジェクト単位でデータセットを読み取り専用にする

作業ツリーの外にあるデータセット（例: `/data/datasets`）を、**そのプロジェクトでだけ**、読み取りを確認なしにし、書き込みは確認（ask）のままにする手順。グローバルの方針は `/tmp/*` だけを事前許可している。前提は YOLO を切っていること（切っていると ask は自動承認され、事前許可の意味がない）。

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
- **package の一覧の変更**: `pi-web-access` を外した（家の検索は自作の MCP `websearch`）。`pi-mcp-adapter` は `is-work` の機だけ入れる（他の機は pi 組み込みの MCP で足りる）。評価は [記録](../research/agents/pi-stock-packages-evaluation-2026-11.md)。
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

- **plan mode の設定**: `home/dot_pi/agent/modify_pi-plan-mode.json.py.tmpl` が `~/.pi/agent/pi-plan-mode.json` を配る。拡張が `/plan settings` で書き換えるので、既存のキーはすべて保ち、次の 2 つだけ無いときに補う。`defaultPlanTools` = `["read","bash","grep","find","ls","ask_user_question"]` に検索 MCP の完全名 4 つ（`mcp__websearch__web_search`・`mcp__websearch__fetch_page`・`mcp__websearch__search_papers`・`mcp__agentcore_websearch__web_search_tool__WebSearch`）を足したもの（許可リストは完全一致の名前だけ。この 4 つは [MCP の `pi_exposure = "direct"`](mcp-servers.md#pi_exposurepi-への見せ方) でモデルへ直接見せている。**既存の `defaultPlanTools` を持つファイルにも**、無い名前だけ末尾へ追記する（和集合。順序・利用者の名前は保つ。リストでない値は触らない）。`subagent` は入れない。子は別プロセスで plan mode の block が及ばないため）、`defaultPlanExportPath` = `.tmp/keep/plan/`（既定の `PLAN.md` で作業ツリーを汚さない）。拡張の側で `grep`・`find`・`ls` を使うには pi 本体の settings での有効化が要る（未実施）。
- **goal の運用**: 設定は拡張の既定（`continuationLimits.automaticTurns` = 25・`noProgressTurns` = 3・`rpc.enabled` = false・`retryUsageLimits` = false）。**`/goal` は必ず `--tokens` つきで使う**（例: `/goal --tokens 500k <目的>`）。**時間の上限は無い**ので、離席中は外側の `timeout` と合わせる。
- **限界**:
  - `bg_run` は、`cc-safety-net` の tool 名の既定（`bash`・`powershell` だけ）には入っていないが、`rule.json` の `command_tools` で宣言すれば解析される（[cc-safety-net の規則](#cc-safety-net-の規則)。宣言した状態で、`bg_run` 経由の `git reset --hard` が block されることを実機で確かめた）。`pi-permission-system` の deny・ask は `shellTools` 経由で効く。
  - pi-background の自動背景化は、pi 組み込みの bash のときだけ効く。**bash を置き換える拡張（サンドボックス系・`pi-patty-bg-tasks` など）を入れない**。入れると無効になる。pi を閉じると実行中の job は死ぬ。
  - `/goal` の完了は同じエージェントの**自己申告**（`goal_complete`）。独立した検証ではない。独立性が要るときは review の子を手順に入れる。
  - `pi-rewind` は **GPL-3.0**。npm で参照するだけで、このリポジトリにコードを取り込まない。戻せるのは作業ツリーのファイルだけ（`git commit`・ブランチ操作・push は戻らない）。
  - **`pi-rewind` の警告「Checkpoint failed: Command failed with exit code 1」（2026-11-10 に確認）**: `/reload` の直後のターンで出た。
    - 確かめたこと: 拡張のコードは、ターンの開始時に `git commit`（`--allow-empty` なし）を呼ぶ。変更が無いと git は「nothing to commit」を**標準出力**に出して終了コード 1 になる（使い捨ての repo で再現。標準エラーは 0 バイト）。拡張は、標準エラーが空だと「exit code 1」とだけ表示する。
    - 推測（未確認）: 拡張が覚えている「前回の記録」が `/reload` 後に古く、作業ツリーが記録済みの状態と一致して、食い違いで失敗した。確かめるには記録用の git（`~/.pi/agent/ayu/`）を読む必要があるが、方針で deny。
    - 観察: `/reload` のあと、ターンごとに繰り返し出た（1 つの依頼の途中のターンでも出る。最初の記録が失敗すると、拡張が次のターンでも作り直すため）。主な作業ツリーに変更が無いあいだ、直らない。
    - コードから分かること: 拡張が覚える「前回の記録」は、`/reload` 後にセッションの最後の記録（`afterCommit`）から決まる。これが記録用 git の先頭とずれ、作業ツリーが先頭と同じだと、毎回「nothing to commit」で失敗する。作業ツリーに変更が入ると、commit が成功して覚える値が更新され、直る見込み（統合など、主な作業ツリーを変える操作のあとで確かめる。未確認）。
    - 影響: 警告が出たターンは、巻き戻しの地点にならない。データは失われない。
    - 上流: 0.4.6 が npm の最新で、リポジトリ `ayu-exorcist/oh-my-pi` は 2026-07-28 にアーカイブ済み（読み取り専用）。同じ警告の Issue は無く、直る見込みもない。
    - 方針: 利用者が `/rewind` を使う予定なので、拡張は残す。毎ターン出るようなら（変更の有無に依らず）、拡張を外すか代わりを探す。
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
- **settings の `subagents.agentOverrides`**（`modify_pi_stock_settings.py.tmpl`）: 組み込みの `scout`（`read`・`grep`・`find`・`ls`・`contact_supervisor`）と `oracle`（`read`・`grep`・`find`・`ls`）の `tools` を読み取り専用に絞る（組み込みの既定は `bash`・`write` を持つ）。`reviewer`（読み取り専用）・`worker` は変えない。検索の子 `researcher`（`read`・`write`）・`evidence-auditor`（`read`）には、機の検索の MCP を `mcp:websearch`（家）・`mcp:agentcore-websearch`（会社 PC）で足す（[理由と会社 PC の設定](mcp-servers.md#子のエージェントへの検索-mcp-の渡し方)）。利用者が同じ役の `tools` を書いていれば保つ（無いときだけ補う）。他の `subagents` のキー・他の役の上書きも保つ。
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
- **permission**（`pi-permission-policy.json`）: `subagent_supervisor` は allow、`subagent_launch`（workflow の子の起動ごとの確認）は **ask**。`gate`・`acceptance.verify` のシェルは bash の規則の外なので使わない。
- 試験は `test/test_pi_subagents_config.py`（描画して確かめる。実機の apply は行わない）。
