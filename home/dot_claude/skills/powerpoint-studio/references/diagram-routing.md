# Diagram Rendering Decision

図の編集可能性より、意味とレイアウトの健全性を優先する。複雑な図をPowerPoint
ネイティブ図形で無理に組むと、矢印、分岐、ループ、ラベルが崩れやすい。

## Source hierarchy

作図を始める前に、次の順で既存図を探す。

1. 公式ドキュメント、標準仕様、原著論文、元OSSの図
2. 信頼できる一次資料に付属する図
3. Graphviz、D2、Mermaid、PlantUMLによる決定論的な自作図
4. 単純な場合だけPowerPointネイティブ図形

公式図が次を満たすなら、自作より優先する。

- 説明したい概念と意味が一致する
- 投影サイズでラベルが読める
- 出典、ライセンス、または引用としての利用条件を記録できる
- 不要なマーケティング表現や別の前提を含まない
- クロップ・注釈によって原図の意味を変えない

公式図が概念の一部だけを説明する場合は、公式図を引用し、プロジェクト固有部分だけを
ネイティブ要素または外部作図で補うhybridを使う。

## Use native PowerPoint shapes

原則として次をすべて満たす場合。

- ノード6個以下
- エッジ7本以下
- 分岐点1個以下
- ループ、入れ子サブグラフ、swimlaneがない
- エッジ交差がない
- ラベルが短い
- PowerPoint上で頻繁に要素を編集する必要がある

適するもの:

- 3〜5段階の直線フロー
- 単純な比較
- タイムライン
- 1つの判断ゲート
- KPIや概念の関係図

## Use a dedicated deterministic diagram tool

次のどれかがある場合は、Graphviz、D2、Mermaid、PlantUMLなどでSVG/PNGを生成する。

- ノード7個超またはエッジ8本超
- 複数の分岐、ループ、fan-out / fan-in
- 入れ子サブグラフ、cluster、swimlane
- 自動エッジルーティングが必要
- 長いラベルが複数ある
- トポロジーの正確さが重要
- ネイティブ作図のレンダリングで1度でも交差・崩れが発生した

生成AI画像にトポロジーや文字を描かせない。ソースから決定論的に生成する。

## Hybrid

中程度の複雑さでは、図本体をSVG/PNG、タイトル・結論・注釈をネイティブ要素にする。
外部図は一枚の主画像として十分に大きく配置し、細かなサムネイルにしない。

## Complexity score

```bash
uv run scripts/choose_diagram_renderer.py diagram-spec.json
```

- 0〜3: native
- 4〜6: hybrid
- 7以上: external

スコアは判断補助であり、過去に崩れた図はスコアに関係なくexternalへ切り替える。

## External diagram delivery

- `.dot`, `.d2`, `.mmd`, `.puml`などのソースを残す。
- SVGを優先する。互換性問題があれば幅2400px以上のPNGを使う。
- deckと同じfont・surface/base/main/accent paletteを使う。
- 外部画像参照を埋め込み、viewBoxとラベル境界を検査する。
- PPTX/PDF変換後の原寸レンダーで、文字、矢印、cluster境界を確認する。
- 画像にはalt textを付ける。
- 公式図は `quoted-official`、再描画は `adapted`、完全自作は `original` とsource
  ledgerで区別する。

## Process topology: main path, exceptions, and returns

プロセス図は、ノードの見た目より先に経路の役割を分ける。

1. **入口を一つ示す。** `START`、入力、triggerのいずれかを左端または上端に置く。
2. **主経路を一直線にする。** 通常ケースは左→右または上→下の一方向へ進める。
3. **例外分岐を主経路と直交させる。** human確認、fallback、errorは上下または左右へ外す。
4. **戻り線は外周を通す。** 途中ノード、通常矢印、ラベルの間を横切って戻さない。
5. **分岐ラベルはdecisionの近くへ置く。** 線の交差点、ノード境界、別edgeの近くへ置かない。
6. **合流先を明示する。** 複数線を空白で合流させず、node、bus、route pointを使う。
7. **終了を一つ以上示す。** `END`、response、persistなど、図をどこで読み終えるかを示す。

通常経路・例外経路・戻り経路は、色だけに依存せず位置でも区別する。たとえば
主経路を中央、human loopを下、timeout/fallbackをさらに下へ置く。

Graphvizの自動配置で戻り線が主経路を横切る場合は、次の順で直す。

- edge labelを自動配置せず、`shape=plain`のラベルnodeを固定する。
- 不可視route nodeを図の外周へ置き、戻り線のbendを固定する。
- `dot`のrank制約で無理なら、`neato -n2`と固定`pos`へ切り替える。
- 固定`pos`はノードの**中心**であり、文字幅やノード幅を予約しない。実際の幅・高さに
  clearanceを加えてから座標を決める。フォントだけを拡大しない。
- `neato -n2`もエッジを自動配線する。`splines=ortho`や`pin=true`は衝突回避の保証ではない。
  stderrの `bounding boxes ... touch`、`falling back to straight line edges`、
  edge-label非対応警告が出たら生成成功と扱わない。
- それでも不安定なら、`references/diagram-geometry.md` の検査付き座標指定SVGへ切り替える。
  ルーティングの劣化をPNG化で隠さず、座標・文字計測・画像の生成履歴を保持する。

図を作る前に、次のspecを用意して検査する。

```json
{
  "entry": "start",
  "nodes": ["start", "decision", "continue", "human"],
  "main_path": ["start", "decision", "continue"],
  "edges": [
    {"from": "start", "to": "decision", "kind": "main"},
    {"from": "decision", "to": "continue", "kind": "main", "label": "明確"},
    {"from": "decision", "to": "human", "kind": "branch", "label": "曖昧"},
    {"from": "human", "to": "decision", "kind": "return", "label": "再開", "route": "outside"}
  ]
}
```

```bash
uv run scripts/audit_diagram_topology.py diagram-spec.json
```

この監査は入口、主経路、分岐ラベル、到達可能性、戻り線の外周指定を確認する。
`route: outside` は設計上の宣言だけで、実画像の線の場所は検証しない。
また、矢印ラベルは独立した意味上のノードにしない。たとえば「NO、そのまま戻る」を
処理箱にすると、存在しない処理を追加したように読まれる。分岐条件は線の脇に置く。
長い帰還線は外周の専用レーンへ通し、合流は実ノードか明示したjunctionに接続する。
経路が重なるからといって全エッジを重なり検査の対象外にしない。

レンダリング後は別途、矢印長、arrowhead、ラベルとの8px以上のclearance、
ノード間隔、交差を最終PDFの1600px以上の原寸PNGで目視する。
ソース画像だけでなく、スライドへのcontain配置後の文字サイズと縦横両方の制約を確認する。

`deck-plan.json` の `meta.diagram_specs` にspecを列挙すると、
`validate_deck.py` がstrict QAの一部としてすべて検査する。
対応する実座標は `meta.diagram_layouts` にすべて列挙する。一部ページだけを登録し、
他の同種図を未検査にしない。宣言監査と実座標監査の使い分けは
`references/diagram-geometry.md` を参照する。
