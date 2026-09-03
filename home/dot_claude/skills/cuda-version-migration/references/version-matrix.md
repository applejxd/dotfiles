# バージョンの対応表

移行先を決めるとき、揃える必要があるのは 4 つ。**どれか 1 つでも外すと、
ビルドは通るのに実行時に落ちる**という形で表面化する。

| 決めるもの | 確認方法 | 制約 |
| --- | --- | --- |
| GPU の SM | `torch.cuda.get_device_capability()` | ここ向けのコードが `.so` に無いと動かない |
| ドライバ | `nvidia-smi` の `CUDA Version` | toolkit の major がこれを超えると動かない |
| toolkit（nvcc） | `nvcc --version`（`$CUDA_HOME/bin` のもの） | 削除された SM はコンパイルできない |
| torch wheel | `torch.version.cuda` | nvcc と **major が一致**していること |

`nvidia-smi` の `CUDA Version` は**ドライバが対応する CUDA の上限**であり、
インストールされている toolkit ではない。両者は普通に食い違う（実測環境:
ドライバは 13.1 表示、toolkit は 12.8 / 12.9 / 13.3 が同居）。

## 削除された GPU アーキテクチャ

移行で最初にぶつかる壁。**古い `TORCH_CUDA_ARCH_LIST` をそのまま渡すと
`nvcc fatal` で即死する。**

| 世代 | SM | CUDA 11 | CUDA 12 | CUDA 13 |
| --- | --- | --- | --- | --- |
| Kepler | sm_35 / sm_37 | 可（非推奨） | **不可** | 不可 |
| Maxwell | sm_50 / sm_52 / sm_53 | 可 | 可（警告） | **不可** |
| Pascal | sm_60 / sm_61 / sm_62 | 可 | 可（警告） | **不可** |
| Volta | sm_70 / sm_72 | 可 | 可（警告） | **不可** |
| Turing | sm_75 | 可 | 可 | 可 |
| Ampere | sm_80 / sm_86 / sm_87 | 可 | 可 | 可 |
| Ada | sm_89 | 11.8+ | 可 | 可 |
| Hopper | sm_90 | 11.8+ | 可 | 可 |
| Blackwell | sm_100 / sm_120 | 不可 | 12.8+ | 可 |

実測（`nvcc -arch=sm_XX` に空のカーネルを与えた結果）:

```
12.8: sm_37 -> nvcc fatal   : Unsupported gpu architecture 'sm_37'
12.8: sm_50 -> nvcc warning : Support for offline compilation for architectures
                              prior to '<compute/sm/lto>_75' will be removed in
                              a future release
12.8: sm_50 60 61 70 75 80 86 89 90 100 120 -> すべて成功
13.3: sm_70 -> nvcc fatal   : Unsupported gpu architecture 'sm_70'
13.3: sm_75 80 86 89 90 100 110 120 -> すべて成功
```

CUDA 12.8 の警告文が「12 の次で 75 未満を消す」と予告しており、実際に 13 で
消えている。**CUDA 12 でビルドが通っても、警告が出ているなら 13 では通らない。**

### 既定の arch list

`setup.py` に埋め込む既定値は、toolkit の世代で分ける。

```python
_cuda_major = int((torch.version.cuda or "0").split(".")[0])
if _cuda_major >= 13:
    _default = "7.5;8.0;8.6;8.9;9.0;10.0;12.0+PTX"
else:
    _default = "5.0;6.0;6.1;7.0;7.5;8.0;8.6;8.9;9.0+PTX"
```

CUDA 12 側で `10.0` / `12.0`（Blackwell）を既定に入れないのは、12.8 未満の
toolkit では `Unsupported gpu architecture` になるため。必要なら環境変数で
足す。

ローカル開発では自分の SM 1 つだけを指定するとビルドが数倍速い。`mise.toml`
に `TORCH_CUDA_ARCH_LIST = "8.6"` のように書く。配布用の wheel を作るときだけ
広いリストにする。

**`+PTX` を末尾に 1 つ入れておくこと。** SASS が無い新しい GPU でも、PTX が
あればドライバが JIT する。無いと `no kernel image is available for execution
on the device` になる。

## torch wheel と CUDA の対応

PyTorch の wheel は CUDA を内蔵しており、`download.pytorch.org/whl/<cuXXX>/`
ごとに提供バージョンが違う。**PyPI の `torch` は既定の CUDA しか選べない**ので、
CUDA を固定したいなら index を明示する。

実測（2026-09 時点、cp313 / manylinux_2_28_x86_64）:

| index | 提供されている torch |
| --- | --- |
| `cu128` | … 2.9.1, 2.10.0, 2.11.0 |
| `cu130` | … 2.12.1, 2.13.0, 2.14.0 |
| PyPI 既定 | 2.14.0（CUDA 13 系） |

つまり **CUDA 12 に留まるなら torch を上げ切れない**。逆に torch の最新を
使いたいなら CUDA 13 へ行くしかない。移行の動機はたいていこれ。

```bash
# index にどの版があるか調べる
curl -s https://download.pytorch.org/whl/cu130/torch/ \
  | grep -o "torch-2\.[0-9]*\.[0-9]*%2Bcu130-cp313-cp313-manylinux_2_28_x86_64" \
  | sed "s/torch-//;s/%2B.*//" | sort -uV | tail -3
```

## nvcc と torch の major が一致していること

拡張は `$CUDA_HOME` の cudart にリンクされ、torch は wheel に同梱された
cudart を使う。major が違うとプロセス内に別 ABI の cudart が 2 つ載る。

minor 差は CUDA の minor version compatibility で吸収される。実測では
**nvcc 13.3 + torch 2.14.0+cu130（CUDA 13.0）+ ドライバ 13.1 表示**の
組み合わせで全テストが通っている。major さえ揃っていればよい。

## ドライバ

- CUDA 12 の toolkit → ドライバ 525 以降
- CUDA 13 の toolkit → ドライバ 580 以降
- WSL2 では Windows 側のドライバが `/usr/lib/wsl/lib/libcuda.so.1` として
  見える。Linux 側にドライバを入れてはいけない

ドライバが足りない場合の症状は `CUDA driver version is insufficient for CUDA
runtime version` で、これはビルドではなく実行時に出る。
