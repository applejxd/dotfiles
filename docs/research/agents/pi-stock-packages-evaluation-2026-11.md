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

## 検索（決定の経緯）

- 検索の送り先が限られる環境では、検索は agentcore-websearch の MCP だけを使う。`pi-web-access` は、鍵なしだと第三者へクエリが出るので入れない。
- 家の機は、自作の MCP（`home/dot_config/agents/websearch/`）に揃える。**例外として自作を選んだ**（[ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md#例外として残す自作の一覧)）。理由: 各サービスの無料枠のフォールバック（Brave → Exa → Tavily → DuckDuckGo）、論文の専用のフォールバック（OpenAlex → Semantic Scholar → Crossref → arXiv）、クエリの秘匿チェック・SSRF 防止を満たす既製の MCP が、調べた範囲（npm の検索。網羅ではない）で見つからず、既存のスキルの CLI の核を再利用すれば小さく足りるため。
- 既製の候補: Brave 公式 MCP（`@brave/brave-search-mcp-server`。MIT。月間 14 万）は検索のみでフォールバックが無い。論文用の MCP（OpenAlex・Semantic Scholar など）は複数ある。

## 標準機能で足りないもの（調査の発見）

- **背景のシェル実行**: pi 本体の bash は前景のみ（公式の文書は tmux の案内だけ）。`pi-subagents` の背景実行は**エージェント**単位で、ログを残して完了通知で起こす `bg_run` のような機能は無い。背景の成功の通知が親を自動で起こすかは未確認。
- **plan mode・`/goal`・ステータス表示・通知・メモリ・巻き戻し**: 標準には無い。下の候補を参照。

## 見つけた他の候補（未評価。月間 DL の順。`pi-package` の語での検索）

評価の前の一覧で、導入の推奨ではない。導入するときは [探し方と評価](../../../.agents/skills/pi-extension-dev/references/public-research.md) の手順で、README と権限の範囲を読んでから決める。

| 軸 | 候補（月間 DL） | 備考 |
| --- | --- | --- |
| オーケストレーション | `@tintinweb/pi-subagents`（6.0 万）、`pi-goal-x`（2.9 万。`/goal`）、`pi-gauntlet`（1.7 万。ゲートつきワークフロー）、`pi-crew`（1.6 万。チーム・worktree・非同期）、`pi-herdsman`（1.0 万）、`pi-maestro-flow`（0.9 万）、`@chankov/agent-fleet`（0.9 万）、`@trevonistrevon/pi-loop`（0.6 万。再起床・背景監視） | 自作の `/goal`・並列 worker・背景実行の代替になりうる |
| plan mode | `@agimon-ai/po-plan`（2.3 万。編集ツールを外した計画モード。計画を保存） | 自作の `/plan` の代替 |
| git・worktree | `@agimon-ai/po-git`（2.3 万。worktree ごとのセッション）、`pi-dev-flow`（1.1 万。計画 → 実装 → リリースのゲート）、`@henryqw/pi-deps`（0.2 万） | |
| メモリ | `pi-memory`（6.8 万）、`pi-hermes-memory`（2.7 万）、`gentle-engram`（2.0 万） | 方針が合うかの評価が要る（鍵・外部送信） |
| 通知 | `@pi-unipi/notify`（0.6 万）、`@lwlee2608/pi-notify`（0.3 万。スマホ通知）、`@narumitw/pi-notify`（0.2 万） | 自作の `notify` の代替 |
| 巻き戻し・チェックポイント | `@ayulab/pi-rewind`（0.4 万）、`checkpoint-pi`（0.1 万） | |
| ステータス表示 | `@xynogen/pix-footer`（0.3 万。モデル・トークン・git・TPS）、`@erichll/pi-statusline`（0.15 万）、`@firstpick/pi-extension-git-footer-status`（0.16 万）、`pi-agent-suite`（0.4 万。フッターと割当の表示を含む多機能） | 自作の `activity` の代替 |

## 未確認

- 実機での `chezmoi apply`・package の取得・permission-system の bash パターンの一致・YOLO の動作。
- `pi-subagents` の前景の子と permission-system の連携。背景の完了通知が親を起こすか。
- Windows 実機。
