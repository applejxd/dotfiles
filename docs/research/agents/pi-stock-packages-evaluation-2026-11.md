# stock の pi の package の評価（2026-11）

- **日付**: 2026-11-08〜09（月間ダウンロード数は 2026-11-07 時点。npm の公開 API）
- **目的**: ADR-0030 で pi を公式の既定＋人気の package へ戻すにあたり、入れる package を 1 つずつ評価して決めた記録。方針は [ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md)。
- **方法**: `npm view`・`npm pack`（展開して README・設定・ソースを**読むだけ**）。出典は各 package の同梱 README と、npm の公開 API。数値は人気の目安で、安全性の証拠ではない。
- **一覧の正本**: `home/.chezmoitemplates/pi-stock-packages`（版固定）。

## 評価と決定

| # | package（版） | 月間 DL | 役割 | 決定 |
| --- | --- | --- | --- | --- |
| 1 | `@gotgenes/pi-permission-system`（42.0.0） | 4.5 万 | 権限の判定（allow / ask / deny）と承認画面。YOLO mode（`/permission-system`。ask の自動承認で、明示の deny は効く） | 残す。方針 A（読み取り系は許可・危険なものと秘密は deny・それ以外は ask）を設定で配る。設定が無いと全部 ask になる |
| 2 | `cc-safety-net`（2.7.6） | 13.6 万 | 破壊的コマンドと秘密へのアクセスを、実行前に解析して拒否（聞かない固定の網）。sandbox ではない | 残す。standard（既定。設定不要） |
| 3 | `pi-subagents`（nicobailon。0.87.0） | 79.9 万 | 子エージェント（組み込みの scout・reviewer・worker・oracle など）・背景実行・ワークフロー | 入れる。permission-system との連携（前景の子の ask の転送）は未確認。もう 1 つの候補 `@gotgenes/pi-subagents`（1.7 万。連携が文書化）は見送り |
| 4 | `pi-mcp-adapter`（7.0.1） | 153.8 万 | MCP の接続（遅延起動・MCP UI・OAuth をキーチェーンへ・他の CLI の設定の取り込み）。入れると pi 組み込みの MCP を自動で OFF にする | 検索の送り先が限られる環境の機だけ入れる（利用者の選択）。pi 1.5.0 は組み込みの MCP を持つので、他の機は組み込みで足りる |
| 5 | `pi-web-access`（0.47.0） | 123.4 万 | Web 検索・ページ取得・GitHub の clone・動画の解析。鍵なしでは第三者（Exa）へクエリが出る | **入れない**（一覧から削除。2026-11-09）。家の検索は、自作の MCP `websearch`（下）に揃える |
| 6 | `@juicesharp/rpiv-todo`（2.15.0） | 9.6 万 | `todo` ツール・`/todos`・エディタ上のパネル。状態は会話から再構築 | 入れる |
| 7 | `@juicesharp/rpiv-ask-user-question`（2.15.0） | 17 万 | `ask_user_question`（最大 4 問・選択肢・メモ・プレビュー） | 入れる |

- 3・4・5 は作者が同じ（nicobailon）で、1 人の保守者への依存が増える。版を固定する。
- 6・7 は作者が別（juicesharp）。日本語の UI 翻訳は無い（英語）。

## 追加の 4 つの評価と決定（2026-11-09）

利用者が確認して決めた。原文の評価は archive の pi-eval（`background.txt`・`plan-goal.txt`・`rewind-notify.txt`。通知・ステータス表示の節は、下の「通知・ステータス表示の決定」）。月間 DL は npm の last-month（2026-11-07 まで）。

| # | package（版） | 月間 DL | 役割 | 権限の範囲（ソースの読み） | 決定 |
| --- | --- | --- | --- | --- | --- |
| 8 | `pi-background`（0.4.2。MIT） | 3,050 | 背景シェル実行。`bg_run`・`bg_status`・`bg_kill`。bash が 120 秒を超えると自動で背景化。終了で親を起こす | 子プロセスのみ。ネットワーク送信なし。ログは `/tmp/pi-bg/` | 入れる。`shellTools` に `bg_run` を足し、bash と同じ判定に通す |
| 9 | `@narumitw/pi-plan-mode`（0.60.0。MIT） | 27,893 | `/plan`。`tool_call` の block だけで読み取り専用（`setActiveTools` を呼ばない）。計画の保存・承認・実装 | ネットワーク・子プロセス・環境変数の読みなし。書くのは設定 JSON と export 先の md | 入れる。`defaultPlanTools`・`defaultPlanExportPath` を設定で配る |
| 10 | `@narumitw/pi-goal`（0.55.0。MIT） | 24,636 | `/goal`。token 予算・自動応答数の上限（25）・無進捗 3 回で停止・`goal_wait` | ネットワーク・子プロセス・環境変数の読みなし。書くのは session と設定 JSON | 入れる。設定は既定のまま。`--tokens` つきで使う運用 |
| 11 | `@ayulab/pi-rewind`（0.4.6。**GPL-3.0**） | 4,467 | `/rewind`・`/checkpoint`。別の bare repo に外部 index でスナップショットを取り、利用者の `.git` に書かない | ネットワークなし。子プロセスは `git` のみ。復元時に作業ツリーへ `reset --hard`・`clean -fd` | 入れる（npm の参照のみで、コードは取り込まない）。実機の確認が導入の条件 |

- 取り込む版は、tarball（`npm pack` で展開して読むだけ。実行なし）で、ツール名・引数名・設定のキーを確かめた: `bg_run({command, cwd?, wake_on?})`・`bg_status`・`bg_kill`・コマンド `/bg`。`plan_mode_question`・`plan_mode_complete`・コマンド `/plan`。`goal_complete`・`goal_blocked`・`goal_wait`。`/rewind`・`/checkpoint`（ツールは足さない）。`pi-plan-mode.json` のキー `defaultPlanTools`・`defaultPlanExportPath`。`pi-goal.json` の既定（`automaticTurns: 25`・`noProgressTurns: 3`・`rpc.enabled: false`・`retryUsageLimits: false`）。
- 却下した候補: `pi-background-tasks`（peer が pi 0.81〜0.84 のみ・既定で Anthropic のリクエストを書き換える）・`@agimon-ai/po-*`（BUSL-1.1・alpha・Po 前提）・`pi-patty-bg-tasks`（完了の wake が弱い）・`pi-plan`（`setActiveTools` で他のツールを消す）・`pi-goal-x`（auditor が permission-system を通らない）・`@schovest/pi-goal`（派生で更新が止まっている）・`pi-dev-flow`（feature 運用と二重）・`checkpoint-pi`（利用者の `.git` に書き、`git reset --hard` でブランチの先頭を動かす）。
- **bash を置き換える拡張を入れない**: pi-background の自動背景化は、pi 組み込みの bash のときだけ包む（`background.ts` の `session_start`）。bash を置き換える拡張（サンドボックス・`pi-patty-bg-tasks`・`@agimon-ai/po-runner` など）を入れると、自動背景化は無効になる（`bg_run` は残る）。

### 未確認（実機。導入の条件）

- pi-rewind: worktree の中で `/rewind` して、`git status`・`git reflog`・`git stash list` が変わらないこと。保存の時間・容量。
- pi-background: 12 分のコマンドで、終了時に親が起きること（`sendMessage` の `triggerTurn` がアイドル中に新しいターンを始めるか）。pi 1.5.0 との実機の動作。
- plan と goal: permission-system との `tool_call` の実行順（plan mode が block する呼び出しで ask が先に出ないか）。Workflow Mutex の pi 1.5.0 での保証（README は 0.84.2 で特性確認）。
- plan mode の `grep`・`find`・`ls` を使うには、pi の settings で有効化が要る（README の注意）。**有効化した**（stock の settings.json の `defaultTools: ["+grep", "+find", "+ls"]`。2026-11-09）。pi は、この 3 つが無いときだけ「ファイル操作は bash で」という規則をシステムプロンプトに入れるので、有効にすると専用ツールの説明に切り替わる（`dist/core/system-prompt.js`）。使われていなければ、セッションの記録を見て外す（設定の 1 行）。
- plan mode の許可リストに検索 MCP を足した（許可リストは完全一致の名前だけで、パターンは使えない）。`websearch`・`agentcore-websearch` を `exposure: direct` で見せ、完全名 4 つを `defaultPlanTools` へ追記する（`codemode` を許すと任意の MCP が呼べるため退けた）。未確認: `direct` のツールが plan mode で実際に通ること・検索中に ask が出ないこと・`/mcp` で `direct` と表示されること・`agentcore-websearch` の完全名（規則から導いたもの。生のツール名 `web-search-tool__WebSearch` は実機で確認済み）・`pi-mcp-adapter` が別名で出す可能性。詳細は [MCP サーバ](../../spec/mcp-servers.md#pi_exposurepi-への見せ方)。
- 自作の `/plan` を持つ custom プロファイルとのコマンド名の衝突は、stock では起きない（自作の拡張を配らない）。
- 検索は決定済み: `pi-web-access` は入れない、`pi-mcp-adapter` は `is-work` の機だけ入れる（一覧は `is-work` で分岐）。`~/.pi/agent/mcp.json` は `generate.py --target pi-mcp` で配る。通知・ステータス表示は次の節。

### 通知・ステータス表示の決定（2026-11-09）

- **ステータス表示は、標準のフッターのまま。** TPS を出すのは、評価した 8 つのうち `@xynogen/pix-footer` だけで、価格・ベンチの取得（`modelgrep.com`・`benchlm.ai` への GET）と pix 系の依存が増えるので見送り。背景ジョブの数は pi-background（入力欄の上の行 `⏵ 5 jobs`）、エージェントの数は pi-subagents のウィジェット・FleetView が出す（フッターで件数を出す拡張は候補の中に無かった）。次点は `@narumitw/pi-statusline`。
- **通知は、何も足さず、使ってみる。** 利用者の要件: **ask と、ユーザ入力を受け付けられる待機（`agent_settled`）だけ**。流れている最中（子の完了での再起床・背景ジョブ・自動継続）では鳴らさない（前の自作は頑繁でうっとうしかった）。
  - Orca: 自前の拡張 `orca-agent-status.ts` が `ui_prompt` と最終の idle（子エージェント稼働中は final にしない）を扱うので、追加は不要と見込む（実機で確認）。stock の apply はこのファイルを消さない。
  - Zed: 承認待ちは permission-system の `promptNotifications: ["bell"]`（初期値）、質問待ちは rpiv-ask-user-question の BEL。Zed の Terminal Threads がフォーカス外の端末の BEL を通知にする。
  - 完了の BEL は、評価した package に無い（`@yefengr/pi-notify` は Ghostty・WezTerm・kitty・iTerm2 だけを対象にする OSC）。必要になったら、`agent_settled` で BEL を鳴らす最小の自作（ADR-0031 の例外の 2 件目）か、スマホ通知（`@lwlee2608/pi-notify`。評価の推し。外部サービスと手動の `/notify on` が要る）を足す。

## 検索（決定の経緯）

- 検索の送り先が限られる環境では、検索は agentcore-websearch の MCP だけを使う。`pi-web-access` は、鍵なしだと第三者へクエリが出るので入れない。
- 家の機は、自作の MCP（`home/dot_config/agents/websearch/`）に揃える。**例外として自作を選んだ**（[ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md#例外として残す自作の一覧)）。理由: 各サービスの無料枠のフォールバック（Brave → Exa → Tavily → DuckDuckGo）、論文の専用のフォールバック（OpenAlex → Semantic Scholar → Crossref → arXiv）、クエリの秘匿チェック・SSRF 防止を満たす既製の MCP が、調べた範囲（npm の検索。網羅ではない）で見つからず、既存のスキルの CLI の核を再利用すれば小さく足りるため。
- 既製の候補: Brave 公式 MCP（`@brave/brave-search-mcp-server`。MIT。月間 14 万）は検索のみでフォールバックが無い。論文用の MCP（OpenAlex・Semantic Scholar など）は複数ある。

## 標準機能で足りないもの（調査の発見）

- **背景のシェル実行**: pi 本体の bash は前景のみ（公式の文書は tmux の案内だけ）。`pi-subagents` の背景実行は**エージェント**単位で、ログを残して完了通知で起こす `bg_run` のような機能は無い。背景の成功の通知が親を自動で起こすかは未確認。
- **plan mode・`/goal`・ステータス表示・通知・メモリ・巻き戻し**: 標準には無い。下の候補を参照。

## 見つけた他の候補（未評価。月間 DL の順。2026-11-07 時点。`pi-package` の語での npm 検索）

評価の前の一覧で、導入の推奨ではない。導入するときは [探し方と評価](../../../.agents/skills/pi-extension-dev/references/public-research.md) の手順で、README と権限の範囲を読んでから決める。

| 軸 | 候補（月間 DL） | 備考 |
| --- | --- | --- |
| 背景のシェル実行 | `pi-background-tasks`（2.1 万。永続の背景シェル・ウォッチャ・ログ）、`@agimon-ai/po-runner`（2.3 万。監視つきのシェル実行・ログ）、`pi-background`（0.3 万。「長いコマンドを背景で実行し、終わったら pi を起こす」）、`pi-patty-bg-tasks`（0.3 万。120 秒で自動の背景化）、`@ian-pascoe/pi-termctrl`（0.15 万。対話端末・背景ジョブ・`/ps` パネル） | pi 本体に無い機能。自作の `bg_run`（ログと完了通知で起こす）の代替になりうる |
| plan mode | `@narumitw/pi-plan-mode`（2.8 万。Codex 風の読み取り専用 `/plan`）、`@agimon-ai/po-plan`（2.3 万。編集ツールを外し、計画を保存）、`pi-plan`（0.1 万） | 自作の `/plan` の代替 |
| `/goal` | `pi-goal-x`（2.9 万）、`@narumitw/pi-goal`（2.5 万。自律の単一目的）、`@agimon-ai/po-goal`（2.2 万）、`@schovest/pi-goal`（1.6 万） | 自作の `/goal` の代替。`@narumitw` は plan-mode・goal・notify・sync・statusline の作者で、UX を揃えやすいが保守者が集中する |
| オーケストレーション | `@quintinshaw/pi-dynamic-workflows`（5.3 万）、`@tintinweb/pi-subagents`（6.0 万）、`pi-gauntlet`（1.7 万。ゲートつきワークフロー）、`pi-crew`（1.6 万）、`pi-herdsman`（1.0 万）、`pi-maestro-flow`（0.9 万）、`@chankov/agent-fleet`（0.9 万）、`@trevonistrevon/pi-loop`（0.6 万。再起床・背景監視） | すでに `pi-subagents` を入れているので、重なるものは外すか入れ替えるかを評価 |
| git・worktree | `@agimon-ai/po-git`（2.3 万。worktree ごとのセッション）、`pi-dev-flow`（1.1 万。計画 → 実装 → リリースのゲート）、`pi-herdr-agents`（0.9 万。Herdr 上の非同期サブエージェントと、任意の worktree）、`@henryqw/pi-deps`（0.2 万） | Herdr を入れている場合は相性を確かめる |
| ステータス表示 | `pi-powerline-footer`（4.4 万。Powerline 風）、`pi-cache-optimizer`（1.8 万。キャッシュ率の表示を含む）、`@ravshansbox/pi-statusline`（1.1 万）、`@narumitw/pi-starship`（0.4 万。Starship 風の TOML 設定）、`@narumitw/pi-statusline`（0.3 万）、`@xynogen/pix-footer`（0.3 万。モデル・トークン・git・TPS）、`pi-agent-suite`（0.4 万。フッターと割当の表示を含む多機能）、`pi-harness-runtime`（7.9 万。**BETA。「本番向けではない」と注記**） | 自作の `activity` の代替。種類が多く好みの問題。リポジトリの内容の表示を含むものは権限の範囲を確かめる |
| 左戻し・チェックポイント | `@ayulab/pi-rewind`（0.4 万。`/rewind`）、`checkpoint-pi`（0.1 万。git ベース） | YOLO mode を使うときの「回復」の網。自作基盤では「戻せるか」を重視していた |
| 通知 | `@pi-unipi/notify`（0.6 万）、`@lwlee2608/pi-notify`（0.3 万。スマホ通知）、`@henryqw/pi-bark`（0.2 万。iOS の Bark）、`@narumitw/pi-notify`（0.2 万） | 自作の `notify` の代替。承認待ちや長い作業の完了の知らせ |
| メモリ | `pi-memory`（6.8 万）、`pi-hermes-memory`（2.7 万）、`gentle-engram`（2.0 万） | これまでの記録に需要は見あたらない。入れるなら鍵・外部送信の評価が要る |

## 圧縮（2026-11-09 の決定）

- `@thgilciffart/pi-compaction@0.3.1` を、**要約の指示（brief）の恒久設定だけ**に使う（`auto` のしきい値は使わない）。しきい値は本体の `compaction.modelOverrides` の `reserveTokens = 300000`（窓 100 万のモデル。70 万で発動）。自作は足さない。
- 根拠と集計は [長い文脈は要らない（論文）と圧縮の方針](long-context-compaction-paper-2026-11.md)。

## 未確認

- 検索の MCP（実機）: `uv` が PATH にあること・stdio の起動・pi 組み込みの MCP が `mcp.json` の `websearch` を読むこと・permission-system の `mcp` の allow が探索系（`mcp_status` など）を自動で allow にするか。
- 実機での `chezmoi apply`・package の取得・permission-system の bash パターンの一致・YOLO の動作。
- `pi-subagents` の前景の子と permission-system の連携。背景の完了通知が親を起こすか。
- Windows 実機。

## オーケストレーションの評価と決定（2026-11-09）

出典は、`pi-subagents`（nicobailon。0.87.0）の同梱の README・docs・ソース（`npm pack` を展開して読んだだけで、実行なし）と、他の候補の tarball。原文は `.tmp/keep/pi-eval/orchestration-*.md`（archive へは別途）。

- **結論**: 他の package は入れず、`pi-subagents` だけで足りる（条件つき）。実機の確認は、まだしていない。
  - 子は**全部背景**にする（`forceTopLevelAsync: true`）。前景の子には親の拡張が載らず、permission-system と cc-safety-net が効かないため。背景の子には載る。
  - 組み込みの `scout` は bash と write を持つので、`agentOverrides` で読み取り専用に絞る。計画役は `oracle` を絞って使う。レビューは組み込みの `reviewer`（読み取り専用）。
  - permission に足す: `subagent_supervisor`（allow）。`subagent_launch`（workflow の子の起動ごとの確認）は **ask のまま**（allow にすると、`gate`・`acceptance.verify` のシェルコマンドが bash の規則を迂回する。それらは使わない）。
- **worktree の運用は、利用者の選択で N（拡張ネイティブ）から始める**: トップレベルで 1 回の `async: true` の workflow を呼び、書き込む子に `worktree: true`（使い捨ての worktree と枝 `pi-subagents/…`。patch と handoff の記録）。合わなければ F（親が feature worktree を作り、`subagent({agent, task, cwd, async:true})` で渡す。`cwd` は正規の引数）へ切り替える。比較: N は拡張の意図に沿い、後始末は拡張が行うが、git flow（1 feature = 1 枝）との形が合わず、`subagent_launch` の確認が毎回出る。F は git flow に合い、学習量が小さいが、並列は workflow ではなく複数の独立した呼び出しで、patch・lane の記録は得られない。運用の手順は `.agents/skills/feature-orchestration/references/pi-subagents.md`。
- **他の候補の判定**: `dynamic-workflows`・`pi-crew`・`agent-fleet` は、子に拡張が載らず permission が効かないので除外。`pi-herdsman` は外部（herdr）依存で除外。`pi-gauntlet` は `pi-subagents` との入れ替え専用で保留（「verify が通るまで review に進まない」の考え方だけ運用に取り込む）。`pi-loop` は `MonitorCreate` だけに関心が残るが `pi-background` で足りる。`@tintinweb/pi-subagents` は入れ替える理由なし。
- **実機で確かめる 4 点**: idle の親が完了通知で起きること／背景の子の bash が permission-system と cc-safety-net に止められること／**子の ask が親の画面へ転送されること**（最大の不確実性。0.87.0 のコードは `PI_SUBAGENT_PARENT_SESSION` を渡すが、permission-system の docs は別の package にしか触れていない）／`worktree: true` の子の patch を親が適用できること。
- **設定値（実装済み。仕様は [agent-config-generation](../../spec/agent-config-generation.md#pi-subagents-の設定)）**: `subagent/config.json` = `forceTopLevelAsync: true`（強制）・`worktreeProvider: "native"`・`maxActiveAsyncRunsPerSession: 4`・`maxSubagentDepth: 1`・`maxSubagentSpawnsPerRun: 32`（後 4 つは無いときだけ補う）。`agentOverrides.scout.tools` = `read, grep, find, ls, contact_supervisor`、`agentOverrides.oracle.tools` = `read, grep, find, ls`（`tools` は文字列の配列。`+`/`-` の増分指定は不可）。permission は `subagent_supervisor` = allow・`subagent_launch` = ask。
- **実機で確かめる 4 点（すべて未確認）**:
  1. idle の親が、完了通知で起きる。
  2. 背景の子の bash が、permission-system と cc-safety-net に止められる（`/subagents-doctor`）。
  3. 子の ask（`contact_supervisor`）が親の画面へ転送され、離席から戻って答えられる。
  4. `worktree: true` の子の patch（`artifactPaths` の handoff の記録）を、親の feature worktree へ適用できる。
- **そのほかの未確認**: `maxActiveAsyncRunsPerSession` の上限を超えたときの挙動（拒否かキューか）。`subagent_launch` を ask にしたとき、背景の子の起動が確認画面で止まらないか。`worktreeProvider: "native"` で、worktree の置き場（リポジトリの隣の `worktrees/<プロジェクト名>/`）が書き込み境界に入るか。

## Ralph Wiggum ループ系の評価と決定（2026-11-09）

出典は、npm の検索（`keywords:pi-package ralph`。20 件ほど）と、上位 3 件の tarball（`npm pack` で展開して読んだだけ。実行なし）。原文は archive の pi-eval。

- **結論: 追加の package は入れない。** 既定は `/goal`（`pi-goal`。導入済み）。新しい文脈が要るときは、`pi-subagents` の workflow で「毎回新しい子を起こす」ループを書く（[運用ガイド](../../../.agents/skills/feature-orchestration/references/pi-subagents.md)の「Ralph ループ」。スクリプト例つき。検証は未実施）。
- **候補の判定**:
  - `@tmustier/pi-ralph-wiggum@0.2.5`: 同じセッションの次のターンを回すだけで、新しい文脈にならず `pi-goal` と重なる。→ 除外。
  - `@lnilluv/pi-ralph-loop@2.1.2`: 子プロセスを `--no-extensions` で起動する（`src/runner-rpc.ts`）ので、permission-system と cc-safety-net が子に効かない。`commands:` を拡張自身が実行し、`shellTools` の判定を通らない別経路もできる。→ 除外。
  - `@rahulmutt/pi-ralph@0.4.0`: 同じプロセス内で `ctx.newSession()` を使うので、拡張は親のまま載る。ただし完了判定・無進捗の検出・予算がなく、固定回数を回すだけ。最終更新は 2026-04 で止まり、ライセンスの表記が食い違う（README は MIT、package.json と LICENSE は Apache-2.0）。→ 次点。
  - 詰め合わせ（`@pi-unipi/*`・`pi-hooks`・`pi-spiral`・`pi-corp` など）: 必要でない機能まで入る。→ 除外。
- **理由**: Ralph の主な利点は文脈の肥大を避けることだが、利用者の過去のセッションの集計では、長い文脈による質の低下の兆候が見つからなかった（[圧縮の研究ノート](long-context-compaction-paper-2026-11.md)）。新しい文脈にする必要性が、今はデータから支持されない。
- **未確認**: **`pi-subagents` の背景の子に permission-system と cc-safety-net が載るか**（実機で確かめる 4 点の 2。載らなければ workflow のループも lnilluv と同じ迂回になる）。`@rahulmutt/pi-ralph` の `newSession` の後に permission-system の状態（allow の記憶・YOLO）が引き継がれるか。GitHub の Issue の対応状況（npm の情報のみ見た）。
- **関連**: `@badliveware/pi-compaction-continue`（圧縮の後や停滞の後に促す見張り）は、圧縮の後の自動の再開に関係する（自作しないと決めた件。必要になったら評価する）。

## btw の評価と決定（2026-11-09）

出典は、npm レジストリ（`https://registry.npmjs.org/@narumitw%2Fpi-btw/latest`）・pi.dev の README（`https://pi.dev/packages/@narumitw/pi-btw`）・tarball の展開（取得・展開だけで、実行なし）。いずれも 2026-11-09 に取得した。

- **結論: `@narumitw/pi-btw@0.63.5` を入れる**（利用者の指示 2026-11-09）。`pi-stock-packages` で版を固定し、`is-work` の分岐の外（全ての機）に置く。**導入の条件は、実機での `/btw` の動作確認**（まだしていない）。
- **事実（レジストリ・tarball）**:
  - 版 0.63.5。MIT。2026-11-06 公開（GitHub Actions の trusted publisher。SLSA の provenance の記載あり。署名は検証していない）。月間 18.1K DL。展開後 999,945 バイト・50 ファイル。
  - peer 依存は `@earendil-works/pi-ai`・`pi-tui`・`pi-coding-agent`（いずれも `*`）。実依存は `@narumitw/pi-tui-kit ^0.69.1` の 1 つ。devDependencies は pi 1.5.0（実機と同じ版）でビルドされている。
  - tarball の sha512 は、レジストリの公表値（`sha512-sH2q5rmUHJ6rF9N8VlsuMq/kDI8GJqR31huvgxojnl0/OR4wwR3PBKFIQrRYX/kxeR06JS8l8wcaX1EYbxS6qw==`）と一致した。
  - 同じ作者（`@narumitw`）の `pi-plan-mode`・`pi-goal` は導入済み。
- **コードの確認（grep のみ。`src/` と、実際に読み込まれる `dist/` の両方。全コードのレビューではない）**:
  - 登録するのはコマンド `/btw` だけ（`registerTool` は 0 件）。モデル呼び出しは `completeSimple`（`tools` の指定なし）で、README の「The side model does not execute tools」と整合する。
  - `fetch`・URL・`process.env` は 0 件。ファイル書き込みは `settings.ts` だけで、`$PI_CODING_AGENT_DIR/pi-btw.json`（通常は `~/.pi/agent/pi-btw.json`）へ、一時ファイル経由で原子的に書く（設定を変えたときだけ）。
  - 子プロセスは `openUrlInBrowser`（`xdg-open` / `open` / `rundll32`。シェルを介さず、リンクを開く用途）の 1 か所だけ。`as any`・`@ts-ignore` は 0 件。pi 以外の依存は `@narumitw/pi-tui-kit` と node の組み込みだけ。
- **README の記述（未検証）**: `/btw <質問>` で本体と別のスレッドを開く。本体へは明示したときだけ戻せる（エディタに入れるだけで送信しない）。モデル・思考レベルは本体と別に指定でき、既定は本体と同じ。**質問と選んだ文脈は、そのモデルの提供元へ送られる**。TUI モード専用。再開できる状態はメモリ内だけ（`/new`・`/resume`・`/fork`・`/reload`・再起動で破棄）。1 セッションで開ける BTW は 1 つ。Pi 0.85 未満では「最新へ移動」の操作が無い。
- **権限の観点（上のコードの確認からの読み）**: ツールを登録せず、モデル呼び出しは `completeSimple` なので、permission-system の判定の対象（ツール呼び出し）にならない。`xdg-open` の起動も拡張のコードからで、判定の対象外。よって permission の設定は足さない。`pi-btw.json` も配らない（既定のまま）。
- **候補の判定**:
  - `pi-btw`（dbachelder 版・tbroadley 版）: 本物のサブセッションで `read`/`bash`/`edit`/`write` を持つ。2026-10-21 の調査（[pi-public-extensions-survey](pi-public-extensions-survey.md)）で「導入しない」と判断済み。→ 除外。
  - `@pandi-coding-agent/btw@0.1.1`（ツールなし・履歴に残さない）: npm 上で deprecated（「`@pandi-coding-agent/pandi-btw` へ改名」）。後継は未確認。→ 見送り。
  - `@firstpick/pi-extension-btw`・`@nguyenquangthai/pi-btw`・`@pi-unipi/btw`・`pi-mono-btw`: 検索結果の説明文しか見ておらず、判断できない。→ 未評価。
- **理由**: ツールを登録せず（モデル呼び出しはツールなし）、本体と別のスレッドで質問できる。導入済みの plan mode・goal と同じ作者で、pi 以外の実依存が 1 つだけ。自作の `btw`（`home/dot_pi/agent/extensions/btw/`）は custom プロファイルでだけ配る（stock は自作の拡張を配らない）ので、コマンド名 `/btw` は衝突しない。
- **未確認（実機・コード）**:
  - 依存 `@narumitw/pi-tui-kit` のコードは見ていない。README が書く「非公開のレイアウトアクセス（公式のサポート保証なし）」の具体的な箇所は、grep では特定できなかった。dist が src からのビルド結果と一致するかは検証していない。provenance の署名は検証していない。
  - インストールも実行もしていない。`chezmoi apply` 後に pi 1.5.0 が package を取得して `/btw` が動くこと、Orca の端末での表示、`pi-plan-mode`・`/goal` との共存は、実機で確かめていない。Windows 実機は未検証。

## tok/s 表示の評価と決定（2026-11-09）

出典は、npm レジストリ・npm のダウンロード数の API（last-month）・tarball の展開（`npm pack` と展開だけで、実行なし）・検索結果の README。いずれも 2026-11-09 に取得した。コードは grep と一部の読みだけで、全体のレビューではない。

- **結論: `pi-show-token-rate@0.3.0` を入れる**（利用者の指示 2026-11-09）。`pi-stock-packages` で版を固定し、`is-work` の分岐の外（全ての機）に置く。**導入の条件は、実機での表示の確認**（まだしていない）。
- **事実（レジストリ・tarball）**:
  - 版 0.3.0。MIT。作成 2026-10-08・最終更新 2026-10-18。メンテナは 1 人（luohuidong）。リポジトリは `https://github.com/luohuidong/pi-extensions`（`packages/pi-show-token-rate`）。月間 398 DL。
  - tarball は 17,631 バイト・15 ファイル（`src/` の .ts・README・LICENSE・CHANGELOG・package.json）。**tarball の sha512 は、レジストリの公表値（`sha512-6dDPWv4ZIzt5QOgd0PZl86hjMjj/WRUv75fT0NrloV4p4oAAF5fIt0FG70O7JTD8gZm80z2H4GDhbk56zWYjZg==`）と一致した。** レジストリの署名（`dist.signatures`）はあるが検証していない。レジストリの応答に provenance の attestations は無かった。
  - 依存なし。peerDependencies は `@earendil-works/pi-coding-agent: *` だけ。package.json の pi マニフェストは `extensions: ["./src/index.ts"]`。
- **コードの確認（grep のみ。配布物は `src/`・README・LICENSE・CHANGELOG だけ。全コードのレビューではない）**:
  - 次は **すべて 0 件**: `fetch(`・URL（`https?://`）・`process.env`・`child_process`/`execSync`/`spawn`・`node:fs`/`writeFile`/`readFile`・`node:net`/`node:http`/`node:https`/WebSocket・`eval(`/`new Function`・`as any`/`@ts-ignore`・`registerTool`・`appendEntry`/`sendMessage`/`sendUserMessage`。pi 以外の import は無い。
  - 登録するのはコマンド `/token-rate`（引数なし。表示の切り替え）だけ。表示は `ctx.ui.setStatus`。
- **測り方（`src/` のコメントからの読み。実測では未確認）**: TTFT は、assistant メッセージ自身の timestamp（pi が応答のストリームを開いた時刻）から、最初のトークンを含むストリームのイベント（thinking を含む）までの差。300 秒を超える値は捨てる。ストリーム中の TPS は直近の窓の速度。provider が使える `usage.output` を返さない間は、文字数から推定する（全角・CJK は 1 文字 ≒ 1 トークン、半角は 4 文字 ≒ 1 トークン、ツールの JSON は 2.5 文字 ≒ 1 トークン）。ストリームが終わると値は残して薄く表示する。履歴・平均は無い。
- **候補の比較**（月間 DL は npm の API の last-month。規模・触るものは tarball の展開と grep）:
  - `pi-token-speed`（gsanhueza）: 5,800 DL・0.12.0（2026-10-20）・展開後 404KB・58 ファイル。窓の平均 TPS をステータス行に出す。色の選択画面などの設定 UI があり、設定ファイルを書く（`settings-storage.ts` の `writeFile`）。→ 数字 1 つの表示には大きすぎるので見送り。
  - `@monotykamary/pi-tps`: 1,949 DL・1.3.19（2026-11-02）・`index.ts` 995 行。ターンごとに通知し、セッションへ `appendEntry('tps')` で記録し、`/tps-export` で `~/.cache` へ書き出して `execSync` で `xdg-open`/`open` を実行する。→ 触る範囲が広いので見送り。
  - `pi-show-token-rate`: 398 DL。→ **採用**（ステータス行とコマンドだけ。ファイル・ネットワーク・子プロセスが無い）。
  - `@nbafrank/pi-tks`: 357 DL・0.1.3（2026-10-22）・展開後 44KB。ローカルモデル向けで、ライブ TPS・最終の decode 速度・prefill 速度・TTFT を出す。コマンド `/tps`。ファイル・ネットワーク・子プロセスは grep で 0 件。→ **代替の第 1 候補**。
  - `pi-tps`（summertime-wu）91 DL・`@kinarajv/pi-tps-extensions` 69 DL・`@yqt5420/pi-token-speed` 50 DL・`pi-ttft`（TTFT のみ）25 DL: 利用が少なく、検索結果の説明文しか見ていない。→ 未評価。
  - 自作の `speed`（`home/dot_pi/agent/extensions/speed/index.ts`。100 行。直近 1 回の TTFT と decode 速度、取れない値は直前の値を残す、reasoning がストリームに出ない経路では `~` を付ける）: stock では配備されない（凍結。ADR-0030）。→ **代替の第 2 候補**。復活には [ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md) の記録（理由・維持費・撤去条件）と承認が要る。
  - 先行の調査記録: [pi-public-extensions-survey](pi-public-extensions-survey.md) の記録 P8（2026-10-31。当時は公開の拡張を導入せず、README だけで比較した）。
- **ほかに確認したこと**: pi 1.5.0 の本体には TPS の表示が無い（docs と dist の grep。`tokens per second` のヒットは、OpenRouter の経路指定の項目 `preferred_min_throughput` の説明だけで、表示の機能ではない）。
- **理由**: [ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md)（既存の拡張で足りるかを先に確認する）。ステータス行だけを触り、ファイル・ネットワーク・子プロセスを使わない最小の候補。日本語の文字数の推定が考慮されている。導入は 1 行の版固定で済む。
- **代替に切り替える条件・撤去**: 実機で数値が極端に外れる（Copilot 経由で reasoning がストリームに出ないときの過小など）、他のステータス表示と競合する、更新が止まる、のいずれかなら、`@nbafrank/pi-tks` か自作 `speed` の復活を評価する。撤去は `pi-stock-packages` の 1 行を消すだけ。
- **未確認**: 実機の TUI・Orca での見え方、Copilot 経由の数値の精度、pi 1.5.0 との実際の互換（peer は `*`）、長期の保守（作者 1 人・公開から約 5 週間）、配布物が GitHub のソースと一致するか（検証していない）。Windows 実機は未検証。
