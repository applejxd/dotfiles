# pi を AI オーケストレーターとして使う仕組みの調査

<!-- 現在の運用の正本は docs/spec/guard/pi-subagents.md。ここは「いつ何を調べたか」を積む場所 -->

## 記録 O1 — 2026-10-26

- **問い**: pi（earendil-works/pi）を AI オーケストレーター（親エージェントはタスクの管理に徹し、複数の子を同時に走らせて管理する）として使える拡張・仕組みはあるか。
  自作のフルガード（子を別プロセス `pi --mode rpc` で、フルガード付きで起動する設計。[pi-subagents](../../spec/guard/pi-subagents.md)）と、どう組み合わせるか
- **対象バージョン**: pi 1.4.0（入れている版）。公開拡張は 2026-10-22〜26 時点の版（各行に併記）
- **環境**: Linux の作業環境。公開情報（README・docs・ソース・npm registry・GitHub API・公式ブログ・changelog）の閲覧と、
  ローカルの pi 1.4.0 の docs・自作拡張のソースの読み取りだけ。**第三者のコードは実行していない・導入していない**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)）
- **方法**: 2 ラウンド。第 1 ラウンド（R1〜R4）で市場・GitHub・pi 本体・他社を広く当たり、第 2 ラウンド（S1〜S4）で有望な候補のソースと
  公式文書の本文まで読んだ。**S が R と食い違うところは S を採った**（下の「材料どうしの食い違い」）。README の記述は「主張」と書く
- **限界**: pi.dev の一覧は DL 順の先頭 50 件（全 5369 件）しか見ていない。長いファイルは先頭 12〜30 KB で切れ、後半は未読。
  npmjs.com は 403 で使えず、registry と GitHub API で代用した。実機での試験は一切していない。DL・star は取得日の値で、増減する

### 結論

1. **導入に値する公開拡張は、見つからなかった。**
   - (a) **親を管理専用にする仕組み**を持つのは、`edxeth/pi-subagents`（orchestrator mode。133 star・個人開発・最終 push 2026-09-18・npm 未公開と読める）と
     `@saifymatteo/pi-orchestrator`（engaged mode。AI 生成と README が開示）などごく少数。他は「親への指針」止まりか、強制の無いプロンプトだけ
   - (b) その少数も、フルガードと合わない。子にフルガードを確実に渡す口が無い、または子の構成の決定権が agent 定義ファイルに分散する
     （edxeth）。子の確認ダイアログを親へ中継しない（Pi-Agents-Team・basnijholt）。`flags` で `--no-approve` を後勝ちで上書きできる（edxeth）。
     `delegate` が自作の `guarded_task` と別経路になる（saifymatteo）
   - (c) 大きい `nicobailon/pi-subagents`（月 558K DL）は、前景の子が親のプロセス内、背景は 1 つの runner プロセスに複数の子が同居する。
     **宣言的な DAG を持つ公開拡張は見つからなかった**。依存関係は JS・TS のプログラムで書く方式（nicobailon の `runs.*`、`@tintinweb` の `SubagentWorkflow`、`pi-fabric`）で、
     `pi-ptc-subagents` はプログラム内のツール呼び出しが `tool_call` フックを迂回する（README が明記）
   - 実績のある拡張は無い。「子 = 別プロセス RPC」型の 4 件は最大 17 star
2. **自作のフルガード（`guarded_task`: 別プロセス・役割・並列・steer・abort・job・worktree 隔離）が土台として十分。** pi 本体の RPC に、
   steer・abort・状態照会・セッション再開・質問の中継の部品は揃っている。足りないのは、親側の管理層:
   - 親を管理専任にする役割（`[pi.profiles.orchestrator] tools=[task, todo, ask, …]` で足せる見込み。ただし親が `read` を失い、保存された子の結果を読めない副作用）
   - 待ち合わせ（any / all・個別の完了通知）、依存関係（DAG）、子から親への質問の中継、費用の硬い上限、失敗の種別つきの返却、並列の書き込みの衝突の検出
3. **借りる設計**は「自作に足りない点と、借りる設計」に出典つきで列挙した（edxeth の controller・saifymatteo の keep-list と予算・nicobailon の `runs.*` と `failureKind`・
   Pi-Agents-Team の abort の順序・pi-legion の wait・yuhua99 の `ask_main_agent`）
4. **他社の知見**: 親が管理専任になりきれない例がある（Claude Code agent teams の公式が「lead が待たず自分で実装し始める」を認める）。
   書き込みの並列は競合が最大の問題（worktree か触る範囲の宣言と、統合前の検収）。トークンはチャットの約 15 倍（Anthropic の自社評価）。
   Cognition は書き込みを単一スレッドに保つ。予算の上限はプロンプトでなくハーネスが強制する。steer を権限昇格の経路にしない。resume が同時数の枠をすり抜けない試験
5. **利用者向けの判断（推測。実機での試験が要る）**: 導入しない（ADR-0016 の方針と整合）。自作の拡張として、`orchestrator` ロール → 待ち合わせ → DAG の順に小さく足すのが妥当。
   試験項目: `ctx.executeTool("guarded_task", …)` が判定と伏字化を通るか、`pis --role orchestrator` での挙動

### 材料どうしの食い違いで直したもの

| 項目 | 前 | 後（採った方） |
| --- | --- | --- |
| `yuhua99/pi-subagent` の子 | R2: 別プロセス RPC 型 | S2: 実装は親プロセス内（`createAgentSession`）。README の「isolated `pi` processes」と実装が食い違う |
| Claude Code の総数上限 | R4: 1 セッション 200（無効化不可） | S4: v2.1.212 で導入、**v2.1.224 で撤去**。現行の公式文書は「総数の上限なし」 |
| Codex の既定の同時数 | R4: 6・深さ 1 | S4: 公式本文は数値を書かない。二次記事が 3 と 6 で割れる。未確認 |
| `edxeth` の規模・steer | R1: star 不明・steer は未読 | S1: 133 star。**親→走行中の子への steer は無い**（許可 3 ツールは起動・kill・resume） |
| `@gjczone/pi-swarm` | R1: v0.4.1・子の形は未確認 | S3: npm 0.9.5・月 168 DL。子は `pi --print`（stdin は閉じ、steer は mailbox ファイル経由） |
| `@saifymatteo/pi-orchestrator` の子 | R1: 別プロセスか未確認 | S3: 別プロセス `pi --mode rpc`（`PI_ORCHESTRATOR_CHILD=1`）。拡張は全継承 |
| `pi-legion` の子 | R2: 別プロセス RPC 型 | S2: 既定は親プロセス内。worktree を持つ centurion だけ別プロセス RPC |
| nicobailon の背景 | R3: 「detached の別プロセス」 | S3: runner 1 プロセスに**複数の子セッションが同居**。子ごとに環境変数で役割を変える方式は使えない |
| Pi-Agents-Team | R2: 2026.10.8。`rpc.command` で差し替えられそう | S2: npm latest 2026.10.11・17 star。`rpc.command/args` は全 worker 共通で、**子ごとの `env` を渡す口が無い** |
| 結論 1 (c) の「DAG なし」 | 親の暫定: 公開拡張に DAG なし | 宣言的な DAG は無い。プログラムで書く型は複数ある（上記）。`pi-swarm` の `TeamPhase` に dependencies 型があるが実装は未確認 |
| 結論 3 の「steer の受信確認」の出典 | 親の暫定: saifymatteo | nicobailon（`runs.steer` の queued / delivered / missed / failed）。saifymatteo は任意 steer が未確認 |

### 候補の一覧

評価: **参考のみ**＝設計の借用元・導入しない／**不適**＝導入も参考も薄い。人気は取得日の値（月 DL は pi.dev か registry）。
「フルガード」は、子にフルガードを確実に載せられるか・判定を通らない経路ができるか。いずれも README・docs・ソースを読んだ範囲の評価（実行はしていない）。

| 名前・版 | star / DL | 親子の構造 | 親の役割 | 並列 / DAG | steer / 停止 | フルガードとの両立 | 評価 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `edxeth/pi-subagents` 2.9.2（git のみ） | 133 star | 別プロセス `pi -p`、または mux の別ペイン | **管理専用の mode**（`setActiveTools`）。プロンプト全置換 | async・`children`。DAG なし | kill / resume。**走行中の子への steer なし** | 経路はあるが agent 定義ごとの宣言。`flags` 後勝ち・resume のメタデータ上書き | 参考のみ（親の絞り方の根拠） |
| `@saifymatteo/pi-orchestrator` 0.10.0 | 月 DL 未確認 | 別プロセス `pi --mode rpc` | **engaged**: keep-list + gate + 方針の毎ターン追記 | 並列 8・同時 4・queue 32・chain。DAG なし | cancel・ターン予算の steer→kill・stall kill。任意 steer は未確認 | 子は全拡張を継承。役割を伝える口と起動コマンドの差し替えが無い。`delegate` が二重経路 | 参考のみ（設計の借用元） |
| `nicobailon/pi-subagents` 0.83.0 | 月 558K | 前景: 親プロセス内。背景: runner 1 つに複数の子 | 管理 mode なし（「親への指針」） | `runs.all/lanes`・JS で DAG | `runs.steer`（受信確認）・interrupt・stop・resume・自動再開 | 同居プロセス。capability ceiling で外から制限可。external-cli runner で起動コマンドを差し替え可 | 参考のみ（設計は最有力） |
| `@tintinweb/pi-subagents` 0.22.0 | 月 32.8K・1.4k star | 親プロセス内 | 管理 mode なし | 同時 10・`SubagentWorkflow`（JS） | steer・停止・resume | 子に組み込みの `bash` が渡る。役割を子ごとに変えられない | 不適（導入）／参考 |
| `@gotgenes/pi-subagents` 25.0.4 | 月 14.5K | 親プロセス内 | mode なし | 同時 4 | steer・`ask_parent` / `notify_parent` | 同様に衝突 | 参考のみ |
| `Pi-Agents-Team` 2026.10.11 | 17 star | 別プロセス `pi --mode rpc --no-session` | 管理寄り（プロンプトで代行禁止。強制なし） | 上限なし・全件待ち。DAG なし | steer（個別・一括）・abort→kill | `env` を渡せない・command 共通・`extension_ui_response` を返さない | 参考のみ（構造は最も近い） |
| `pi-legion` 4.0.0 | 2 star | 既定は親プロセス内。centurion のみ別プロセス RPC | 分隊長が管理（固有の 4 段フロー） | 同時 30 ノード・状態機械 | steer・graceful / force stop・孤児掃除 | 構造が衝突（in-process 既定）。648 KB | 参考のみ（不適寄り） |
| `basnijholt/pi-subagents` | 2 star・2026-02 以降更新なし | 別プロセス RPC（素の `pi`） | 規定なし | 同期型・上限なし | stop のみ | 不可（ツール・拡張を絞らない） | 参考のみ |
| `yuhua99/pi-subagent` | 0 star | **親プロセス内**（S2 で訂正） | `role: orchestrator` ポリシー | 最大 5 | `subagent_ctl`（steer / stop） | 構造が衝突 | 参考のみ（`ask_main_agent`） |
| `pi-fabric` 0.126.0 | 月 31.6K | 別プロセス pi（runner 差し替え可・tmux も可） | full-code: 親のツールは `fabric_exec` のみ（中から core ツールを呼べる） | プログラムで DAG | steer / followUp / stop・60 秒無出力で kill | 子は拡張を継承。`extensions:false` で外れる。プログラム内の判定経路は未確認 | 参考のみ（導入は大改造） |
| `@kontextmind/kxm` 0.7.206 | 月 29.5K | 常駐 worker（hub 経由。別マシン可） | coordinator は `--tools` で自分で絞る | fanout・ステージ・gate | cancel。実行中の steer は未確認 | `KXM_PI_COMMAND`・`KXM_WORKER_EXTENSION_PATHS` で差し替え可。通信路が増える | 参考のみ（目的が違う） |
| `@gjczone/pi-swarm` 0.9.5 | 月 168 | 別プロセス `pi --print` | team leader（絞りなし） | 5（上限 128）。DAG は未確認 | mailbox 経由・TaskStop | `allowBashWrite:false` はプロンプトだけ。起動コマンド固定 | 参考のみ |
| `pi-ptc-subagents` 6.0.3 | 月 4,290 | 別プロセス pi | 絞りなし | プログラム | stop のみ | **`tool_call` フックを迂回**（README が明記） | 不適 |
| `pi-cowboy` 0.22.2 | 月 3,104 | 別プロセス（Herdr の別ペイン）。外部ハーネスも混在 | 親が spawn / merge / cleanup | 同時 4 | 親・人が steer | 外部ハーネスは判定の外。spawn の引数は未読 | 参考（worktree + merge の型） |
| `pi-background-tasks` | 月 44.9K | 別プロセス `pi --mode json`（拡張を読まない） | 管理に徹しない。書き込みの子なし | 固定の Fusion のみ | kill のみ | `bg_run` が素通し・子にガードが載らない | 不適 |
| `@groeponline/pi-agent-orchestrator` 0.19.1 | 月 2,023 | **ホストプロセス内** | 絞りなし | swarm / crew / schedule | ダッシュボードで steer・kill | 同一プロセスで衝突。権限は親から継承し子は緩められない（主張） | 参考のみ |

### 候補ごとの根拠

凡例: **事実**＝README・docs・ソースの本文を読んで確かめた／**主張**＝README の宣伝文句／**推測**。出典の URL は末尾の一覧。

#### `edxeth/pi-subagents`（orchestrator mode。S1・R1 でソースを読んだ）

- **事実**: 親のツールを `api.setActiveTools()` で絞り、`tool_call` で許可外を `block`（二重化）。`before_agent_start` で**システムプロンプトを全置換**（標準プロンプト・他拡張の追記は失われる）。
  許可ツールは README では `subagent` / `subagent_kill` / `subagent_resume` の 3 つ（`tool-names.ts` は未読）。基準のツール一覧は `appendEntry` で保存して復元し、保存に失敗したら切り替えない。
  切替は子が走っていない間だけ。子は環境変数（`PI_SUBAGENT_*`）で判定して orchestrator を常に無効にする
- **事実**: 子は `spawn(…, {detached:true})`。background は `--no-approve` 固定、frontmatter の `flags:` はそのまま argv に足され**後勝ち**（`--approve` で上書き可）。親の環境を丸ごと継承（`deny-env` で除外可）。
  `extensions` 未指定は `--no-extensions` を付けず、親が CLI の `-e` で渡した拡張は子へ**継承されない**。`PI_SUBAGENT_PI_COMMAND` で起動コマンドを差し替えられる
- **事実**: resume は子が書けるセッションのメタデータから起動引数を復元する。後勝ちで上書きされないのは `spawnBudget` / `spawnableAgents` / `denyTools` の 3 つだけ（コードコメント）。`flags` / `env` / `extensions` は上書きされ得る（**推測**）
- **事実**: issue #31（open）: 親が Bun 単体版 pi（pi 1.4.0）のとき、interactive の子の起動に失敗して**制限の無い既定セッション**になる。同じ報告が「v2.9.2 が pi 1.4.0 で動いた」ことも示す（第三者の確認）。#30 `idle-timeout` が効かない
- **事実**: 親→走行中の子への steer は無い。DAG なし。自動の再割り当てなし。子→親は `caller_ping` / `subagent_done`。結果は `pi.sendMessage({…}, {triggerTurn:true, deliverAs:"steer"})` で親へ届く
- **評価**: 導入しない。fork して起動部分（3 箇所の spawn）を書き換える規模は自作と同じ。親の絞り方は設計の根拠になる

#### `@saifymatteo/pi-orchestrator`（S3。docs 全体と `src/delegate.ts` の先頭 30000 字）

- **事実**: engaged（既定）で `before_agent_start` が委譲方針を毎ターン**追記**、`setActiveTools` で `keepTools`（完全一致・glob・`ext:<id>`）だけ残し、`tool_call` で他を block（ADR-0001 hard-tool-gate）。`delegate` は常に残る。README 冒頭に「GLM 5.3 Flash が書いた」と開示
- **事実**: 子は `pi --mode rpc`（`PI_ORCHESTRATOR_CHILD=1`）。既定は**全ツール**で、`--exclude-tools` と子側の gate の二重で絞る（許可リストでなくブロックリスト）。子はグローバルに入れた拡張をすべて継承
- **事実**: 共有プール（`maxConcurrency` 4・`maxQueuedRuns` 32）。`maxTurns` 既定 50 で到達時に子へ steer 1 回、+5 ターンで kill。stall watchdog 既定 10 分。子側に親 PID の心拍 watchdog。
  完了は `agent_settled` と `stopReason` で判定（終了コードは見ない）。配信が未確認なら保持して `retry-delivery`（自動再送はしない）
- **未確認**: 後半のソース（起動引数・環境変数の全体）。任意の steer の action
- **評価**: 親を管理に徹させる最有力の実装だが、`delegate` が自作と二重経路になる。設計の借用元

#### `nicobailon/pi-subagents`（R1・R3・S3）

- **事実**: 前景の子は親プロセス内。背景は detached runner 1 つに**多数の子セッション**が同居し、ambient 拡張はその runner に読み込まれる。`PI_SUBAGENT_CHILD=1` など。親のツールを削る機構は無い（workflows.md が「親への指針で、実行時のモードではない」と明記）
- **事実**: workflow スクリプトは、ファイル・シェル・任意ツールの無いサンドボックスで `runs.run/all/lanes/steer/status` だけを使う。`failureKind`（validation / script / child / return-serialization / timeout / detached-child / runtime）、`reuseFrom` と 24 時間以内の自動 resume、
  `usageBudget` / `toolBudget` / `timeoutMs`（いずれも opt-in）、`runs.steer` の受信確認、`gate` と `outputSchema`
- **事実**: `capability ceiling`（`registerSubagentCapabilityCeiling`）で、別拡張がセッション単位で子のツール・agent を外から制限できる。docs 自身が「同一プロセスのポリシー境界で、悪意ある拡張への sandbox ではない」と明記。
  `runner.type: external-cli` で任意コマンドを子にできる（stdin 渡しの単発。steer は劣る）。「失敗した lane を別の実行方式へ黙って切り替えない」が運用規約
- **事実**: `async:false` で待つ間は、背景の子の supervisor への質問に返せない（docs が明記）。npm 10.4 MB・依存 5
- **未確認**: `src/runs/background/` 本体、`registerRequiredChildExtensions` の中身、worktree 隔離の実装

#### `Pi-Agents-Team`（R2・S2。`worker-process.ts`・`launch-policy.ts`・`worker-manager.ts` 前半・`rpc-client.ts`・`config.ts`）

- **事実**: 子は `pi --mode rpc --no-session`、`detached:true`、終了はプロセスグループへ SIGTERM→250 ms 後 SIGKILL。`--tools` は正確な名前の列挙、拡張は既定で全無効（`--no-extensions`）+ 役割の `extensions` を `--extension` で明示。
  起動時の上書きは**狭める方向だけ**。`pathScope` は pi のツール層で強制されないと自白（コメント原文）
- **事実**: abort は、状態を先に `aborted` に固定→`clear_queue`→`abort`（1 秒）→失敗ならプロセス kill。`waitForTerminal` は全件待ちで、timeout・親への質問（relay）で早期復帰。並列数の上限は無い。`env` は渡さず親の環境を継承。
  `SupportedRpcCommand` に `extension_ui_response` が無い。repo の issue は 0 件（利用者が少ないため、問題が無い証拠には弱い）
- **未確認**: `extensions/pi-agent-team/index.ts`（64 KB）、`worker-manager.ts` 後半。pi 1.4.0 での動作（検証版は 1.1.0）

#### `pi-legion`・`basnijholt`・`yuhua99`（S2）

- **pi-legion**（README・`headless-child-contract.md` のみ。**主張に近い**）: `wait` の timeout は停止を意味せず、生存中の子・経過・次の選択肢（extend / steer_again / stop / force_stop）を返す。
  `onBlocked`（`forward` / `auto-approve` / `notify`）。失敗の分類表（settled / retired / gone→failed / timeout / aborted）。孤児スキャン。既定の backend が in-process
- **basnijholt**（ソース全文 26 KB）: 完了を `agent_end` で判定（settled との差を踏む）。Node の `readline` を使う（pi の文書が U+2028 の問題を警告）。無活動タイムアウト（既定 300 秒）。stop は子 1 つだけの kill（孫が残る）
- **yuhua99**（`runner.ts` 全文）: 子は SDK で親プロセス内、拡張は `subagent` を持つものを除いて全継承。`ask_main_agent`（custom tool。1 run に 1 件保留→親が応答）

#### tmux・ダッシュボード系（R2。README を読んだだけ。**主張**）

- `pasky/pi-side-agents`（別 tmux window の対話 pi + worktree + merge）、`RielJ/pi-git-worktrees`（`tmux send-keys` で入力欄へ流し込む。heartbeat の polling）、`revazi/pi-tmux-orchestrator`
  （実装 1・レビュー 1 の固定 2 役。restart / abort は別々の確認・曖昧な配送は fail-closed）、`koenzhao/pi-agent-hub`（人間向け tmux ダッシュボード）、
  `sven1103-agent/pi-central`（RPC + 承認ドック。**macOS 専用**の Seatbelt 前提）
- 共通: 親→子が構造化されない・完了が確定イベントでない（画面・heartbeat の推定）・子にフルガードの起動規約を渡す保証が無い。**人間向けの画面としては有望・エージェントの親には不適**
- Orca orchestration（スタブの記述のみ。ガイド本体は未取得）・Herdr（SKILL の範囲）は、親が `agent send-keys` / `pane run` で子の端末に任意入力でき、**判定なしに子を叩く経路になり得る**（推測）。フルガードの設計とは別枠の審査が要る

#### 調べたが該当が無かった・未読のもの

- 検索語（R1）`pi coding agent package orchestrator multi-agent npm pi-package`・`pi-package swarm OR teams OR workflow OR dag subagents extension pi coding agent npm`（"ralph"・"dag"・"boomerang"・日本語の語は未実行）。
  `vibe-kanban` / `Conductor` / `claude-squad` が pi に対応しているかは確認できなかった（vibe-kanban の対応一覧に pi は出ず。`cline/kanban` の issue #604 は提案で未実装）
- README 未読（説明文のみの主張）: `@miadi/agent-pi`・`pi-gauntlet`・`@neilurk12/pi-agent-modes`（orchestrator モードを名乗る。月 71 DL）・`pi-orchestrator-config`・`@a-t-h-i/bot-lobby`・`pi-opium`・
  `@nkyriazis/pi-orchestrator`・`@ret2hell/pi-herdr-orchestrator` ほか。`andrraa/pi-orchestrator` は registry の検索で見つからず。YYLO・ReevesAgents・Rove・`pi-intercom`（1:1 のメッセージ。親の管理機能なし）
- 反例・批判: 各候補の issue は、edxeth の新しい 3 件以外は読んでいない。Reddit r/PiCodingAgent に「拡張なしでも AGENTS.md と herdr + pi ペインで足りる」という意見がある（検索の抜粋のみ）

### pi 本体の仕組みと限界

出典: ローカルの pi 1.4.0 の docs ディレクトリの extensions・sdk・rpc・rpc-commands・rpc-extension-ui・cli・settings（各 .md）と、`examples/extensions/subagent/`（**事実**）。

| 目的 | 仕組み | 限界 |
| --- | --- | --- |
| 子を別プロセスで | `pi --mode rpc`（JSONL）。`prompt` / `steer` / `follow_up` / `abort` / `clear_queue` / `get_state` / `get_session_stats` / `new_session` / `switch_session`。型付きの `RpcClient` が同梱 | 1 子 = 1 プロセス = 1 セッション。`steer` は現ターンのツール実行後・次の LLM 呼び出し前に届く |
| 子を同一プロセスで | SDK `createAgentSession`。`tools` / `resourceLoader` で子ごとに制御 | 親のガードが自動で及ぶ保証は無い |
| 親のツールを絞る | `--tools a,b`・`-nbt`・`defaultTools`・拡張から `pi.setActiveTools()`。`before_agent_start` でプロンプトを変える | **管理専任を強制する本体の機構は無い**。絞れば実質専任にはできるが、親は `read` を失う（推測） |
| 完了を親へ | `pi.sendMessage({…}, {triggerTurn, deliverAs})`、`agent_settled` | — |
| 質問の中継 | 拡張の `ctx.ui` の dialog が `extension_ui_request` として出て、親が `extension_ui_response` を返すまで子が止まる（timeout で既定値） | `custom()` など TUI 専用は不可 |
| ツールの入れ子 | `ctx.executeTool(name, args)`。`tool_call` / `tool_result` を通る（docs の記述） | 子の LLM ループは作らない。**自作の `guarded_task` を通すかは未実機** |
| 本体に無い | DAG・待ち合わせ（any / all）・費用の上限・親の管理専任 | サンプル `subagent` は `chain` と `parallel`（最大 8・同時 4）だけ。pi.dev は「sub-agents と plan mode は省く。拡張で作れ」と主張 |

### RPC で複数の子を管理するときの落とし穴

出典: pi 1.4.0 の `rpc.md`・`rpc-commands.md`・`rpc-extension-ui.md`（**事実**）と、Pi-Agents-Team・basnijholt の実装との対応（S2）。

| # | 落とし穴 | 対策（推測を含む） |
| --- | --- | --- |
| 1 | `prompt` の成功は受理だけ。完了は `agent_settled`（`agent_end` は途中の可能性）。`disposition:"handled"` は run が始まらない | 完了は `agent_settled` だけで判定。`handled` を待ち続けない |
| 2 | 購読前に完了すると取りこぼす | 子の stdout リスナーを prompt 送信前に付ける。起動→`get_state`→リスナー→prompt の順を固定 |
| 3 | stdout / stderr を読まないと子が止まる（backpressure） | 子ごとに専用の非同期リーダ。stderr も読み、バッファに上限を付ける（2 件の公開拡張は stderr が無制限） |
| 4 | Node の `readline` は U+2028 / U+2029 でも分割する（文書が禁止） | LF だけで分割する自前のパーサ（`StringDecoder`・末尾 `\r` 除去） |
| 5 | dialog 系で子が `extension_ui_response` を待ってブロックする | 親が全 dialog に応答するか、timeout 付きの deny 既定にする |
| 6 | `steer` は割り込みでなく次ターン境界での配信。bash 実行中は効かない | 暴走した bash は `abort_bash`。停止は `clear_queue`→`abort` |
| 7 | abort の応答より前に `agent_settled` が来る | 状態を先に `aborted` に固定してから送る。settled を成功と見なさず `aborted` を見る |
| 8 | abort がハングする。親の異常終了で子が孤児になる | 親側の期限（abort 1 秒）→プロセスグループ kill。起動時に孤児を掃除。子に親 PID を渡して自己終了させる案 |
| 9 | セッションの衝突・再起動後の再開 | `--session-dir` を子ごとに分け、再開は `switch_session`。`get_entries(since)` を永続カーソルに |
| 10 | 暴走（無限ループ・長大出力・費用） | pi 側に上限は無い。親が `get_session_stats` を見て費用・文脈・無活動時間で abort。並列数の上限を持つ |
| 11 | provider 失敗・abort・出力上限は response でなく event に出る | `message_end` の `errorMessage` / `stopReason`・`auto_retry_*`・`agent_settled.aborted` で分類 |
| 12 | 版のずれ | 起動前に子の `pi --version` を確認（Pi-Agents-Team が実施） |

### 他のエージェントの親子設計

凡例: **確認**＝公式文書・changelog の本文を読んだ（S4）／**主張**＝二次記事・自社評価・宣伝。取得は 2026-10。

| 製品 | 親の役割 | 上限・予算 | steer / 失敗 | 隔離 |
| --- | --- | --- | --- | --- |
| Claude Code subagents | 通常作業もする（管理専任ではない）。背景が既定 | 同時 20・深さ 3（履歴は 5→1→3）。**総数は上限なし**（2.1.212 で 200 を導入、2.1.224 で撤去）。`maxTurns`。`--max-budget-usd` は 2.1.217 まで背景の子を止めなかった（changelog 原文） | SendMessage で再開・指示。**どのメッセージも承認にならず、子の権限・設定を変えられない**。背景の失敗は `failed` + 最後の出力。resume は同時数の検査をすり抜けて枠を取る | `isolation: worktree` + git を共有側へ向けるコマンドの検査（2.1.216 で修正） |
| Claude Code agent teams（実験） | lead が割当・統合。**lead が待たず自分で実装し始める**ことを公式が認める | ハード上限なし。3〜5 人が目安。トークンは線形に増える | 共有タスク一覧（依存あり・ファイルロックで claim）・mailbox。タスク状態が遅れて依存が詰まる。メッセージは配送前に審査。計画承認は権限を変えないと自動で通る | 同一ファイルの編集は上書きされるので、ファイル集合を分けよと助言 |
| Codex | 親が spawn・待ち・統合。全員が揃うまで待って 1 応答 | `max_concurrent_threads_per_session`（公式は数値なし）。二次記事は 3 と 6 で割れる | 親へ頼んで steer・停止。非対話で承認が要る操作は失敗して親へ返る。**権限・sandbox は親から継承し、子別に変えられない**（自作の役割ごとの絞りより弱い隔離） | worktree は別機能。並列の書き込みは慎重にと公式が注意 |
| Cursor | 親が文脈を渡す。planner → implementer → verifier のパターン | 同時数の記載なし。入れ子は 2 段まで | 本文に途中指示・停止の記載なし（再開のみ）。親が `~/.cursor/subagents/` の状態を読む | **既定は親のチェックアウトを共有**し、同時編集は上書きされると明記。依頼で worktree / cloud VM |
| Copilot `/fleet` | 依存つきに分解→wave ごとに dispatch→検証→統合 | 未確認 | 子同士は通信せず orchestrator だけが調整。依頼文に境界・検証基準・`(depends on N)` を書く（ブログ） | ファイルシステム共有（境界は依頼文の宣言頼み） |
| Devin | coordinator に徹する（割当・監視・衝突解消・統合）。manager は過度に指示的になりがち（Cognition 自認） | 10 並列の用例。ACU を監視 | 途中の訂正・休止・終了。**エージェントは子と状態を共有していると思い込む**（自認） | 独立 VM |
| OpenCode / oh-my-opencode | Sisyphus が planner + todo 駆動（**主張**。DeepWiki は自動生成） | provider / model ごとの並列設定（主張）。`steps` で反復上限（OpenCode 公式） | 実装役は `task` / `delegate_task` を遮断して再帰を防ぐ（主張）。issue #1359: モデルが必須パラメータを「忘れる」（スニペットのみ） | 未確認 |

- **Anthropic（2025-06。自社評価＝主張）**: lead が計画をメモリへ保存し、子 3〜5 体を並列。トークンはチャットの約 15 倍（単体エージェントは約 4 倍）。「コーディングは並列化しにくく、委譲・調整はまだ得意でない」。
  失敗例は子 50 体・重複検索・互いの邪魔。**lead は子を同期で待ち steer できないと自認**（今の製品は非同期へ進んだ）。成果物はファイルへ出し参照だけを lead へ返す（pi の `.tmp/subagents/*.md` と同型）。失敗時点から再開できる耐久状態
- **Cognition（2025-06→2026-04）**: 原典は「並列に書き込む構成は脆い（暗黙の決定が衝突する）」。続報（2026-04-22）も、**書き込みは単一スレッドに保つ**狭い型だけが実用と結論し、構造のない swarm は distraction とした。
  有効な型はクリーン文脈のレビュー役との往復で、**コーディング役が指摘を選別する橋渡し**が鍵。manager が子と状態を共有していると思い込む点・子→manager→他の子の通信が起きない点は自社の失敗例
- **予算はハーネスが強制する**: 個人の実測（二次・主張）では、プロンプトに「40 ターンで止まれ」と書いても 195 回のツール呼び出しまで止まらなかった。`maxTurns`（frontmatter）は強制され、切れた子は部分結果を返す
- **Augment（二次）・実務者の報告（Reddit。取得失敗でスニペットのみ）**: 共有仕様が無いための暗黙の決定の衝突が主な失敗。人が並列の出力をレビューしきれないと利得が消える。ファイル競合が最大の問題で、worktree + 統合前の test / lint の検収が対策
- **調べたが該当が薄かったもの**: Jules は利用者が独立タスクを投げる型で、親子設計の情報は得られなかった。Copilot `/fleet` の公式 docs 本文は目次で埋まり未読。Reddit の「spawnageddon」は取得が空

### 自作のフルガードに足りない点と、借りる設計

自作の現状（R3。`home/dot_config/pi/harness/index.ts`・`children.ts`・`common.toml.tmpl` を読んだ。行番号は調査時点）: 生存する子は最大 4、`tasks` の一括は最大 12（空き待ち）。
最終状態 6 種（done / blocked / failed / limit / closed / aborted）。1 往復 15 分・80% で steer。`isolation:"worktree"` は単独の新規 `worker` のみ。job は親プロセスのメモリ内。`blocked`（承認待ち）は即 `cancelled`。

| # | 足りない点 | 借りる設計（出典） | 足し方 |
| --- | --- | --- | --- |
| 1 | 親を管理専任にする役割 | **edxeth**: `setActiveTools` + `tool_call` の `block` の二重化、通常ツール一覧の `appendEntry` 保存と復元、子が走っている間は切り替えない、子（`PI_HARNESS_CHILD`）では無効、プロンプトは**全置換でなく追記**（saifymatteo も追記）。**saifymatteo**: keep-list（`delegate` 相当だけ必ず残す）+ gate | 設定の追加で足せる見込み: `[pi.profiles.orchestrator] tools=["task","todo","ask"]`。副作用: 親が `read` を失い、保存された子の結果（`.tmp/subagents/*.md`）を読めない。生成器・試験の更新が要る可能性（未確認） |
| 2 | 待ち合わせ（any / all・個別の完了通知）。一括は全部が終わった時に 1 回だけ通知 | **Pi-Agents-Team**: 全件待ち + relay で早期復帰。**pi-legion**（主張）: `wait` の timeout は停止ではなく、生存中の子・経過・次の選択肢を返す。**nicobailon**: `bg_wait`・`runs.all` | `wait(jobId…)` と個別の完了通知（`children.ts` / `index.ts` の変更。判定器の変更は不要と見込む） |
| 3 | 依存関係（DAG） | **nicobailon**: ツールを持たない JS で `runs.run/all/lanes`（lane の失敗は後続だけ skipped）・`reuseFrom`。**Copilot**: 依頼文に `(depends on N)` | まず親のモデルが `todo` で段取りを書き逐次起動。次に `guarded_task` を `ctx.executeTool` で呼ぶ別拡張（判定を通るかは**未実機**） |
| 4 | 子→親の質問の中継（今は即 `cancelled`。CHG-0026） | **yuhua99**: `ask_main_agent`（1 run に 1 件保留）。**pi-legion**: `onBlocked` を **`forward` に固定**（`auto-approve` は判定の素通しになるので使わない）。**@gotgenes**: `ask_parent` / `notify_parent`。pi の `extension_ui_request` の中継 | 親が全 dialog に応答するか、timeout 付きの deny 既定。**steer・質問への回答を権限昇格の経路にしない**（Claude Code 公式） |
| 5 | 費用の硬い上限 | **nicobailon**: `usageBudget`（soft / hard）・`toolBudget`・`timeoutMs`（超過後の新規起動を拒否。走行中は止めない）。**saifymatteo**: ターン予算（soft steer→+5 で kill）・stall watchdog。**basnijholt**: 無活動タイムアウト（総時間でなくイベント途絶）。Claude Code の `--max-budget-usd` が背景を止めなかった不具合 | 同時数・深さ・費用・子ごとの上限をハーネスが強制。総数は拒否でなく警告（Claude Code が 200 の拒否を撤去した前例）。プロンプトに書いた上限は守られない |
| 6 | 失敗の種別つきの返却 | **nicobailon**: `workflow.failureKind`。**Claude Code**: 背景の失敗は `failed` + 最後の出力、`maxTurns` は partial を印す。**saifymatteo**: `stopReason`。**Pi-Agents-Team / legion**: provider 失敗・abort・出力上限を「成功した idle」と扱わない。**edxeth**: 失敗の分類ごとに「再試行 / resume / 新規」の助言 | 結果の見出しに種別・partial・最後の出力・再開できる ID。最後の出力と partial を返しているかは**未確認** |
| 7 | 並列の書き込みの衝突の検出 | **Cognition / Cursor / Codex / Claude Code teams**: worktree か触る範囲の宣言。統合前の検収（クリーン文脈のレビュー役）。**pi-cowboy・pi-side-agents**: worktree + merge + cleanup の型 | 並列の `worker` は worktree 隔離を原則（今は単独のみ。CHG-0029）。触る範囲を依頼文に書かせ、重なる並列起動を拒否 |
| 8 | 中断・再開（親が落ちると全滅） | **nicobailon**: 自動 resume・`reuseFrom`。**Anthropic**: 失敗時点からの再開。**kxm**: supervisor の再起動 | job 状態の永続化（大きな変更） |
| 9 | 完了判定・停止の作法 | **Pi-Agents-Team**: 完了は `agent_settled` だけ・abort は「状態固定→`clear_queue`→`abort`（1 秒）→プロセスグループ kill」・wait の timeout は停止を意味しない。**saifymatteo**: 配信を保持して `retry-delivery`、子側の親 PID watchdog | 自作はほぼ具備（`agent_settled`・abort あり）。再確認項目として残す |
| 10 | steer の受信確認 | **nicobailon**: `runs.steer` の queued / delivered / missed / failed。**capability ceiling**: 別拡張が子を外から制限できる口 | steer の戻り値に配送状態を足す。ceiling 相当は、役割表で固定する自作の方式のほうが分散しない |

- **借りない**: agent 定義ファイルの frontmatter で子の `flags` / `env` / `extensions` を決める仕組み（信頼境界が分散する）、起動コマンドの外部差し替え（`PI_SUBAGENT_PI_COMMAND`・`KXM_PI_COMMAND`）、resume でセッション内のメタデータを信頼する仕組み、子同士の mailbox（Claude Code 自身が配送前の審査を必要としている）、
  ツール名一致だけのブロックリスト（saifymatteo）、親の「簡単な質問は直接答えてよい」例外。子の構成は harness の役割表で固定する（自作の前提）
- **運用の規則（機能でなく指示）**: 委譲文に「目的・出力形式・使う情報源・境界」を書く（Anthropic・Copilot・Claude Code 公式が一致）。子にしない基準（逐次・同一ファイル・小さい作業）と努力量の規則。
  子の結果は「子の言葉で、承認ではない」という見出しで親へ渡す（Claude Code は注入らしき文字列の走査もする）。pi 側にこの見出しがあるかは未確認
- **試験項目（推測）**: resume・追加依頼が同時数の枠をすり抜けないか（Claude Code は resume が検査をすり抜ける）。上限超過のエラー文で親が再試行を繰り返さないか。steer が子の判定器・権限に影響しないか

### 未確認

- **実機での試験は一切していない**。特に、`orchestrator` ロールを足したときの生成器・試験への影響、`ctx.executeTool("guarded_task", …)` が判定・伏字化を通るか、`pis --role orchestrator` での挙動
- 第三者コードの未読部分: edxeth の `tool-names.ts`・`batch-classifier.ts`・README 本文、saifymatteo の `delegate.ts` 後半、nicobailon の `src/runs/background/`・`permissionRules`、
  Pi-Agents-Team の `index.ts` と `worker-manager.ts` 後半、pi-legion の `src/`、pi-fabric の runner 契約と `src/`、pi-cowboy の spawn、`@tintinweb` の `agent-runner.ts` 後半・issue 71 件の中身
- 数値の出典の限界: Anthropic の 90.2%・15 倍、Devin Review の数値は自社評価。Codex の既定の同時数は公式未記載。Cursor・Copilot の同時数は未確認
- 自作側: `index.ts` の `single` / `job` の形（行 1210 以降）の詳細、pi の `todo` に依存の列があるか
- pi.dev の一覧は先頭 50 件のみ。star・DL は取得日の値（`pi-legion` の DL 等は未確認）。Orca の orchestration ガイド本体（`orca skills get orchestration`）と Herdr が pi を扱えるかは未確認

### 出典

取得日は 2026-10-22〜26（web 取得は registry の time 値・API のレスポンス日付に基づく）。

- pi 本体: ローカルの `@earendil-works/pi-coding-agent` 1.4.0 の docs ディレクトリ（extensions・sdk・rpc・rpc-commands・rpc-extension-ui・cli・settings の各 .md）と `examples/extensions/subagent/`
- 一覧: <https://pi.dev/packages> ・ <https://pi.dev/packages/pi-subagents> ・ npm registry（registry.npmjs.org の `pi-agents-team`・`pi-legion` ほか）・ GitHub API（api.github.com の各リポジトリ）
- edxeth: <https://github.com/edxeth/pi-subagents> （raw の `src/runtime/orchestrator-*.ts`・`src/launch/*`・issue #30・#31）
- saifymatteo: <https://github.com/saifymatteo/pi-orchestrator> （README・docs の development.md と configuration.md・`src/delegate.ts`）
- nicobailon: <https://github.com/nicobailon/pi-subagents> （README・docs の workflows.md・extension-api.md・standalone-background.md・`src/runs/shared/child-tool-plan.ts`）
- tintinweb・gotgenes: <https://github.com/tintinweb/pi-subagents> ・ <https://github.com/gotgenes/pi-packages/tree/main/packages/pi-subagents>
- RPC 系: <https://github.com/KristjanPikhof/Pi-Agents-Team> ・ <https://github.com/zzjcool/pi-legion> ・ <https://github.com/basnijholt/pi-subagents> ・ <https://github.com/yuhua99/pi-subagent>
- その他の拡張: <https://github.com/fabric-runtime/pi-fabric> ・ <https://github.com/kontextmind/kxm> ・ <https://github.com/gjczone/pi-swarm> ・ <https://github.com/a1121611810/pi-ptc-subagents> ・
  <https://github.com/nicobailon/pi-intercom> ・ <https://github.com/electric-dragon-80000v/pi-cowboy> ・ <https://github.com/pasky/pi-side-agents> ・ <https://github.com/rielj/pi-git-worktrees> ・
  <https://github.com/revazi/pi-tmux-orchestrator> ・ <https://github.com/koenzhao/pi-agent-hub> ・ <https://github.com/sven1103-agent/pi-central> ・ <https://github.com/andyrewlee/awesome-agent-orchestrators>
- Claude Code: <https://code.claude.com/docs/en/sub-agents> ・ <https://code.claude.com/docs/en/agent-teams> ・ <https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md> （v2.1.212 / 216 / 217 / 219 / 224）・ <https://wmedia.es/en/tips/claude-code-subagents-limit> （個人の実測）
- Codex: <https://learn.chatgpt.com/docs/agent-configuration/subagents> ・ 二次: <https://convika.com/blog/claude-code-codex-subagents/> ・ <https://antiburn.com/guides/codex/agents-max-concurrent-threads-per-session/>
- Cursor: <https://cursor.com/docs/subagents> ・ OpenCode: <https://opencode.ai/docs/agents/> ・ Copilot: <https://github.blog/ai-and-ml/github-copilot/run-multiple-agents-at-once-with-fleet-in-copilot-cli/>
- Anthropic: <https://www.anthropic.com/research/multi-agent-research-system> ・ Cognition: <https://cognition.com/blog/dont-build-multi-agents> ・ <https://cognition.com/blog/devin-can-now-manage-devins> ・ <https://cognition.com/blog/multi-agents-working>
- 二次: <https://www.augmentcode.com/guides/when-multi-agent-ai-is-overkill> ・ <https://deepwiki.com/code-yeongyu/oh-my-opencode/4.1-sisyphus-orchestrator>
- 自作側: [pi-subagents](../../spec/guard/pi-subagents.md)・[ADR-0016](../../adr/0016-pi-extensions-own-first.md)・[記録 P2](pi-public-extensions-survey.md#記録-p2--2026-10-20-subagents--todo-を公開拡張へ置き換えられるか)

## 記録 O2 — 2026-10-31（よくあるオーケストレーターは、feature の単位・依存・状態・取り込み順をどう持つか）

### 問い

複数の feature を、複数の `worker`（1 worktree = 1 feature = 1 worker）へ並列に任せる親は、feature の単位と依存関係を、明示的に持つべきか。よくあるオーケストレーターは、どう持っているか。
O1（pi の拡張と他社の親子設計）の続き。親側の運用の表（[CHG-0045](../../change/0045-orchestrator-parent.md)、[CHG-0054](../../change/0054-containment-and-async-approval.md)）の根拠にする。

### 対象・方法・限界

- 対象: Beads、Task Master、spec-kit、Claude Code の agent teams（Anthropic の講演の書き起こし記事）、ccpm、Gas Town、Vibe Kanban、研究（Co-Coder）、実践者の記事。取得日 2026-10-31。
- 方法: Web 検索（Brave）と、主要な記事・論文の本文の取得。**動かしていない・導入していない**。原文は非公開の置き場に保存した。
- 種別: **事実**（本文を読んだ）、**抜粋**（検索結果の抜粋だけ）、**二次**（他者の要約）、**推測**。
- 限界: 出典は公式 docs・実践者の記事・ベンダーの講演が中心で、独立した再現は無い。研究は、新規のプロジェクトを生成するベンチマークで、既存のリポジトリの編集とは条件が違う（プレプリント）。

### 観測した事実

| # | 運用 | 内容 | 種別・出典 |
| --- | --- | --- | --- |
| 1 | 依存つきのタスク表と、着手できるものの一覧 | Beads は `bd ready` が、未完了の依存が無い open の課題だけを出す。Task Master は `next` が、状態と完了済みの依存から、次のタスクを出す（`tasks.json` に依存を持つ）。Claude Code の agent teams は、共有のタスク表（pending / in_progress / completed / blocked）で、完了すると依存する後続が自動で解除される。spec-kit は、フェーズ（Setup → Foundational → ユーザーストーリー）と `[P]` 印（別ファイルで依存なしなら並列）で表す | Beads・Task Master・spec-kit は**抜粋**（<https://beads.gascity.com/>、<https://github.com/eyaltoledano/claude-task-master>、<https://github.com/github/spec-kit/blob/main/templates/tasks-template.md>）。agent teams は**二次**（<https://addyosmani.com/blog/code-agent-orchestra/>） |
| 2 | 担当ファイルの明示と、重なるなら直列 | spec-kit は各タスクに、実装するファイルの正確なパスを書く。ccpm は、独立した作業の流れを見つけ、自分のファイルだけを担当させる。**ディスパッチの時点でパスを予約し、重なる場合は並列でなく依存の順序にする**（Raylabs） | spec-kit・ccpm は**抜粋**（<https://github.com/automazeio/ccpm>）。Raylabs は**事実**（<https://dev.to/raylabs/handling-git-merge-conflicts-in-multi-agent-worktrees-1em8>。2026-10-04 の記事） |
| 3 | 取り込みは 1 本ずつ直列 | 最新の本流へ rebase し、その状態で検査し、全部通ったときだけ取り込む。**衝突やテストの失敗では止める（fail-closed）。LLM に衝突を直させるのは危険**（欠落・衝突マーカーの残留）。Gas Town の Refinery は Bors 型の bisecting merge queue。Vibe Kanban の利用者が足した `merge-parallel` は、順に取り込み、衝突で止まる | Raylabs は**事実**。Gas Town は**二次**（<https://rywalker.com/research/gastown>）。Vibe Kanban は Reddit の**抜粋** |
| 4 | 調整の状態を、作業ツリーの外に置く | 共有のチェックリストのファイルは、十数体が更新すると、衝突の元になる。Issues や専用のチケットなど、作業ツリーと独立した場所を使う。Beads は git に紐づく専用の保存先（後に Dolt）で、Gas Town の制御面になっている | **二次**（<https://www.developersdigest.tech/blog/git-worktrees-claude-code-parallel-agents-guide>。Grit という事例の報告） |
| 5 | 並列の数 | agent teams は、3〜5 体が適切（費用は線形に増え、3 体の集中が 5 体の分散に勝つ）。ローカルの資源では、4〜5 体が実用の上限（ビルド・テストの CPU とメモリ）。調整の費用は、体数に対して非線形に増える | **二次**（上の 2 記事） |
| 6 | 結合の強い部分は 1 人に。契約を先に | **Co-Coder**（arXiv 2606.00953、2026-05-31）: ファイルの依存グラフを作り、結合の強いまとまりを同じエージェントに割り当て、依存を見るスケジューラで実行する。報告: CodeProjectEval で、逐次に比べ、成功率 +14.0%、速度 2.10 倍、費用 −35%。DevEval で、成功率 56.8% → 68.1%、1.81 倍、−28%。**依存が最も密なプロジェクトで利得が最大**。無差別なファイル単位の並列は、費用が 60% 増える割に、効率の向上は 1.56 倍。agent teams は、速度が最速でも、成功率が及ばない場合がある（本文の記述は取得できた範囲）。事前に、ファイルごとのシンボルと import を書いた**インターフェースの設計図**を作る | **事実**（論文の報告）。独立した再現は無い。<https://arxiv.org/html/2606.00953> |
| 7 | 親の限界 | 子を直接起動する方式では、親が依存グラフを手で管理する（共有のタスク表も、仲間同士の連絡も無い）。ファイルの範囲づけが雑だと、2 体が同じファイルに書く | **二次**（Addy Osmani の記事） |

### 推測（このリポジトリへの含意）

- 親が、feature の表（単位・担当ファイル・前提・状態・取り込み順）を、明示的に持つのは、主流の型と一致する。今は、親（私）が、会話の中で判断しているだけ。
- **借りる**: 着手できるもの（前提が全部済んだもの）を、表から機械的に出す。計画が変わったら、後続の feature の前提も更新する（Task Master の `update` と同じ発想）。書き込む `worker` は 3〜5 体まで。変わりやすい状態は、リポジトリの外（todo・`.tmp`）に置き、計画だけを案件の「実施計画」の表に置く（すでにそうしている）。
- **借りる（新しい）**: `finish` の前に、統合先との衝突を事前に検査する（`git merge-tree`）。統合先が分岐後に進んでいれば、その件数を見せる。承認の前に、衝突の有無が分かる。
- **契約を先に**: 並列にする部品（新規ファイルだけを触るもの）と、配線（`index.ts` など共有ファイルを触るもの）を分け、部品の型を先に固める（非同期承認の計画で実践する）。
- **借りない**: Gas Town のような大きな基盤（導入の費用と固定化が大きく、今の規模には重い）。LLM による衝突の自動解決。入れ子の「feature lead」（今の基盤は子から子を作れない）。

### 未検証

- 上の運用が、小規模・単独の利用者の、dotfiles のような、設定中心のリポジトリで、同じ効果を持つか（論文はベンチマーク、記事は主に Web アプリ）。
- Beads・Task Master・spec-kit の細部（本文を取得したのは、Raylabs、Co-Coder、Addy Osmani、DevelopersDigest、Gas Town の解説だけ）。
- 事実 5 の数値の出典は二次で、一次の資料（Anthropic の公式の docs）を読んでいない。
