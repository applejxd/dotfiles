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
