# marimo Markdown の数式レンダリング

marimo の `mo.md()` は Markdown を KaTeX で描画する。Jupyter（MathJax）で
表示できていた記法の一部が**そのまま生テキストとして表示される**ため、
移行後に必ず検査する。

実際に38冊のノートブックを移行した際、この問題だけで3回の修正コミットが必要になった。

## 1. 使える記法・使えない記法

| 記法 | 可否 | 備考 |
| --- | --- | --- |
| `$...$` | ✅ | インライン数式 |
| `$$ ... $$` | ✅ | ディスプレイ数式。**唯一の推奨形** |
| `\begin{aligned}...\end{aligned}` | ✅ | `$$` の**内側**に置く |
| `\begin{pmatrix}`, `\begin{cases}` | ✅ | `$$` の内側 |
| `\[ ... \]` | ❌ | 生の `\[` が表示される |
| `\begin{equation}...\end{equation}` | ❌ | Jupyter からの変換直後に大量に残る |
| `\begin{align}`, `\begin{split}`, `\begin{gather}`, `\begin{eqnarray}` | ❌ | 同上。`aligned` へ置換する |

変換直後の `.py` には `\begin{equation}` が残っていることが多い。まとめて
`$$` へ置換する。

```python
# NG（Jupyter からの変換直後）
\begin{equation}
E = mc^2
\end{equation}

# OK
$$
E = mc^2
$$
```

## 2. `$$` は必ず単独行に置く

`$$\begin{aligned}` のように本文と同じ行へ書くと、Markdown 側の処理と
干渉して描画が崩れる場合がある。開始・終了とも `$$` だけの行にする。

```python
# NG
$$\begin{aligned}
a &= b \\
c &= d
\end{aligned}$$

# OK
$$
\begin{aligned}
a &= b \\
c &= d
\end{aligned}
$$
```

## 3. ディスプレイ数式の行頭を「記号 + 空白」で始めない

行頭が `+`, `-`, `*`, `1.` に続けて空白を持つ行は、Markdown が**リスト項目**と
誤認し、数式ブロックがそこで分断される。演算子の直後の空白を削るだけで解決する。

```python
# NG: 「+ v_k」が箇条書きとして解釈される
$$
\begin{pmatrix} x_k \\ y_k \end{pmatrix}
+ v_k,\quad v_k\sim N(0,\sigma^2 I)
$$

# OK
$$
\begin{pmatrix} x_k \\ y_k \end{pmatrix}
+v_k,\quad v_k\sim N(0,\sigma^2 I)
$$
```

行頭を演算子で始めたい場合は、前の行の末尾へ寄せるか `\quad` を挟む。

## 4. 数式ブロック内を字下げしない

`mo.md(r"""...""")` の中身は marimo がインデントを除去してから Markdown へ
渡す。基準よりさらに深く字下げすると**コードブロック**と解釈される。
数式の行は本文と同じ深さに揃える。

```python
# NG
$$
    \vec{k}_1 = f(t, \vec{x})
$$

# OK
$$
\vec{k}_1 = f(t, \vec{x})
$$
```

## 5. `\|` より `\Vert` を使う

`D_{\mathrm{KL}}(q \,\|\, p)` は `\|` の解釈が不安定になることがある。
`\Vert` を使うと確実に描画される。

## 静的検査

書式違反はコミット前に機械的に検出できる。

```shell
python3 ~/.claude/skills/ipynb-to-marimo-pages/scripts/check-display-math.py notebooks
```

検出する内容:

- 使用不可のディスプレイ数式デリミタ（`\[`, `\begin{equation}` など）
- `$$` の数が奇数（対応が取れていない）
- `$$` が単独行になっていない
- ディスプレイ数式内のリスト項目に見える行
- 閉じていない Markdown コードフェンス

CI（Pages のデプロイ前）にも組み込むと、レンダリング崩れの再発を防げる。

## 実レンダリング検査

静的検査は書式しか見ない。**KaTeX が実際に描画できたか**は、生成済み HTML を
ヘッドレスブラウザで開いて確認する。

```shell
uv run --with playwright python \
  ~/.claude/skills/ipynb-to-marimo-pages/scripts/audit-math-rendering.py \
  --site site --notebooks notebooks
# 初回のみ: uv run --with playwright playwright install chromium
```

- ソース内の `$$` の対数 = ページ内の `.katex-display` の数、を照合する
- `.katex-error` が1つでもあれば失敗
- console エラーは、数式描画に関係するものだけを失敗条件に使う
  （資産の404などは `other_console_errors` として報告のみ）

**HTML を目視・grep するだけでは不十分。** marimo の HTML は Markdown を
JSON として埋め込み、描画はブラウザ上で行われるため、崩れているかどうかは
DOM を見ないと判定できない。

## 検査で漏れる領域

数式が「描画されている」ことと「正しい」ことは別問題。添字や係数の誤りは
どちらの検査でも検出できない。数式は必ず対応するコードと突き合わせて確認する。
