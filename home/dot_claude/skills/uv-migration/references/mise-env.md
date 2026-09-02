# CUDA 環境変数を mise で固定する

## 公式が定めているものと、そうでないもの

まずこの区別をつける。CUDA の環境変数として世間で見かけるもののうち、
**NVIDIA が定めているのは 2 つだけ**である。

出典: NVIDIA CUDA Installation Guide for Linux, **11.1.1. Environment Setup**
<https://docs.nvidia.com/cuda/cuda-installation-guide-linux/#environment-setup>

| 変数 | 公式か | 公式の条件 |
| --- | --- | --- |
| `PATH` | **公式・必須** | 「The PATH variable needs to include `export PATH=/usr/local/cuda-<ver>/bin${PATH:+:${PATH}}`」 |
| `LD_LIBRARY_PATH` | **公式・条件付き** | 「when using the **runfile** installation method, the LD_LIBRARY_PATH variable needs to contain `/usr/local/cuda-<ver>/lib64`」（64bit の場合） |
| `CUDA_HOME` | 公式ではない | PyTorch の `torch.utils.cpp_extension` などが参照する慣習 |
| `LIBRARY_PATH` | 公式ではない | リンク時に `libcuda.so` の stub を見つけるために必要 |
| `TORCH_CUDA_ARCH_LIST` | 公式ではない | PyTorch のコード生成対象アーキテクチャ指定 |
| `MAX_JOBS` | 公式ではない | PyTorch のビルド並列度 |

**`LD_LIBRARY_PATH` は deb / rpm でインストールしたなら不要**。
パッケージが `/etc/ld.so.conf.d/` にパスを登録するためである。確認:

```bash
$ cat /etc/ld.so.conf.d/*cuda*
/usr/local/cuda/targets/x86_64-linux/lib
/usr/local/cuda-13/targets/x86_64-linux/lib
/usr/local/cuda-12/targets/x86_64-linux/lib
```

不要なのに設定すると、torch が `nvidia-*` の wheel として同梱している
CUDA ランタイム（cuBLAS, cuDNN など）をシステム側のものが覆い隠す可能性が
ある。設定するなら torch の `cu<N>` と同じバージョンにすること。

## なぜ pyproject.toml ではなく mise なのか

`/usr/local/cuda-12.8` のような**パスはマシンごとに違う**。
`pyproject.toml` に書くとリポジトリを共有した瞬間に壊れる。一方でシェルの
`.bashrc` に書くとプロジェクトごとに違う CUDA を使えず、「自分の環境では
通るのに」の温床になる。

`mise.toml` はリポジトリに置きつつ各自が上書きできる中間層としてちょうど
よい。ディレクトリに入ると自動で適用される。`uv` はビルドのサブプロセスに
親プロセスの環境をそのまま渡すので、`mise` の設定は分離されたビルド環境
にも届く。

## 最小構成

```toml
min_version = "2024.1.1"

[env]
# --- NVIDIA CUDA Installation Guide for Linux, 11.1.1 Environment Setup ---
# "The PATH variable needs to include
#      export PATH=/usr/local/cuda-12.8/bin${PATH:+:${PATH}}"
# mise の `_.path` は PATH に前置するので、上の 1 行と等価。
_.path = ["/usr/local/cuda-12.8/bin"]
#
# 同節の LD_LIBRARY_PATH は runfile インストールのときだけ必要。
# deb / rpm なら /etc/ld.so.conf.d が処理済みなので設定しない。
#   LD_LIBRARY_PATH = "/usr/local/cuda-12.8/lib64"
# --------------------------------------------------------------------------

# 以下は公式ガイドの範囲外
CUDA_HOME = "/usr/local/cuda-12.8"
LIBRARY_PATH = "/usr/local/cuda-12.8/lib64/stubs"
TORCH_CUDA_ARCH_LIST = "8.6"
MAX_JOBS = "8"

[tasks.sync]
run = "uv sync"
```

Python 自体は uv に管理させる（`requires-python` と `uv.lock` で決まる）。
`mise` の `[tools]` にも `python` を書くと二重管理になり、`uv` が作る venv
と `mise` が入れた python がずれる。**どちらか一方にする。**

## 各変数の決め方

### PATH（公式・必須）

**前置**すること。公式ガイドの `${PATH:+:${PATH}}` 形式は前置である
（同節には追記形の例も併記されているが、複数の CUDA が同居する環境では
前置でないと意図しない `nvcc` が勝つ）。

`CUDA_HOME` だけ設定して `PATH` を揃え忘れると、`setup.py` が
`which nvcc` でバージョンを判定する種類のパッケージで矛盾が起きる。
`references/cuda-extensions.md` の「CUDA_HOME だけでは足りない」を参照。

### CUDA_HOME（PyTorch の慣習）

torch のローカルバージョン識別子と一致させる。

```bash
uv run python -c "import torch; print(torch.version.cuda)"   # 12.8
printf '%s\n' /usr/local/cuda*/bin/nvcc                      # 入っている toolkit
```

`nvcc --version`（= `/usr/local/cuda` が指す先）を鵜呑みにしない。
複数バージョンが同居していることが多い。

特に **CUDA 13 は sm_50/60/70 のコード生成を削除した**ので、古い
アーキテクチャを決め打ちしている `setup.py` は CUDA 12.x が要る。

### LIBRARY_PATH（リンク時のみ）

`LD_LIBRARY_PATH`（実行時）と別物である点に注意。`libcuda.so` は
ドライバの提供物で toolkit には無く、リンク用の stub が
`$CUDA_HOME/lib64/stubs` に置かれているが既定の検索パスに入っていない。

### TORCH_CUDA_ARCH_LIST

| GPU | 値 |
| --- | --- |
| RTX 20xx | `7.5` |
| A100 | `8.0` |
| RTX 30xx | `8.6` |
| RTX 40xx | `8.9` |
| H100 | `9.0` |
| RTX 50xx | `12.0` |

```bash
uv run python -c "import torch; print('%d.%d' % torch.cuda.get_device_capability(0))"
```

配布用バイナリを作るのでなければ自分の GPU の 1 つで十分。未来の GPU でも
動かしたいときだけ `8.6+PTX` のように PTX を足す。CI など GPU の無い環境で
ビルドする場合は必ず明示する（torch は GPU を検出できないと既定の長い
リストを使い、ビルドが数倍に伸びる）。

なお `setup.py` 側でこの変数を上書きするパッケージがあり、その場合 mise の
設定は効かない（`references/cuda-extensions.md` を参照）。

## uv 側で環境変数を渡す方法

パッケージ単位でビルド時の環境変数を指定したいときは uv にも機能がある。

```toml
[tool.uv.extra-build-variables]
some-cuda-ext = { TORCH_CUDA_ARCH_LIST = "8.6" }
```

ただし**絶対パスをここに書かない**。マシン依存の値は `mise.toml` の
`[env]` に、マシンに依存しない値は `pyproject.toml` に、と分けるのが安全。

## mise を使わない場合

公式ガイドどおり `export` すればよい。CI ではこれが素直。

```bash
export PATH=/usr/local/cuda-12.8/bin${PATH:+:${PATH}}
export CUDA_HOME=/usr/local/cuda-12.8
export LIBRARY_PATH=/usr/local/cuda-12.8/lib64/stubs${LIBRARY_PATH:+:${LIBRARY_PATH}}
export TORCH_CUDA_ARCH_LIST=8.6
uv sync
```

`.env` に書いて `UV_ENV_FILE=.env uv sync` でもよい。対話的な開発では
`mise` の方が「ディレクトリに入ると効く」ぶん事故が少ない。
