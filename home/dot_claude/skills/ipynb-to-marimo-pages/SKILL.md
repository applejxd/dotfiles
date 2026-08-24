---
name: ipynb-to-marimo-pages
description: "Jupyter notebook (.ipynb) を marimo notebook へ移行し、セル分割とMarkdown解説を整え、HTML化してGitHub Pagesへ公開する。「ipynbをmarimoにして」「marimoノートブックを公開したい」「ノートブックのセルを整理して」「解説セルを整備して」と言われたときに使う。marimo以外のノートブック運用（nbconvert、Quarto、Jupyter Book）には使わない。"
context: fork
agent: general-purpose
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# ipynb → marimo → GitHub Pages 移行スキル

Jupyter notebook を marimo notebook へ移行し、学習・共有に耐える形へ整理して
静的HTMLとして公開するまでの手順。このリポジトリでの実施結果を基にしている。

## 適用範囲

対象は次の全体または一部。フェーズ単位で独立して使える。

| フェーズ | 内容 |
| --- | --- |
| 1 | `.ipynb` → marimo `.py` へ変換 |
| 2 | コードセルを意味単位へ分割 |
| 3 | Markdownセルで各セルの処理内容を解説 |
| 4 | HTML化（ノートブックを実際に実行する） |
| 5 | GitHub Pages で公開 |

**「解説セルを整備して」のようにフェーズ3だけを求められることが多い。**
その場合は全フェーズを実行せず、該当フェーズだけを行う。

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
- **元の `.ipynb` は削除せず `old/` 等へ残す。** 移行の正しさを後から検証する
  唯一の基準になる。このリポジトリは `old/` に保持し、`docs/coverage.md` で
  元教材との対応表を管理している。
- 変換直後は Jupyter 由来の「上から順に流す」構造のままで、marimo の
  依存グラフを活かせていない。フェーズ2で整理する。

変換後、まず静的検査を通す。

```shell
uv run marimo check --strict notebook.py
```

## フェーズ2：コードセルの分割

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
HTMLを書き出してしまう**。成否をログで判定し、失敗時はHTMLを破棄する必要がある。

```shell
if grep -q "some cells failed to execute" "$log"; then
    rm -f "$output"   # 壊れたHTMLを公開しない
    failed=1
fi
```

ビルドスクリプトの雛形は `references/build-site-example.sh`。
`--sandbox` は、ノートブックが PEP 723 のインライン依存を持たない場合は
付けてはならない（隔離環境で依存を解決できず失敗する）。

### 検証

```shell
grep -c 'MarimoExceptionRaisedError\|Traceback (most recent call last)' site/*.html
```

0 でなければ実行時エラーが混入している。

なお **HTML内の日本語は `\uXXXX` エスケープで格納される**。生の日本語で
`grep` しても一致しない。デコードしてから照合すること。

```shell
python3 ~/.claude/skills/ipynb-to-marimo-pages/scripts/grep-exported-html.py site/*.html -- 検索したい文字列
```

## フェーズ5：GitHub Pages 公開

**ノートブックの実行はローカル、デプロイはCI**、と分離する。こうすると
CIにAPIキーを置かずに済み、CI側で課金も発生しない。

- ローカル：`build-site.sh` でHTMLを生成し、`site/` をコミット
- CI：`site/` をアップロードするだけ（ワークフロー例は
  `references/pages-workflow-example.yml`）

注意点：

- 初回は Settings → Pages → Source を **GitHub Actions** にする必要がある。
  ワークフローに `enablement: true` を指定すれば自動化を試みるが、権限に
  よっては失敗する。その場合は手動設定してから再実行する。
- エクスポートされたHTMLは画像を相対パス `imgs/...` で参照する。
  `site/imgs/` を gitignore する運用なら、**デプロイ時にCIで復元する**。

## コミットの分割

このリポジトリでは「ノートブック本体の変更」と「HTML再生成」を
**別コミットに分ける**慣例になっている。HTMLは生成物であり、レビュー時に
本体の差分だけを追えるようにするため。

```text
docs(notebooks): 各コードセルの処理内容をMarkdownで解説
docs(site): Markdown解説を追加した状態でHTMLを再生成
```

## 検証コマンドまとめ

```shell
uv run ruff check *.py                  # 静的検査
uv run marimo check --strict *.py       # marimo の依存グラフ検査
uv run pre-commit run --all-files       # リポジトリ定義の全フック
```

**`marimo check --strict` は実行時エラーを検出しない。** `mo` が未定義で
Markdownセルが全滅していても素通りする。実行時の健全性を確かめるには
`marimo export html` まで通す必要がある。

## 参照ファイル

パスはこのスキルの base directory 基準。実体は
`~/.claude/skills/ipynb-to-marimo-pages/`（`~/.copilot/skills` はここへの symlink）。
`${CLAUDE_SKILL_DIR}` / `${COPILOT_SKILL_DIR}` は **Copilot CLI では展開されない**ため、
スクリプトを実行する際は上記の絶対パスで書く。

| ファイル | 内容 |
| --- | --- |
| `references/marimo-cell-rules.md` | セル分割時の変数ルールと構文 |
| `references/pitfalls.md` | 実際に踏んだ落とし穴と対処 |
| `references/markdown-templates.md` | Markdownセルの記述テンプレート |
| `references/build-site-example.sh` | HTML化スクリプトの雛形 |
| `references/pages-workflow-example.yml` | Pages デプロイのワークフロー例 |
| `scripts/verify-code-cells-unchanged.py` | コードセル不変の検証 |
| `scripts/audit-markdown-coverage.py` | Markdown解説の網羅状況の集計 |
| `scripts/grep-exported-html.py` | エクスポート済みHTMLの日本語検索 |
