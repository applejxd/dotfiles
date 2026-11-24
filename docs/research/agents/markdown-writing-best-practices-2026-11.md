# Markdown 文書の書き方の調査（2026-11）

- 観測日: 2026-11-24
- 問い: `docs/` の Markdown が読みにくい。公開の指針と実測から、何を規則にするか
- 反映先: `home/dot_agents/skills/sdd-docs/references/markdown-style.md`

## 結論

- 利用者の好みは、長文のベタ書き禁止・図表と箇条書き・経緯を物語にしない。調査結果と矛盾しない
- 原因の中心は、1 文の長さ・文章入りの表のセル・太字の多用・壊れた太字・経緯の叙述
- 規則は `markdown-style.md` にまとめた。案件・ADR・調査記録のテンプレートも合わせて改めた
- 検査は、既存の markdownlint を継続する。助言だけの検査スクリプトと Mermaid の構文検査は、承認待ちの候補にした

## 現状の実測

対象は `docs/` の 103 ファイル（12,625 行）。コードブロックは除く。

| 指標 | 値 |
| --- | --- |
| 200 字超の行 | 671 |
| 最長の 1 行 | 3,670 字 |
| 太字 | 2,483 か所 |
| 80 字超の表のセル | 506 |
| 100 字超の文（textlint） | 958 |
| 壊れた太字（`**` が残る） | 15 か所・9 ファイル |

textlint（`preset-ja-technical-writing` 12.1.0）の違反は、`docs/` で 1,295 件、スキル自身の文書で 18 件。100 字超の文はスキルを含めて 964 件で、長さの中央値は 126 字、200 字超は 109 件。

| 違反の種類 | 件数 |
| --- | --- |
| 文の長さ（100 字超） | 958 |
| 同じ助詞の連続 | 148 |
| 句点の不統一 | 52 |
| ですます・である混在 | 47 |
| 読点が 4 つ以上 | 39 |

### 再現手順

- 基準: `cc2c1140`（develop）、Node 26.13.1。作業は `.tmp/` の使い捨てで、集計の出力は残していない
- textlint 16.1.3 + `textlint-rule-preset-ja-technical-writing` 12.1.0
  - 設定: `{"rules": {"preset-ja-technical-writing": true}}`
  - コマンド: `textlint -c .textlintrc.json -f json 'docs/**/*.md' 'home/dot_agents/skills/sdd-docs/**/*.md'`
- 壊れた太字: `markdown-it-py`（CommonMark）で本文をパースし、テキストに `**` が残るものを数えた
- 行・太字・セル: 使い捨ての数え上げ（コードブロックを除く）。定義の近い `lint_style.py` でも数値は出るが、一致はしない
- Mermaid: `mermaid` 12.3.0 と `jsdom` で `mermaid.parse()` を呼んだ
- スキル自身の文書は違反が少ない。違反は、スキルが書かせた `docs/` 側に多い

## 取り込んだ知見

確度の印は、`markdown-style.md` の凡例に合わせる。

### 表

- 強: セルはインラインだけで、リスト・改行は入らない（GFM §4.10）
  - <https://github.github.com/gfm/>
- 中: 表は 1 事実の短い値で組む。セルに文章を入れる表は悪い表（Google）
  - <https://google.github.io/styleguide/docguide/style.html>
- 中: 比較表は 5〜7 個までの選択肢を複数の属性で比べる場面に向く（NN/G）
  - <https://www.nngroup.com/articles/comparison-tables/>
- 中: 1 列だけの表は箇条書きにする（Google developer documentation style guide）
  - <https://developers.google.com/style/tables>

### 箇条書きと段落

- 中: 一文を短くする。論点を 1 つにする。3 つ以上の情報を並べるときは箇条書き（公用文作成の考え方。検索抜粋で確認。本文は未取得）
  - <https://www.bunka.go.jp/seisaku/bunkashingikai/kokugo/hokoku/pdf/93651301_01.pdf>
- 中: 箇条書きは 2〜7 項目。導入の 1 文を付ける（Microsoft・plainlanguage.gov）
  - <https://learn.microsoft.com/en-us/style-guide/scannable-content/lists>
  - <https://digital.gov/guides/plain-language/writing/>
- 中: 長い指示文書は、密な段落より見出しと箇条書きのほうが従われやすい（Claude Code）
  - <https://code.claude.com/docs/en/memory.md>
- 弱: 一律に箇条書きにせず、散文と比べて良いほうを選ぶ（LINE のテクニカルライティング講座）
  - <https://engineering.linecorp.com/ja/blog/line-technical-writing-course/>

### 強調

- 中: 太字は UI 名と先頭語だけにする。強調に使うと、重要な箇所が分からなくなる（Google・GOV.UK）
  - <https://developers.google.com/style/text-formatting>
  - <https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/style-guides/a-to-z-style-guide/>
- 強: `**` は約物の隣で効かない（CommonMark §6.2 の flanking 規則）。CommonMark 本体の修正は未反映（issue #650 と PR #839 が open）
  - <https://spec.commonmark.org/0.31.2/>
  - <https://github.com/commonmark/commonmark-spec/issues/650>
  - 実測: `これは**「重要」**です。` は太字にならない（markdown-it 0.31 準拠）
  - GitHub も同じ規則（cmark-gfm）。直接の描画確認は未実施

### 文章（日本語）

- 中: 1 文 100 字以内・読点 3 つまで・同じ助詞を続けない（textlint の既定。「厳しめ」の設定と明記されている）
  - <https://github.com/textlint-ja/textlint-rule-preset-ja-technical-writing>
- 中: 1 内容の文のほうが、複数内容の文より解答が速かった（吉田ら 2002。抄録のみ）
  - <https://www.jstage.jst.go.jp/article/jmet/25/4/25_25.4_217/_article/-char/ja/>
- 弱: 括弧の中を読み飛ばす読者がいる。重要な情報を括弧に入れない（Google）
  - <https://developers.google.com/style/parentheses>
- 弱: 全角と半角英数字の間の空白は、JTF は入れず、Microsoft は入れる。流派が逆
  - 既存の docs は Microsoft 流。変えない

### 構造

- 中: 読者は読まずにスキャンする（NN/G。1997 年・小規模の実験。方向は複数の記事で一致）
  - <https://www.nngroup.com/articles/how-users-read-on-the-web/>
- 強: 結論を先に置く。Rust RFC は Summary を 1 段落、MADR は結論を詳細比較より先に置く
  - <https://raw.githubusercontent.com/rust-lang/rfcs/master/0000-template.md>
  - <https://adr.github.io/madr/>
- 中: H1 は 1 つ、見出しは段を飛ばさない。見出しだけ読んで内容が分かるようにする（Google・GOV.UK・markdownlint）
- 中: ADR は 1 決定 1 文書・1〜2 ページ。大きい文書は更新されない（Nygard）
  - <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>
- 中: 設計書は実装後に「アーカイブ」として扱い、半端に正しい文書として残さない（Google）
  - <https://google.github.io/styleguide/docguide/best_practices.html>
- 数値が無いもの: 見出しの深さ・節の数・1 文書の長さ。`markdown-style.md` では「目安」の印を付けた

### 経緯・履歴

- 中: reference（spec 相当）は現在の姿を記述するだけにする。経緯・選択肢・理由は explanation に置く（Diátaxis）。このリポジトリでは `spec/` にだけ当てる（ADR・調査記録は保存の規約が優先）
  - <https://diataxis.fr/reference/>
  - <https://diataxis.fr/explanation/>
- 中: 要約を先頭に、時系列を末尾に置く。SRE のポストモーテムは Timeline を最後に置く
  - <https://sre.google/sre-book/example-postmortem/>
- 中: 書く基準を事前に決め、必要なときだけ書く（SRE）
  - <https://sre.google/sre-book/postmortem-culture/>
- 中: 見送った案は、案・理由を表にする（MADR・Rust RFC の代替案の節）
- 弱: 「現在」「新しい」を避け、日付か版で書く（Kubernetes。検索抜粋のみ）

### Mermaid

- 中: 図は、言葉で説明しにくい情報にだけ使う。図の中の文字を画像にしない。図は完全な文で導入する（Google）
  - <https://developers.google.com/style/images>
- 強: GitHub は ` ```mermaid ` のフェンスを描画する。版は `info` で確かめる
  - <https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams>
- 強: 小文字の `end` は構文エラーになる。特殊文字は `"…"` で囲む（公式）
  - <https://mermaid.js.org/syntax/flowchart.html>
  - 実測（Mermaid 12.3.0・jsdom）: 日本語ラベル（引用符つき）は通る
  - エラーになる: ノード ID の小文字 `end`、半角括弧入りの無引用ラベル
  - 通る: ラベル中の語 `end`、全角括弧の無引用ラベル、`%%` のコメント内の `end`
- 中: `accTitle` / `accDescr` で代替テキストを付けられる。GitHub 上の効果は未確認
  - <https://mermaid.js.org/config/accessibility.html>
- 弱: ノード数・色・1 図 1 メッセージは、出典に数値が無い。経験則として置いた
- 未確認: GitHub の Mermaid の版・ダークモード・ノード数の上限。LLM が Mermaid を読む精度

### 日本語 Markdown の描画

- 弱: 段落内の改行は、Firefox では除去され、Chrome 系では空白になる（2023〜2024 年の報告。2026-11 の再検証なし）
  - <https://github.com/commonmark/commonmark-spec/issues/744>
  - <https://zenn.dev/yasuraok/articles/7c8a6dc3f9bb10>
- 中: `text-autospace`（全角と半角の間の自動の空白）は、Firefox 145 と Safari 27 が対応。Chrome は未対応
  - <https://web-platform-dx.github.io/web-features-explorer/features/text-autospace/>

### AI が書く文章

- 中: 過剰な太字・誇張・三点列挙は AI 文章の兆候。症状を消すだけでは足りない（Wikipedia）
  - <https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing>
- 弱: 書式が LLM の精度を決めるという強い証拠は見つからなかった。小さいモデルで影響が大きい

## 既存の道具の評価（ADR-0031）

| 候補 | 扱い | 理由 |
| --- | --- | --- |
| markdownlint-cli2 | 継続 | 導入済み。MD013（行長）は日本語で意味が薄く off のまま |
| textlint + ja-technical-writing | 参考 | 既定が厳しく、全件に当てると 1,295 件。npm の依存が増える |
| Vale + AI 臭の規則 | 見送り | 英語前提。日本語での有効性が未確認 |
| `mermaid.parse`（Node + jsdom） | 候補 | 実測で構文エラーを検出。依存の追加が要る。承認待ち |
| 助言のみの検査スクリプト | 候補 | 下の説明。承認待ち |

助言のみの検査スクリプト（`scripts/lint_style.py`）:

- 理由: 既存の道具に「表のセルの長さ」「壊れた太字」「括弧の入れ子」を見るものが無い
- 維持費: 標準ライブラリだけの 1 ファイル（約 650 行）と試験 63 件
- 撤去の条件: 上の項目を markdownlint か textlint の設定で代替できたとき
- 扱い: 落とさない（助言のみ）。変えた行だけを見る。別の feature（`sdd-docs-style-lint`。この調査の feature に積む）にして、利用者の承認まで統合しない

### AI 向けのスキルの評価

| 名前 | 扱い | 取り込んだ点 |
| --- | --- | --- |
| blader/humanizer | 参考 | 「症状だけ消さない」。英語中心で、導入はしない |
| anthropics/skills の doc-coauthoring | 参考 | 読者テストの発想 |
| mattpocock/skills の writing-for-agents | 参考 | 肥大を避ける・手順と参照を分ける |
| vercel-labs の writing-guidelines | 参考 | 規則の項目だけ。実行時の URL 取得は見送り |
| awesome-copilot の documentation-writer | 参考 | Diátaxis で分類してから書く |
| obra/superpowers の writing-skills | 見送り | スキル作成向けで、docs の整形ではない |

- 出典（読んだもの）: <https://github.com/anthropics/skills>・<https://github.com/blader/humanizer>・<https://github.com/mattpocock/skills>・<https://github.com/vercel-labs/writing-guidelines>
- 採用実績の数値は、二次の一覧（lazyskills）による。独立の検証はしていない

## 未確認

- 日本語の可読性の実証（文長・漢字率・箇条書きと理解度）の本文。抄録のみ
- 公用文作成の考え方の本文（PDF が取得できなかった）
- GitHub での描画の直接確認（強調・改行・Mermaid の版）
- 表のセルの適量・括弧の害の実証。出典に数値が無い
- Conventional Commits・Write the Docs のナビ設計・Stripe の変更履歴の扱い
