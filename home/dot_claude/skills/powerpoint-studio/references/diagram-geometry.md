# Diagram Geometry: measure, route, render, verify

## Why external diagrams still break

外部ツールを使っても、長い識別子、フォント変更、固定座標、エッジラベルが組み合わさると
配置は壊れる。Graphvizは終了コード0のまま直交配線を直線へフォールバックする場合がある。
画像を一枚にしてPPTXへ貼ると、通常のPPTX重なり検査には内部の衝突が見えない。

したがって、意味・実座標・最終レンダーの三つを分けて検査する。

| 段階 | 検査対象 | これだけでは分からないこと |
| --- | --- | --- |
| `audit_diagram_topology.py` | 入口、分岐条件、到達可能性、主経路 | 実際の線の位置、文字の幅 |
| `audit_diagram_geometry.py` | 文字計測、箱・線・ラベル・矢印の衝突、配置後の文字寸法 | 図の意味、読み順の自然さ、PDF変換の差 |
| 最終PDFの原寸レビュー | 切れ、余白、矢印の追跡、読解しやすさ | 再生成時の再現性 |

## Layout first

1. 原典から意味上のノードと分岐だけを取り出す。説明ラベルを架空の処理箱へ置き換えない。
2. 最終スライド上で使える幅・高さ、文字の最小pt、書体を先に決める。
3. 実フォントで最も長い行を測り、左右paddingを加えてノード幅を決める。
   高さは各行の実測境界、行間、上下paddingから決める。
4. 主経路のノード、エッジ、条件ラベルのための空間を**別々に**確保する。
   ラベルを線の中央へ置いたり、背景で線を消してごまかしたりしない。
5. 戻り線に独立したレーンを与える。ノードの境界に接続し、最後の線分に
   矢印の長さ以上の余裕を残す。無関係な箱やラベルを横断させない。
6. 収まらなければ箱を拡張、説明を短縮、図を分割する。文字縮小と図全体の縮小は最後の手段。

フォントを変えたら、その後の座標検査と画像生成もやり直す。単に`fontsize`だけを
上げて古い座標、PNG、QAを流用しない。

## Measured SVG path

不安定な自動配線の代わりに、`examples/diagram-layout.json` を出発点とする。
`*.layout.json`の一つの実座標から、文字計測、SVG生成、幾何検査を行う。
座標は左上原点、edge pointsは直交折れ線、node boxは`[x, y, width, height]`。
`font_path`は実在する使用書体のファイルを指定する。別書体への黙った代替はしない。
`padding`はノードだけでなくラベルの予約矩形にも適用される。背景を描かないラベルでも、
文字の実測高さに上下paddingを加えた高さを確保する。

```bash
uv run scripts/render_diagram.py process.layout.json \
  --output process.svg --report process.geometry.json
uv run scripts/audit_diagram_geometry.py process.layout.json
```

検査不合格時は非ゼロ終了し、SVGを正常な成果物として更新しない。
背景を塗った大きな箱で衝突を隠す、全エッジをallowlistにする、検査閾値を
下げて通す修正ではなく、線や文字のための空間を増やす。

PNGが必要なら検査済みSVGから既存の`sharp`等で2400px以上へラスタライズする。
SVGとPNGの縦横比を一致させ、再生成コマンドをデッキのbuildへ含める。
引用画像には無理にこのJSON形式を適用せず、出典・クロップ・読める配置を検査する。

### Scale and clearance

contain配置では、`scale_pt = min(72 * width_inches / width,
72 * height_inches / height)`。実際の文字は`font_size * scale_pt`となる。
横幅だけで判定すると、縦方向の制限で縮んだ図を見逃す。
`placement.min_font_pt`はデッキの注釈下限以上にする。
図中文字の各役割を、本文・注釈・タイトルの体系へ合わせる。

clearanceはSVGの座標単位で指定する。最終PNGで8px以上を確保するには、
最終PNGの拡大率を逆算して設定する。padding、線幅、矢印の幅も含めて余裕を取る。
固定値8をどんな縮尺にもそのまま使わない。

## Deck gate and provenance

`meta.diagram_specs`は意味の検査用に残し、作図した全ページの実座標を
`meta.diagram_layouts`へ登録する。

```json
{
  "diagram_specs": ["assets/process.spec.json"],
  "diagram_layouts": [{
    "path": "assets/process.layout.json",
    "image": "assets/process.png",
    "slide": 3,
    "shape": "process-diagram",
    "provenance": "assets/process.provenance.json"
  }]
}
```

`shape`はPPTXの画像objectName。QAは画像の埋め込みバイト列、実配置寸法、
レイアウトの書体を照合する。画像生成時のprovenanceも保存し、レイアウトだけを
直して旧PNGを納品する事故を防ぐ。フィールドは実装のCLIとexampleに従う。
成功後のレポートにはレイアウトと画像のSHA-256を残す。

provenanceは`layout_sha256`、`svg_sha256`、`image_sha256`、
`renderer_sha256`の4キーを持つ。最後の値は使用した`diagram_geometry.py`のSHA-256。
SVGはPNGと同stemの隣接ファイルへ置き、レンダラーのバイト列を最適化・整形せず保持する。
監査は現レイアウトから再生成したSVGとも照合する。PNGのラスタライズに成功した後だけ
receiptを保存する。これは生成履歴の検査であり、最終PDFの目視を代替するものではない。

## Final review

最終PPTXをPDFへ変換し、修正箇所の前後ページも含めて1600px以上で描画する。
入口から終了まで各エッジを指で追うつもりで読む。
YES/NOの対応、帰還先、枝分かれ、空白での合流、矢印の向き、線上の文字を確認する。
モンタージュは全体構成用であり、図内部の合格判定には使わない。

図の座標やフォントを一度でも変えた後は、画像、PPTX、PDF、レンダー、QAを
一連で再生成する。古いレポートの「問題なし」を最終版へ引き継がない。
