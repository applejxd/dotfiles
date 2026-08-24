# marimo のセル分割ルール

marimo はセルを関数として扱い、変数の依存関係をDAGで解決する。
Jupyter の「上から順に実行」とは前提が違うため、セルを分割する際に固有の制約がある。

## 1. 変数はノートブック全体で一意でなければならない

同じ名前を複数のセルで代入すると `multiple-definitions` エラーになる。

```python
# NG: 2つのセルが同じ `loader` を定義している
@app.cell
def _():
    loader = WebBaseLoader(url_a)
    ...

@app.cell
def _():
    loader = WebBaseLoader(url_b)   # multiple-definitions
    ...
```

同じ処理を別のパートで繰り返す場合は、用途を表す接頭辞を付けて衝突を避ける。

```python
overview_loader = WebBaseLoader(...)   # パート1用
blog_loader     = WebBaseLoader(...)   # パート2用
```

衝突は静的検査で検出できる。

```shell
uv run marimo check --strict notebook.py
```

## 2. `_` 接頭辞の変数はセルを跨げない

アンダースコアで始まる変数はセルローカルであり、他のセルから参照できない。
1つのセル内で完結していた `_loader` のような変数を持つセルを分割するときは、
通常の名前へ変更して `return` する必要がある。

```python
# 分割前（1セル内で完結、_ 付きでよい）
@app.cell
def _():
    _loader = WebBaseLoader(url)
    docs = _loader.load()
    return (docs,)

# 分割後（loader を次のセルへ渡すため通常名にして return）
@app.cell
def _():
    loader = WebBaseLoader(url)
    return (loader,)

@app.cell
def _(loader):
    docs = loader.load()
    return (docs,)
```

## 3. セルの最後の式が出力として表示される

中間値を見せたい場合は、代入だけで終わらせず最後に式を置く。

```python
@app.cell
def _(blog_documents):
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=300, chunk_overlap=50
    )
    document_chunks = text_splitter.split_documents(blog_documents)
    len(document_chunks)   # ← セルの出力として表示される
    return (document_chunks,)
```

`len(...)` のように件数を出すだけでも、処理の途中経過を追いやすくなる。
複数行の文字列は `print()` を使うとそのまま確認できる。

この「裸の式」は Ruff の B018（useless-expression）に引っかかるため、
`pyproject.toml` で無効化しておく。

```toml
[tool.ruff.lint]
ignore = [
    "B018",    # marimo displays bare expressions as cell output.
    "PLR1711", # marimo emits explicit returns for cells without outputs.
]
```

## 4. `with app.setup:` ブロック

全セルから参照される import や共通ヘルパーはここへ置く。

```python
with app.setup:
    import marimo as mo
    import numpy as np

    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)
```

**このブロックは marimo のUI上では折りたたまれ、読み手からは見えにくい。**
ここに置いたヘルパーは、ノート冒頭のMarkdownセルで解説すること。

## 5. クラス定義

セル内で完結しないクラスは `@app.class_definition` を付けてモジュール直下へ置く。

```python
@app.class_definition
class RouteQuery(BaseModel):
    """Route a user query to the most relevant datasource."""

    datasource: Literal["python_docs", "js_docs", "golang_docs"] = Field(...)
```

Markdownセルはこの直前にも置ける。

## 6. Markdownセルは依存グラフに影響しない

Markdownセルは変数を定義も参照もしないため、どこに挿入しても
既存セルの実行順序・出力は変わらない。解説の追加は安全な操作である。

```python
@app.cell(hide_code=True)
def _():
    mo.md(r"""
    本文
    """)
    return
```

`hide_code=True` により、エクスポート時にコード部分が隠れて本文だけが表示される。
