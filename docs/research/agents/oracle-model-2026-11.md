# oracle のモデルを、親・worker と別系統にするか（2026-11-10 の調査）

観測日: 2026-11-10。依頼: `oracle`（二番目の意見を出す子）を、親・`worker`（Claude Sonnet 5.5）と同じ系統のままにするか、`reviewer`（GPT 6.1 sol）と同じにするか。
調べたのは論文の**要旨**で、本文は読んでいない。ブログ・Reddit は体験談で、重みは低い。

## 問い

二番目の意見・レビューを出す役は、書く側と同じ系統のモデルがよいか、別系統がよいか。

## 根拠

- **同じモデルによる自己点検は、ほとんど効かない。**
  - Huang ほか「Large Language Models Cannot Self-Correct Reasoning Yet」（[arXiv:2310.01798](http://arxiv.org/abs/2310.01798)、2023）: 外部のフィードバックなしの自己修正では、推論は改善しない。
  - Stechly ほか「On the Self-Verification Limitations of Large Language Models on Reasoning and Planning Tasks」（[arXiv:2402.08115](https://arxiv.org/abs/2402.08115)、2024）: GPT-4 の自己批評で性能が大きく落ち、確かな外部の検証者で大きく上がった。
- **評価役は、同じ系統の出力を好む。** Wataoka ほか「Self-Preference Bias in LLM-as-a-Judge」（[arXiv:2410.21819](https://arxiv.org/abs/2410.21819)、2024）: GPT-4 に有意な自己選好。原因は、慣れた（低 perplexity の）文章を好むことらしい。
- **別系統のレビューは、非対称に効く**（1 件の実験）。Xiang ほか「Cross-Model LLM Code Review: Should you use Claude to review Codex or vice versa?」（[arXiv:2607.21656](https://arxiv.org/abs/2607.21656)、2026-07-22、KDD'26 のワークショップ）。LiveCodeBench の 116 問。レビュー役はテストを実行できない。

  | 組み合わせ | 合格率 |
  | --- | --- |
  | Claude が Codex の案を見る | 71.6% → 89.7% |
  | Codex の自己レビュー | 71.6% → 84.5% |
  | Codex が Claude の案を見る | 91.4% → 82.8%（悪化。p=.046） |
  | Claude の自己レビュー | 91.4%（変化なし） |

  著者の結論は「有用な組み合わせは非対称。Claude が Codex を見るのがよく、逆はよくない」。**見る側が書く側より強いか**が効くと読める。
- 「別系統のレビューが良い」という記事（MindStudio のブログ・Reddit・GitHub の例）は多いが、実験ではなく体験談。

## 解釈と決定

- 親が Sonnet（xhigh）なので、`oracle` が Sonnet だと、自己選好・自己点検の限界の両方に当たる懸念がある。→ **`oracle` を、親と別系統の GPT 6.1 sol の high にする**（`reviewer` と同じ）。設定は単純になる。
- 費用: `oracle` は親の会話を引き継ぐ（`context: fork`）。別モデルでは読み込みの再利用が効かず、少し高い。
- **懸念**: 今の `reviewer` は、書く側が Claude、見る側が GPT で、実験の悪化した向きと同じ。実験は競技プログラミング形式で、私たちの作業（設定・docs・設計の監査）と性質が違う。この向きが私たちの作業で問題ないかは、下の実験で確かめる。

## 未確認

- 実験の本文（モデルの版・設定）。要旨だけを読んだ。
- GPT 6.1 sol が Sonnet 5.5 より強いか（私たちの作業で）。

## 実験: reviewer の向き（Claude が書き、別系統が見る）は、私たちの作業で問題ないか（2026-11-10）

懸念: 上の実験（Xiang 2026-07）では、Codex が Claude の案を見ると悪化した。今の `reviewer`（GPT 6.1 sol の high）は、Claude（Sonnet 5.5）が書いた変更を見る向きで、同じ。

**方法**: このリポジトリの実際のコードに、欠陥を埋めた差分を 7 件用意し（書いたのは Claude）、同じ依頼文で `reviewer` を 2 つのモデルで動かした: GPT 6.1 sol の high と、Sonnet 5.5 の high（`subagent` の `model` 指定。設定は変えない）。
各ケース 1 回ずつ（n=7）。読み取り専用で、差分と意図を読んで監査する。データ（差分・意図・実行の対応）は `.tmp/keep/ab-reviewer/`。

| ケース | 埋めた欠陥 | sol (high) | Sonnet 5.5 (high) |
| --- | --- | --- | --- |
| A | 利用者の値を上書きする（値の比較が抜けた） | MAJOR で発見 | BLOCKER で発見 |
| B | `globalConcurrencyLimit: 0` は無効（読み込みが失敗する） | MAJOR で発見 | BLOCKER で発見（実装の行まで追った） |
| C | 入れ子の `permission` は agent 定義が無効 | BLOCKER で発見 | BLOCKER で発見 |
| D | 条件が反転（T1 に入る試験だけを省く） | MAJOR で発見 | BLOCKER で発見（印の誤記録まで説明） |
| E | docs が実装と食い違う（16 と 8） | **MINOR で発見**（判定は「注意つき OK」） | BLOCKER で発見 |
| F | なし（正しい整理） | 指摘なし（正解） | 指摘なし（正解） |
| G | **試験の更新漏れ**（対照のつもりだったが、実際は欠陥あり） | MAJOR で発見 | MAJOR で発見（docs のずれも指摘） |

- **欠陥の発見（6 件）**: sol は 6 件すべてを発見したが、E は MINOR（重大でない）。Sonnet は 6 件すべてを MAJOR 以上で発見した。
- **誤指摘（欠陥なしの対照）**: F の 1 件で、どちらも 0 件。
- **傾向**: 悪化の兆しは見えない。sol は簡潔で、重大度をやや低く付ける（E）。Sonnet は二次的な指摘が多く、重大度をやや高く付ける。差は誤差の範囲。

**限界**:

- n=7 で、各 1 回。
- 欠陥なしの対照が F の 1 件しかない（G は私の作り方の不備で、欠陥を含んでいた）。論文の悪化の仕組み（見る側が余計な「修正」を入れる）は、誤指摘の多さで測るべきで、この実験ではほとんど測れていない。
- C は、リポジトリの記録（`docs/research/…`・試験の注記）が手がかりとして読めてしまい、どちらのモデルも、それを引いた。独立した知識の比較ではない。
- 論文は、レビュー役が案を**書き直す**設定。ここは**指摘だけ**を出す設定。

**結論**: `reviewer` は GPT 6.1 sol のままにする。悪化の兆しはなく、別系統の目は保てる。誤指摘の多さを測るには、欠陥なしの差分を増やした追加の実験が要る。
