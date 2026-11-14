# ask の自動判定（LLM を判定役にする案）の評価（2026-11）

- **日付**: 2026-11-15。出典の日付は各項目に記す。数値は、記載のない限り提供者の自社測定。
- **目的**: 確認（ask）の内容が分からず判断に困るので、エージェント（LLM）に自動判定させたい、という案の評価。方針は [ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md)（既存を先に評価。自作は最後の手段）。
- **方法**: ① 導入済みの拡張（`@gotgenes/pi-permission-system` v42.0.0）の docs とソースの読解、② 公開の package・他の主要エージェントの公式 docs・記事・論文の調査（`researcher` 3 件、`scout` 1 件）、③ 候補のソースを取得して grep（実行はしない）、④ 審査ログ（80 件）の分類。

## 結論

**今は導入しない**。自動 allow の効く範囲が、ask 全体の約 12% しかない（下の実測）。残りは、人が確認すべき意図した関門と、拡張が自動 allow を認めない外のフォルダの ask。外のフォルダは、決定的な規則（パスの危険度）で減らす。

## 実測: ask の内訳（審査ログ 80 件）

| 区分 | 件数 | 割合 | 判定役で自動 allow |
| --- | --- | --- | --- |
| 意図した関門（規則で ask にした `chezmoi apply`・`git flow finish`・`rebase`・`git config` など） | 36 | 45% | してはいけない（人が確認するための関門） |
| 外のフォルダ（`external_directory*`） | 32 | 40% | できない（拡張が allow を defer に下げる） |
| bash の不明な形（wrapper・opaque・unparsed・`*`） | 10 | 12% | 唯一できる範囲 |
| その他（`watchdog_diff`） | 2 | 2% | — |

n が小さく、1 週間足らずのログ。傾向を見る用途で、統計的な結論ではない。

## 事実（確かめたもの）

- **拡張の入口**: `authorizerChain` に判定役（link）を登録でき、ask に対して allow / deny（理由つき）/ defer を返せる。`external_directory` と `path` の allow は defer に下げられる（例外は「ディスク上に何も無いパスに見えるだけのトークン」）。出典: 導入済み v42.0.0 の `docs/configuration.md`（Authorizer chain 節）。
- **第一者 `@gotgenes/pi-permission-model-judge`**: `external_directory` の typo パスの自動 deny だけ。allow は出さない。出典: 同 package の README（2026-11-15 取得）。
- **第三者の link（pi.dev・GitHub の README。コードは `pi-permission-classifier` だけ精査）**: `pi-permission-classifier`（v0.6.1、MIT、約 1,200 DL/月）・`@mzwing/pi-permission-auto-review`（1.0.1、約 1,600 DL/月）・`pi-permission-ai-guard`（0.15.0、約 1,000 DL/月）。独立型に `pi-verdict`・`pi-bouncer` ほか。
- **`pi-permission-classifier` のソース（commit `3d6ab876`、2026-11-03）**: `package.json` に install 系のスクリプトが無い。`src/` に `fetch`・`http(s)://`・`child_process`・`process.env`・`writeFile` が無い（grep）。実行時の依存は `zod` だけ。`path` と `external_directory` は判定対象外（README）。**`verdicts` に「deny と defer だけ（allow を出さない）」の設定が無い**（`allow-deny-defer`・`allow-defer`・`allow-deny` のみ）。shadow（記録だけ）モードも無い。
- **他の主要エージェント**: Claude Code（auto mode）・Codex（Auto-review）・Cursor（Auto-review）が LLM 判定を持つ。3 社とも、決定的な規則・sandbox を先に通し、残りだけを判定モデルに送る。拒否は理由つきで返し、連続して拒否されたら人に戻す。出典: Anthropic（2026-03-25）、OpenAI（2026-04-30）、Cursor（2026-06-11）の公式の記事。
- **誤許可の実測**: Anthropic の自社測定は、やりすぎ操作の見逃し 17%（n=52）・誤拒否 0.4%（n=10,000）。独立評価（arXiv:2604.04978）は、曖昧な認可の場面で見逃し 81.0%。単発コマンドの LLM 判定は、良性:危険 = 20:1 で適合率が 0.27〜0.52 に落ちる（Kontext の自社ベンチ）。
- **注入**: 判定役を騙す攻撃は実在する（promptfoo DB・arXiv:2510.09023。二次情報）。Anthropic は、判定役にツール出力とエージェントの発言を見せないことで対策している。
- **決定的な境界の効果**: sandbox はプロンプトを 84% 減らす（Anthropic の社内実測、2025-10）。

## 推測

- LLM の allow は意見に過ぎず、deny か「人へ defer」に限るのが、研究と整合する（研究者の推測）。
- bash の不明な形の 12% も、中身が読めない wrapper が多く、判定役に読ませても材料が足りない可能性が高い。

## 決定

1. 導入しない。理由は、効く範囲が約 12% で、費用（モデル呼び出し・遅延・コマンド文面の外部送信・版の追従）に見合わない。
2. 外のフォルダの ask は、決定的な規則（パスの危険度で allow / ask / deny）で減らす。方針は [permission-system の設定](../../spec/agent-config-generation.md#permission-system-の設定)。
3. **再検討の条件**: ask の内訳で、自動 allow できる範囲（bash の不明な形）が 30% を超える、または、拡張が外のフォルダの allow の委譲を認めたとき。そのときは、`pi-permission-classifier`（`verdicts: allow-defer` か `allow-deny-defer`、`onError: defer`）を、`reviewer` にソースを精査させてから試験導入する。
4. 「deny と defer だけ」の判定役は、既製品に無い。必要になったら、ADR-0031 の手続き（理由・維持費・撤去条件の記録と、利用者の承認）で自作を検討する。

## 未確認

- `@mzwing/pi-permission-auto-review`・`pi-permission-ai-guard` のソースと、外のフォルダの扱い。GitHub の issue。
- 外のフォルダの判定に特化した精度データ。
- 候補の実機での遅延・費用。

## 追記: 土台の是非と、説明の試験導入（2026-11-15）

利用者の前提が変わった: 想定した関門（`chezmoi apply`・`git flow finish` など）を除く ask は、人がほぼ判断できない。そこで、AI の説明を足す案を見直した。

- **土台は `@gotgenes/pi-permission-system` v42 のまま**。独立型の候補（`@zhushanwen/pi-permission`・`pi-verdict`・`pi-bouncer`・`auto-permission-system`・`@hank-warren/pi-auto-permissions`）と、ほかの 4 件（`@aliou/pi-guardrails`・`@pi-kit/permissions`・`@thurstonsand/pi-permissions`・`pi-permission-modes`）は、「AI は deny か人へ渡すだけ（コードで強制）」と「画面に説明を出す」の両方を満たさない。子の ask の転送とタイムアウト拒否を確認できたのも、この拡張だけ。移行費は大: 試験の判定表が拡張の内部モジュール 9 個を直接 import している（`test/agents/pi_stock/permission_check.mjs`）、約 420 行の規則は後勝ちの順序に依存、`commandEffects` 相当が移行先に無い、離席運用（5 分で拒否）と審査ログの形式に依存。
- **`pi-permission-ai-guard` は見送り**（`reviewer` の監査が BLOCK）。障害が続くと circuit breaker の既定で ask が自動 deny になる、`Ctrl+Alt+G` の `lenient` で defer が allow に変わる（人の関門が人に届かない。無効化の設定キーが無い）、cache が別の背景の allow を再利用する、JSON の `"password":` 形式が伏せ字化されず外部へ送られる。allow をコードで禁じられないことが、人の関門を守る要件と合わない。
- **`pi-permission-explain@0.1.1` を試験導入**（利用者の決定）。利用者が `Ctrl+E` を押したときだけ、モデルが 1 文（140 字以内）で説明を、画面上のウィジェットに出す。ソース 402 行を読んだ事実（`reviewer` の監査でも確認）: 依存なし・独自の通信実装なし（押下したときだけ、pi のモデル API 経由で外部へ送る）・ファイル書き込みなし（設定の読み取りだけ）・`registerAuthorizer` も `tool_call` フックもイベントの書き換えも無い（判定に影響する経路が無い。これは現在の実装の性質で、プロセスの権限隔離ではない）。`permissions:ui_prompt` と `permissions:decision` のイベントだけを使い、v42 のイベントの形（`requestId`・`surface`・`value`・`request`・`forwarding.requesterAgentName`）と一致する。pi 1.5.2 に `ctx.ui.onTerminalInput`・`modelRegistry.complete`・`hasConfiguredAuth` がある。
- **受容した限界**: ① 押さないと見えない。② 説明は英語で、「1 文・140 字以内」はプロンプトでの要求に過ぎず、出力は強制されない。プロンプトは固定で、変えられない。③ 説明の材料は、コマンドや対象の文字列だけ（伏せ字化なし）が、既定ではセッションのモデルの提供元へ送られる。設定で軽いモデル（`github-copilot/claude-haiku-5.5`）を指定した。ただし、見つからない・認証が無いときは、警告してセッションのモデルへ戻る（送り先と費用が変わる）。④ コマンドに注入された文が、説明を誤らせうる。説明は「安全」と断定しない指示だが、強制ではない。人は、承認画面の生のコマンドを見る。⑤ 研究では、説明は判断の正確さを上げず、誤りでも受け入れやすくする結果が優勢（Bansal 2021、Buçinca 2021）。⑥ 0.1.x の個人開発。
- **使い方の注意（`reviewer` の MAJOR。未回答の時計）**: `Ctrl+E` は、承認ダイアログへの入力を横取りする。このため、`Ctrl+E` だけを押して説明を読んでいても、ダイアログの「未回答」の時計（既定 5 分）が止まらず、表示から 5 分で拒否される。**先に `Ctrl+O`（生の要求を展開する、判断しない操作）を押して時計を止めてから、`Ctrl+E` を押す**。`promptTimeoutMs` の無効化は、離席時の拒否を失うので勧めない。恒久対応は上流への依頼（説明の操作でも在席を認識する）。
- **設定の注意**: `key` を `y` や `enter` のような単独キーに変えない。Kitty の repeat が、承認ダイアログに届き、承認になる恐れがある（現設定の `Ctrl+E` では起きない）。説明の呼び出しに固有の期限・中断が無い（応答が終わらない間は、その ask の説明を再試行できない。承認と拒否は操作できる）。
- **確かめること**: 実機で `Ctrl+E` が効くか。説明が判断の助けになるか。ask が出た後、説明を押す前に答えてしまわないか。
- **撤去の条件**: 説明が助けにならない、または `registerAnnotator`（#654）が出て、画面内に常時表示する形に移れる。撤去は、`pi-stock-packages` の 1 行と、`extensions/permission-explain/config.json` の削除。
- **次の候補**: 明らかな誤りの自動 deny は、`@gotgenes/pi-permission-model-judge`（deny か defer だけ）を雛形にした判定役の自作を検討する（ADR-0031 の手続きと承認が要る）。上流の #654 には、常時表示の需要を書き込む。
