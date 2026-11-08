# stock の pi の package の評価（2026-11）

- **日付**: 2026-11-08〜09（月間ダウンロード数は 2026-11-07 時点。npm の公開 API）
- **目的**: [ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md) で pi を公式の既定＋人気の package へ戻すにあたり、入れる package を 1 つずつ評価して決めた記録。方針は [ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md)。
- **方法**: `npm view`・`npm pack`（展開して README・設定・ソースを**読むだけ**）。出典は各 package の同梱 README と、npm の公開 API。数値は人気の目安で、安全性の証拠ではない。
- **一覧の正本**: `home/.chezmoitemplates/pi-stock-packages`（版固定）。

## 評価と決定

| # | package（版） | 月間 DL | 役割 | 決定 |
| --- | --- | --- | --- | --- |
| 1 | `@gotgenes/pi-permission-system`（42.0.0） | 4.5 万 | 権限の判定（allow / ask / deny）と承認画面。YOLO mode（`/permission-system`。ask の自動承認で、明示の deny は効く） | 残す。方針 A（読み取り系は許可・危険なものと秘密は deny・それ以外は ask）を設定で配る。設定が無いと全部 ask になる |
| 2 | `cc-safety-net`（2.7.6） | 13.6 万 | 破壊的コマンドと秘密へのアクセスを、実行前に解析して拒否（聞かない固定の網）。sandbox ではない | 残す。standard（既定。設定不要） |
| 3 | `pi-subagents`（nicobailon。0.87.0） | 79.9 万 | 子エージェント（組み込みの scout・reviewer・worker・oracle など）・背景実行・ワークフロー | 入れる。permission-system との連携（前景の子の ask の転送）は未確認。もう 1 つの候補 `@gotgenes/pi-subagents`（1.7 万。連携が文書化）は見送り |
| 4 | `pi-mcp-adapter`（7.0.1） | 153.8 万 | MCP の接続（遅延起動・MCP UI・OAuth をキーチェーンへ・他の CLI の設定の取り込み）。入れると pi 組み込みの MCP を自動で OFF にする | 検索の送り先が限られる環境の機だけ入れる（利用者の選択）。pi 1.5.0 は組み込みの MCP を持つので、他の機は組み込みで足りる |
| 5 | `pi-web-access`（0.47.0） | 123.4 万 | Web 検索・ページ取得・GitHub の clone・動画の解析。鍵なしでは第三者（Exa）へクエリが出る | **入れない方向**。家の検索は、自作の MCP（下）に揃える |
| 6 | `@juicesharp/rpiv-todo`（2.15.0） | 9.6 万 | `todo` ツール・`/todos`・エディタ上のパネル。状態は会話から再構築 | 入れる |
| 7 | `@juicesharp/rpiv-ask-user-question`（2.15.0） | 17 万 | `ask_user_question`（最大 4 問・選択肢・メモ・プレビュー） | 入れる |

- 3・4・5 は作者が同じ（nicobailon）で、1 人の保守者への依存が増える。版を固定する。
- 6・7 は作者が別（juicesharp）。日本語の UI 翻訳は無い（英語）。

## 追加の 4 つの評価と決定（2026-11-09）

利用者が確認して決めた。原文の評価は [archive の pi-eval](../archive/2026-11-agent-stack/pi-eval/)（`background.txt`・`plan-goal.txt`・`rewind-notify.txt`。通知・ステータス表示の節は、下の「通知・ステータス表示の決定」）。月間 DL は npm の last-month（2026-11-07 まで）。

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
- 自作の `/plan` を持つ custom プロファイルとのコマンド名の衝突は、stock では起きない（自作の拡張を配らない）。
- 検索（pi-web-access・pi-mcp-adapter）は、この決定に含めない（保留）。通知・ステータス表示は次の節。

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

## 未確認

- 実機での `chezmoi apply`・package の取得・permission-system の bash パターンの一致・YOLO の動作。
- `pi-subagents` の前景の子と permission-system の連携。背景の完了通知が親を起こすか。
- Windows 実機。
