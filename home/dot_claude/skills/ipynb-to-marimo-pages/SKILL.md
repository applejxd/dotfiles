---
name: ipynb-to-marimo-pages
description: "Jupyter notebook (.ipynb) を marimo notebook へ移行し、セル分割とMarkdown解説を整え、HTML化してGitHub Pagesへ公開する。「ipynbをmarimoにして」「marimoノートブックを公開したい」「ノートブックのセルを整理して」「解説セルを整備して」「marimo の数式が正しく表示されない」と言われたときに使う。marimo以外のノートブック運用（nbconvert、Quarto、Jupyter Book）には使わない。"
context: fork
agent: general-purpose
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# ipynb → marimo → GitHub Pages 移行スキル

Jupyter notebook を marimo notebook へ移行し、学習・共有に耐える形へ整理して
静的HTMLとして公開するまでの手順。2つのリポジトリでの実施結果を基にしている
（数冊規模の教材移行と、38冊一括のリポジトリ全体移行）。

## 適用範囲

対象は次の全体または一部。フェーズ単位で独立して使える。

| フェーズ | 内容 |
| --- | --- |
| 1 | `.ipynb` → marimo `.py` へ変換 |
| 2 | コードセルを意味単位へ分割し、Jupyter/Colab 依存を除去 |
| 3 | Markdownセルで各セルの処理内容を解説（数式の書式に注意） |
| 4 | HTML化（ノートブックを実際に実行する） |
| 5 | GitHub Pages で公開 |

**「解説セルを整備して」のようにフェーズ3だけを求められることが多い。**
その場合は全フェーズを実行せず、該当フェーズだけを行う。

数十冊を一括で扱う場合は、原本の1対1検査・自動検出ビルド・生成物の鮮度検査が
追加で必要になる。`references/large-scale-migration.md` を参照する。

## 事前に必ず確認すること

作業前にユーザーへ確認する。既定値を勝手に決めない。

1. **どのフェーズを実施するか**（上表のどれか）
2. **APIコストの許容**（フェーズ4はノートブックを実行する。有料APIを呼ぶ
   ノートブックなら課金が発生する。モデルのダウンロードが走ることもある）
3. **フェーズ3の粒度**：全コードセルに1対1で付けるか、意味のあるセルのみか
4. **既存Markdownを書き換えてよいか**（追記のみか、加筆・整理もするか）

## フェーズ1：ipynb → marimo 変換

```shell
uv run marimo convert notebook.ipynb -o notebook.py
```

- 出力は**アウトプットが除去された** marimo notebook。
- **元の `.ipynb` は削除せず `legacy/`（`old/`）等へ残す。** 移行の正しさを
  後から検証する唯一の基準になる。冊数が多い場合は原本と変換後の1対1対応を
  機械的に検査し、リネームは対応表（`migration-map.json`）へ記録する。
- **ファイル名がライブラリ名と衝突しないか確認する。** `sklearn.py` の中の
  `import sklearn` はそのファイル自身を指す。`matplotlib.py`、`open3d.py` も
  同様。衝突する場合は内容を表す名前へリネームする。
- 変換直後は Jupyter 由来の「上から順に流す」構造のままで、marimo の
  依存グラフを活かせていない。フェーズ2で整理する。

変換後、まず静的検査を通す。

```shell
uv run marimo check --strict notebook.py
```

## フェーズ2：コードセルの分割と Jupyter 依存の除去

marimo はセルを関数として扱い依存関係をDAGで解決する。分割時の制約は
`references/marimo-cell-rules.md` に詳しくまとめてある。要点は3つ。

1. **変数はノートブック全体で一意。** 同名の再代入は `multiple-definitions`
   エラー。用途を表す接頭辞（`overview_chunks` など）で衝突を避ける。
2. **`_` 接頭辞の変数はセルを跨げない。** セル分割時に `_loader` のような
   変数は通常の名前へ変えて `return` する必要がある。
3. **セルの最後の式が出力として表示される。** 中間値を見せたいセルは代入で
   終わらせず `len(chunks)` のような式を置く。

分割の指針：**1セル1目的**。「読み込み」「分割」「ベクトル化」を1セルに
詰めず、それぞれの中間結果を確認できる単位に分ける。

セル内で完結しないクラスは `@app.class_definition` を付けてモジュール直下へ置く。

### Jupyter / Colab 固有の記述を落とす

変換直後の `.py` には、marimo では動かない記述がそのまま残る。

| 残るもの | 対処 |
| --- | --- |
| `%matplotlib inline` などの magic | 削除 |
| `!pip install ...` | 依存を `pyproject.toml` へ移す |
| `display(...)` | セル末尾の裸の式にする |
| `google.colab` / Colab バッジ | 削除し、データ取得を固定URLへ置換 |
| `IPython.display` | `mo.image` / `mo.Html` へ置換 |

**動画・アニメーション・3D描画は headless で成立する形へ置き換える。**
matplotlib のアニメーションは `to_jshtml()` を `mo.Html(...)` で包むか、GIF を
生成して `mo.image("data:image/gif;base64,...")` で埋め込む。3D描画は
offscreen レンダリングを使い、失敗時は明示的に静止画へフォールバックする。

乱数 seed と device（CPU/GPU）は明示し、反復計算には必ず上限を置く。
実行時間の暴走はフェーズ4で初めて表面化し、全体を止める。

## フェーズ3：Markdownセルの整備

### 書式

marimo の Markdown セルは次の形式に**統一する**。

```python
@app.cell(hide_code=True)
def _():
    mo.md(r"""
    本文
    """)
    return
```

- `import marimo as mo` は `with app.setup:` に置き、セル署名は `def _():`
  とする（引数を取らない）。**`def _(mo):` は使わない。**
  理由は `references/pitfalls.md` の「Ruff の --fix が import marimo を削除する」。
- `mo.md(r"""...""")` の中に `"""` を書かない。
- Markdown セルは変数を定義も参照もしないため、**依存グラフに影響しない**。
  既存セルの実行順序・出力を変えずに安全に挿入できる。

### 数式は KaTeX の制約に従う

**移行後に最も頻発する不具合。** marimo の Markdown は KaTeX で描画するため、
Jupyter（MathJax）で通っていた記法の一部が生テキストとして表示される。
全規則は `references/math-rendering.md`。要点は4つ。

- ディスプレイ数式は `$$...$$` のみ。`\[...\]`、`\begin{equation}`、`align`、
  `split`、`gather` は**描画されない**。複数行は `$$` の内側で `aligned` を使う
- `$$` は開始・終了とも**単独行**に置く（`$$\begin{aligned}` は不可）
- 数式ブロック内で行頭を「`+` などの記号 + 空白」にしない。Markdown のリスト
  項目と誤認されて数式が分断される（`+ v_k` は `+v_k` と書く）
- 数式ブロック内を字下げしない。コードブロックと解釈される

```shell
python3 ~/.claude/skills/ipynb-to-marimo-pages/scripts/check-display-math.py notebooks
```

`ruff` も `marimo check --strict` も数式の書式を**一切検証しない**。
このチェックはフェーズ5の CI にも入れる。

### 何を書くか

コードを読まなくても分かるように、次の4点を埋める。

- **使用データ**：どのURL・どのファイル・どの範囲か
- **前処理パラメータ**：分割サイズや閾値。**単位を明記する**
  （文字数かトークン数か、など取り違えやすいもの）
- **作成するDB・成果物**：インメモリか永続か、保存先はどこか
- **関数・クラスの入出力**：入力の型と意味、処理の要点、出力の型と意味

### 書式のハイブリッド運用

- **通常のセル**：散文2〜4文。「何を入力に、何をして、何が出力されるか」。
- **インデックス構築セル・自作関数セル**：散文＋箇条書き。
  テンプレートは `references/markdown-templates.md`。

### 粒度

全コードセルに1対1で付けなくてよい。`len(x)` を表示するだけの些細なセルは、
直前のまとまったMarkdownで**まとめて言及**する。

> 次の2セルは、検索の実行と、返ってきた件数の確認です。

この書き方をする場合、**実際のセル数・順序と一致しているか必ず確認する**。

### 共通ヘルパーの解説を忘れない

`with app.setup:` ブロックは marimo 上で**折りたたまれて見えない**。
そこに定義したヘルパー関数は、読み手から存在が見えないまま各セルで使われる。
ノート冒頭に「このノートブックの共通部品」セルを置いて解説する。

### 事実確認は必須

**lint は日本語の説明文の誤りを一切検出しない。** 書いた内容は必ずコードで
裏を取る。実際にこのリポジトリでは、初稿に13件の事実誤りが残っていた。

| 誤りの型 | 例 |
| --- | --- |
| 単位の取り違え | `chunk_size` を文字基準と書いたが実際はトークン基準 |
| 既定値の推測 | ライブラリの既定 `k` を確認せず記述 |
| 近似手法の断定 | 近似検索の結果が厳密解と「一致する」と断定 |
| 環境変数で変わる値の断定 | 埋め込み次元を固定値として記述 |
| 引用の不正確な写し | 公式ドキュメントの既定値リストを誤記 |

**推測で書かない。** 既定値はライブラリの実装（`.venv/` 配下）を読んで確認する。

```shell
grep -rn "DEFAULT_K" .venv/lib/python3*/site-packages/langchain_chroma/vectorstores.py
```

### コードを変更していないことの検証

Markdown 整備でコードセルを壊していないか、機械的に確認する。

```shell
python3 ~/.claude/skills/ipynb-to-marimo-pages/scripts/verify-code-cells-unchanged.py
```

AST でセル本文を抽出し、`HEAD` 版と現在版で非Markdownセルが完全一致するかを
検証する。差分があれば内容を表示する。

## フェーズ4：HTML化

`marimo export html` は**ノートブックを実際に実行する**。有料APIを呼ぶ
ノートブックでは課金が発生する。事前にユーザーの合意を得る。

```shell
uv run marimo export html notebook.py -o site/notebook.html --force
```

**重要な落とし穴**：`marimo export html` は**セルが例外を投げても exit 0 を返し、
HTMLを書き出してしまう**。次の3つをすべて検査し、1つでも該当したら
**出力を削除**して失敗扱いにする。

```python
ERROR_MARKERS = (
    "some cells failed to execute",      # marimo の stdout
    "MarimoExceptionRaisedError",        # stdout と生成HTMLの両方に出る
    "Traceback (most recent call last)",
)
```

stdout だけでなく**生成された HTML 本体も検査する**。正規表現で書く場合、
raw 文字列内の `\\(` は「バックスラッシュ + 括弧」になり永久にマッチしない
（実際に踏んだ。`references/pitfalls.md` の11節）。

ビルドスクリプトの雛形は2種類ある。

| 雛形 | 用途 |
| --- | --- |
| `references/build-site-example.sh` | 数冊規模。一覧を手で持つ |
| `references/build-site-example.py` | 自動検出・manifest 付き。冊数が多い場合 |

`--sandbox` は、ノートブックが PEP 723 のインライン依存を持たない場合は
付けてはならない（隔離環境で依存を解決できず失敗する）。

### 検証

```shell
grep -c 'MarimoExceptionRaisedError\|Traceback (most recent call last)' site/*.html
```

0 でなければ実行時エラーが混入している。

**数式が実際に描画されたかは HTML の grep では判定できない。** marimo は
Markdown を JSON として埋め込み、KaTeX の描画はブラウザ上で行われる。
ヘッドレスブラウザで `.katex-display` の数をソースと突き合わせる。

```shell
uv run --with playwright python \
  ~/.claude/skills/ipynb-to-marimo-pages/scripts/audit-math-rendering.py \
  --site site --notebooks notebooks
```

なお **HTML内の日本語は `\uXXXX` エスケープで格納される**。生の日本語で
`grep` しても一致しない。デコードしてから照合すること。

```shell
python3 ~/.claude/skills/ipynb-to-marimo-pages/scripts/grep-exported-html.py site/*.html -- 検索したい文字列
```

## フェーズ5：GitHub Pages 公開

**ノートブックの実行はローカル、デプロイはCI**、と分離する。こうすると
CIにAPIキーを置かずに済み、CI側で課金も発生しない。

- ローカル：ビルドスクリプトでHTMLを生成し、`site/` をコミット
- CI：検査してから `site/` をアップロードするだけ（ワークフロー例は
  `references/pages-workflow-example.yml`）

CI の検査は**デプロイの直前**に置く。最低限、次の3つ。

1. 数式の書式（`check-display-math.py`）
2. 生成物の鮮度：ソースと HTML の SHA-256 を manifest と照合し、
   **ソースだけ更新して再生成し忘れた状態**を弾く
3. サイトの整合：例外マーカー・ローカルリンク切れ・index との過不足

`site/` をコミットする構成では、2 が無いと古いページを平気で公開してしまう。
実装は `references/large-scale-migration.md` の7節。

注意点：

- 初回は Settings → Pages → Source を **GitHub Actions** にする必要がある。
  ワークフローに `enablement: true` を指定すれば自動化を試みるが、権限に
  よっては失敗する。その場合は手動設定してから再実行する。
- エクスポートされたHTMLは画像を相対パス `imgs/...` で参照する。
  `site/imgs/` を gitignore する運用なら、**デプロイ時にCIで復元する**。
- ワークフローの `paths:` に `notebooks/**` も含める。ソースだけの push でも
  検査が走り、鮮度ゲートで止められる。

## コミットの分割

「ノートブック本体の変更」と「HTML再生成」は**別コミットに分ける**。
HTMLは生成物であり、レビュー時に本体の差分だけを追えるようにするため。

```text
docs(notebooks): 各コードセルの処理内容をMarkdownで解説
docs(site): Markdown解説を追加した状態でHTMLを再生成
```

## 検証コマンドまとめ

```shell
uv run ruff check *.py                  # 静的検査
uv run marimo check --strict *.py       # marimo の依存グラフ検査
uv run pre-commit run --all-files       # リポジトリ定義の全フック
python3 ~/.claude/skills/ipynb-to-marimo-pages/scripts/check-display-math.py notebooks
```

検査の守備範囲は次の通り。**上のどれも実行時エラーを検出しない。**

| 検査 | 検出できるもの | 検出できないもの |
| --- | --- | --- |
| `ruff` | 構文・未使用 import | marimo 固有の制約すべて |
| `marimo check --strict` | 変数の重複定義・循環参照 | 実行時エラー、`mo` 未定義 |
| `check-display-math.py` | 数式の書式違反 | 数式の内容の誤り |
| `marimo export html` | 実行時エラー | 数式が描画されたか |
| `audit-math-rendering.py` | KaTeX の描画失敗 | 数式の内容の誤り |

`marimo check --strict` は、`mo` が未定義で Markdownセルが全滅していても
素通りする。実行時の健全性を確かめるには `marimo export html` まで通す。

## 公開前の独立レビュー

数十冊規模の移行や、ビルド・検査基盤を新設した場合は、**公開前に独立した
レビューを1回入れる**。実際にこの工程で、失敗検知の正規表現が常に真になる
バグと、部分ビルドが鮮度検査を素通りさせる穴という、実害のある欠陥が
2件見つかった。指摘が無くなるまで反復する。

## 参照ファイル

パスはこのスキルの base directory 基準。実体は
`~/.claude/skills/ipynb-to-marimo-pages/`（`~/.copilot/skills` はここへの symlink / junction）。
`${CLAUDE_SKILL_DIR}` / `${COPILOT_SKILL_DIR}` は **Copilot CLI では展開されない**ため、
スクリプトを実行する際は上記の絶対パスで書く。

| ファイル | 内容 |
| --- | --- |
| `references/marimo-cell-rules.md` | セル分割時の変数ルールと構文 |
| `references/math-rendering.md` | 数式の書式規則と検査方法 |
| `references/pitfalls.md` | 実際に踏んだ落とし穴と対処 |
| `references/markdown-templates.md` | Markdownセルの記述テンプレート |
| `references/large-scale-migration.md` | 数十冊規模の移行・ビルド基盤の運用 |
| `references/build-site-example.sh` | HTML化スクリプトの雛形（数冊規模） |
| `references/build-site-example.py` | 自動検出・manifest 付きビルドの雛形 |
| `references/pages-workflow-example.yml` | Pages デプロイのワークフロー例 |
| `scripts/verify-code-cells-unchanged.py` | コードセル不変の検証 |
| `scripts/audit-markdown-coverage.py` | Markdown解説の網羅状況の集計 |
| `scripts/grep-exported-html.py` | エクスポート済みHTMLの日本語検索 |
| `scripts/check-display-math.py` | 数式の書式検査（静的） |
| `scripts/audit-math-rendering.py` | 数式の描画検査（Chromium で実測） |
