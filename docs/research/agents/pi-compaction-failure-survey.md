# 圧縮の失敗の調査（公式の報告・変更履歴・セッション記録）

- **日付**: 2026-11-02
- **対象**: pi 1.4.0（2026-10-21）。モデル `github-copilot/claude-sonnet-5.5`（context 1M・出力上限 128K。`pi --list-models` の表示）
- **状態**: **原因は未確定**。失敗の文言をセッションに残す観測を足す（末尾の「次」）
- **結論**: 利用者は「画面にエラーや警告が出る」失敗を感じているが、**セッションの記録には成功した圧縮しか残らず、文言が取れない**。公式の既知の不具合のうち、1.4.0 で直ったものが多い。残る候補は「大きな要求の一時的な失敗」「中断（Esc）」「モデル・認証の条件」で、記録がないので判別できない

## 問い

- 圧縮（`/compact` と自動）で「失敗が続く」のは、何が原因か
- 自作の圧縮（`session_before_compact`）が既定の圧縮に落ちた理由は、残っているか

## 実測した事実（セッションの記録）

対象は、2026-10-30 に始めたこの会話のセッション 1 本（約 67 MB・7,846 行）。

| 項目 | 値 |
| --- | --- |
| 圧縮の記録（`type: "compaction"`） | 11 回。**すべて成功** |
| 作った経路 | 11 回とも自作の圧縮（`fromHook: true`） |
| 区切り | 11 回とも、ターンの途中で切れる分割ターン（要約に `Turn Context (split turn)`） |
| 圧縮前のトークン数 | 約 46 万〜83 万 |
| 要約の長さ | 約 2.7 万〜4.4 万字 |
| `errorMessage` | `Operation aborted` の 17 件だけ（中断。利用者の Esc とみられる = 推測）。`stopReason: "error"` は 0 件 |
| 失敗の文言（`Compaction failed`・`Auto-compaction failed`・`既定の圧縮にする`） | **記録に無い**（検索で一致したのは docs・変更履歴の引用だけ） |

- 直近の圧縮: 中断から完了まで 3 分 40 秒（利用者の操作時間を含む）
- 範囲の注意: 他のセッションの記録は、一致を目視した範囲だけ

## 実測した事実（pi 1.4.0 とこのリポジトリ）

- 本体の経路: 失敗や中断は、画面に `Compaction failed: …` / `Auto-compaction failed: …` と出る。セッションには**残らない**（成功した圧縮だけが `type: "compaction"` になる）
- 本体のイベント `session_compact_failed`: 理由（`manual`・`threshold`・`overflow`）・エラー文・中断か・再試行か・拡張由来かを、拡張へ渡す。**拡張が登録しないと、どこにも残らない**
- 自作の圧縮（`index.ts` の `session_before_compact`）: `compact()` が失敗したら、警告通知（`圧縮の指示を付けられなかったので既定の圧縮にする: <理由>`）と標準エラーに理由を出して、既定の圧縮に落とす。**理由は画面と標準エラーにしか残らなかった**
- 1.4.0 の変更履歴（修正済みのもの）:
  - 要約の出力上限（`reserveTokens` の 0.8 倍）を撤廃。要約はモデルの出力上限まで使える（#9512・#9075）
  - 分割ターンの先頭を要約するとき、`/compact <instructions>` の指示が無視される問題（#11058）
  - Copilot で、大きな要求本文が HTTP 413 になる問題（#11016）。圧縮して再試行する
  - 1.3.0: `The service is temporarily unavailable` で再試行が起きず、圧縮が 1 回目で失敗する問題（#10965）
- 自作の再試行: 「要約が出力上限で切れたら `reserveTokens` を倍にして 1 回やり直す」は、**1.4.0 では効かない**（`createSummarizationOptions` が `maxTokens` を渡さない）。害は無い

## 公式の報告（取得 2026-11-02。検索語は下）

| 報告 | 症状 | 要点 |
| --- | --- | --- |
| [#11176](https://github.com/earendil-works/pi/issues/11176) | `Compaction failed: Summarization failed: generation hit the token cap …`（1.1M の窓の 24%） | 原因は要約の出力上限と、思考が上限を食うこと。回避は思考を下げて `/compact`。上限の撤廃は #11036（1.3.0 の後）。ラベルは no-action |
| [#11207](https://github.com/earendil-works/pi/issues/11207) | 同じ文言（pi 1.3.0・思考 `max`・出力上限 13,107） | 要約が、セッションの思考レベルを引き継ぐ。回避は `/thinking off` → `/compact` → 元に戻す。ラベルは no-action |
| [#6768](https://github.com/earendil-works/pi/issues/6768)・[#7579](https://github.com/earendil-works/pi/issues/7579) | Copilot の Enterprise で `421 Misdirected Request` | 要約が、解決済みの接続先（baseUrl）を落とす。本体で修正済み（変更履歴）。自作の圧縮は baseUrl を反映している |
| [#3438](https://github.com/earendil-works/pi/issues/3438) | Copilot の `claude-opus-4.7` で、思考 `medium` のとき 400（`effort "high" is not supported`） | **状態は未確認**（要点だけ読んだ） |
| [#2567](https://github.com/earendil-works/pi/issues/2567) | Copilot の `gpt-5-mini` で 400（`'none' is not supported`） | **状態は未確認** |

- 反例: #11176・#11207 の回避策（思考を下げる・上限を上げる）は、1.3.0 以前の原因に対するもの。1.4.0 では原因そのものが撤廃されたので、同じ症状は出にくいはず（推測）
- 検索語: 「earendil-works pi coding agent compaction failed github copilot error」「pi-coding-agent "Auto-compaction failed" OR "Compaction failed" issue 1.4」

## 候補（すべて推測。記録が無いので判別できない）

| 候補 | 根拠 | 判別に要るもの |
| --- | --- | --- |
| 大きな要求の一時的な失敗（413・過負荷・切断・タイムアウト） | 入力が約 46 万〜83 万トークンで、要約に数分かかる。本体の再試行は 3 回まで | エラー文の HTTP 状態 |
| 中断（Esc）の後の警告 | `Operation aborted` が 17 件。圧縮の直前に中断している | `aborted: true` の記録 |
| モデル・認証の条件の 400・421 | 公式の報告に前例。環境ごとに違う | エラー文 |
| 要約が出力上限で切れる | 1.4.0 では上限が 128K で、要約は 4 万字前後（トークン数は未計測）。**起きにくい** | `token cap` の文言 |
| 自作の hook 自身の例外 | `fileOps` の処理が、保護の外にある | 画面の `Extension error` |

## 限界と未確認

- 失敗の文言は、利用者の画面にだけあった。**今回は取得できていない**
- 実モデルで、約 70 万トークンの要約を再現していない（費用が大きい）
- 本体の「分割ターンの前半の要約には、指示が入らない」（自作の圧縮の仕様の記述）が、1.4.0 の #11058 の修正で変わったかは**未確認**
- #3438・#2567 の現在の状態は未確認

## 次

- **観測を足す**: 失敗した圧縮の理由を、セッションの `custom` エントリとして残す（`harness-compact-fallback` = 自作の圧縮が既定に落ちたとき、`harness-compact-failed` = 本体の経路が失敗・中断したとき）。入ったあとで失敗したら、セッションの記録を読めば原因が分かる
- 判別できたら、候補に合わせて直す。費用の大きい再試行を、原因が分からないまま足さない
- 陳腐化した `reserveTokens` の再試行の撤去と、分割ターンの指示の仕様の確認は、記録が溜まってから判断する
