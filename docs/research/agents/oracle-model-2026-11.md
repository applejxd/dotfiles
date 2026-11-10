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
