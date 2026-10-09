# CHG-0020: OpenCode のハーネスを pi へ移す

- **状態**: In progress
- **更新日**: 2026-10-09
- **基準**: pi 1.1.0、OpenCode v2.0.22、コミット d5f012c、WSL2 (Ubuntu)

## 目的と非目的

普段使いの AI CLI を OpenCode から pi（earendil-works/pi）へ移す。このリポジトリが OpenCode のために
持っているハーネス（permission の生成、guide plugin、checkpoint plugin、子エージェント、`ocs`）を、
pi の上で作り直す。移すと決めた理由と判断材料は [CHG-0019](closed/0019-pi-harness-port-evaluation.md)。
要点は、判定とツールの実行が自分のコードに収まり、偽のモデル（faux）で通信なしに試験できることで、
上流の挙動を実機で測って追いかける保守が小さくなること。

受入条件（移行を終えたと言える条件）:

- 今の OpenCode のハーネスの保護を下げない: 秘密ファイルの read / edit の deny、未掲載の shell の確認、
  作業ツリーの外の edit の確認、shell 出力の伏字化、bypass の子の起動制限、Fence の境界（ADR-0012）
- 判定とツールの実行が、ハーネスの読み込み失敗・入力の書き換え・判定器の異常のどれでも許可側へ倒れない
- 守るためのロジックを、偽のモデルを使った試験で固定する。pi の内部の挙動に頼る 4 点
  （「現在地」の「引き継ぐ前提」）も試験で検出する
- 普段の作業（skills・MCP・編集・テスト・コミット・再開・圧縮）が pi で 1 周回る

非目的:

- Claude Code / Copilot CLI の設定を変えること（判定器を共有するかは段 1 で決めるが、変えるなら別の案件）
- oh-my-pi（`omp`）の評価（[CHG-0006](0006-pi-harness-trial.md) が持つ）
- 移行の途中で OpenCode のハーネスを改良すること。OpenCode の穴は CHG-0017 の補修までで止める
  （[CHG-0018](closed/0018-opencode-policy-role-split.md) は所有の規則までで閉じた）

> **2026-10-09、利用者が方針を決めた。** Orca と Zed は素の `pi`（ハーネス無し）を呼ぶ形のまま変えない。
> `pis`（ハーネス付き）は利用者が自分で起動するとき用で、**優先度を下げる**。段 1〜5 で作ったもの
> （判定 API・ハーネス・`pis`・境界）は、いまの状態で止めて保守だけにする。素の `pi` が保護無しで動くことは、
> [CHG-0006](0006-pi-harness-trial.md) の「利便性を取り、払う代償を明記する」という軸のとおり（保護が要る作業は
> `pis` か `pis --boundary` で起動する）。段 6 は、この方針に合わせて内容を改める（下の計画表）。

## 実施計画

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1 | **判定 API**。CLI に依存せず allow / ask / deny と理由を必ず返し、異常時は拒否する判定器を作る。規則は `common.toml` から生成し、「共通の禁止」と「役割ごとのプロファイル」に分ける（CHG-0018 の設計を引き継ぐ） | 完了（誘導・境界の中・`work_read` は段 2 / 段 4 へ） |
| 1a | `[pi]` を正本にする。`[opencode.shell] allow`・`redact`・`external_read`・`skill_scripts` を `[pi]` へ移し、OpenCode へは `generate.py` が写す。OpenCode の出力は変えない | 完了 |
| 1b | 判定 API `decide()` を作る。応答に `source` を入れ、異常は deny | 完了（[判定 API](../spec/pi-decide.md)） |
| 1c | `decide()` が今の `check_bash.py` と同じ入力で同じ deny / ask を返すことを試験で固定する | 完了（1041 件で一致） |
| 2 | **ハーネス拡張**。試作（`scripts/pi-harness-spike/`）を本番の形にする: ツールは組み込みに無い名前、`execute()` で再判定、確認は 1 件ずつ、伏字化は `content`・`structuredContent`・`details`、圧縮のファイルの一覧の補い、子エージェント、MCP はハーネスから登録 | 完了 |
| 2a | ハーネスの核: 別名のツール、判定 API の呼び出し（`execute()` で最終の判定）、確認の順番待ち、伏字化、圧縮のファイルの一覧、`[agent_env]`、`rules.json` の生成、偽のモデルの試験 | 完了（[pi のハーネス](../spec/pi-harness.md)） |
| 2b | 子エージェント（役割と bypass の受け渡し、子の拒否を構造化して返す）と、MCP をハーネスから登録 | 完了（[子エージェント](../spec/pi-harness.md#子エージェント)・[MCP](../spec/pi-harness.md#mcp)） |
| 2c | 誘導（`[[opencode.shell.guide]]` の 13 件）の仕分けと判定器への取り込み | 完了（4 件を `[[pi.guide]]` へ。[誘導](../spec/pi-decide.md#誘導)） |
| 3 | **配布**。pi の導入（`agent-cli-install`）、設定、起動の入口（`-nbt -ne -e <ハーネス>` を固定する）、`common.toml` の `[[mcp]]` から MCP を生成 | 完了（起動は `pis`、[起動](../spec/pi-harness.md#起動)・[pi の設定](../spec/pi-harness.md#pi-の設定)） |
| 4 | **境界**。`ocs` の仕組みで pi を Fence で包む。境界用の agent 置き場を起動ごとに書き出す | 完了（`pis --boundary`。[境界](../spec/pi-harness.md#境界)） |
| 5 | **ハーネス以外の機能**。checkpoint（`session_before_compact`）、モデルの階層と effort、確認画面の説明、`git commit` の件名と本文の表示、`/fleet`、キーバインド、Orca、Windows、検証コマンドを畳む `verify` ツール（CHG-0002 の段階 5 から移管） | 完了 |
| 5a | checkpoint を圧縮の要約の指示に置き換える（`compact()` に雛形の要点を渡す） | 完了（実際のモデルでも確認） |
| 5b | `git commit` の確認に件名・本文を出す（`commit-message.js` を取り込む） | 完了 |
| 5c | formatter（edit / write の後に既存の hook を呼ぶ） | 完了 |
| 5d | `/fleet`（プロンプトテンプレートの生成）・キーバインド・共通の指示（`AGENTS.md`）の配布 | 完了 |
| 5e | Orca・Zed から起動するときの扱い（Orca の拡張を読む・RPC の確認の期限）。起動の入口は、利用者の判断で素の `pi` のまま（`pis` は利用者の起動用） | 完了 |
| 6 | **OpenCode の撤去**（任意。優先度低）。Orca・Zed は素の `pi` のままなので「切り替え」は要らない。残るのは、OpenCode の生成・plugin・`ocs` の OpenCode 部分・docs・Windows の導入を消すかどうかの判断。規模は、配布物 約 3,900 行、`generate.py` の OpenCode 関連 約 1,300 行、テスト 約 19,700 行、docs 約 9,700 行。CHG-0017 を閉じ、CHG-0005 を再開できる状態にする。Windows は pi のハーネスが無いので、OpenCode を残すか決める | 未着手（保留） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

段 1〜4 で受入条件の保護をそろえ、段 5 で使い勝手をそろえ、段 6 で切り替える。段 6 までは OpenCode を
普段使いのまま残す。

## 現在地

段 1 を進めている。2026-10-09 に利用者が 2 つ決めた。

- **判定器は Claude Code / Copilot CLI と共有する。** hook の出力は変えない（「判定 API の入力（案）」）
- **`[pi]` を正本にし、OpenCode の値は `generate.py` で作る。** 段 6 で消すのが OpenCode 側になる

段 5 の実装を終えた（2026-10-09）。圧縮の指示は `compact()` を `streamSimple` 経由で呼び、Copilot では認証の
`baseUrl` を反映しないと 401 になることが実機で分かった（偽のモデルでは見えない）。実際のモデルで、要約に合格条件と
「未作成」の扱いが入ることを確かめた。**利用者から、Orca と Zed から pi を開くことがほとんどと聞いた。**
どちらも起動の入口が `pi` のままだとハーネスを通らない。Orca は `pis` が Orca の状態表示の拡張を読めるように
した。Zed は RPC で起動されるので、確認に期限を付けた。起動の入口を `pis` にする方法を、利用者に確認する。

段 4 を終えた（2026-10-09）。利用者の判断（推奨どおり）で、入口は `pis --boundary`、設定は共有キーを
`[opencode.sandbox]` のまま読み、pi の追加分を `[pi.sandbox]` に置いた。実際の Fence で、境界チェックが合格し、
境界の内側から実際のモデルを呼べ、内側で作ったセッションを外の `pi -c` で再開できた。
**未確認だった認証の写しは問題があった**: OpenAI の認証は期限 47 分の OAuth で、写しの中で更新されると本物が
失効しうる。そこで pi を子プロセスとして動かし、終了後に新しい認証だけを本物へ戻して写しを消す形にした。

段 3 を終えた（2026-10-09）。利用者の判断で、起動の入口は別名のコマンド `pis` にし（素の `pi` は段 6 まで
そのまま）、`~/.pi/agent/settings.json` は生成器の持ち物のキー（既定のモデル・思考の強さ・skills の置き場）だけを
差し替える。pi 本体は `agent-cli-install` が公式インストーラーで入れる（mise の Node.js が前提）。`pis` は
`--no-approve` で作業先の `.pi/` を読まず、`~/.pi/agent/mcp.json` にサーバがあれば起動しない。

段 2 を終えた（2026-10-09）。2c で OpenCode の誘導 13 件を仕分け、読み書きを pi のツールへ寄せる 4 件を
`[[pi.guide]]` へ移した（OpenCode も `pi = "<id>"` で同じものを使う）。残る 9 件は、判定器の意味解析や allow の
扱いで足りることを、判定器に代表のコマンドを通して確かめた（`cd`・リダイレクト・`--output`・`git -c … commit`・
`pip`・危険な `rm` / `find`）。

2b を終えた（2026-10-09）。利用者の判断（案 A）で、権限の範囲は `[pi.profiles]` に置き、子エージェントは
`[pi.agents]` に役割・階層・指示を書く形にした。役割は `implementer` / `reader` / `committer` / `worker` の 4 つで、
`committer` だけが `git status` / `git diff` を確認なしで通す。実際のモデルで、親（Sonnet 5.5）が `explore` を起動して
結果を受け取れた。起動の形は `pi -nbt -ne -e builtin:mcp -e ~/.config/pi/harness` に変わった（MCP のため）。

2a を終えた（2026-10-09）。ハーネスの本体は `~/.config/pi/harness/`（[pi のハーネス](../spec/pi-harness.md)）。
偽のモデルの試験 13 件が通り、実際のモデル（Copilot の Sonnet 5.5）でも読み取り・`git log`・確認の拒否が
期待どおりに動いた。判定 1 回は 0.1 秒ほど（Python の起動）で、`tool_call` と `execute()` で同じ入力なら 1 回にした。

段 1 を終えた（2026-10-09）。判定 API は [判定 API](../spec/pi-decide.md) が正本。
`check_bash.py` の試験に出てくる 1041 件のコマンドで、hook の deny / ask と判定器の decision が一致した
（deny 555・ask 147・hook が何も返さない 339）。

1a（`[pi]` の正本化）では、4 つの節を `[pi]` へ移し、`generate.py` の `load_common` で OpenCode の位置へ
写す（[pi と共有する節](../spec/agent-config-generation.md#pi-と共有する節)）。2 つのユーザで、OpenCode・Claude・
Copilot の生成の出力が移す前と一致した。

### 引き継ぐ前提（CHG-0019 の試作で確かめたこと）

[試作の記録](../research/agents/pi-harness-spike.md)の E1〜E4。

- 起動は `pi -nbt -ne -e <ハーネス>`。ハーネスのツールは組み込みに無い名前（試作では `guarded_*`）にする
- 最終の判定はツールの `execute()` の中。`tool_call` の判定は前段の案内と確認画面
- 確認は 1 件ずつ出す。重なるのは codemode の中で並べた呼び出しだけだが、順番待ちは 10 行ほど
- 伏字化は、ハーネスが持つツールは `execute()` の中、持たないツールは `tool_result` で例外を投げずに
  結果ごと差し替える
- 子エージェントは同じハーネスを付けた子の pi プロセス。親は bypass の印を環境変数で渡し、子の拒否は
  `blocked` として返す
- Fence の境界では、agent 置き場を書けるようにする（pi は読むときにも `.lock` を作る）。本物の
  `~/.pi/agent` は境界に入れず、境界用の agent 置き場を起動ごとに書き出す

**pi の内部の挙動に頼る 4 点**（公開の約束ではない。版を上げるたびに試験で確かめる）:

1. `/reload` は直前に有効だったツールを名前で有効にし直す（E1）
2. 圧縮の直前のイベントの `preparation` が既定の要約にそのまま渡る（E2）
3. bash の `details.truncation.content` に生の出力が入る（E3）
4. 設定と認証を読むときにも agent 置き場に `.lock` を `mkdir` する（E4）

### CHG-0018 から引き継ぐ設計

- **共通の禁止**は、どの役割からも解除できない。**役割ごとのプロファイル**は、宣言したエージェントの
  全部に必ず当てる（当てていなければ生成で止める。CHG-0018 の対策 3）
- プロファイルは今の OpenCode の棚卸しを出発点にする: 実装役（`build` 相当・作業役・bypass 系）、
  読み取り役（`explore`・`plan`・`review`・`commit` 相当）、なし
- 配置先の設定の所有の規則（生成器の持ち物の範囲を決め、古い値を消す）は、pi の設定の生成にも当てる

### 段 1 の前の棚卸し（2026-10-09）

`home/dot_config/agents/common.toml.tmpl`（d5f012c）のうち、OpenCode のハーネスが使っている節を
pi でどう扱うかを分けた。件数は描画前のテンプレートを読んだもの。

#### CLI 共通の節

Claude Code / Copilot CLI と共有している節。pi でも入力にする。

| 節 | 中身 | pi での扱い |
| --- | --- | --- |
| `[bash] deny`（85）・`ask`（23） | コマンドの先頭一致の禁止と確認 | **共通の禁止**と、実装役の確認。`command_policy.py` の正規化（`cd &&`・`git -C`・連結の分割）をそのまま使う |
| `[bash] allow`（14） | Claude の自動承認 | **使わない**。pi は未掲載が確認になるので、allow は無確認の実行を意味する。`git diff` / `git status` は `.git/config` から任意コマンドを起動できるので、今の OpenCode と同じく別の狭い一覧にする |
| `[bash] ask_hook_owned`（1: `rm`） | hook が承認要否を決める ask | 判定器の `rm` の免除（作業ツリーの中と確証できる削除）をそのまま使える。OpenCode のように素の ask に戻す必要が無い |
| `[bash.deny_guide]`（user_only 63・elsewhere 2・alternative 6） | deny の理由と代替の説明 | 判定の理由として返す。今は OpenCode 専用だが、中身は CLI に依存しない |
| `[file] read_deny_globs`（48）・`write_deny_globs`（41）・`deny_exceptions`（1） | 秘密のパスの読み書きの禁止と例外 | **共通の禁止**。`matches_read_deny` が例外まで扱える。`**` を OpenCode の記法へ変換する処理は要らない |
| `[file] read_ask_globs`（0）・`write_ask_globs`（1） | パスの確認 | 実装役の確認 |
| `[agent_env]` | git の入力待ちを防ぐ環境変数 | bash の起動前に入れる（試作の bash の `spawnHook` か環境の付け足し） |
| `[[mcp]]`（1） | MCP サーバ | ハーネスから `registerMcpServer` で登録する（CHG-0019 E3） |
| `[provider.*]` | モデルの通信先 | 境界の通信の許可 |
| `[[hooks]]`（5） | Claude / Copilot の hook | `format-file.sh` / `markdownlint.sh` は edit / write の後に呼ぶ（段 5）。`redirect-tmp.py` は中身を見て決める。`check_bash.py` / `check_file_read.py` は判定器そのものなので呼ばない |

#### 判定器の意味解析

`home/dot_claude/hooks/lib/bashrules/`。Claude / Copilot の hook だけが使っている。

- deny 側 27 項目（うち 2 つは設定の読み込みの確認と `[bash] deny` の照合。残る 25 が意味解析で、
  `check_rm_root_guard`・`check_pipe_to_shell`・`check_secret_env_echo`・`check_guard_tampering` など）、
  ask 側 6 項目（うち 1 つは `[bash] ask` の照合。残る 5 が `check_gh_api_mutation`・`check_curl_wget_mutation` など）
- **OpenCode には届いていなかった。** plugin が JavaScript で、Python の判定器を呼べないため、
  `[[opencode.shell.guide]]` の正規表現で一部を真似ていた（`pip` の誘導、`rm` の危険な形など）。
  pi のハーネスは判定器を子プロセスで呼べるので、これらが全部効くようになる

#### OpenCode 専用の節

| 節 | pi での扱い |
| --- | --- |
| `[opencode.shell] allow`（5） | 実装役の無確認の一覧へ移す |
| `[[opencode.shell.guide]]`（13） | 1 件ずつ見直す。判定器の意味解析と重なるもの（`pip`・`rm` の危険な形・`find -delete`）は捨てる。ツールへの誘導（`cat` / `head` / `tail` / `sed -n` → read、ヒアドキュメント → write）と、allow したコマンドの書き込み形の歯止めは残す。`cd` の誘導は pi の bash に `workdir` 引数が無いので文面を変えるか捨てる |
| `[opencode.redact]`（規則 9） | そのまま使う。伏せる先に `structuredContent` と `details` を足す（CHG-0019 E3） |
| `[opencode.external_read]`（3） | 実装役・読み取り役の作業ツリーの外の読み取りの許可 |
| `[opencode.skill_scripts]`（3） | 実装役の無確認の一覧。リダイレクトの禁止もそのまま |
| `[opencode.agent]` / `[opencode.agents]`（8）と `[opencode.bypass_children]` | 役割（ロール）の宣言へ移す。4 つの一覧のうち「bypass の子の外部読み取りだけ確認を省く」は、子が同じハーネスで判定するので要らなくなる見込み |
| `[opencode.model.*]` | 階層をそのまま使い、役割に割り当てる（「未解決点」のモデルの階層） |
| `[opencode.commands.fleet]` | 段 5 |
| `[opencode.sandbox]` と `.permissions` / `.policies` | 段 4 の境界。境界の中の既定（shell の確認を外す）は、判定器へ「境界の中」を渡して分ける |
| `[opencode.keybinds]`・`ask_description`・`formatter`・`service`・`auto_update`・`websearch` | 段 5 か不要（`service` は常駐サービスが無いので不要） |

#### pi では要らなくなる処理

glob の `**` の変換、後勝ちの並べ替え、`restate_global_deny`、deny の例外と
ask の交差（`wildcard_intersection`）、`guarded_subagents` / `bypass_child_agents` の照会、`grep` / `glob` の
結果フィルタ（ツールをハーネスが持つので判定の前に止められる）。

### 段 5 の仕分け（2026-10-09）

ハーネス以外の機能を、今の OpenCode での姿と pi の部品を確かめたうえで分けた（推奨。利用者の確認待ち）。

| 機能 | 今の OpenCode | pi での扱い | 判断 |
| --- | --- | --- | --- |
| checkpoint（圧縮をまたぐ引き継ぎ） | plugin（214 行）・`checkpoint.py`・skill・`AGENTS.md` の節。圧縮の要約を 6 節の記録にして `.tmp/` へ保存し、圧縮後に注入する | pi の圧縮の要約はセッションに残り、再開しても消えない。`session_before_compact` で `compact()` に雛形の要点（「Next は手順まで書く」「略語を展開する」）を渡すだけにする。外部ファイル・skill・注入の印は作らない | **作り直す（小さく）**。要らなくなる: plugin・`checkpoint.py`・skill・`AGENTS.md` の節 |
| モデルの階層と effort | `[opencode.model]`（`default` / `routine` / `worker` / `deep` / `second_opinion`） | 子エージェントは階層から引く（済）。親は `settings.json`（済）。階層の表を `[pi]` へ移すのは段 6 | **済 + 段 6** |
| 確認画面の説明（`ask_description`） | 60 文字以上のコマンドで、安価なモデルが 1 行の説明を作り toast で出す | 作らない。確認画面は生のコマンドと、判定の理由（`reason`）を出す（済）。判定器の誘導と deny で確認の数が減っている | **要らなくなる** |
| `git commit` の件名と本文の表示 | `commit-message.js`（216 行、純関数）を TUI の確認画面の上に出す | ハーネスが同じ `commit-message.js` を取り込み、確認画面の本文に件名・本文・追加するパスを出す。取り込めなければ出さない（飾りなので止めない） | **作る（小）** |
| `/fleet`（並列作業） | コマンドの指示文と、作業役 `fleet-worker` / `bypass-fleet-worker` | 作業役は `[pi.agents.worker]` で済。指示文は pi のプロンプトテンプレート（`~/.pi/agent/prompts/fleet.md`）にし、`[opencode.commands.fleet]` から生成する。pi は 1 つの返答に並んだ tool call を並列に実行する | **作る（小）**。`-ne` でプロンプトテンプレートが読まれるかは未確認 |
| キーバインド | `[opencode.keybinds]`（Ctrl+D で終了、Ctrl+C / Esc で中断、`service.restart`） | `~/.pi/agent/keybindings.json` の持ち物として生成する（`app.interrupt` に Ctrl+C を足し、`app.clear` を外す）。`service.restart` は常駐サービスが無いので要らない | **作る（小）** |
| `verify` ツール（CHG-0002 の段階 5） | 未実装 | 作らない。検証コマンドを許可に載せると、リポジトリの設定（pre-commit の hook）を経由した任意コード実行を確認なしで通す。bypass なら確認は元から出ない | **見送り** |
| formatter | `[opencode.formatter]`（markdownlint など） | `guarded_edit` / `guarded_write` の後に、既存の PostToolUse hook（`format-file.sh` / `markdownlint.sh`）を呼ぶ。整形は pi のファイル書き込みの順番待ちの中で行う | **作る（小）** |
| 共通の指示（`AGENTS.md`） | `~/.config/opencode/AGENTS.md`（共通の指示 + OpenCode 固有の 2 節） | `~/.pi/agent/AGENTS.md` へ共通の指示だけを配る | **作る（小）** |
| skills | `~/.config/opencode/skills`（checkpoint） | `[pi.settings] skills` に `~/.claude/skills` を入れた（済）。checkpoint の skill は作らない | **済** |
| Orca・herdr | Orca の上書き設定を `shellenv.sh` で補う。herdr は Copilot / Claude の hook を登録 | pi 向けには要らない見込み。Orca や herdr から pi を起動するか、pi に herdr の連携があるかは未確認 | **未確認（利用者に確認）** |
| Windows | OpenCode は Windows にも配る | pi・ハーネス・`pis`・境界は Unix だけ。Windows は OpenCode を外すまで使う | **段 6 で決める** |

**段 6 で消えるもの（見込み）**: guide plugin（`index.js` 511 行・`commit-message.js` 216 行・`tui.ts` 140 行。
`commit-message.js` はハーネスへ移す）、checkpoint plugin（214 行）・`checkpoint.py`・checkpoint の skill、
`[opencode.*]` の約 25 の節、`generate.py` の OpenCode 専用の生成、`ocs` の OpenCode 部分、`oc-utils`、
`shellenv.sh` の OpenCode の節。

### 判定 API の入力（案）

**判定器は Claude Code / Copilot CLI と共有する（案）。** 共有するのは判定の中身
（`command_policy.py` と `bashrules`）で、Claude / Copilot の hook の出力は変えない。

- 新しい入口 `decide(request) -> response` を足す。pi のハーネスはこれを呼ぶ。`check_bash.py` は当面
  そのままにし、載せ替えるなら別の案件にする（「目的と非目的」の非目的）
- 応答に**どこで決まったか**（`source`: 規則・意味解析・既定）を入れる。Claude / Copilot は「既定」なら
  何も返さない（今の契約）。pi は役割の既定（実装役なら ask）を使う。これで CHG-0019 のレビューの
  BLOCKER 3（空の出力を allow と読む誤り）を構造で防ぐ
- 異常（入力の不備・タイムアウト・例外）は deny を返す。ハーネスは、形の正しい応答以外を deny と読む

```text
request:  { tool, input, cwd, role, bypass, boundary }
response: { decision: allow | ask | deny, reason, source: rule | check | default, guide? }
```

評価順はコードに固定する（設定の並びに意味を持たせない）。

1. **共通の禁止**: `[bash] deny`・意味解析の deny・`[file]` の deny（例外を含む）。どの役割・bypass・境界でも外れない
2. **役割のツール**: 役割に無いツールは deny（読み取り役の bash・edit など）
3. **役割の確認と許可**: `[bash] ask`・意味解析の ask・`[file]` の ask・作業ツリーの外の edit・誘導（deny と案内）。
   無確認の一覧（`[opencode.shell] allow` と skill のスクリプトの後継）に当たれば allow
4. **既定**: 実装役は ask、読み取り役は deny
5. **bypass**: 3・4 の ask だけを allow にする（今の ADR-0014 と同じ）
6. **境界の中**: 今の `drop_shell` に当たる確認だけを外す

`common.toml` には `[pi]` の節を足し、役割（プロファイル）・無確認の一覧・誘導・伏字化・外部の読み取り・
skill のスクリプト・境界を置く。`[opencode.*]` から移すものは、段 6 で OpenCode を撤去するまで
両方に置く（同じ値を 2 か所に書く期間ができる。生成器で片方から作れるなら作る）。

## 未解決点

- **判定器に入れていないもの。** 境界の中の既定（`boundary`）と、`[opencode.sandbox] work_read` の読み取りの許可。
  段 4 で入れる
- **判定 1 回ごとの Python の起動（0.1 秒ほど）。** 1 つの呼び出しで 1 回にした。長い作業で気になるかは
  常用で見る。気になれば判定器を常駐させる（複雑さが増すので、まずは測る）
- **`[[opencode.shell.guide]]` の 13 件の仕分け。** 「OpenCode 専用の節」の表の方針で、1 件ずつ決める
- **Windows。** pi は Windows に対応しているが、ハーネス・判定器・境界を Windows で動かすかは未定
  （今の `ocs` も Ubuntu / WSL のみ）
- **Orca。** Orca が起動する pi に、起動の入口（`-nbt -ne -e`）をどう渡すか
- **認証の戻しの実機確認。** 戻す処理は単体試験で固定した（新しい分だけ・ロック・壊れた写し）が、実際に期限切れの
  トークンを境界の内側で更新させて確かめてはいない（期限が近いトークンがある機会に確かめる）
- **ツールの名前。** 別名にしたとき、skill やシステムプロンプトの指針が `bash` / `read` を名指しする箇所を
  どう扱うか（小さな課題では 4 モデルとも迷わなかった）
- **子エージェントの拒否の渡し方。** 試作は文言（`not approved:`）で見分けた。本番は構造化して渡す
- **モデルの階層の置き場。** 子エージェントは `[opencode.model.tier.*]` から引いている（`#variant` を
  `:variant` に読み替え）。`[pi]` を正本にする方針に合わせて移すか。Bedrock のモデル ID が pi で通るかは未確認

## 次の調査・実験

- 段 5 の入口: ハーネス以外の機能の仕分け（checkpoint・モデルの階層と effort・確認画面の説明・`git commit` の
  件名と本文の表示・`/fleet`・キーバインド・`verify` ツール）。今の OpenCode での使われ方と、pi でそのまま
  使えるもの・作り直すもの・要らなくなるものに分ける
- 試作のスクリプト（`run.sh`・`paths-run.sh`・`child-run.sh`・`fence-run.sh`）を、段 2 で `test/` の
  回帰試験へ移す方法を決める（pi が無い環境では skip する）

## 評価基準

**必須**: 「目的と非目的」の受入条件のすべて。

**望ましい**:

- `generate.py` の OpenCode 専用の生成（後勝ちの並べ替え・glob の変換・写し直し）を撤去できる
- Claude Code / Copilot CLI と判定器を共有できる
- pi の版を上げたとき、試験だけで内部の挙動の変化に気付ける

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| pi + ツールを自分で持つハーネス（CHG-0019 の C2） | CHG-0019 の試作で BLOCKER と段 4 の項目がすべて合格 | 確認の順番待ち・子エージェント・伏字化の経路・境界を自前で持つ。pi の内部の挙動に 4 点頼る | 「未解決点」 | 採用 | 段 1 |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |

## 実装・検証

## 重要な更新

- **2026-10-09**: 利用者が、Orca と Zed は素の `pi` のまま、`pis` は利用者の起動用で優先度を下げてよいと決めた。
  段 5e を完了にし、段 6 を「OpenCode の撤去（任意）」に改めて保留にした
- **2026-10-09**: 段 5 の実装を終えた（5a〜5d）。圧縮の指示・commit の確認の本文・整形・`/fleet`・キーバインド・
  共通の指示・Orca の拡張の読み込み。利用者が Orca と Zed から pi を開くと分かり、起動の入口の切り替えが段 6 の
  最優先になった
- **2026-10-09**: 段 4 を終えた。`pis --boundary` が `ocs --harness pi` へ引き継ぐ。認証の写しの問題
  （OAuth の更新が本物へ戻らない）に対し、子プロセスで動かして終了後に新しい認証だけを戻し、写しを消す形にした
- **2026-10-09**: 段 3 を終えた。起動は `pis`（素の `pi` は段 6 まで残す）、`settings.json` は持ち物のキーだけ。
  `pis` は `--no-approve` を付け、`~/.pi/agent/mcp.json` にサーバがあれば起動しない
- **2026-10-09**: 段 2 を終えた（2c）。誘導 13 件のうち 4 件を `[[pi.guide]]` へ移し、判定器と OpenCode の
  両方が使う形にした。残る 9 件は判定器のほかの規則で足りる
- **2026-10-09**: 2b を終えた（案 A。役割は `[pi.profiles]`、子エージェントは `[pi.agents]`）。
  役割に無いツールはハーネスが登録しないようにした（読み取り役の子が bash を試して拒否されるのを避ける）。
  MCP は `-ne` で組み込みの対応ごと外れるので、`-e builtin:mcp` を起動の形に足した
- **2026-10-09**: 2a を終えた。試作のハーネスを本番の形にし、`~/.config/pi/harness/` に配る。
  判定 1 回は 0.1 秒ほどで、`tool_call` と `execute()` で同じ入力なら判定を使い回すようにした
- **2026-10-09**: 段 1 を終えた。`decide()` を `~/.claude/hooks/` に置き（判定の中身の `bashrules` が
  そこにある）、役割を `[pi.profiles]` に足した。`check_bash.py` の試験の 1041 件で hook と判定が一致した
- **2026-10-09**: 利用者が、判定器を Claude / Copilot と共有すること、`[pi]` を正本にすることを決めた。
  1a として 4 つの節を `[pi]` へ移し、OpenCode へは `generate.py` で写す形にした（出力は不変）
- **2026-10-09**: 第一サポートが決まったので、保留中の案件を整理した。CHG-0002 は段階 0〜3 の採用で閉じ、
  段階 5 の `verify` ツールを段 5 へ移した。CHG-0005 の再開条件を「段 6 で OpenCode の節を撤去したあと」にした
- **2026-10-09**: 段 1 の前の棚卸しをした。判定器の意味解析（deny 25 種・ask 5 種）は OpenCode に
  届いておらず、pi では子プロセスで呼べるので全部効くと分かった。判定器を Claude / Copilot と共有し、
  応答に「どこで決まったか」を入れる案を立てた
- **2026-10-09**: 起票。CHG-0019 で利用者が移行すると決めた。CHG-0018 は所有の規則（P）までで閉じ、
  プロファイルの設計をこの案件に引き継いだ

## 終了結果
