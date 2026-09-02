# torch を pyproject.toml だけで解決する

## 何を決めるのか

torch の wheel は `torch==2.10.0+cu128` のように **CUDA バージョンがローカル
バージョン識別子として wheel に焼き込まれている**。つまり「どの CUDA 向けの
torch を入れるか」は解決時に決める必要があり、`torch` とだけ書くと PyPI の
既定ビルドが入る。

決めるべきは 3 つ。

1. torch のバージョン
2. CUDA のバージョン（`cu128` など）
3. Python のバージョン（wheel の cp タグ）

## 基本形

```toml
[project]
requires-python = ">=3.10,<3.13"
dependencies = ["torch>=2.10,<2.11"]

[tool.uv.sources]
torch = { index = "pytorch-cu128" }

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true
```

### `explicit = true` は必須

これが無いと uv は **全パッケージ**を PyTorch のインデックスからも探す。
PyTorch のインデックスは PyPI のミラーではないので、無関係なパッケージの
解決が壊れたり、古いバージョンに落ちたりする。`explicit = true` にすると
「`[tool.uv.sources]` で明示的にこのインデックスを指したパッケージだけ」が
対象になる。

`torchvision` / `torchaudio` を使うなら、それぞれ `[tool.uv.sources]` に
同じインデックスを書く。書き忘れると PyPI 版が入り、torch と ABI が
食い違う。

## CUDA バージョンの選び方

ドライバは**前方互換**なので、ドライバの CUDA バージョン以下の wheel なら
動く。`nvidia-smi` の "CUDA Version" はドライバが対応する上限であって、
インストール済み toolkit のバージョンではない。

```console
$ nvidia-smi | head -3
| NVIDIA-SMI 590.57   Driver Version: 591.86   CUDA Version: 13.1 |
```

この場合 cu118 / cu124 / cu126 / cu128 / cu130 いずれの wheel も動く。

**GPU の compute capability も確認する**。新しい CUDA ほど古い世代を切る。

| GPU | sm | 備考 |
| --- | --- | --- |
| GTX 10xx (Pascal) | 6.1 | CUDA 13 で削除 |
| RTX 20xx (Turing) | 7.5 | |
| A100 | 8.0 | |
| RTX 30xx (Ampere) | 8.6 | |
| RTX 40xx (Ada) | 8.9 | |
| H100 (Hopper) | 9.0 | |
| RTX 50xx (Blackwell) | 12.0 | cu128 以降が必要 |

```bash
uv run python -c "import torch; print(torch.cuda.get_device_capability(0))"
```

**CUDA 拡張をソースからビルドするなら、`cu<N>` は「インストール済みの CUDA
Toolkit と一致するもの」を選ぶ**。torch が cu128 なら nvcc も 12.8 を使う。
これが `references/mise-env.md` の `CUDA_HOME` の話につながる。

## uv のバージョンによる差

`--torch-backend=auto`（環境変数 `UV_TORCH_BACKEND`）は **`uv pip install`
専用**で、uv 0.8.12 の `uv sync` には無い。

```bash
$ uv sync --help | grep torch-backend      # 何も出ない
$ uv pip install --help | grep torch-backend
      --torch-backend <TORCH_BACKEND>   [env: UV_TORCH_BACKEND=]
```

`uv pip` を使うと「pip の手動実行をやめる」という移行の目的から外れるので、
プロジェクト管理では常に `[[tool.uv.index]]` を明示する。副次的な利点として、
インデックスが pyproject に書かれることで**マシンに依存せず同じ wheel が
入る**（`auto` は実行環境のドライバを見て毎回変わりうる）。

## CPU 版へのフォールバック

CI など GPU の無い環境も同じ pyproject で回したい場合は、環境マーカーでは
なく extra で分ける。CUDA の有無はマーカーで表現できない。

```toml
[project.optional-dependencies]
cpu = ["torch>=2.10,<2.11"]

[tool.uv.sources]
torch = [
  { index = "pytorch-cpu", extra = "cpu" },
  { index = "pytorch-cu128", extra = "cu128" },
]
```

`uv sync --extra cpu` / `uv sync --extra cu128` で切り替える。両方を同時に
入れないよう `[tool.uv] conflicts` で排他を宣言しておく。

```toml
[tool.uv]
conflicts = [[{ extra = "cpu" }, { extra = "cu128" }]]
```

## ダウンロード量の見積り

torch + 依存する `nvidia-*` パッケージで **3〜4 GB** ある。回線が細い環境
では 1 時間以上かかる。uv は途中で中断すると再開しないので、`uv sync` は
止めずに最後まで走らせる。

複数プロジェクトを移行するときは **Python バージョンを揃える**。uv の
キャッシュ（`~/.cache/uv`）は wheel 単位なので、cp312 で揃えれば 2 つ目
以降は再ダウンロードが発生しない。
