# 事例: Pointnet2_PyTorch を CUDA 12.8 と 13.3 へ

`erikwijmans/Pointnet2_PyTorch`（最終更新は CUDA 10 / PyTorch 1.4 の時代）を、
同一マシン上の 2 つの toolkit へ移行して全テストを通した記録。

- 環境: WSL2 / Ubuntu 24.04 / GCC 13.3 / RTX 3070 (sm_86) / ドライバは
  `nvidia-smi` が CUDA 13.1 と表示
- 移行 A: CUDA 12.8 + torch 2.11.0+cu128 → 30 passed
- 移行 B: CUDA 13.3 + torch 2.14.0+cu130 → 30 passed
- どちらも `rm -rf .venv && uv sync --locked` からの再現で 30 passed

**ソースの差分は A と B で完全に同じ**（分岐は `setup.py` の中で
`torch.version.cuda` を見て行う）。違うのは `pyproject.toml` の index と
`mise.toml` の CUDA パスだけ。

## 移行の対象範囲

CUDA に依存するのは `pointnet2_ops_lib/` だけなので、そこに絞った。
リポジトリ上位の学習コードは `hydra-core==0.11.3` と
`pytorch-lightning==0.7.1` にピン留めされていて、これは CUDA の版とは無関係な
別の移行になる。既存の `tests/` も hydra 0.11 の API に依存していて動かない
ため、CUDA ops 専用のテスト（`tests_ops/`）を新規に書いた。

## 踏んだエラー（発生順）

### 1. `nvcc fatal : Unsupported gpu architecture 'compute_37'`

```python
# pointnet2_ops_lib/setup.py（原文）
os.environ["TORCH_CUDA_ARCH_LIST"] = "3.7+PTX;5.0;6.0;6.1;6.2;7.0;7.5"
```

環境変数を**代入**しているので、外から `TORCH_CUDA_ARCH_LIST=8.6` を渡しても
無視される。sm_37 は CUDA 12 で削除済み。

```python
# 修正後
_cuda_major = int((torch.version.cuda or "0").split(".")[0])
if _cuda_major >= 13:
    _default_arch_list = "7.5;8.0;8.6;8.9;9.0;10.0;12.0+PTX"
else:
    _default_arch_list = "5.0;6.0;6.1;7.0;7.5;8.0;8.6;8.9;9.0+PTX"
os.environ.setdefault("TORCH_CUDA_ARCH_LIST", _default_arch_list)
```

同じリストが `pointnet2_utils.py` の JIT フォールバック側にも重複して
書かれていた（下記 3）。

### 2. `Attempted to use ninja as the BuildExtension backend but we could not find ninja`

`[dependency-groups] build = ["ninja", ...]` はプロジェクトの venv に入るだけで、
uv がビルド分離のために作る一時 venv には入らない。`extra-build-dependencies`
の側にも書く必要がある。ninja が無いと distutils にフォールバックし、
逐次コンパイルになって桁で遅くなる。

### 3. `undefined symbol: _ZNK3c1010TensorImpl15incref_pyobjectEv`

ビルドは成功し、`import` で落ちた。原因は**ビルド環境の torch とランタイムの
torch が別物**だったこと。`extra-build-dependencies = ["torch"]` はバージョンを
指定していないので PyPI の最新（当時 2.14.0）が入り、ランタイム側は index 経由の
2.11.0+cu128 だった。

```toml
[tool.uv.extra-build-dependencies]
pointnet2-ops = [
    { requirement = "torch", match-runtime = true },
    "setuptools>=68", "wheel>=0.44", "ninja>=1.11",
]
```

`match-runtime = true` は**静的メタデータが必要**で、最初は次で弾かれた。

```text
error: Extra build requirement `torch` was declared with `match-runtime = true`,
       but `pointnet2-ops` does not declare static metadata,
       making runtime-matching impossible
```

`setup.py` にしか名前・版・依存が書かれていなかったため。`pyproject.toml` を
新設してメタデータを移し、`setup.py` は `ext_modules` の記述だけにした。

```toml
# pointnet2_ops_lib/pyproject.toml（新規）
[project]
name = "pointnet2_ops"
version = "3.0.0"
requires-python = ">=3.10,<3.14"
dependencies = ["torch"]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["pointnet2_ops"]
include-package-data = true
```

### 4. import 失敗が JIT 再コンパイルに化ける

3 のとき、実際に出力されたのはこれだった。

```text
UserWarning: Unable to load pointnet2_ops cpp extension. JIT Compiling.
```

`pointnet2_utils.py` が `except ImportError` で `torch.utils.cpp_extension.load`
に落ち、しかもそこでも古いアーキ一覧を代入していたので、最終的に
`compute_37` のエラーが**エラーの中のエラーとして**出た。フォールバックを
削除して `import pointnet2_ops._ext as _ext` だけにした。

### 5. `exit(-1)` によりテストが消える

`cuda_utils.h` の `CUDA_CHECK_ERRORS` が `fprintf` + `exit(-1)` だった。
`TORCH_CHECK` へ置換。効果は `references/testing-cuda-ops.md` に実測を載せた。

### 6. `three_nn` の戻り値が二乗距離だった

参照実装との比較で発覚。CUDA 側は二乗距離を返し、Python ラッパが `sqrt` する。
テストを書かなければ気づかないまま「移行完了」にしていた。

## 最終的な差分

```text
 pointnet2_ops_lib/pointnet2_ops/_ext-src/include/cuda_utils.h  | 16 +++---
 pointnet2_ops_lib/pointnet2_ops/_ext-src/include/utils.h       |  8 +--
 pointnet2_ops_lib/pointnet2_ops/_ext-src/src/ball_query.cpp    |  2 +-
 pointnet2_ops_lib/pointnet2_ops/_ext-src/src/group_points.cpp  |  4 +-
 pointnet2_ops_lib/pointnet2_ops/_ext-src/src/interpolate.cpp   |  6 +-
 pointnet2_ops_lib/pointnet2_ops/_ext-src/src/sampling.cpp      |  6 +-
 pointnet2_ops_lib/pointnet2_ops/pointnet2_utils.py             | 27 +---------
 pointnet2_ops_lib/setup.py                                     | 40 ++++++-----
 pyproject.toml                                                 | 66 ++++++++++--------
 + pointnet2_ops_lib/pyproject.toml, mise.toml, tests_ops/, uv.lock
```

`.cpp` 側の差分はすべて `AT_ASSERT` → `TORCH_CHECK` の置換。`.cu` は 1 行も
変えていない（`at::cuda::getCurrentCUDAStream()` を既に使っており、THC も
`__shfl` も使っていなかった）。**CUDA 11 世代のコードでも、ビルド設定さえ
直せばカーネル本体は無変更で通ることがある。**

## CUDA 12.8 版の設定

```toml
# pyproject.toml
[project]
name = "pointnet2"
version = "3.0.0"
requires-python = ">=3.10,<3.14"
dependencies = ["torch>=2.11,<2.12", "pointnet2-ops"]

[dependency-groups]
build = ["ninja>=1.11", "setuptools>=68", "wheel>=0.44"]
dev = ["numpy>=2.0", "pytest>=8.0"]

[tool.uv]
default-groups = ["build", "dev"]

[tool.uv.sources]
torch = { index = "pytorch-cu128" }
pointnet2-ops = { path = "pointnet2_ops_lib" }

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.extra-build-dependencies]
pointnet2-ops = [
    { requirement = "torch", match-runtime = true },
    "setuptools>=68",
    "wheel>=0.44",
    "ninja>=1.11",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["pointnet2"]
```

```toml
# mise.toml
[tools]
python = "3.13"
uv = "latest"

[env]
_.path = ["/usr/local/cuda-12.8/bin"]
CUDA_HOME = "/usr/local/cuda-12.8"
LIBRARY_PATH = "/usr/local/cuda-12.8/lib64/stubs"
TORCH_CUDA_ARCH_LIST = "8.6"
MAX_JOBS = "8"

[tasks.sync]
run = "uv sync"
[tasks.rebuild]
run = "uv sync --reinstall-package pointnet2-ops"
[tasks.test]
run = "uv run pytest tests_ops -v"
```

## CUDA 13.3 版との差分

```diff
 # pyproject.toml
-dependencies = ["torch>=2.11,<2.12", "pointnet2-ops"]
+dependencies = ["torch>=2.14,<2.15", "pointnet2-ops"]
-torch = { index = "pytorch-cu128" }
+torch = { index = "pytorch-cu130" }
-name = "pytorch-cu128"
-url = "https://download.pytorch.org/whl/cu128"
+name = "pytorch-cu130"
+url = "https://download.pytorch.org/whl/cu130"

 # mise.toml
-_.path = ["/usr/local/cuda-12.8/bin"]
-CUDA_HOME = "/usr/local/cuda-12.8"
-LIBRARY_PATH = "/usr/local/cuda-12.8/lib64/stubs"
+_.path = ["/usr/local/cuda-13.3/bin"]
+CUDA_HOME = "/usr/local/cuda-13.3"
+LIBRARY_PATH = "/usr/local/cuda-13.3/lib64/stubs"
```

torch のバージョンが変わるのは、**CUDA 12 の index には 2.11 までしか無い**
ため。CUDA 13 へ行く動機は実質これになる（`references/version-matrix.md`）。

nvcc は 13.3、torch が内蔵する CUDA は 13.0 で minor がずれているが、
minor version compatibility の範囲なので全テストが通っている。

## 落とし穴（環境側）

`mise.toml` の `[env]` は**シェルの環境変数を上書きする**。

```text
$ TORCH_CUDA_ARCH_LIST=9.0 mise exec -- printenv TORCH_CUDA_ARCH_LIST
8.6
```

一時的に別のアーキで試したいときは `mise exec` を経由せず、素の
`uv sync` / `uv run` に必要な変数（`PATH`, `CUDA_HOME`, `LIBRARY_PATH`,
`TORCH_CUDA_ARCH_LIST`, `MAX_JOBS`）を自分で渡す。

## 検証結果

```text
$ mise exec -- uv run pytest tests_ops -q      # CUDA 12.8 / torch 2.11.0+cu128
30 passed in 3.01s
$ mise exec -- uv run pytest tests_ops -q      # CUDA 13.3 / torch 2.14.0+cu130
30 passed in 6.40s

$ rm -rf .venv && uv sync --locked && uv run pytest tests_ops -q
30 passed   # 両方
```

テストの内訳は 3 ファイル。

| ファイル | 内容 |
| --- | --- |
| `tests_ops/conftest.py` | 6 カーネル分の純 PyTorch 参照実装とフィクスチャ |
| `tests_ops/test_ops_correctness.py` | 参照実装との一致、勾配、中心差分、入力検証、起動設定の網羅 |
| `tests_ops/test_modules_e2e.py` | SA / MSG / FP モジュールの forward+backward、30 step の学習、autocast |
| `tests_ops/test_build_provenance.py` | JIT フォールバック検出、ABI、nvcc と torch の major 一致、fatbin の SM |
