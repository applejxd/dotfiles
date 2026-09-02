# CUDA 拡張を uv でビルドする

`setup.py` の冒頭で `from torch.utils.cpp_extension import CUDAExtension` を
する類のパッケージ（pointnet2_ops, MinkowskiEngine, torch-batch-svd,
warpconvnet, flash-attn など）は、uv の既定のビルド分離下では torch が
見えず失敗する。ここが移行で最も詰まる部分。

## まず入手元を確認する

PyPI に wheel があるならこの文書は不要。ソースビルドが要るのは、

- PyPI に sdist しか無い（例: `warpconvnet` は 1.5.0〜1.8.2 が全て `.tar.gz`）
- PyPI に無く GitHub にしか無い（例: `pointnet2_ops`, `KNN_CUDA`,
  `torch_batch_svd` は `pypi.org/simple/<name>/` が全て 404）

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/simple/<name>/
```

## 分岐: 入手元によって使う機能が違う

**これを間違えると解決段階で詰む。**

| 入手元 | メタデータ | 使う機能 |
| --- | --- | --- |
| PyPI の sdist | `PKG-INFO` があるのでビルド不要で読める | `no-build-isolation-package`（`uv sync` 1 回で通る） |
| git / ローカルパス | 無いので `prepare_metadata_for_build_wheel` が走る | `extra-build-dependencies`（分離は維持） |

### PyPI sdist の場合: no-build-isolation

```toml
[project]
dependencies = ["torch>=2.10,<2.11", "warpconvnet>=1.8.2"]

[dependency-groups]
build = ["ninja>=1.11", "pybind11>=2.13", "setuptools>=68", "setuptools-scm<10", "wheel>=0.44"]

[tool.uv]
default-groups = ["build"]
no-build-isolation-package = ["warpconvnet"]
```

これで `uv sync` **1 回**で通る。uv は先にバイナリ wheel をプロジェクトの
venv へインストールしてから、分離を切ったパッケージをその venv を使って
ビルドするためである。

ビルド分離を切ると `build-system.requires` は無視され、プロジェクトの venv
だけが見える。そのため `setuptools` / `wheel` / `ninja` などのビルド
バックエンドを `[dependency-groups]` に入れて venv 側に置く必要がある。

うまくいかない場合の切り分けとして 2 段階に分けることもできる。

```bash
uv sync --no-install-package warpconvnet   # torch とビルドバックエンドだけ
uv sync                                     # 拡張を建てる
```

### git ソースの場合: extra-build-dependencies

git チェックアウトには `PKG-INFO` が無いので、uv は **解決の段階で**
メタデータ生成のためにビルドバックエンドを起動する。このとき venv はまだ
空なので、`no-build-isolation-package` を指定していると次で落ちる。

```text
× Failed to build `pointnet2-ops @ git+https://.../Pointnet2_PyTorch.git`
╰─▶ ModuleNotFoundError: No module named 'setuptools'
```

`--no-install-package` を付けても回避できない。インストールを飛ばすだけで
解決はするからである。鶏と卵になるので、分離は維持したまま**ビルド環境の
側に** torch を注入する。

```toml
[tool.uv.extra-build-dependencies]
pointnet2-ops = ["torch", "setuptools", "wheel"]
knn-cuda = ["torch", "setuptools", "wheel"]
torch-batch-svd = ["torch", "setuptools", "wheel"]
```

これなら `uv sync` 1 回で通る。ビルド環境の torch は
`[tool.uv.sources]` の指定に従うので、ランタイムと同じ wheel が使われる
（`torch>=2.10,<2.11` のように範囲を狭く切っておくこと。ビルド時と実行時で
torch のマイナーバージョンがずれると ABI が合わず `undefined symbol` で
落ちる）。

`extra-build-dependencies` は preview 扱いなので `uv sync` のたびに警告が
出る。`[tool.uv] preview-features = [...]` で黙らせようとしないこと。この
キーは uv 0.8.12 には存在せず、**`[tool.uv]` に未知のキーが 1 つでもあると
uv はセクション全体を破棄する**。しかも止まるのではなく警告だけ出して続行
するので、`extra-build-dependencies` が無効化されたままビルドが走り、元の
`ModuleNotFoundError` に戻る。

```text
warning: Failed to parse `pyproject.toml` during settings discovery:
  unknown field `preview-features`, expected one of `required-version`, ...
```

`[tool.uv]` を編集したら、この warning が出ていないことを必ず確認する。

## 静かに壊れるパターン

**最も危険な失敗は、失敗しないこと。** 一部のパッケージは torch が
import できないと拡張なしのビルドに縮退し、**インストールは成功する**。

`warpconvnet` の `setup.py` は実際にこう書かれている。

```python
# Allow sdist generation without torch installed.
# When torch is not available, setup() runs with no ext_modules (source-only).
try:
    import torch
    ...
except ImportError:
    ...
# Defaults for sdist-only mode (no torch)
```

この状態でも `import warpconvnet` は通り、`from warpconvnet.models.fcgf
import ResUNetBN2C` も通る。落ちるのは実際に GPU カーネルを呼んだとき。

**必ずネイティブモジュールの実体を確認する。**

```bash
uv run python -c "
import importlib.util
spec = importlib.util.find_spec('warpconvnet._C')
assert spec, 'MISSING: degraded build without CUDA kernels'
print(spec.origin)
"
```

`.so` のパスが出れば本物。`None` なら縮退ビルド。

## `/usr/bin/ld: cannot find -lcuda`

全ての `.cu` のコンパイルが通った後、**リンクだけ**が失敗する。

```text
/usr/bin/ld: -lcuda が見つかりません
collect2: error: ld returned 1 exit status
```

`libcuda.so` は CUDA Toolkit ではなく**ドライバ**が提供する。リンク用の
スタブは `$CUDA_HOME/lib64/stubs/libcuda.so` にあるが、このディレクトリは
リンカの既定検索パスに入っていない。

```bash
export LIBRARY_PATH="$CUDA_HOME/lib64/stubs${LIBRARY_PATH:+:$LIBRARY_PATH}"
```

`LD_LIBRARY_PATH`（実行時の検索パス）ではなく `LIBRARY_PATH`（リンク時の
検索パス）である点に注意。NVIDIA の公式ガイドが 11.1.1 で触れているのは
前者だけで、しかも runfile インストールのときに限られる。`LIBRARY_PATH` は
公式ガイドには出てこない、拡張をビルドする側の都合である。

スタブに対してリンクしても SONAME は `libcuda.so.1` なので、実行時には
本物のドライバライブラリが解決される。

WSL2 では本物のドライバライブラリが `/usr/lib/wsl/lib/libcuda.so.1` に
あり、`ldconfig` の対象ではあるがリンク用の `libcuda.so` シンボリック
リンクとしては使えないことがある。上のスタブ指定で解決する。

## CUDA_HOME だけでは足りない: PATH の nvcc も揃える

`CUDA_HOME` を正しく設定しても、`PATH` 上の `nvcc` が別バージョンだと壊れる
ことがある。`setup.py` が `which nvcc` で toolkit を探し、そのバージョンに
応じてマクロを切り替える実装になっているためである。

```python
# warpconvnet/setup.py
result = subprocess.run(["which", "nvcc"], capture_output=True, text=True)
```

CUDA 13.3 が `PATH` の先頭にあり `CUDA_HOME` が 12.8 を指している状態で
実際に起きたエラー:

```text
/usr/local/cuda-12.8/bin/nvcc
error: identifier "PFN_cuTensorMapEncodeTiled" is undefined
error: identifier "PFN_cuTensorMapEncodeIm2col" is undefined
2 errors detected in the compilation of ...
```

コンパイラ自体は 12.8 が使われているのに、マクロは 13.3 向けに選ばれている
ため辻褄が合っていない。

`PATH` の設定は NVIDIA CUDA Installation Guide for Linux の
**11.1.1. Environment Setup** が定める必須手順でもある。

```bash
export PATH=/usr/local/cuda-12.8/bin${PATH:+:${PATH}}
```

`CUDA_HOME`（PyTorch の慣習であり公式ガイドには無い）とは必ずセットで、
同じバージョンを指すようにする。詳細は `references/mise-env.md`。

```toml
[env]
_.path = ["/usr/local/cuda-12.8/bin"]   # 公式ガイドの PATH 前置と等価
CUDA_HOME = "/usr/local/cuda-12.8"
```

## setup.py が環境変数を上書きしてくる

`TORCH_CUDA_ARCH_LIST` を設定しても効かないことがある。`setup.py` が
自分で代入しているためである。

```python
# pointnet2_ops_lib/setup.py
os.environ["TORCH_CUDA_ARCH_LIST"] = "5.0;6.0;6.1;6.2;7.0;7.5;8.0;8.6;8.7;8.9;9.0+PTX"
```

```python
# knn_cuda/setup.py
os.environ["TORCH_CUDA_ARCH_LIST"] = "5.0;6.0;6.1;6.2;7.0;7.5;8.0;8.6;8.9;9.0"
```

このとき起きること:

- **ビルドが非常に長くなる**（アーキテクチャの数だけコード生成する）
- **新しい nvcc で失敗する**。CUDA 13 は sm_50 / 60 / 70 世代を削除したので、
  上のリストは `nvcc fatal: Unsupported gpu architecture 'compute_50'` に
  なる。**この種のパッケージは CUDA 12.x の toolkit でビルドすること。**

複数の CUDA を入れている環境では `CUDA_HOME` で明示的に選ぶ。
`nvcc --version` が返すのは `/usr/local/cuda` が指す先であって、torch が
必要とするものとは限らない。

## git 由来のバージョン採番

`setup.py` の中で git を叩くものがある。

```python
# torch-batch-svd/setup.py
rev = "+" + subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode("ascii").rstrip()
```

uv の git ソースはチェックアウトに `.git` を残すので通るが、tarball 展開や
`path` ソースにするとここで落ちる。その場合は `setuptools-scm` の
`SETUPTOOLS_SCM_PRETEND_VERSION` に相当する回避が要る。

## ビルド並列度とメモリ

`MAX_JOBS` を指定しないと `ninja` が論理コア数だけ並列に走り、nvcc の
プロセスがメモリを食い潰して OOM で落ちる。物理コア数の半分程度から始める。

```toml
MAX_JOBS = "8"
```

## 検証チェックリスト

1. `uv sync` を `.venv` を消した状態から通す
2. `importlib.util.find_spec("<pkg>._C")` が `.so` を返す
3. `torch.cuda.is_available()` が `True`
4. リポジトリの smoke test / demo を GPU で走らせる
