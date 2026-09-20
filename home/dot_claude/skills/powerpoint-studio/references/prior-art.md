# Prior Art and Design Choices

調査日: 2026-09-11

## Adopted

- **PptxGenJS**: 編集可能なネイティブ要素を座標で制御できる。
  <https://github.com/gitbrent/PptxGenJS>
  - `fit: shrink/resize` は生成直後に必ず再レイアウトされるとは限らないため、
    事前の文字予算とレンダリング検査を優先する。
  - 既存 PPTX の slide copy や image placeholder を含むテンプレート編集は主用途ではない。
- **Letta slides skill / OpenAI-derived office helpers**: overlap、out-of-bounds、
  image sizing、text sizing、render、font substitution の決定論的検査。
  Apache-2.0。<https://github.com/letta-ai/skills/tree/main/tools/slides>
- **PPTMaker-skill**: deck JSON をプレビューと PPTX の単一ソースにする考え、
  archetype と template の分離。
  <https://github.com/Mr-Q526/PPTMaker-skill>
- **guizang-ppt-skill**: visual rhythm、layout catalog、screenshot framing、
  speaker-note planning。
  <https://github.com/op7418/guizang-ppt-skill>
- **python-pptx**: 既存テンプレートの master / layout / placeholder を保持する経路。
  <https://github.com/scanny/python-pptx>
- **Graphviz / Mermaid / PlantUML / D2**: 決定論的な図の生成。PPTX では SVG/PNG として配置。
  D2 のように viewBox、フォント、画像の data URI 化を明示する実装を参考にする。
- **Vega-Lite / matplotlib / Plotly**: 再現可能なデータ可視化。
- **PPTAgent / PPTEval**: content、design、coherence を分離して評価し、
  生成と評価を閉ループ化する。
  <https://arxiv.org/abs/2501.03936>
- **UniPPTBench / UniPPTEval**: 入力形式ごとの要求充足と text-visual alignment を
  一般的な見栄えとは別に評価する。
  <https://arxiv.org/abs/2605.17356>
- **SlidesGen-Bench**: source grounding、visual rhythm、usability、editability を
  人手評価と校正する考えを採用する。
  <https://github.com/YunqiaoYang/SlidesGen-Bench>
- **PresentBench**: 漠然とした美観評価ではなく、検証可能な細粒度 rubric を使う。
  <https://presentbench.github.io/>

## Rejected as a default

- 任意 HTML をスクリーンショット化して全ページを貼る: 編集性とアクセシビリティを失う。
- 生成画像へ文字、数値、軸、システム図を任せる: 文字破綻と意味の誤りを検出しにくい。
- 小さい文字へ縮める自動 fit: テンプレートへ収まっても読めない。
- テキスト量だけを見た品質評価: 視覚の破綻、図の誤読、物語の弱さを検出できない。
- 単一スタイルの固定テンプレート: 内容と視覚表現が一致しない。

## Original additions

- deck plan と最終 PPTX の対応検証
- content slide の meaningful visual gate
- raster image の実表示 PPI 検査
- placeholder 残存検出
- text fit の保守的推定
- montage + full-size + factual integrity の三段レビュー
- actionable finding がゼロになるまでの収束条件
