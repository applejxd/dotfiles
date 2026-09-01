# 日本語 TeX 組版

## エンジン選択

### LuaLaTeX

新規の日本語化では第一候補。Unicode、OpenType、`luatexja-fontspec` を使いやすい。

### XeLaTeX

原著が `fontspec` と XeTeX 固有機能へ依存する場合の候補。日本語処理は `xeCJK` など既存構成に合わせる。

### upLaTeX

和文クラスや pLaTeX 系パッケージへ強く依存する既存原稿で選ぶ。欧文原稿を新たに和訳する用途では、移植コストを見て LuaLaTeX と比較する。

## フォント

推奨順:

1. 原ノ味明朝 Regular / 原ノ味角ゴシック Regular
2. Noto Serif/Sans/Mono CJK JP
3. IPAex 明朝/ゴシック
4. プロジェクト指定の埋め込み可能な日本語フォント

原ノ味フォントでは本文に Regular、`\textbf` に Bold を割り当てる。

```tex
\setmainjfont{HaranoAjiMincho-Regular.otf}[
  BoldFont=HaranoAjiMincho-Bold.otf
]
\setsansjfont{HaranoAjiGothic-Regular.otf}[
  BoldFont=HaranoAjiGothic-Bold.otf
]
\linespread{1.15}
```

本文が太く見える場合は、先に別の PDF ビューアと画像レンダリングで比較する。長文の行送りは `\linespread{1.15}` を出発点とし、`1.10` から `1.20` の範囲で調整する。行送りを変えると数式の上下間隔と改ページも変わるため、全ページ数と図表配置を再確認する。

配布条件と PDF への埋め込み可否を確認する。見つからないフォント名を決め打ちせず、`fc-list :lang=ja family` で環境を確認する。

## 既存パッケージとの衝突

- LuaLaTeX では `inputenc` は不要で、読み込むと無視される警告が出る。
- `fontenc` は欧文フォント用途で残せる場合があるが、フォント置換の結果を確認する。
- `CJK`、`xeCJK`、pLaTeX 専用クラスを無条件に併用しない。
- `hyperref` の PDF メタデータを日本語版へ更新する。
- 文書クラスの表示名 `Contents`、`Figure`、`Table`、`References` を日本語化する。

## レイアウト

- 原著が Letter の場合、日本語版は A4 へ変えるかを記録する。
- 日本語化で行長が変わるため、表の列幅、キャプション、脚注、コード、URL を確認する。
- 長い数式は `aligned`、`split`、`multline` を検討するが、式の意味と番号を変えない。
- overfull 警告を消すだけの過度な縮小は避け、画像化して実害を判断する。
