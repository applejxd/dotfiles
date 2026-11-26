# 実物の検証と再発防止の汎用スキル

pstack の手法を参考にした 5 本を、chezmoi の一つの変更として配る。Pi には独立した Agent Skills として登録し、振り分け用の親スキルは作らない。
この文書は配布候補の仕様であり、利用端末への適用済みを意味しない。公式プラグインや実行コードは組み込まない。

## 入口と使い分け

自然文の依頼に合うスキルを Pi が選ぶ。固定の合言葉は要らない。明示するなら `/skill:<名前>` を使う。

| 用途 | スキル | 選ぶ場面 |
| --- | --- | --- |
| 利用者の操作を確かめる | [`verify-behavior`](../../home/dot_agents/skills/verify-behavior/SKILL.md) | 実画面・CLI・出力の確認、検証手順の整備 |
| 差分が壊し得る範囲を確かめる | [`blast-radius`](../../home/dot_agents/skills/blast-radius/SKILL.md) | 互換性や他の経路への影響を調べる |
| 繰り返す失敗を防ぐ | [`prevent-repeat`](../../home/dot_agents/skills/prevent-repeat/SKILL.md) | 注意だけでは同じ原因のミスが再発する |
| 問題を言語化する | [`reframe`](../../home/dot_agents/skills/reframe/SKILL.md) | 同じ説明が複数の問題を指し得る |
| 操作順を検証する | [`verify-state`](../../home/dot_agents/skills/verify-state/SKILL.md) | 再試行や承認の順序で約束が破れ得る |

既存スキルと迷ったときは、依頼の成果物で見分ける。

- 保存後の画面を確かめるなら `verify-behavior`、保存と取り消しの順序を変えて破れる条件を確かめるなら `verify-state` を使う。
- 古い利用者への波及を調べるだけなら `blast-radius` を使う。範囲が互換性だけでも、指摘・修正・再レビューを繰り返すなら既存の `review-loop` を使う。
- 分かっているミスを仕組みで止めるなら `prevent-repeat`、セッション記録から繰り返す不満を洗い出すなら既存の `friction-review` を使う。
- 何を調べるかを決めるなら `reframe` を使う。文献・原典を集めるなら、配布されている環境では既存の `imozuru` を使う。

## 実行と境界

- Pi が見る名前と説明からモデルが本文を選ぶ。スキルを読むこと自体は、検査の実行や合格を保証しない。
- 個々のリポジトリの指示と既存の検査を優先する。全リポジトリへの `AGENTS.md` や専用スキルの生成は前提にしない。
- 通常の誤字修正や既存の単体テストで十分な変更には、実物検証や状態モデルを足さない。
- イベントの順序を調べるときは、少数なら実コードのテストを使う。TLA+ などの基盤や外部依存は同梱しない。
- 新しい依存、外部書き込み、公開・承認、端末への配布をこの手順だけで許可しない。実行できない検証は未確認とする。

汎用の手順は `home/dot_agents/skills/` に置き、配布先の `~/.agents/skills/` を Pi の標準検出に任せる。
操作コマンドや合格条件は対象リポジトリ側に残す。候補間の初回測定と既存スキルとの境界の点検は[発火測定の記録](../research/agents/pstack-skill-trigger-2026-11.md)に記す。
参考にしたのは [pstack 0.15.48 の設計](https://github.com/cursor/plugins/tree/9e278fe4d4ecd8bfe98b1b79bf4be662efb338cc/pstack) である。`poteto-mode`、モデル設定、対抗レビュー、自動 push・マージは含めない。
