# 実際に踏んだ落とし穴

このリポジトリの移行作業で実際に発生した問題と対処。
すべて再現・修正の実績があるもの。

## 1. Ruff の `--fix` が `import marimo as mo` を削除する

### 症状

Markdownセルが実行時に全滅する。**`marimo check --strict` は素通りする。**

```text
MarimoExceptionRaisedError: name 'mo' is not defined
```

### 原因

marimo のセルには2つの書き方があり、Ruff から見た `mo` の扱いが違う。

```python
# 形式A: mo をグローバル参照する（Ruff が使用を検出できる）
with app.setup:
    import marimo as mo

@app.cell(hide_code=True)
def _():
    mo.md(r"""...""")


# 形式B: mo を引数で受け取る（Ruff からは import が未使用に見える）
@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""...""")
```

形式Bのファイルに `ruff check --fix` を実行すると、モジュールレベルの
`import marimo as mo` が F401 と判定されて**削除される**。
結果として `mo` を定義するセルが消え、全Markdownセルが実行時に落ちる。

実際にこのリポジトリでは、13個のMarkdownセルが一度に壊れた。
`marimo export html` を実行するまで気づけなかった。

### 対処

**形式Aに統一する。** `with app.setup:` で import し、セル署名は `def _():`。

```shell
# 形式Bが残っていないか確認する
grep -c 'def _(mo):' *.py
```

### 検知

`marimo check --strict` では検出できない。`marimo export html` を実行して
`name 'mo' is not defined` が出ないことを確認する。

## 2. `marimo export html` はセルが落ちても exit 0 を返す

### 症状

エクスポートが成功したように見えるが、HTMLの中身がエラー表示になっている。

### 原因

`marimo export html` は、セルが例外を投げても終了コード0で、
かつHTMLファイルを**書き出したうえで**終了する。

### 対処

ログを検査し、失敗していたらHTMLを削除する。

```shell
if ! uv run marimo export html "$nb" -o "$out" --force >"$log" 2>&1; then
    rm -f "$out"; failed=1; continue
fi
if grep -q "some cells failed to execute" "$log"; then
    rm -f "$out"; failed=1; continue   # 壊れたHTMLを公開しない
fi
```

外部サイト（Wikipedia、YouTube等）の一時的な不調もここに現れる。
その場合は再実行すれば解消することが多い。

## 3. エディタ上に出る偽の診断

### 症状

VS Code などで marimo notebook を開くと、実在しない警告が大量に出る。

| コード | 内容 |
| --- | --- |
| `F401` | `marimo` imported but unused |
| `F821` | 未定義の名前 |
| `I001` | import が未整列 |

CLI では同じファイルが問題なく通る。

### 原因

エディタは marimo notebook を `vscode-notebook-cell://` スキームで扱い、
**セルを1つずつ独立したファイルとして** linter へ渡す。
marimo のセルは実際にはファイル全体で1つの名前空間を共有するため、
セル単体で見ると import も定義も見えない。

### 対処

**エディタの表示ではなくCLIの結果を信頼する。**

```shell
uv run pre-commit run --all-files
```

## 4. エクスポートされたHTML内の日本語は `\uXXXX` エスケープ

### 症状

追加したはずの日本語がHTMLに含まれていないように見える。

```shell
grep -c 'このノートブックの共通部品' site/notebook.html   # → 0
```

### 原因

marimo は各セルの内容をJSONとしてHTMLへ埋め込む。非ASCII文字は
`\u3053\u306e...` の形式でエスケープされる。

### 対処

デコードしてから照合する。`scripts/grep-exported-html.py` を使う。

```shell
python3 scripts/grep-exported-html.py site/*.html -- 検索文字列
```

## 5. `--sandbox` は依存を解決できずに失敗する

ノートブックが PEP 723 のインライン依存メタデータを持たない場合、
`marimo export html --sandbox` は隔離環境で依存を解決できず失敗する。
プロジェクトの仮想環境をそのまま使うなら `--sandbox` を付けない。

## 6. HTMLの差分は巨大に見えて実は小さい

marimo の出力は単一行のJSONへ埋め込まれるため、`git diff --stat` 上は
数行の変更に見える。逆に、1文字の変更でも行全体が差し替わる。
レビュー時にHTMLの差分を精査しても意味がないため、
**ノートブック本体とHTML再生成はコミットを分ける**。

## 7. lint は説明文の事実誤りを検出しない

Markdown解説を書く作業では、ruff も marimo check も**内容の正しさを一切
検証しない**。このリポジトリでは初稿に13件の事実誤りが残っていた。

典型的な誤りの型：

- **単位の取り違え**：`chunk_size` が文字基準かトークン基準か
  （`RecursiveCharacterTextSplitter(...)` は文字、
  `.from_tiktoken_encoder(...)` はトークン）
- **既定値の推測**：ライブラリの既定値を確認せずに書く
- **近似手法の断定**：近似検索の結果が厳密解と「一致する」と書く
- **環境変数で変わる値の断定**：モデル名が可変なのに次元数を固定値で書く
- **引用の不正確な写し**：公式ドキュメントの記述を写し間違える

対処：**書いた内容は必ずコードで裏を取る。** 既定値は `.venv/` 配下の
実装を読んで確認する。独立したレビュー工程を設けると効果が高い。

## 8. `transformers` が marimo をノートブック環境と判定して IPython を要求する

`sentence-transformers` や `transformers.Trainer` を marimo 内で import すると
失敗することがある。

```text
ModuleNotFoundError: No module named 'IPython'
```

`transformers` の `is_in_notebook()` が `"marimo" in sys.modules` を
チェックしており、真なら `IPython.display` を無条件に import するため。
marimo はファイル冒頭で `import marimo` するので import 順では回避できない。

対処：`ipython` を直接依存に追加する。コードから import していなくても必要。
依存整理の際に「未使用だから」と削除しないよう、コメントで理由を残す。
