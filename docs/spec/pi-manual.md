# pi / pis ハーネス利用者マニュアル

- **目的**: `pi`（このリポジトリが配るフルガード付きの pi）と `pis`（サンドボックス付きの起動）の、**今ある機能・設定の変え方・独自コマンド**を、忘れたときに見直す
- **詳しい仕様**: 各節と末尾の正本の文書。機能の地図は [pi の機能](pi-features.md)
- **運用モード**: pi 単独 / PR ビューア併用の使い分けは [運用モード](operation-modes.md)

> **状態（2026-11-05 時点）**
>
> - 記載した既定値は、リポジトリに同梱された設定の値
> - 保留の承認（`/pending approve`・`git_integrate`）は撤去済み。統合は必須確認（TUI）か PR ビューアの「統合する」ボタン（[CHG-0062](../change/0062-pr-hub-simplify.md)、履歴は [guard/pi-pending.md](guard/pi-pending.md)）
> - PR ビューアの書き込み系の旗（`--allow-merge`・`--allow-create`・`--allow-jobs`）は既定で無効。ジョブ・起票・markdown 描画・worktree の所有（`wt_owner.py`）・統合用の枝（`bundle.py`）・掃除（`wt_clean.py`）の道具が入った。使い分けは [運用モード](operation-modes.md)
> - 反映は `chezmoi apply` と pi の再起動の後

## 早見（1 画面）

### 最初にやること

| やりたいこと | 操作 |
| --- | --- |
| 普段の起動（直近を再開） | `pis`（Linux / WSL はサンドボックス付き・bypass 標準 ON → §2） |
| 新規セッションで起動 | `pis --new`（bypass を切るなら `pis --no-bypass` → §2） |
| 状態・要対応の確認 | フッターを見る、または `/board` で盤面を開く（→ §3, §4） |
| 変更の検査 | 日常は `mise run verify`、コミット前に `mise run verify:all`（→ §8） |

### よく使うコマンド

| コマンド | 動作（→ §2, §4） |
| --- | --- |
| `/board` / `/pending` | 盤面の表示 / 退避したコミットの一覧・表示・破棄 |
| `/bypass [on\|off]` | ask 判定の確認省略を切替（実行中の子は停止） |
| `/orchestrate [on\|off\|status]` | 親の作業ツールを隠して計画・判断・委譲へ絞る |
| `/plan` | 計画モードの切替（書き込み・実行ツールを外す） |
| `/agents` / `/worktrees` | 子の一覧・状態確認 / 隔離 worker の一覧・回収・破棄 |
| `/btw [--plain] <質問>` | 履歴や文脈に残さない、ついでの質問 |
| `pk [<話題>]` | リポジトリの補助スクリプトの一覧・実行（シェル用 → §2） |

### よく使う設定

| 対象 | 場所・キー（生成物は直接編集しない → §7） |
| --- | --- |
| 全マシン共通の正本 | `home/dot_config/agents/common.toml.tmpl`（編集後は chezmoi の apply） |
| マシン別の上書き | `~/.config/agents/local.toml`（`[pis.network]`・`[pi.sandbox]` 等 5 節のみ） |
| 作業先ごとの許可範囲 | `<起動ディレクトリ>/.opencode/sandbox.toml`（`read`・`write` 等） |
| リポジトリごとの統合先と接頭辞の設定を変える | `<リポジトリ>/.agents/config/pi.json`（コミットした内容だけが効く → §7.6） |
| 起動時の一時追加・切替 | `PIS_EXTRA_READ`、`PI_HARNESS_ROLE`、`PI_HARNESS_ORCHESTRATE` |

### 困ったとき

| 症状 | 対処（→ §8, §9） |
| --- | --- |
| 事前検査に落ちる / 読めない | `pis --check` で確認 / `PIS_EXTRA_READ` や `[pi.sandbox] read` で追加 |
| 子が起動できない | 同時上限 4 件・役割の `task` 有無・`/plan` 制限・ToDo ID 指定を確認 |
| 退避したコミットが増えた | `/pending list` と `drop` で整理 |
| `chezmoi diff` が全部 new file | サンドボックス外で実行する（内側ではホームが不可視 → §8） |
| ガード自体が故障した | 復旧専用で `pi -ne --tools read,bash,edit,write`（保護なし → §9） |

## 1. 概要

| 要素 | 内容 |
| --- | --- |
| フルガード（ハーネス） | pi の拡張。ツール呼び出しを deny / confirm / ask / allow に判定し、出力の伏字化、子エージェント、承認つき操作を提供する。設定は `~/.config/pi/harness/rules.json`（生成物） |
| `pis` | サンドボックス（Fence）の中で pi を起動する入口。標準の起動方法 |
| 素の `pi` | Unix では設定でフルガードが載る。違いはサンドボックスの有無、作業先の `.pi/` を読むか、`mcp.json` を止めるか。Windows の素の `pi` にはサンドボックスが無い |

判定の意味（詳細は [guard/pi-decide.md](guard/pi-decide.md)）:

| 結果 | 意味 |
| --- | --- |
| deny | 実行しない。bypass でも外れない |
| confirm | 確認する。bypass でも確認する（外部への送信・公開、元に戻せない git 操作、保護ブランチへの統合、`chezmoi apply` / `chezmoi update`） |
| ask | 確認する。bypass が ON のときは確認なしで通す |
| allow | そのまま通す |

OS 別の違い:

- Windows には `/fleet` と `/stepback` を配らない。
- Unix の子エージェントのツール名は `guarded_task`。Windows は subagents 拡張の `task`（引数は `agent` と `task` だけ）。

## 2. 起動

### 2.1 `pis`

```text
pis [--bypass | --no-bypass] [--no-sandbox] [--no-broker] [--new] [--role <役割>] [--] [pi の引数...]
```

| オプション | 効果 |
| --- | --- |
| （なし） | Linux / WSL ではサンドボックスの中で起動し、bypass はオン。Linux 以外は起動を断り `--no-sandbox` を案内する |
| `--no-sandbox` | フルガードだけで起動する。bypass は既定でオフ。stderr に警告が出て、フッターに `⚠ no sandbox` が出る |
| `--bypass` / `--no-bypass` | bypass の初期値を明示する。明示したほうが既定に勝つ |
| `--role <役割>` | 親の役割を指定する（環境変数 `PI_HARNESS_ROLE`）。`rules.json` に無い役割を渡すと、ツールが 1 つも登録されない |
| `--no-broker` | Copilot・GitHub・検索のブローカーを外す。内側に本物の Copilot 認証が入る |
| `--new` | 新しいセッションで始める。既定は、この作業ディレクトリの直近のセッションを開く（`--continue` を先頭に足す） |
| `--boundary` | 標準と同じ意味の別名。`--no-sandbox` とは併用できない |
| `--` | これ以降を pi へ渡す |

- サンドボックス側だけが解釈するオプション: `--no-backup`（起動前の退避を省く）、`--check`（起動せず内側から検査）、`--allowlist`（通信を許可リスト型に戻す）。
- `--role` で親に使えると docs が明記している役割は `implementer`（既定）と `reader` のみ。`worker` などは未確認。
- 次のときは起動を断る: フルガードが未配備、`~/.pi/agent/mcp.json` にサーバがある、危険な起動場所、事前検査に落ちた、Fence が無い。
- `pi` に渡す共通フラグ: `--no-approve -nbt -ne -e builtin:mcp`。これに自作の拡張、`--skill`、フルガード（`-e ~/.config/pi/harness`）が加わる。
- 故障時の復旧（ガードも境界も無い）: `pi -ne --tools read,bash,edit,write`

### 2.2 `pk`（補助スクリプトの入口）

| 使い方 | 動作 |
| --- | --- |
| `pk` | 話題の一覧 |
| `pk <話題> [引数]` | `<話題>/run.sh`（無ければ唯一の `*.sh`）を `sh` で実行。話題は一意な部分一致でよい |
| `pk -n <話題>` | 実行せず、入口と先頭コメントを表示 |
| `pk --complete` / `pk -h` | 補完 / ヘルプ |

- 置き場は `$PK_ROOT`、カレントから上へ探した `.tmp/keep`、`~/.local/share/chezmoi/.tmp/keep` の順です。

- 詳細: [guard/pi-guard.md](guard/pi-guard.md)（起動）、[sandbox/index.md](sandbox/index.md)（起動のモード）、[development.md](development.md)（`pk`）

## 3. 画面の見方

### 3.1 フッターと入力欄の下

| 表示 | 意味 | 出る条件 |
| --- | --- | --- |
| `⚡ bypass` | bypass が ON | ON の間 |
| `🧭 orchestrate` | orchestrate が ON | ON の間 |
| `🔒 sandbox` | サンドボックスの内側で実測が通った | カナリア検査に通ったとき |
| `⚠ no sandbox` | サンドボックスなし | `pis --no-sandbox` |
| `📥 保留 N 件` | 退避した（旧形式の）コミットが N 件ある | 1 件以上 |
| `📌 完了/総数 ▶ 進行中` | todo の進捗。全部 done なら `✅ 完了/総数` | 項目があるとき（中止は数えない） |
| `⏸ plan` | 計画モードが ON | ON の間 |
| `📝<N>t/s <T>s` | 直近のモデル呼び出しの速度（`~` は概算） | 呼び出し後。子では出ない |
| `🤖 <agent> <経過>, …` と `⚙️ N jobs` | 動いている子エージェントとバックグラウンドジョブ（入力欄の下） | 動いているとき。子は 3 件まで、超えると `🤖 N subagents` |

- `🔒 sandbox` と `⚠ no sandbox` は目印であって、安全の根拠ではありません。

### 3.2 通知と確認画面

- 作業が終わって入力待ちになったとき、確認画面を出す前、`ask` の前に、端末の BEL が鳴る（TUI のとき）。
- 起動時に「フルガードの判定の外で動きうるものがあります: …」と警告が出ることがある（`mcp.json` のサーバや、作業先の `.pi/` の拡張など）。
- 通常の確認画面は「実行してよいですか？」（コマンドと理由を表示）。
- bypass でも出る確認の見出し:
  - 「⚠ bypass でも確認が要る操作 (外部への送信・公開、元に戻せない git 操作)」
  - 「⚠ 保護ブランチへの統合 (bypass でも確認が要る)」
- 必須確認の期限は 5 分（`[pi.confirm] timeout_seconds = 300`）。無反応は deny。
- 確認できない実行（print・子）では、確認が要る操作は拒否する。

### 3.3 キー操作

| 場面 | キー |
| --- | --- |
| 全体 | `app.interrupt` = `escape` / `ctrl+c`、`app.exit` = `ctrl+d`、`app.clear` = 割り当てなし |
| 全文ビューア（確認画面の「全文を見る」） | `↑↓` `j/k`、`Space/b`（ページ）、`g/G`（先頭/末尾）、`q`・Enter・Esc で閉じる |
| `/btw` の答え画面 | `↑↓` `j/k`、`Space/b`、`g/G`、Enter / Esc / `q` で閉じる |
| `ask` パネル | `↑↓` 移動、Enter 選択/送信、Tab / Shift+Tab で問の移動、Space（複数選択）、Esc で中止。無操作は 5 分で時間切れ |

- キーバインドは `[pi.keybinds]` から `~/.pi/agent/keybindings.json` を丸ごと生成します。手で足したキーは次の apply で消えます。

## 4. 独自のコマンド（スラッシュコマンド）

- 利用者だけが呼べます（モデルは呼べません）。

| コマンド | 内容 | 条件・補足 |
| --- | --- | --- |
| `/bypass [on\|off]` | bypass の切り替え。引数なしは反転 | ON にするときだけ確認画面が出る。deny・confirm・サンドボックスは有効のまま。切り替えると動いている子は全部止まる。UI が無いと ON にできない |
| `/orchestrate [on\|off\|status]` | 親を計画・判断・委譲に絞る。引数なしは `status` | 作業ツール（bash・edit・write・bg_*・MCP）を隠す。子・Windows・`[pi.orchestrate]` が無い・`task` を持たない役割では使えない。`/reload` を跨いで保つ |
| `/plan` | 計画モードの切り替え | 残るツールは read / grep / find / ls / todo / task / ask。計画を番号付きで返すと「実行する / 計画のまま続ける / 計画を直す」を尋ねる |
| `/board` | 盤面（読み取り専用） | feature ⇄ worktree、保留（旧形式の退避）、子、隔離 worker、モード・bg の 5 節。モード行は `bypass` / `orchestrate` / `sandbox` の状態 |
| `/agents` | 動いている子の一覧（状態・経過・最後のツール・使用量） | 同じ cwd と役割の子だけ |
| `/agent <agent> <依頼>` | 子を直接起動する | `agent` は `explore` / `review` / `plan` / `commit` / `worker`。結果はチャットに出る（モデルのターンは起こさない） |
| `/worktrees [show\|collect\|discard <jobId>\|unlock]` | 隔離 worktree の一覧・回収のやり直し・破棄 | `collect` と `discard` は確認あり。`unlock` は古いロックの解除 |
| `/pending [list\|show\|drop]` | 退避したコミット（旧形式）の扱い | 引数なしは `list`。後述 |
| `/todos [tidy\|clear]` | タスクリストの表示 | `tidy` は完了・中止を消す。`clear` は全部消す |
| `/btw [--plain] <質問>` | いまの会話を踏まえた、ついでの質問（履歴に残さない） | 既定は読み取り専用の子 `explore` が調べる（上限 3 分）。`--plain` はツールなしで現在のモデルが答える（上限 2 分） |
| `/delegate-stats` | 直近 10 発言分の読み取り量と委譲の件数 | 記録のみ。`PI_DELEGATE_NUDGE=0` で止まる |

- `/agents`・`/agent`・`/worktrees` は `guarded_task` が登録されたときだけ使えます。

プロンプトテンプレート（`~/.pi/agent/prompts/` に配られる。Windows には配らない）:

| コマンド | 内容 |
| --- | --- |
| `/fleet <依頼>` | 依頼を並列に動かせる作業に分け、`worker` を同時に起動して進める |
| `/stepback [質問]` | 質問（省略すると直前の質問と回答）からステップバック質問を作り、先にそれを考えてから答え直す |

`/pending` のサブコマンド:

| サブコマンド | 内容 |
| --- | --- |
| `list` / `show [<id>]` | 一覧 / 表示 |
| `drop [<id>]` | 破棄 |

- 承認して実行する経路（`approve`・`resolve`・`unlock`・`log`・巡回）は撤去済み（[guard/pi-pending.md](guard/pi-pending.md)）。統合は、TUI の必須確認、`merge-cli`（利用者が端末で実行）、PR ビューアの「統合する」ボタンのいずれか（[運用モード](operation-modes.md)）
- pi 本体の組み込みコマンド（`/compact`・`/reload`・`/model` など）はこのリポジトリの管轄外で、ここでは扱いません。

- 詳細: [guard/pi-extensions.md](guard/pi-extensions.md)、[guard/pi-subagents.md](guard/pi-subagents.md)、[guard/pi-pending.md](guard/pi-pending.md)

## 5. モデルが使うツール

- 役割ごとに付くツールが違います（6.2）。

| ツール | 目的 | 付く役割 |
| --- | --- | --- |
| `guarded_bash` | シェルの実行 | implementer / explorer / committer / worker |
| `guarded_read` | 読み取り（`path` `offset` `limit` `tail`） | 全役割 |
| `guarded_edit` | 完全一致の置換で部分編集（`path` `edits[]`） | implementer / worker |
| `guarded_write` | 新規作成・全面書き換え（`path` `content` `append`） | implementer / worker |
| `guarded_grep` / `guarded_find` / `guarded_ls` | 検索・一覧 | 全役割 |
| `guarded_action` | 承認つきの外部操作 | implementer / orchestrator（親だけ） |
| `guarded_task` | 子エージェントに仕事を任せる | `task` を持つ役割（implementer / orchestrator）。子と Windows には無い |
| `bg_run` / `bg_log` / `bg_kill` | 長いコマンドのバックグラウンド実行・ログ確認・停止 | bash を使える役割 |
| `ask` | 選択肢つきの質問（最大 4 問） | implementer / orchestrator。UI が無い実行では隠れる |
| `todo` | タスクリスト | implementer / orchestrator |
| MCP ツール（`mcp__*`） | 設定で宣言した MCP サーバのツール | implementer のみ。環境変数が空の機では登録されない |

- `guarded_read` の `tail` は末尾 N 行で、`offset` と併用できない。32 MiB を超えるファイルは不可。
- `guarded_write` の `append` を true にすると末尾に追記する（改行は足さない）。
- 子が使えるのは `guarded_*` と MCP だけ（`ask` / `todo` / `bg_*` / `task` / `action` は使えない）。

### 5.1 `guarded_action`（承認つき操作）

- 承認はツールが 1 回だけ取ります
- 引数はシェルを通さず `argv` で実行します

| 操作 ID | 内容 | `params` |
| --- | --- | --- |
| `git_commit` | コミット | `message`（1200 字まで）、`dir?`（cwd 配下の別 git リポジトリの最上位を相対パスで） |
| `gh_issue_comment` | issue にコメント | `repo` `number` `body`（8000 字まで） |
| `gh_issue_edit_body` | issue の本文を編集 | `repo` `number` `body` |
| `gh_issue_edit_title` | issue のタイトルを編集 | `repo` `number` `title`（1 行、256 字まで） |

- `git_commit` の確認画面の選択肢は「承認して実行 / 全文を見る / 編集して承認 / 拒否」。他の操作は「全文を見る」が無い。
- `git_commit` はステージ済みが無いとエラーになる。
- feature の linked worktree（HEAD が `feature/*`）での `git_commit` は、確認なしで実行される。
- 承認が時間切れ（5 分）、または利用者が不在と分かっているときは、実行せず `refs/pi/pending/` に退避する（8.2）。

### 5.2 `guarded_task`（子エージェント）

| 形 | 引数 |
| --- | --- |
| 新規 | `agent` `task`、任意で `keep` `background` `model` `effort` `todo` `isolation: "worktree"` `cwd` |
| 並列 | `tasks:[{agent, task, model?, effort?, cwd?}]`（最大 12 件）。`background` だけ併用可 |
| 続き | `jobId` `task` `background`（`keep` した子だけ） |
| 状態・一覧 | `{jobId, status:true}` / `{list:true}` |
| 追加指示 | `{jobId, steer:"…"}` |
| 中断 / 終了 | `{jobId, abort:true}`（子は残る）/ `{jobId, close:true}` |

- `effort` は `minimal | low | medium | high | xhigh | max`。`off` は不可。
- `todo` ツールが有効なとき、`explore` / `review` / `worker` の新規起動には `todo` の ID が必須。
- `isolation:"worktree"` は新規の `worker` 1 件だけで、`keep` とは併用できない。
- `cwd`（絶対パス）は子の実行場所。親のリポジトリの `git worktree list` に載る worktree と realpath が完全に一致するときだけ許可（`isolation` とは併用不可）。終了時に本体の `git status` が起動前から変わっていれば、結果に ⚠ の行が付く。
- 同時に生かせる子は最大 6。1 往復の既定上限は 15 分で、`plan` だけ 30 分。
- `/plan`（計画モード）の間は、読み取り専用の役割の子（`explore` / `review` / `plan`）だけ起動・続行できる。

- 詳細: [guard/pi-extensions.md](guard/pi-extensions.md)（`guarded_action`）、[guard/pi-subagents.md](guard/pi-subagents.md)（`guarded_task`）

## 6. モードと役割

### 6.1 モード

| モード | 入り方 | 画面の目印 | 何が変わるか |
| --- | --- | --- | --- |
| サンドボックス（Fence） | 起動時のみ（`pis` が標準、`--no-sandbox` で外す）。起動後は変えられず、再起動する | `🔒 sandbox` / `⚠ no sandbox` | 作業ツリー外の読み書き・通信・認証情報を狭める。開けた場所は allow、外は理由つき deny。日常の shell の ask は確認なしになる。deny・confirm・伏字化は変わらない |
| bypass | 起動時に `--bypass` / `--no-bypass` か環境変数 `PI_HARNESS_BYPASS`。起動後は `/bypass` | `⚡ bypass` | ask を確認なしで通す。deny・誘導・confirm は効いたまま。セッションには保持しない |
| orchestrate | 起動時に環境変数 `PI_HARNESS_ORCHESTRATE=1/0` か `[pi.orchestrate] default`（今は `off`）。起動後は `/orchestrate` | `🧭 orchestrate` | 親の役割が `orchestrator` になる。作業は `worker` に任せる |
| plan（計画モード） | `/plan`。状態はセッションに保存され、再開時に復元される | `⏸ plan` | 書き込み・実行のツールを外す |

- `/plan`（計画モード）と、子エージェントの `plan`（計画役）は別物です。
- 使い分け: 計画（利用者と対話）は `/plan`、実装を子へ任せて自走させるときは `/orchestrate`。計画の終わりに「実行の契約」を固定して自走する（[計画と自走](orchestration.md#計画と自走)）。
- 非同期承認は撤去済みです（履歴は [CHG-0055](../change/closed/0055-async-approval.md)）。

### 6.2 役割（`[pi.profiles.*]`）

| 役割 | ツール | 既定 | 補足 |
| --- | --- | --- | --- |
| `implementer`（親の既定） | bash・read・edit・write・grep・find・ls・task・todo・ask・action・`mcp__*` | ask | `shell_deny` に git の状態変更などがある |
| `reader` | read・grep・find・ls | deny | 読み取り専用 |
| `explorer` | bash・read・grep・find・ls | deny | bash は `wc` と読み取り専用の git（`status` `diff` `log` `show` `ls-files`）だけ |
| `committer` | bash・read・grep・find・ls | deny | `git status` `git diff` `git log` などだけ |
| `worker` | bash・read・edit・write・grep・find・ls | ask | `git add` `commit` `stash` `checkout` `switch` `restore` `reset` は deny |
| `orchestrator` | read・grep・find・ls・task・todo・ask・action | deny | `/orchestrate on` の間だけ親の役割になる |

### 6.3 子エージェント（`[pi.agents.*]`）

| 名前 | 目的 | 役割 | モデルの階層 | bypass 継承 |
| --- | --- | --- | --- | --- |
| `explore` | 読み取り専用の探索 | `explorer` | なし（親の現在のモデル） | する |
| `review` | 別系統モデルでの独立レビュー | `explorer` | `second_opinion` | する |
| `plan` | 大きな変更の実装計画（bash なし。`C1:` 形式の条件番号の突き合わせを検査し、警告のみ） | `reader` | `deep` | しない |
| `commit` | コミットの計画を返すだけ（ステージもコミットもしない） | `committer` | `routine` | しない |
| `worker` | 割り当てられた 1 作業を担当範囲で実装（コミットはしない） | `worker` | `worker` | する |

- 子は入れ子にしない。子の確認要求は、UI が無いので ask・confirm が deny になり、結果は `blocked` で返る。
- 子から親への通信は無い（結果の返却と完了通知のみ）。
- 完了通知には `.tmp/subagents/<通番>-<job id>.md` が書かれる（50 件・7 日）。
- モデルと effort は、利用者が指示したときだけ指定する。
- モデルの階層の決め方は [agent-model-assignment.md](agent-model-assignment.md)。

- 詳細: [guard/pi-decide.md](guard/pi-decide.md)（役割）、[guard/pi-subagents.md](guard/pi-subagents.md)、[orchestration.md](orchestration.md)

## 7. 設定の変え方

### 7.1 流れ

1. `home/dot_config/agents/common.toml.tmpl` の `[pi.*]` / `[pis.*]` を編集する（単一ソース）。
2. chezmoi の `modify_*.py.tmpl` が描画済みの設定を `scripts/agents/generate.py --target <名前>` に渡して生成する。未知のキーや不正な値は、生成時に拒否される。
3. 生成物を直接編集しない。`~/.pi/agent/settings.json` / `mcp.json` / `extensions/**` / `~/.config/pi/harness/**` は、判定器が書き込みを拒否する。

| `--target` | 生成物 | 備考 |
| --- | --- | --- |
| `pi-harness` | `~/.config/pi/harness/rules.json` | 完全生成 |
| `pi-settings` | `~/.pi/agent/settings.json` | 持ち物のキーだけ差し替える |
| `pi-keybindings` | `~/.pi/agent/keybindings.json` | ファイルごと生成 |
| `pi-subagents` | `~/.pi/agent/extensions/subagents/agents.json` | Windows の素の pi 用 |
| （プロンプト） | `~/.pi/agent/prompts/*.md` | `[pi.commands.*]` から |

- 設定を変えたあと pi 側で `/reload` が要るかは**未確認**です。

- 詳細: [agent-config-generation.md](agent-config-generation.md)

### 7.2 主な設定（`common.toml.tmpl` の同梱値）

| 節 | 決めること | 主なキーと同梱値 |
| --- | --- | --- |
| `[pi]` | 既定の役割・自作の拡張 | `default_role = "implementer"`。`own_extensions` = todo, plan, btw, activity, ask, notify, delegate-nudge, speed |
| `[pi.shell]` | 無確認で通す shell（前方一致） | `allow` 5 件。載せたコマンドは `> path` による書き込み手段にもなる |
| `[pi.confirm]` | bypass でも確認する操作 | `bash`（`gh` の変更系・`chezmoi apply/update`）、`checks`、`timeout_seconds = 300`、`local_git = true`、`integration = true` |
| `[pi.integrate]` | 保護ブランチへの統合の判定 | `target = "develop"`、`protected_refs`（main, master, develop, release/\*, hotfix/\*）、`skip_confirm_in_free_zone = true` |
| `[[pi.actions]]` | 承認つき操作 | 4 件（`git_commit` と `gh_issue_*` 3 件） |
| `[pi.redact]` | 出力の伏字化 | `enabled = true`（false にすると生成が止まる）。`rule` は 9 件 |
| `[pi.external_read]` | 作業ツリー外で無確認に読める場所 | 3 件（各 CLI のスキル置き場） |
| `[pi.skill_scripts]` | 無確認で実行できるスキルのスクリプト | `[[allow]]` 11 件 |
| `[[pi.guide]]` | 当たると案内つきで deny（bypass でも外れない） | 6 件 |
| `[pi.settings]` | pi の `settings.json` の持ち物 | `defaultThinkingLevel = "xhigh"`、`skills`、`extensions`、`defaultTools = []` |
| `[pi.model.tier.*]` / `[pi.model.catalog.*]` | 子のモデルの階層の上書き / 選べるモデルの範囲 | プロバイダごと |
| `[pi.sandbox]` | `pis` の追加の読み取り・保護 | `read` `control_dirs` `deny_read` `protected` |
| `[pis.broker]` | ブローカー（`copilot` `github` `search`） | `off` / `auto` |
| `[pis.network]` | 通信の方式 | `mode` は `denylist` か `allowlist`（プロバイダで出し分け） |
| `[pi.profiles.*]` | 役割ごとのツールと既定 | 6.2 |
| `[pi.orchestrate]` | orchestrate の起動時の状態 | `default = "off"` |
| `[pi.agents.*]` | 子エージェント | 6.3。`timeout_minutes`（既定 15、1〜120）、`inherit_bypass` など |
| `[pi.keybinds]` | キーバインド | 3.3 |
| `[pi.commands.*]` | `/fleet` と `/stepback` | `description` `argument_hint` `template` |

- `[pi.confirm] timeout_seconds` は 10〜3600 の整数です。

### 7.3 マシン別の上書き

`~/.config/agents/local.toml`（chezmoi 管理外。`apply` で消えない）に書けるのは次の 5 節だけです。

| 節 | 動き |
| --- | --- |
| `[pis.network]` | `deny` / `local_ports` は追記。`mode` / `allow_loopback` / `allow_private_direct` は置き換え |
| `[pi.sandbox]` | `read` / `network_allow` / `deny_read` の追記だけ。`write` / `protected` / `control_dirs` は警告して無視 |
| `[pis.broker]` | 置き換え |
| `[sandbox]` | 追記のみ |
| `[[copilot.locations]]` | 追記 |

- 上の節以外（`[pi.integrate]` `[pi.confirm]` `[pi.profiles]` など）を書いても反映されない。
- ファイルが無ければ無視する。壊れた TOML は警告して無視する。
- `~/.config/agents` は `pis` の内側から書けないので、エージェントが自分で緩めることはできない。
- 場所は `AGENTS_LOCAL_CONFIG` で差し替えられる。

```toml
[pis.network]
deny = ["example.com"]
local_ports = [8080]

[pi.sandbox]
read = ["/data1"]
```

起動ごとの追加:

| 方法 | 内容 |
| --- | --- |
| `<起動ディレクトリ>/.opencode/sandbox.toml` | `read` / `write` / `network_allow` / `devices`。その作業先だけに効く |
| `PIS_EXTRA_READ` | コロン区切りの絶対パス。読み取りだけ |
| `PIS_EXTRA_DEVICES` | コロン区切りの `/dev/` 直下。許可リスト方式 |

### 7.4 キルスイッチ

| 設定 | 同梱値 | 切ったときの挙動 |
| --- | --- | --- |
| `[pi.integrate] skip_confirm_in_free_zone` | `true` | `false` にすると、feature の worktree の `git_commit` も毎回確認する |
| `[pi.confirm] local_git` / `integration` | `true` | `false` で、それぞれ必須確認をやめる |
| `[pi.redact] enabled` | `true` | `false` にすると生成が止まる（pi のフルガードは伏字化が前提） |

- 保留の承認のキルスイッチ（`[pi.pending]`・`[pi.integrate] enabled`）は撤去済み

### 7.5 環境変数（利用者が使うもの）

| 変数 | 意味 |
| --- | --- |
| `PI_HARNESS_ROLE` | 親の役割（`pis --role` が設定する） |
| `PI_HARNESS_BYPASS` | `1` なら起動時から bypass（`pis` が必ず設定する） |
| `PI_HARNESS_ORCHESTRATE` | `1` / `0` で orchestrate の起動時の状態を指定 |
| `PI_HARNESS_CHILD_CONTEXT` | `inherit` / `extract` で、子へ渡す AGENTS.md を全文にするか役割ごとの抜粋にするかを指定（`[pi.child] context` より優先。起動済みの親には届かない） |
| `PI_DELEGATE_NUDGE=0` | `/delegate-stats` の記録を止める |
| `PI_TODO_NO_REMINDER=1` | todo の続行の促しを止める |
| `PI_AUTOCHECKPOINT=0` / `PI_AUTOCHECKPOINT_PERCENT` | 文脈の使用率による自動の保存と圧縮を止める / 閾値（既定 80。[仕様](guard/pi-extensions.md#文脈の使用率による自動の保存と圧縮)） |
| `PIS_EXTRA_READ` / `PIS_EXTRA_DEVICES` | 7.3 |
| `AGENTS_LOCAL_CONFIG` | `local.toml` の場所の差し替え |
| `DOTFILES_RESYNC_WEBSEARCH_KEYS=1` | apply 時に検索の鍵を取り直す |

- `PI_HARNESS_BOUNDARY` `PI_HARNESS_ALLOWED` `PI_HARNESS_CHILD` `PI_HARNESS_CHILD_AGENT` `PI_HARNESS_CHILD_CONTEXT_REPORT` `PI_HARNESS_NO_SANDBOX` などは内部用や表示用や試験用なので、設定しない
- 検索の鍵（`BRAVE_API_KEY` など）は `pis` が内側へ渡さない

### 7.6 プロジェクトごとの設定（`pi.json`）

各リポジトリの `.agents/config/pi.json` で、統合まわりの 3 つだけをそのリポジトリ用に変えられる。7.3 の `local.toml`（マシン別）とは別の仕組み。

| キー | 意味 | 省略したときの既定 |
| --- | --- | --- |
| `target` | 統合先（`/board` の比較先・`git flow finish` のプレビュー） | `[pi.integrate] target`（このリポジトリの同梱値は `develop`） |
| `source_prefixes` | 統合元として許す接頭辞 | `["feature/", "bugfix/"]` |
| `free_zone_prefixes` | 自由区（確認なしのコミット）の接頭辞 | `["feature/"]` |

最小の例（作業ブランチを `task/` にする）:

```json
{
  "integrate": {
    "source_prefixes": ["task/"],
    "free_zone_prefixes": ["task/"]
  }
}
```

統合先を `production` にする例:

```json
{
  "integrate": {
    "target": "production"
  }
}
```

**変えられるもの・変えられないもの**:

| 項目 | 可否 |
| --- | --- |
| 統合先 | 全体の保護ブランチ（`[pi.integrate] protected_refs`）の中から選ぶ。例の `production` は、全体の保護に入っているときだけ使える |
| 統合元・自由区の接頭辞 | 変えられる。末尾は `/`。保護ブランチと重なる接頭辞は無効 |
| 保護ブランチ | **変えられない**（全体設定のまま）。`protected_refs` を書くと設定全体が無効になる |

**効くタイミング**:

- 設定は、**コミットした内容（HEAD）だけ**が効く。作業ツリーの編集は、コミットするまで反映されない
- 自由区の接頭辞は、**主ブランチ（主 worktree の HEAD）に入るまで効かない**。feature の中で書き換えても、自分の自由区は広がらない。統合で主ブランチに入ってから効く
- **主 worktree が保護ブランチ上にないと、自由区は効かない**（確認が増える）。主 worktree が detached HEAD・保護でないブランチ上のとき。設定が無いリポジトリでも同じ
- 自由区の設定を**読めないとき**（git の失敗など）も、自由区は効かない（確認が増える）。設定が無い・無効のときは、従来どおり全体の既定

**無効なとき**:

- 未知のキー・型違い・大きすぎる・保護との重なりなどが 1 つでもあると、**設定全体が無効**になり、全体の既定で動く（保護は緩まない）
- `/board` に、無効であることと診断コード（`invalid_json`・`unknown_key`・`prefix_overlaps_protected` など）が 1 行出る。入力の中身は出ない
- ファイルが無い・まだコミットしていない場合は、何も出ず全体の既定

**その他**:

- `git flow … finish` を直接実行したときの確認画面は、cwd と主 worktree の両方の設定を見る。どちらかが統合先か統合元の接頭辞を変えている・読めないときは、統合の内容を出さない（「確認できない」と出る）。
- pi の project trust とは連動しない
- `.agents/config/pi.json` の変更は、PR ビューアの統合画面で「リスクのあるパス」として見える（`[pi.integrate] risk_paths` の同梱の対象）
- 実際の `pi.json` は、まだどのリポジトリにも置いていない（実機確認の後）
- 仕様と診断コードの一覧: [guard/pi-extensions.md](guard/pi-extensions.md#プロジェクトごとの設定pijson)
- 未確認: Windows、実機（`pis`・実 TUI）での見え方

## 8. 日常の運用

### 8.1 承認

- `guarded_action` は、内容の全文と argv を見せて 1 回だけ承認を取る。bypass でも省略しない。
- feature の linked worktree（`feature/*`）の `git_commit` だけは確認なしで実行される。それ以外のコミットは確認する。
- `git flow feature finish` や `git merge` などの保護ブランチへの統合は、bypass でも必須確認。承認画面に、行き先・衝突の事前検査・squash メッセージ・コマンド全文が出る。時間切れなら、再試行せず指示を待つ。
- main への統合と push は、利用者が自分で行う。
- feature の統合は、AI が `guarded_pr_summary` で PR に要約を出し、利用者が PR ビューアの「統合する」ボタンを押す（merge commit。[CHG-0062](../change/0062-pr-hub-simplify.md)）。

### 8.2 時間切れと保留

- 確認の期限は 5 分。
- `git_commit` の時間切れ・UI 無し・不在は、実行せず `refs/pi/pending/<時刻>` に退避して作業を続ける（`not approved:` で返る）。取消・拒否は退避しない。
- `git_commit` 以外の時間切れは拒否のまま。
- 退避は `/pending` で確認・破棄する。取り込み済み・重複・30 日超は自動で片付く。
- `/pending approve` と `git_integrate` は撤去済み（[guard/pi-pending.md](guard/pi-pending.md)）。

### 8.3 feature の並列開発

1. `git flow feature start <名前> --worktree --no-fetch` で起票する（worktree は `.tmp/worktrees/<名前>/`）。
2. 親が `worker` を `background: true` で起動する。1 worktree = 1 feature = 1 worker で、担当外を触らせない。
3. 完了のたびに `scripts/parallel_check.py` と `feature_gate.py` を回し、親が `git add` と `git_commit`（`dir` に worktree）を行う。
4. `guarded_pr_summary` で PR に要約を出し、利用者が PR ビューアの「統合する」ボタンで取り込む（AI が `git flow feature finish` を実行するときは 8.1 の必須確認）。

- 手順と依頼文の雛形は、スキル `feature-orchestration`（`.agents/skills/`）にある
- 複数の pi の会話を並行して使うときは、取り込み（`finish`・`merge`）を窓口の 1 会話だけが行う
- ほかの会話はコミットまで

- 詳細: [guard/pi-subagents.md](guard/pi-subagents.md)（並列実装の運用、複数の会話の運用）

### 8.4 検査

| 場面 | コマンド |
| --- | --- |
| 日常（変更に応じた選択実行） | `mise run verify` |
| コミット前に 1 回（全件） | `mise run verify:all` |
| 全体の lint / secret scan | `uv run pre-commit run --all-files` |

- 全件検査は `verify-all.lock` で 1 本ずつになる。待ちの上限は `VERIFY_LOCK_TIMEOUT`（既定 1800 秒）。
- 詳細は [development.md](development.md) の「検証の方針と選択実行」。

## 9. 困ったとき

| 困りごと | 対処 |
| --- | --- |
| 承認が時間切れになった | `git_commit` は退避されるので `/pending` で確認・破棄する。それ以外は拒否になるので、再試行せず新しい指示を出す |
| 退避したコミットが増えた | `/pending list` で確認し、`/pending drop` で破棄する |
| Fence の中で読めない | `~/work/...` など許される場所で起動する（`~`・`/mnt`・`/tmp` は拒否）。読み取りを足すなら `PIS_EXTRA_READ` か `.opencode/sandbox.toml` の `read`。事前検査に落ちたら `pis --check` で詳細を見る |
| ガードのソースをサンドボックスで編集できない | `pis --no-sandbox` で行う |
| `/copy` で Clipboard unavailable | `pis` が `PI_CLIPBOARD_OSC52=1` を渡す。端末側で OSC 52 の書き込みを許可する |
| `Invalid arguments for tool …`、引数が空 | `troubleshooting-agents.md` の該当節と、[guard/pi-extensions.md](guard/pi-extensions.md) の「ツール引数の JSON を壊さない設定」 |
| ブローカーが動いていない | エラー文の案内に従う。一時的に外すなら `pis --no-broker` |
| 起動を断られた | 2.1 の「起動を断る」条件を確認する |
| ガードが故障して使えない | 2.1 の復旧コマンド（ガードも境界も無い） |
| フッターの表示が古い | docs に記載なし（未確認） |

- `.env` や `*.pem` は、サンドボックスの起動時に隠されます。

## 10. 詳しい文書への案内

| 知りたいこと | 文書 |
| --- | --- |
| 機能の地図 | [pi-features.md](pi-features.md) |
| 起動・bypass・confirm の UI | [guard/pi-guard.md](guard/pi-guard.md) |
| 判定・役割 | [guard/pi-decide.md](guard/pi-decide.md) |
| 子・orchestrate・並列実装・複数会話 | [guard/pi-subagents.md](guard/pi-subagents.md) |
| `guarded_action`・`/plan`・`/pending`・拡張 | [guard/pi-extensions.md](guard/pi-extensions.md) |
| 保留の履歴（撤去済み） | [guard/pi-pending.md](guard/pi-pending.md)、[CHG-0062](../change/0062-pr-hub-simplify.md) |
| プロジェクトごとの統合設定（`pi.json`） | 7.6、[guard/pi-extensions.md](guard/pi-extensions.md#プロジェクトごとの設定pijson)、[CHG-0057（プロジェクトごとの統合設定）](../change/0057-per-project-integrate.md) |
| サンドボックス | [guard/pi-sandbox.md](guard/pi-sandbox.md)、[sandbox/index.md](sandbox/index.md)、[sandbox/fence-boundary.md](sandbox/fence-boundary.md)、[sandbox/broker.md](sandbox/broker.md) |
| 設定の生成 | [agent-config-generation.md](agent-config-generation.md) |
| モデルの割り当て | [agent-model-assignment.md](agent-model-assignment.md)、[CHG-0043（モデルカタログ）](../change/0043-model-catalog.md) |
| Web 検索の許可規則 | [web-search.md](web-search.md) |
| worktree と統合の確認 | [CHG-0053（worktree と統合の関門）](../change/0053-worktree-integration-gate.md) |
| `guarded_action` の簡素化 | [CHG-0050（guarded_action の簡素化）](../change/0050-slim-guarded-action.md) |
| オーケストレーション一覧 | [orchestration.md](orchestration.md) |
| 検査・ブランチ・`pk` | [development.md](development.md) |
| トラブルシュート | [troubleshooting-agents.md](troubleshooting-agents.md) |

## 付録: 未確認・既知のズレ

- `pis --help` の実出力は未確認。`executable_pis` の usage と `pis.py` の `USAGE` 定数の食い違いは解消した（入口の説明を `pis.py` に合わせた）。2.1 の表は `pis.py` の定義に従った。
- フッターの `🧭 orchestrate` / `⏸ plan` / `📥 保留 N 件` は、これまで `docs/spec` に記載が無く、**本書が初めて記載**した（コードで確認）。
- 実機で未確認と明記されているもの: 実 TUI での確認画面の見え方、Zed・Windows、Bedrock の GPT-6.1 のツール呼び出し。
- `guarded_edit` の `newText` など、pi 本体の組み込み定義に由来する引数は未確認。
