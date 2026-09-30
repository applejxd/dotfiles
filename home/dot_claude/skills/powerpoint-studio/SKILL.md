---
name: powerpoint-studio
description: "編集可能な PowerPoint（.pptx）の新規作成・大幅改稿・テンプレートへの内容充填に使う。「パワポを作って」「PowerPoint 資料で図や実験結果を見やすく貼って」「スライドをデザインして」「テンプレートに収めて」で使う。Use to create, substantially redesign, or fill a template with an editable .pptx deck. .pptx のテキスト抽出や軽微な一語置換には使わない。"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebFetch, WebSearch, Task
---

# PowerPoint Studio

見た目のよいページを偶然作るのではなく、**構成設計、テンプレート適合、視覚化、
機械検査、レンダリング、独立レビュー**を一つの閉ループにする。

## 場所の定義

- **スキルの展開先** `SKILL_DIR`: この `SKILL.md` があるディレクトリ
  （通常 `~/.claude/skills/powerpoint-studio`）。`scripts/`・`assets/`・`references/`・
  `pyproject.toml`・`package.json` と依存（`.venv`・`node_modules`）はここにある。
- **作業ディレクトリ** `WORK_DIR`: 利用者のプロジェクト内の成果物置き場。
  `deck-plan.json`・`.js`・`.pptx`・画像・`./.tmp/` の QA 出力はここに置く。

`SKILL_DIR` は `SKILL.md` を読み込んだパスから決め、`WORK_DIR` をカレントにして実行する。
Python スクリプトは次の形で呼ぶ。入出力のパスは `WORK_DIR` 基準（カレント基準）で明示する。

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/<名前>.py" <引数>
```

以降の `<名前>.py` の例はこの形の省略で、`references/` の `uv run scripts/...` も同様に読み替える。

JavaScript（PptxGenJS）は初回だけ `npm ci --prefix "$SKILL_DIR"` で依存を用意する。
デッキのソースは `WORK_DIR` に置き、helper は展開先の絶対パスで読み込む
（helper の依存は helper 自身の位置から解決される）。

```bash
SKILL_DIR="$SKILL_DIR" NODE_PATH="$SKILL_DIR/node_modules" node deck.js
```

## 品質契約

最終成果物は `references/quality-standard.md` の Hard gates（描画・テキスト・画像・
テンプレート・出典・時間・図・色・構造などの合格条件）と Visual review gates を満たすまで
完成ではない。閾値と判定基準はすべてそこを正本とし、本文では重複して書かない。
全ページの PNG を一覧と原寸の両方で目視確認することも含む。

## 必須ワークフロー

### 1. 入力を棚卸しする

- 目的、聴衆、持ち時間、意思決定、必須メッセージを特定する。
- 発表者名、所属、発表日、イベント名を取得する。未提供なら推測せず例外として記録する。
- 既存テンプレート、旧資料、画像、表、実験ログ、URL、ブランド規定を列挙する。
- 不足情報が本質的でなければ、合理的な仮定を明示して進める。
- 素材の事実と生成した解釈を混同しない。
- 原典ベースの資料では `references/source-fidelity.md` に従い、主張台帳と引用規則を使う。
- 原典そのものを紹介・批評するレビュー資料では `source_review.enabled = true` とし、
  原典の区切り、順序、具体的な技法名、次へ進む理由、学び、限界を残す。
  一般的なベストプラクティスへ置換して、どの教材のレビューか分からなくしてはいけない。
- 日本語資料の表現を整えるときは `references/japanese-wording.md` を使う。
  一般的な説明と正式名称・コード識別子を分け、意味と単位を確認してから訳す。

### 2. 先に `deck-plan.json` を作る

PowerPoint を触る前に、`references/deck-plan-schema.md` に従う構成案を作る。

各ページに最低限、次を持たせる。

- `role`: hook / context / evidence / mechanism / decision / action / close
- `claim`: 観客が一文で持ち帰る結論
- `evidence`: claim を支えるデータ、引用、スクリーンショット、図
- `visual`: chart / diagram / screenshot / photo / table / native-shapes
- `layout`: 使用するテンプレートレイアウトまたは構図
- `speaker_goal`: そのページを見せる間に説明すること
- `timing_seconds`: そのページの予定時間
- `optional_cut_seconds`: 遅延時に削れる時間

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/validate_plan.py" deck-plan.json
```

ページタイトルを章名だけにしない。「結果」「背景」ではなく、結論をタイトルにする。
時間指定がある場合は `references/timing-and-notes.md` を読み、話者ノート、途中の
通過時刻、短縮可能箇所、ペーシング検証を先に設計する。
技術入門は `references/narrative-balance.md` に従い、各ページを
Why / What / How / Proof / Operate / Actionへ分類する。
新規デッキは `references/one-message-density.md` に従い、
`meta.message_policy.enabled = true` とする。各ページへ `message_mode`、
`detail_policy`、`information_units` を付け、overviewでは何を認識し、
何を後で参照するかを `reading_goal` に明記する。
また `meta.chrome_policy` を有効にし、ユーザーが明示しない限り
`header: none`、`footer: none`、`page_numbers: required` とする。
`meta.typography_policy` にはprimary/mono書体、最小サイズ、タイトル・本文・注釈・
ページ番号のサイズ帯を定義する。Graphviz等の作図ソースにも同じ書体名を明示し、
図だけ別の書体や過大な文字にしない。

15分以上の発表は `references/presentation-structure.md` に従う。1枚目は内容を表す
**タイトル**を最大の文字で置き、2枚目は短い目次、最後は全体を思い出せるまとめにする。

費用報告が有効な場合は、調査と構成の確定直後に
`references/cost-estimation.md` のチェックポイントを実行する。ここまでの実測費用と、
完遂までの `low / base / high` を分けてユーザーへ示す。
標準対象は Claude Code + Amazon Bedrock とし、Copilot CLIの金額換算は明示要求時だけ行う。

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/estimate_cost.py" cost-checkpoint-input.json \
  --output cost-checkpoint.json
```

### 3. 実装経路を選ぶ

| 条件 | 経路 |
| --- | --- |
| `.pptx` テンプレートがある | Template-first |
| 既存ページの見た目を厳密に残す | OOXML / exemplar-slide |
| テンプレートなしで編集可能性を優先 | PptxGenJS |
| 複雑な図やコード、数式 | SVG/PNG を生成し配置 |

図解はまず公式・原著・元OSSに適切な図があるか調べ、その後
`references/diagram-routing.md` の複雑度基準でquoted-official / native / hybrid /
externalを選ぶ。
分岐、ループ、再結合、入れ子を含む図をネイティブ図形へ無理に押し込まない。
プロセス図は `references/diagram-routing.md` の主経路・例外分岐・戻り線の規則を使い、
`audit_diagram_topology.py` で入口、主経路、分岐ラベル、外周returnを検査する。
これは意味の検査であり、線が本当に外周を通る証明ではない。
固定座標図・複数の戻り線・過去に崩れた図では `references/diagram-geometry.md` を読み、
実フォントで文字を測り、ノード・ラベル・矢印の座標を同じソースから生成・検査する。
Graphviz の警告、特に `bounding boxes ... touch` や `falling back` を解消せず進めない。
長い実装名や大きいフォントに変更したら、箱と線を含めて再配置する。

テンプレート指定時は、最初に次を実行する。

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/inspect_template.py" template.pptx --output template-inventory.json
```

`references/template-workflow.md` を読み、利用するレイアウトと各プレースホルダーの
文字予算を決める。テンプレートを背景画像にして似せるだけの実装は禁止。

### 4. 視覚を内容と同時に設計する

- 本文ページは原則として意味のある視覚要素を 1 つ以上持つ。
- 箇条書きの代わりに、比較、プロセス、階層、因果、時間、分布、証拠の形へ変換する。
- 実験結果は「グラフ + 主要数値 + 解釈 + 条件」の組で示す。
- スクリーンショットは余白除去、枠、背景、キャプション、必要な注釈を付ける。
- 図のラベルはスライド上で読める大きさにし、矢印の交差と線の曖昧さを避ける。
- 装飾目的の画像で文字だけページ判定を回避してはいけない。

画像処理と図解の基準は `references/visual-workflow.md` を読む。
配色、背景、ラベル部品は `references/visual-system.md` を読む。新規デッキでは
`style-policy.json` を作り、surface と base / main / accent、許可するニュートラルを固定する。
既存デッキのレイアウト改善では `references/layout-review.md` を読む。
全ページを同じ構図へ揃えるのではなく、表の列、比較カード、目次、階層図の役割ごとに
配置を見直す。読ませる主要語を注釈サイズへ縮めて、広いカードの余白を残さない。

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/frame_screenshot.py" input.png output.png \
  --canvas 1600x1000 --caption "Evaluation dashboard" \
  --callouts callouts.json
```

### 5. 編集可能性を保って実装する

新規デッキは原則 PptxGenJS を使い、ソース `.js` も納品する。

```javascript
const {
  imageSizingContain,
  imageSizingCrop,
  safeOuterShadow,
  warnIfSlideHasOverlaps,
  warnIfSlideElementsOutOfBounds,
} = require(`${process.env.SKILL_DIR}/assets/pptxgenjs_helpers`);
```

- 単純な棒・折れ線・円グラフは PowerPoint ネイティブチャートにする。
- 複雑な図は SVG、写真・スクリーンショットは高解像度 PNG/JPEG にする。
- 外部作図へ切り替えた場合も、Graphviz/D2/Mermaid/PlantUMLのソースを納品する。
- `fit` / `autoFit` に丸投げせず、内容を短くし、必要ならページを分ける。
- 文字サイズの下限は `references/quality-standard.md` に従う。
- Unicode の `•` を使わず、箇条書き API を使う。
- すべての主要画像に代替テキストを付ける。
- 意図的な重なりには、ソースコード上で短い理由コメントを残す。
- 各ページ作成後に overlap / out-of-bounds helper を呼ぶ。
- PptxGenJS 出力は presentation-level XML の順序が不正になる版がある。次で検査し、
  必要なら正規化した別ファイルを最終成果物にする。

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/validate_ooxml.py" deck.pptx
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/normalize_ooxml.py" deck.pptx deck-normalized.pptx
```

Apache-2.0 の helper API は `references/pptxgenjs-helpers.md` を参照する。

### 6. 一回で終わらせず品質ゲートを回す

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/validate_deck.py" deck.pptx \
  --plan deck-plan.json \
  --source deck.js \
  --template template.pptx \
  --style-policy style-policy.json \
  --output-dir ./.tmp/powerpoint-qa
```

このコマンドは構造監査、レンダリング、キャンバス外検査、フォント検査、
モンタージュ作成を行う。エラーを一つずつ消す。

さらに次を必ず実施する。

1. モンタージュで全体の流れ、密度、単調さを確認する。
2. 各 PNG を原寸で確認し、文字切れ、図の交差、画像のぼけ、余白の崩れを見る。
   図はSTARTから終了まで矢印を一本ずつ追う。戻り線、線上の文字、矢印のない帰還、
   説明用ラベルを実行ノードに見せていないかも確認する。
   表の見出しとセルの整列、主要語と補足の主従、横並びによる不自然な改行も確認する。
   保護したい整列・主要語の文字下限は `meta.layout_checks` に宣言して再発を検出する。
   表現の見直しでは、画像化された図の文字と話者ノートも対象にする。
   「予算」の単位や、反復・終了の関係を訳語だけで曖昧にしない。
3. 内容を作ったエージェントとは別のレビュアーに、PPTX と PNG を渡して評価させる。
4. 指摘は資料のソース（`.js`・`deck-plan.json`・素材）だけへ反映し、再生成する。
   スキル自体の変更はしない。スキルへの改善案は報告で提案するに留める
   （書き換えは別途利用者の承認が要る）。
5. ラウンド上限・停滞・完了の条件と、止めたときの報告は
   `references/quality-standard.md` に従う。

レビュー観点は `references/review-rubric.md` を使う。

原典ベースの資料は、見た目のレビューとは別コンテキストで source fidelity review
を行う。時間指定のある資料は、計画時間の合計だけでなく、実際の話者ノートから
ペーシングを検証する。

## テンプレート充填の絶対規則

- レイアウト名やプレースホルダー番号を推測しない。inventory の値を使う。
- 長文を小さい文字へ押し込まない。要約、分割、別レイアウトへの変更を先に行う。
- 写真は contain / cover を意図的に選び、縦横比を壊さない。
- 素材数が枠数より少ない場合、余った見出し、アイコン、写真枠をグループごと削除する。
- 素材数が多い場合、1 枠へ詰め込まずページを複製または追加する。
- 元テンプレートを上書きせず、別名で保存する。
- LibreOffice でのレンダリング結果だけでなく、可能なら PowerPoint でも開く。

## デッキ全体の構成規則

- 最初の 2 ページで「なぜ今見る価値があるか」を示す。
- 3〜5 ページごとに、証拠・図解・大きな数値など視覚リズムを変える。
- 変化の目的を説明できない同一構図の反復を避ける。Before/Afterや段階改善では、
  比較可能性のため同じ構図を意図的に反復してよい。
- 1 ページ 1 主張。複数の独立主張は分ける。情報単位の上限は
  `references/quality-standard.md` と `references/one-message-density.md` に従う。
- ヘッダー・フッター・ページ番号の扱いは `references/quality-standard.md` の Chrome に従う。
- 長い説明型発表で最後に表示するページはまとめにする。まとめの最終項目や口頭の
  終わりを、判断、行動、問いへ接続してよい。
- ページ間の因果が説明できないページは削除または移動する。

## 生成物

最低限、次を残す。

- 最終 `.pptx`
- 再生成可能な `.js` またはテンプレート充填用ソース
- `deck-plan.json`
- 使用した画像・図
- QA レポート、モンタージュ、レンダリング PNG
