# Template-first Workflow

## 1. Inventory

```bash
uv run scripts/inspect_template.py template.pptx --output template-inventory.json
```

確認するもの:

- slide size
- slide master / layout names
- placeholder index, type, name, bounds
- サンプルページの shape 名、座標、文字サイズ
- theme font と theme color
- 画像枠の縦横比

レイアウト番号をコードへ直書きせず、名前と placeholder index の対応表を作る。

## 2. Content budget

各枠について、元サンプルの次を上限として扱う。

- 最大行数
- 元の最小フォントサイズ
- 1 行あたりのおおよその文字数
- 箇条書き数
- 画像比率

置換文が上限を超える場合の優先順位:

1. 重複・修飾語を削る
2. 主張を短いタイトルへ、詳細をノートへ移す
3. 同じテーマ内の別レイアウトへ変更
4. ページを分ける
5. 最後に、テンプレートが許す範囲でフォントを縮小する

## 3. Layout selection

内容の型とレイアウトの型を一致させる。

| 内容 | 適切なレイアウト |
| --- | --- |
| 一つの結論 | hero / big number |
| 比較 | two-column / before-after |
| 因果・処理 | process / flow / system |
| 実験結果 | chart + takeaway |
| 製品証拠 | screenshot + callout |
| 複数案 | option cards / matrix |
| 実行計画 | timeline / roadmap |

## 4. Preservation rules

- `Presentation(template.pptx)` から開始し、元マスターとレイアウトを使う。
- placeholder へ書き込み、同じ役割の shape を新規追加しない。
- `text_frame.text` 一括代入で書式を壊さず、段落と run を保つ。
- exemplar slide を再利用するときは shape だけでなく relationship、group、chart、
  media を含む完全複製を行う。
- 元テンプレートを保存し、出力先を分ける。

## 5. Verification

テンプレート元と生成物について同じ DPI のモンタージュを作り、次を比較する。

- 余白
- タイトル位置
- グリッド
- 色と書体
- 画像枠比率
- フッター、ロゴ、ページ番号

テンプレートらしさを維持するために情報を過密化してはいけない。
