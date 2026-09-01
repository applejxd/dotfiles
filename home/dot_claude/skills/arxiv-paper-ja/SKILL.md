---
name: arxiv-paper-ja
description: arXiv の論文・技術ノートを自然な日本語へ全文翻訳し、数式・図表・引用を保った日本語 PDF としてタイプセットする。ユーザーが arxiv.org の abs/pdf URL や arXiv ID を示して「和訳」「翻訳」「日本語 PDF」「タイプセット」を依頼したら必ず使う。TeX ソース取得、ライセンス確認、専門用語の訳語決定、図表翻訳、LuaLaTeX/XeLaTeX のエンジン・日本語フォント調整、ビルド、目視を含む PDF 検証まで扱う。
compatibility: curl または Python 3、tar、latexmk、LuaLaTeX と luatexja-fontspec、pdftotext、pdfinfo、mutool を推奨。
---

# arXiv 論文の和訳 PDF 作成

arXiv URL から原著の構造をできるだけ保持し、専門分野として自然な日本語訳と再現可能な PDF を作る。

## 成果物

次を作業ディレクトリ内へ保存する。

- 最終の日本語 PDF
- 再ビルド可能な日本語 TeX ソースと必要な図版・参考文献
- 論文固有の用語集
- 取得元、ライセンス、組版設定、解決した問題を記した作業記録

## ワークフロー

### 1. URL とライセンスを確認する

1. `abs`、`pdf`、バージョン付き URL のいずれからも arXiv ID を抽出する。
2. `~/.claude/skills/arxiv-paper-ja/scripts/fetch_arxiv_source.py` でメタデータ、論文ページ、TeX ソースを取得する。
3. 論文ページのライセンスを確認する。翻訳・改変・再配布の条件を満たせない場合は全文 PDF を作らず、許可される範囲の要約へ切り替える。
4. 最終 PDF に原著者、原著 URL、ライセンス、翻訳した派生物である旨を表示する。

### 2. 原稿形式を判定する

TeX ソースがある場合は TeX を第一選択にする。数式、引用、ラベル、図版を保持でき、PDF からの再構築より誤りが少ないためである。

TeX ソースがない、またはコンパイル不能な場合のみ PDF 抽出へ切り替える。段組み、脚注、数式、表をページごとに照合し、抽出順序を盲信しない。

### 3. 翻訳前に論文を把握する

タイトル、要旨、目次、導入、結論、主要図表を先に読む。分野、論文の主張、記号体系、対象読者を把握してから訳語を決める。

`references/translation-guidelines.md` を読み、論文固有の用語集を作る。機械的な逐語訳ではなく、その分野で通用する訳語を優先する。一般的な誤訳候補は `references/terminology.md` を参照する。

### 4. TeX を壊さず翻訳する

翻訳対象:

- タイトル、見出し、本文、脚注
- 要旨、謝辞、付録
- 図表キャプション、表の見出し・セル
- `\text{...}`、`\underbrace{...}_\text{...}` など数式内の説明
- 図中の自然言語ラベル

原則として保持するもの:

- 数式と記号
- `\label`、`\ref`、`\eqref`、`\cite` のキー
- BibTeX キーと参考文献の原題
- URL、ファイルパス、画像ファイル名
- 定着したモデル名・製品名・人名

長文を分担するときは、節境界で分割し、全担当が同じ用語集を使う。統合後に一人が全文を校閲し、節をまたぐ照応、用語、文体を揃える。

### 5. 図表を処理する

各図を実際に開いて確認する。

- 数式記号だけの図: 画像を保持し、キャプションを翻訳する。
- 編集可能な TikZ/PGF/SVG: ソース内ラベルを翻訳して再生成する。
- ラスター画像に英語ラベルがある: 元データや生成コードを探して再作成する。入手できなければ、背景を損なわないオーバーレイを作り、元図を改変したことを記録する。
- グラフ: 軸名、凡例、注記を翻訳する。変数名、単位、固有名詞は保持する。
- 表: セル内容を翻訳し、列幅と改行を再調整する。

### 6. 日本語組版を設定する

標準は LuaLaTeX と `luatexja-fontspec`。TeX Live に同梱されやすく、学術文書として端正な原ノ味明朝 Regular を本文の第一候補にする:

```tex
\usepackage{luatexja-fontspec}
\setmainjfont{HaranoAjiMincho-Regular.otf}[
  BoldFont=HaranoAjiMincho-Bold.otf
]
\setsansjfont{HaranoAjiGothic-Regular.otf}[
  BoldFont=HaranoAjiGothic-Bold.otf
]
\setmonojfont{Noto Sans Mono CJK JP}
\linespread{1.15}
\renewcommand{\contentsname}{目次}
\renewcommand{\figurename}{図}
\renewcommand{\tablename}{表}
\renewcommand{\refname}{参考文献}
```

画面向け PDF では複数のビューアまたは画像レンダリングでも本文の黒みと行密度を確認する。長文では `\linespread{1.15}` を出発点とし、図表配置やページ数に応じて調整する。Regular が実際に太く見える場合のみ Light を検討する。原ノ味フォントがなければ Noto CJK JP、次に IPAex を試す。既存ソースが XeLaTeX、upLaTeX、独自クラスへ強く依存する場合は、全面移植より既存エンジンへの日本語対応を優先する。詳細は `references/latex-typesetting.md` を読む。

### 7. ビルドして段階的に直す

`latexmk -lualatex -interaction=nonstopmode -halt-on-error main-ja.tex` を使う。

1. まず致命的エラーを直す。
2. 未解決の引用・参照がなくなるまで再ビルドする。
3. 欠落グリフを直す。
4. overfull/underfull はログだけで判断せず、該当ページを画像化して切断・重なりを確認する。
5. 一時的な回避で数式や内容を削らない。

### 8. PDF を検証する

`~/.claude/skills/arxiv-paper-ja/scripts/validate_pdf.py` を実行し、さらに代表ページを画像化して見る。

最低限、以下を確認する。

- PDF が開け、ページ数と用紙サイズが妥当
- タイトルとメタデータが日本語版を示す
- 目次、本文、数式、図、表、参考文献が表示される
- 日本語を `pdftotext` で抽出できる
- `Missing character`、未解決引用・参照、致命的エラーがない
- 英語のまま残った見出し、キャプション、表、数式注釈がない
- `\begin{document}` / `\end{document}` と TeX 環境が均衡している

問題が起きたら `references/troubleshooting.md` に照らして解決し、今回固有の解決策を作業記録へ追記する。

## 完了条件

PDF の存在だけで完了にしない。翻訳範囲が全文であり、専門用語が自然で、図表を含む内容が欠落せず、再ビルドと表示確認が成功した時点で完了とする。
