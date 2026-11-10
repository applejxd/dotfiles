# ケーススタディ

実際に移行して GPU 上で動作確認した 2 リポジトリの記録。検証環境は
WSL2 / RTX 3070 (sm_86) / ドライバ CUDA 13.1 / CUDA Toolkit 12.8・12.9・13.3
併存 / uv 0.8.12。

## 1. chrischoy/FCGF — pip + requirements.txt からの移行

### FCGF の移行前

- `requirements.txt` に `MinkowskiEngine` と `# pytorch # for anaconda,
  please refer to pytorch.org for installation` というコメント行
- README は `pip install torch==2.5.1 --index-url ...` と WarpConvNet の
  wheel を GitHub Releases から直接入れる手順
- Python のパッケージ定義そのものが無い

### 移行後の pyproject.toml

```toml
[project]
name = "fcgf"
version = "0.1.0"
requires-python = ">=3.10,<3.13"
dependencies = [
  "easydict>=1.13", "huggingface-hub>=0.34", "joblib>=1.4",
  "matplotlib>=3.9", "numpy>=1.26,<3", "open3d>=0.19", "plyfile>=1.0",
  "scikit-learn>=1.5", "scipy>=1.13", "tensorboardx>=2.6",
  "torch>=2.10,<2.11",
  "warpconvnet>=1.8.2",
]

[dependency-groups]
build = ["ninja>=1.11", "pybind11>=2.13", "setuptools>=68", "setuptools-scm<10", "wheel>=0.44"]
dev = ["pytest>=8.3"]

[tool.uv]
package = false
default-groups = ["build", "dev"]
no-build-isolation-package = ["warpconvnet"]

[tool.uv.sources]
torch = { index = "pytorch-cu128" }

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true
```

`[tool.uv] package = false` に注目。FCGF は `wcn/` `lib/` `model/` が
リポジトリ直下に並ぶ研究コードで、インストール可能なパッケージの体を
なしていない。仮想プロジェクト扱いにすると build backend の設定が一切
不要になり、`uv run python wcn/smoke.py` でそのまま動く。

### FCGF の結果

- 解決: 123 パッケージ
- `uv sync` **1 回**で完了。うち warpconvnet のソースビルドが 9 分 43 秒
  （`.cu` 71 ファイル、`TORCH_CUDA_ARCH_LIST=8.6`、`MAX_JOBS=8`）
- `torch 2.10.0+cu128` / Python 3.12.9
- `.venv` を消して `uv sync --locked` で再現することを確認

```console
$ uv run python wcn/smoke.py
[build] ResUNetBN2C params = 8.753M
[order] offsets match=True  coords match row-for-row=True
[feat] out dim=32  mean L2 norm=1.0000 (expect ~1.0)
[bwd] finite grads on 66/66 params
[overfit] first=1.7358  last=0.1290  drop=1.6068
SMOKE PASSED
```

Open3D のデモ点群 (`o3d.data.DemoICPPointClouds`) を使った実データ検証:

```text
[data]  Open3D DemoICPPointClouds: 198835 / 137833 points
[feat]   (17703, 32) / (12716, 32)
[ransac] fitness=0.6536 inlier_rmse=0.0154
[icp]    fitness=0.6346 inlier_rmse=0.0122
[eval]   rotation error=2.31 deg  translation error=0.199 m
REGISTRATION PASSED
```

### 踏んだ問題

1. **`/usr/bin/ld: -lcuda が見つかりません`**。71 個の `.cu` が全て
   コンパイルできた後、リンクだけ失敗する。`LIBRARY_PATH` に
   `$CUDA_HOME/lib64/stubs` を追加して解決。
2. **`identifier "PFN_cuTensorMapEncodeTiled" is undefined`**。`CUDA_HOME`
   は 12.8 なのに `PATH` の `nvcc` が 13.3 だったため。`setup.py` が
   `which nvcc` でバージョンを判定してマクロを切り替えていた。
3. **静かな縮退**。`warpconvnet/setup.py` は torch が import できないと
   拡張なしでビルドを完了させる。`no-build-isolation-package` を外すと
   `import warpconvnet` は通るのにカーネルが無い状態になる。

## 2. MIT-SPARK/BUFFER-X — conda + install.sh からの移行

### BUFFER-X の移行前

```bash
conda create -n bufferx python=3.11 -y
conda activate bufferx
./scripts/install.sh --cuda cu124 --with-hub
```

`install.sh` は 200 行あり、apt パッケージ、torch、`pip install -e .`、
そして 3 つの CUDA 拡張の git clone + `pip install --no-build-isolation` を
順に実行する。`pyproject.toml` は存在したが、pure-Python の依存だけを
`runtime` extra に持っていて、torch も CUDA 拡張も宣言されていなかった。

### 移行の要点

`install.sh` の各関数を pyproject の対応物へ置き換える。

| install.sh | 移行先 |
| --- | --- |
| `install_system_packages()` | README の前提条件（apt）に残す |
| `install_torch()` | `[tool.uv.sources]` + `[[tool.uv.index]]` |
| `install_python_package()` | `[project] dependencies`（`runtime` extra を昇格） |
| `install_cuda_extensions()` | `[tool.uv.sources]` の git + `extra-build-dependencies` |
| `pip install --upgrade setuptools wheel ninja` | `[dependency-groups] build` |

```toml
[project]
dependencies = [
  # ... requirements/base.txt の内容 ...
  "torch", "torchvision",
  "knn-cuda", "pointnet2-ops", "torch-batch-svd",
]

[dependency-groups]
build = ["ninja>=1.11", "setuptools>=68", "wheel>=0.44"]

[tool.uv]
default-groups = ["build"]

[tool.uv.extra-build-dependencies]
pointnet2-ops = ["torch", "setuptools", "wheel"]
knn-cuda = ["torch", "setuptools", "wheel"]
torch-batch-svd = ["torch", "setuptools", "wheel"]

[tool.uv.sources]
torch = { index = "pytorch-cu128" }
torchvision = { index = "pytorch-cu128" }
pointnet2-ops = { git = "https://github.com/LucasColas/Pointnet2_PyTorch.git", subdirectory = "pointnet2_ops_lib" }
knn-cuda = { git = "https://github.com/MinkyunSeo/knn_cuda.git", rev = "8b21dbfc86988f56588a5ed8ca3cc354122c5656" }
torch-batch-svd = { git = "https://github.com/KinglittleQ/torch-batch-svd.git" }
```

**git ソースでは `no-build-isolation-package` が使えない。** 最初はそう
書いて次のエラーで止まった。

```text
× Failed to build `pointnet2-ops @ git+https://github.com/LucasColas/Pointnet2_PyTorch.git#subdirectory=pointnet2_ops_lib`
╰─▶ ModuleNotFoundError: No module named 'setuptools'
```

git チェックアウトには `PKG-INFO` が無いため、uv は**解決の段階で**
`prepare_metadata_for_build_wheel` を呼ぶ。分離を切っているとその実行先は
まだ空のプロジェクト venv になる。`--no-install-package` でも回避できない。
`extra-build-dependencies` でビルド環境側に注入するのが正解。

### 未使用の依存を落とす

`cpp_wrappers/`（`grid_subsampling`, `radius_neighbors`）は
`compile_wrappers.sh` でビルドされ `install.sh` からも呼ばれていたが、
**どの Python モジュールからも import されていなかった**（KPConv 由来の
名残）。移行対象から外した。

```bash
grep -rn "grid_subsampling\|radius_neighbors" --include=*.py . | grep -v ^./cpp_wrappers
# 出力なし
```

### BUFFER-X の結果

- 解決: 126 パッケージ、`uv sync` 1 回
- `torch 2.11.0+cu128` / `torchvision 0.26.0+cu128` / Python 3.12
- git ソースは `uv.lock` にコミット SHA で固定される

```toml
source = { git = "https://github.com/LucasColas/Pointnet2_PyTorch.git?subdirectory=pointnet2_ops_lib#cc9068764276c039921b940260a2a44b178a7f7d" }
source = { git = "https://github.com/MinkyunSeo/knn_cuda.git?rev=8b21...#8b21dbfc86988f56588a5ed8ca3cc354122c5656" }
source = { git = "https://github.com/KinglittleQ/torch-batch-svd.git#c0a96119187f7d55f939d2ff2b92942c6d6ca930" }
```

3 つの拡張が実際に GPU カーネルを実行することを確認:

```text
fps (2, 128)
knn (2, 8, 50)
svd err 1.9073486328125e-06
ALL CUDA KERNELS OK
```

BUFFER-X 自身のモデルコードを Open3D デモ点群に通した結果:

```text
[cfg]  patch.des_r=0.3 patch_sample=512
[data] Open3D DemoICPPointClouds[0] downsampled to 4760 points
[model] MiniSpinNet params = 0.425M
[out]  desc: (512, 32) torch.float32
[out]  equi: (512, 32, 7, 20) torch.float32
SMOKE PASSED
```

### torch のバージョンを揃え損ねた

BUFFER-X 側は `torch` をバージョン指定なしで書いたため `2.11.0+cu128` が
選ばれ、FCGF の `2.10.0+cu128` とキャッシュを共有できず 4 GB を再度
ダウンロードした（回線が 0.5 MB/s だったので 1 時間以上）。**複数の
プロジェクトを移行するときは torch のバージョンと Python のバージョンを
揃える。**

## 共通の mise.toml

`PATH` の設定だけが NVIDIA CUDA Installation Guide for Linux
**11.1.1. Environment Setup** の定める必須項目で、`LD_LIBRARY_PATH` は
runfile インストールのときだけ必要（deb / rpm なら `/etc/ld.so.conf.d/` が
処理済み）。残りは PyTorch 側の都合である。

```toml
[env]
# NVIDIA 公式: export PATH=/usr/local/cuda-12.8/bin${PATH:+:${PATH}} と等価
_.path = ["/usr/local/cuda-12.8/bin"]
# NVIDIA 公式だが runfile インストール時のみ:
#   LD_LIBRARY_PATH = "/usr/local/cuda-12.8/lib64"

# ここから下は公式ガイドの範囲外
CUDA_HOME = "/usr/local/cuda-12.8"
LIBRARY_PATH = "/usr/local/cuda-12.8/lib64/stubs"
TORCH_CUDA_ARCH_LIST = "8.6"
MAX_JOBS = "8"

[tasks.sync]
run = "uv sync"
```

`CUDA_HOME` と `_.path` は必ず同じ CUDA を指すこと。片方だけ設定すると
ケーススタディ 1 の問題 2 が起きる。

この構成で `.venv` とビルドキャッシュを消してから `mise run sync` を
実行し、両リポジトリともソースビルドを含めて再現することを確認した。
