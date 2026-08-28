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

## 9. 数式が生の LaTeX として表示される

`\begin{equation}` や `\[...\]` が、公開ページ上でそのまま文字として出る。
Jupyter（MathJax）では表示できていた記法。

marimo の Markdown は **KaTeX** で描画する。対応するディスプレイ数式の記法は
`$$...$$` だけで、`\[...\]` や `equation` / `align` 環境は解釈されない。
また `$$` の内側でも、行頭が「`+` などの記号 + 空白」の行は Markdown の
**リスト項目**と誤認され、数式ブロックがそこで分断される。

対処の要点は4つ。全規則は `references/math-rendering.md`。

- ディスプレイ数式は `$$...$$` のみ。複数行は `$$` の内側で `aligned` を使う
- `$$` は開始・終了とも**単独行**に置く
- 数式行の行頭を記号と空白で始めない（`+ v_k` は `+v_k` と書く）
- 数式ブロック内を字下げしない（コードブロックと解釈される）

検知は静的検査とブラウザ実測の2段構え。`ruff` も `marimo check --strict` も
**一切検出しない**。

```shell
python3 ~/.claude/skills/ipynb-to-marimo-pages/scripts/check-display-math.py notebooks
```

実際に描画されたかは、ヘッドレスブラウザで `.katex-display` の数を数えるまで
確定しない（`scripts/audit-math-rendering.py`）。

## 10. ノートブック名がライブラリ名と衝突して自己 import になる

`notebooks/ml/sklearn.py` の中の `import sklearn` は、そのファイル自身を指す。
`matplotlib.py`、`open3d.py` も同様。内容を表す非衝突名へリネームし、
原本との対応表（`migration-map.json`）に記録する。

## 11. 失敗検知の正規表現が raw 文字列で壊れる

```python
# NG: r"..." の中の \\( は「バックスラッシュ + (」になり、決してマッチしない
ERROR_RE = re.compile(r"MarimoExceptionRaisedError|Traceback \\(most recent call last\\)")

# OK
ERROR_RE = re.compile(r"MarimoExceptionRaisedError|Traceback \(most recent call last\)")
```

デプロイ前の唯一の実行時エラー検査がこれだった場合、**検査が常に通る**状態に
なる。検知ロジックには「壊れた入力で必ず落ちること」を確認する試験を書く。

## 12. 部分ビルドが生成物の鮮度検査を素通りさせる

`site/` をコミットして CI ではデプロイのみ行う構成では、ソースと生成HTMLの
ハッシュを manifest に記録して鮮度を検査する。ここで `--notebook` のような
部分ビルドを追加すると、素朴な実装では**全冊のハッシュを取り直す**ため、
編集済みだが未再生成の冊まで「最新」と記録され、検査が通ってしまう。

対処：部分ビルドでは既存 manifest を読み、選択した冊の項目だけ更新する。
詳細は `references/large-scale-migration.md` の7節。

## 13. 収束判定のバグで export が終わらない

反復計算のセルは、バグると export が無限に近く伸びる。実際に、QR 反復の
収束判定が**更新前の行列**を参照していたため1冊が25分以上かかり、修正後は
11秒になった。反復には必ず上限（`max_iter`）を置き、export の所要時間を
冊ごとに記録しておくと異常に気づける。

## 14. `marimo check --fix` が三重引用符の中身を書き換える

`marimo check --fix` は、単一関数だけのセルを `@app.function` へ昇格させて
デデントする。関数内の三重引用符リテラルに意図的なインデントがあると、
その**文字列の中身が変わる**。プロンプト文字列などを持つノートブックでは、
`--fix` の後に差分を確認する。
