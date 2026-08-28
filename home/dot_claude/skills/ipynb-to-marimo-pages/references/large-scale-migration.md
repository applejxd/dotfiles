# 大規模移行（数十冊）の運用

38冊の Jupyter notebook を一括で marimo へ移行し、GitHub Pages へ公開した際の
知見。数冊なら手作業で足りるが、冊数が増えると次の仕組みが必要になる。

## 1. 原本の保全と1対1検査

原本 `.ipynb` は `legacy/` へ**すべて残す**。移行の正しさを後から検証できる
唯一の基準になる。

- `legacy/**.ipynb` と `notebooks/**.py` が1対1で対応することを機械的に検査する
- リネームした notebook は対応表 `migration-map.json` に記録する
  （`{"ml/sklearn.ipynb": "ml/ridge_regression_diabetes.ipynb"}` の形）
- 検査スクリプトは「原本にない notebook」「notebook にない原本」の両方向を報告する

冊数が多いと「変換し忘れ」「原本の削除し忘れ」が必ず起きる。目視では追えない。

## 2. ファイル名がライブラリ名と衝突すると自己 import になる

`notebooks/ml/sklearn.py` は、そのノートブック自身の `import sklearn` を
横取りする。`matplotlib.py`、`open3d.py` も同じ。

```text
notebooks/ml/sklearn.py     → import sklearn がこのファイル自身を指す
notebooks/others/open3d.py  → 同上
```

**内容を表す非衝突名へリネームし、`migration-map.json` に記録する。**
`ridge_regression_diabetes.py`、`open3d_point_cloud_registration.py` のように、
何をするノートブックかが分かる名前にする。

## 3. Jupyter / Colab 依存の除去

変換直後の `.py` には、marimo では動作しない記述がそのまま残る。

| 残るもの | 対処 |
| --- | --- |
| `%matplotlib inline` などの magic | 削除 |
| `!pip install ...` | 依存を `pyproject.toml` のグループへ移す |
| `display(...)` | セル末尾の裸の式にする |
| `from google.colab import ...` | 削除し、データ取得を固定URLへ置換 |
| Colab バッジの Markdown | 削除 |
| `IPython.display` 依存 | `mo.image` / `mo.Html` へ置換 |

## 4. headless で実行できる形にする

`marimo export html` は GUI のない環境で実行される。

- **matplotlib のアニメーション**：`to_jshtml()` の結果を `mo.Html(...)` で包む。
  または GIF を生成して base64 で `mo.image("data:image/gif;base64,...")` に渡す
- **3D 描画（Open3D 等）**：offscreen レンダリングを優先し、失敗時は明示的な
  フォールバック（静止画）へ落とす。無言で失敗させない
- **TensorBoard・ipywidgets・入力待ち**：静的HTMLでは意味がないため置換する

## 5. 実行時間と決定論

全冊を実行するため、1冊の暴走が全体を止める。

- 乱数は seed を固定し、device（CPU/GPU）を明示的に選択する
- 反復計算には**必ず上限**を置く。実際に、収束判定が更新前の行列を参照していた
  バグで1冊が25分以上かかり、修正後は11秒になった
- 巨大なベンチマークは、教材としての意図を保ったまま代表的な規模へ縮小する
- 認証が必要なデータセット（Kaggle 等）は公開データか合成データへ置換する

## 6. ビルドは自動検出にする

notebook の一覧を手で管理しない。`notebooks/` を再帰的に走査し、AST で
「`marimo` を import し `app` を定義しているか」を見て判定する。
index も検出結果から生成する。追加時に一覧を更新し忘れる事故が消える。

雛形は `build-site-example.py`。

## 7. 生成物の鮮度をハッシュで保証する

`site/` をコミットして CI ではデプロイのみ行う構成では、
**ソースだけ更新して HTML を再生成し忘れる**事故が起きる。

`site/notebooks-manifest.json` に、各 notebook の
`source_sha256` と `html_sha256` を記録し、デプロイ前に照合する。

- `source_sha256` 不一致 → ソースを変えたのに再生成していない
- `html_sha256` 不一致 → 生成物が手で編集された

### 部分ビルドの落とし穴

`--notebook` で一部だけ再生成するオプションを付けると、素朴な実装では
**全 notebook のハッシュを取り直してしまう**。編集済みだが未再生成の別冊まで
「最新」として記録され、鮮度ゲートが素通りする。

対処：部分ビルド時は既存 manifest を読み込み、**選択した notebook の項目だけ**
更新する。加えて、

- 既存 manifest が無ければ部分ビルドを拒否する
- 検出した notebook 集合と manifest のキー集合が食い違えば拒否する
  （notebook の削除・追加時に全ビルドを強制できる）

## 8. 失敗の検出は stdout と HTML の両方を見る

`marimo export html` はセルが落ちても exit 0 で HTML を書き出す。次の3つを
すべて検査し、1つでも該当したら**出力を削除**して失敗扱いにする。

```python
ERROR_MARKERS = (
    "some cells failed to execute",
    "MarimoExceptionRaisedError",
    "Traceback (most recent call last)",
)
```

正規表現で書く場合、raw 文字列内の `\\(` は「バックスラッシュ + 括弧」に
なる点に注意。実際にこの誤りで `Traceback (most recent call last)` の側が
**永久にマッチしない**検査が本番へ入りかけた。

```python
# NG: r"Traceback \\(most recent call last\\)" → 実在しない文字列にマッチ
# OK
ERROR_RE = re.compile(r"MarimoExceptionRaisedError|Traceback \(most recent call last\)")
```

## 9. サイト全体の整合検査

デプロイ前に、生成物そのものを検査する。

- 全 HTML に例外マーカーが無いこと
- 全 HTML のローカルリンク（`a`, `img`, `script`, `link`, `source`, `video`）の
  参照先が実在すること
- index のリンク集合と、実在する notebook ページの集合が**完全一致**すること
  （欠落と余分の両方を報告する）

## 10. 並行作業とレビュー

- 分野ごとに担当範囲（`notebooks/simulation/**` など）を**排他的に**割り当てる。
  同じファイルを複数で触ると marimo の変数一意制約と衝突して収拾がつかない
- 一括ビルドは**2回**通す。1回目の一時状態やキャッシュに依存していないことを、
  クリーンな2回目で確認する
- 公開前に独立レビューを1回入れる。実際にこの工程で、上記8の正規表現バグと
  部分ビルドの鮮度ゲート抜けという2件の実害ある欠陥が見つかった
