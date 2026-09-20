# Deck Plan Schema

PowerPoint 実装前に JSON で作る。構成の問題を座標調整へ持ち込まないための契約である。

```json
{
  "meta": {
    "title": "Deck title",
    "audience": "Who decides or learns",
    "audience_assumptions": {
      "known": ["Python", "AI coding assistants"],
      "explain": ["RAG", "agent state", "evaluation"],
      "omit": ["framework installation details"]
    },
    "presenter": {
      "name": "optional; never infer",
      "affiliation": "optional; never infer"
    },
    "duration_minutes": 15,
    "session_duration_minutes": 18,
    "buffer_minutes": 3,
    "objective": "Decision or behavior sought",
    "message_policy": {
      "enabled": true,
      "focused_max_units": 5,
      "overview_max_units": 7
    },
    "source_review": {
      "enabled": true,
      "review_label": "原典を実装順にたどる選択的レビュー",
      "minimum_direct_slide_ratio": 0.6,
      "max_sections_per_slide": 5,
      "works": [
        {
          "id": "source-a",
          "title": "Source A",
          "sections": ["1-3", "4-6"],
          "minimum_review_slides": 2
        }
      ],
      "omissions": []
    },
    "chrome_policy": {
      "enabled": true,
      "header": "none",
      "footer": "none",
      "page_numbers": "required"
    },
    "typography_policy": {
      "enabled": true,
      "primary_font": "Noto Sans CJK JP",
      "mono_font": "Noto Sans Mono CJK JP",
      "minimum_font_size": 11,
      "deck_title_range": [40, 56],
      "slide_title_range": [25, 34],
      "body_range": [14, 22],
      "caption_range": [11, 13.5],
      "page_number_range": [10, 12],
      "max_size_steps_per_slide": 6,
      "title_minimum_difference_pt": 5,
      "title_minimum_ratio": 1.2,
      "generated_diagram_apparent_font_range": [10, 18],
      "generated_diagram_sources": [
        {
          "path": "assets/diagrams/architecture.dot",
          "image": "assets/diagrams/architecture.png",
          "placement_width_inches": 10.5,
          "render_dpi": 220
        }
      ]
    },
    "diagram_specs": [
      "assets/diagrams/main-flow.spec.json"
    ],
    "diagram_layouts": [
      {
        "path": "assets/diagrams/main-flow.layout.json",
        "image": "assets/diagrams/main-flow.png",
        "slide": 3,
        "shape": "main-flow-diagram",
        "provenance": "assets/diagrams/main-flow.provenance.json"
      }
    ],
    "layout_checks": [
      {
        "slide": 3,
        "kind": "alignment",
        "shapes": ["comparison-header", "comparison-cell"],
        "axis": "left",
        "tolerance_inches": 0.03
      },
      {
        "slide": 4,
        "kind": "font-size",
        "shapes": ["primary-method-name"],
        "minimum_pt": 14,
        "require_no_autofit": true
      }
    ],
    "template": "optional/path/template.pptx",
    "language": "ja"
  },
  "slides": [
    {
      "id": "s01",
      "role": "hook",
      "title": "結論を述べるタイトル",
      "claim": "このページで観客が理解する一文",
      "message_mode": "focused",
      "detail_policy": "explain",
      "information_units": ["比較対象A", "比較対象B", "判断基準"],
      "reading_goal": "overviewのときだけ、何を認識し何を後回しにするかを書く",
      "source_sections": [
        {"work": "source-a", "sections": ["1-3"]}
      ],
      "review_lens": {
        "builds": "このsectionで具体的に作るもの",
        "why_next": "次のsectionへ進む理由",
        "takeaway": "このsectionから学ぶこと",
        "caveat": "教材固有条件または適用限界"
      },
      "evidence": ["metric: 42%", "source: experiment.csv"],
      "visual": {
        "type": "chart",
        "source": "assets/result.csv",
        "purpose": "差が偶然ではないことを示す"
      },
      "layout": "template-layout-name or composition",
      "speaker_goal": "口頭で補う内容",
      "timing_seconds": 90,
      "optional_cut_seconds": 15,
      "transition": "次ページにつながる理由"
    }
  ]
}
```

## One message and information units

`layout_checks`は確認済みの列整列や主要文字の下限を守る任意の回帰検査。
指定値を他デッキの既定値へ流用せず、そのデッキの読み方に合わせて選ぶ。
同名shapeの全要素が対象となる。詳細は `layout-review.md` を参照する。

`diagram_specs`は経路の意味、`diagram_layouts`は画像内部の実座標を検査する。
固定座標・ループを含む再構成図は両方へ登録し、レイアウトJSONのノードとエッジを
意味上のspecへ対応させる。書式と画像生成履歴は `diagram-geometry.md` を参照する。

- `claim` はページ全体を一文で要約する。独立した結論を列挙しない。
- `message_mode: focused` は一つの因果、比較、手順、判断を詳しく説明する。
- `message_mode: overview` は複数要素の**関係や地図そのもの**を一メッセージとして示す。
- `information_units` は観客がその場で意識的に処理する領域、段階、比較対象を列挙する。
  図形やラベルの個数ではない。
- 初期上限は focused 5個、overview 7個。overviewには `reading_goal` を必須とし、
  「5領域の位置だけ認識し、細かい手法名はリンク先で読む」のように詳細の扱いを示す。
- `detail_policy`:
  - `explain`: その場で意味まで説明する。
  - `recognize`: 名前・位置・関係だけを認識させる。
  - `reference`: 詳細は配布資料、リンク、付録で後から読む。

## Roles

- `hook`: 反差、問題、重要な数値で注意を得る
- `context`: 前提、対象範囲、用語を揃える
- `evidence`: データ、実験、ユーザー観察を示す
- `mechanism`: なぜ起きるか、どう動くかを図解する
- `decision`: 選択肢、トレードオフ、推奨を示す
- `action`: 実行計画、担当、期限を示す
- `close`: 判断、問い、記憶に残す一文で閉じる

## Visual types

`chart`, `diagram`, `screenshot`, `photo`, `table`, `native-shapes`, `none`

`none` は表紙、章扉、短い引用、締めだけで使用できる。本文ページの `none` は失敗。

## Ambiguity checks

- 表紙の比喩が「現在すでに導入済み」なのか「これから導入」なのかを曖昧にしない。
- timeline は Week 0 のような慣例を説明なしで使わず、期間の始点・終点を一意にする。
- pilot、target、illustrative、actual を明示し、仮の数値を実績に見せない。

原典ベースの資料では `meta.source_grounded: true` を指定し、各ページの `evidence`
から `references/source-fidelity.md` の source ledger へ追跡できるようにする。

模式図、指標、チャートには `actual / derived / illustrative / target` の種別を付ける。
`actual` は母数、期間、出典を必須とする。
