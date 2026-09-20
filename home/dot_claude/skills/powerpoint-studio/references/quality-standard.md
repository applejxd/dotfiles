# Quality Standard

## Hard gates

`scripts/validate_deck.py` が非ゼロ終了したデッキは納品しない。

| 項目 | 合格条件 |
| --- | --- |
| Canvas | すべての描画要素がスライド内に収まる |
| Text fit | 推定オーバーフローなし。本文 18pt 未満は明示的例外のみ。テンプレート由来のメタ情報は 9pt を絶対下限とする |
| Overlap | テキスト同士の実面積重複なし。意図的オーバーレイは allowlist に記録 |
| Assets | 壊れた画像なし。主要ラスター画像は表示サイズ換算 140 PPI 以上 |
| Placeholders | `{{...}}`, TODO, lorem ipsum, sample text が残っていない |
| Visual evidence | 本文ページは意味のある chart / diagram / screenshot / photo / table を持つ |
| Fonts | 必須フォントが欠落していない。代替時も CJK と記号を含めて読める |
| Template | 指定テンプレートのページ寸法、マスター、レイアウト、テーマを維持 |
| Render | 全ページを 1600px 以上でレンダリングできる |
| Source fidelity | 原典ベースの主張、引用、図、実装名が source ledger へ追跡可能 |
| Timing | 時間指定時は全ページに時間・話者ノートがあり、合計・チェックポイント・短縮策を検証 |
| Label containment | pill / badge / tag / chip の文字が背景図形の内側に収まる |
| Color system | 新規デッキは surface と base / main / accent を定義し、背景色の種類を制限 |
| Structure | 長い発表はタイトル・目次・最後のまとめを持つ |
| Audience fit | 既知概念、説明する語彙、許容する実装詳細が audience assumptions と一致 |
| Keywords | 重要語、状態、境界、変数が話者ノートだけでなくスライド上にも明記 |
| Presenter metadata | 発表者名・所属を取得して表紙へ表示。未提供時は推測せず例外記録 |
| Diagram routing | 複雑度に適したnative / hybrid / external方式を選び、外部図はソースを保持 |
| Diagram geometry | 作図警告0件。固定座標図の文字・箱・線・ラベル・矢印を同一ソースで検査し、最終配置の文字下限を満たす |
| Layout groups | 宣言した列・行の整列と主要語の文字下限を満たし、対象名の欠落や意図しない自動縮小を見逃さない |
| QA freshness | QA summary の PPTX・plan・source hash が納品物と一致 |

## Visual review gates

1〜5 点で採点し、**すべて 4 以上、平均 4.5 以上**を合格とする。

| 軸 | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Narrative | 順序が不明 | 概ね理解可能 | 主張と証拠が自然に積み上がる |
| Hierarchy | 視線が迷う | 主題は分かる | 3 秒で結論と証拠が分かる |
| Composition | 崩れ・窮屈 | 実用的 | 余白と整列が一貫し洗練 |
| Visual integrity | 図が壊れる | 読める | 因果・量・関係を正しく明示 |
| Evidence | 飾り中心 | 一部が根拠 | 主張に対応する検証可能な根拠 |
| Typography | 小さい・不統一 | 読める | サイズ、行長、強弱が適切 |
| Template fidelity | 無視 | 一部踏襲 | 制約内で自然に拡張 |
| Polish | 未完成感 | 通常品質 | 会議・登壇でそのまま使える |

## No-actionable-finding gate

最終ラウンドでは、独立レビュアーが次を返すこと。

- hard gate failure: 0
- factual or chart integrity issue: 0
- layout or readability issue: 0
- narrative discontinuity: 0
- 明確な修正方法を伴う改善提案: 0

純粋な好みの違いは finding に数えない。
