# CUDA 11 時代のコードで消えている API

CUDA のバージョンを上げるとき、実際に直す必要があるのは 3 層に分かれる。

1. **PyTorch の C++ API**（torch を上げたことによる。CUDA そのものとは無関係）
2. **nvcc のフラグとアーキ指定**（CUDA 本体の変更）
3. **CUDA ライブラリ**（CUB / Thrust / cuSPARSE など）

CUDA 11 の拡張を 12 / 13 へ持っていく作業では、1 と 2 が同時に来る。torch を
据え置いたまま CUDA だけ上げることはできない（wheel が CUDA を内蔵するため）。

## 1. PyTorch の C++ API

以下は torch 2.14 のヘッダで実際に確認した状態。

### THC は消えた

`THC/THC.h` は PyTorch 1.11 で削除された。torch 2.14 の
`torch/include/THC/` に残っているのは 2 ファイルだけで、中身は ATen への
転送でしかない。

```
THC/THCDeviceUtils.cuh
THC/THCAtomics.cuh   ->  #include <ATen/cuda/Atomic.cuh>
                         「torchvision が ATen のヘッダへ移行したら消す」
```

| 旧 | 新 | ヘッダ |
| --- | --- | --- |
| `#include <THC/THC.h>` | 不要。下 2 つで足りる | `<ATen/cuda/CUDAContext.h>` |
| `THCudaCheck(x)` | `AT_CUDA_CHECK(x)`（= `C10_CUDA_CHECK`） | `<ATen/cuda/Exceptions.h>` |
| `THCudaMalloc(state, n)` | `c10::cuda::CUDACachingAllocator::raw_alloc(n)`、可能なら `at::empty` でテンソルに持たせる | `<c10/cuda/CUDACachingAllocator.h>` |
| `THCCeilDiv(a, b)` | `at::ceil_div(a, b)` | `<ATen/ceil_div.h>` |
| `THCState *state` 引数 | 削除（グローバル状態は廃止） | — |
| `THCudaTensor` など | `at::Tensor` | — |
| `#include <THC/THCAtomics.cuh>` | `#include <ATen/cuda/Atomic.cuh>` | — |

### エラーチェックのマクロ

`AT_CHECK` は**削除済み**（torch 2.14 の `c10/util/Exception.h` に定義が無い）。
`AT_ASSERT` / `AT_ASSERTM` は残っているが非推奨で、中身は
`TORCH_INTERNAL_ASSERT` である。

```cpp
// c10/util/Exception.h より
#define AT_ASSERT(...)                                              \
  do {                                                              \
    ::c10::detail::deprecated_AT_ASSERT();                          \
    C10_EXPAND_MSVC_WORKAROUND(TORCH_INTERNAL_ASSERT(__VA_ARGS__)); \
  } while (false)
```

`[[deprecated]]` 属性は「本体側の呼び出しを直すまで」コメントアウトされて
いるので、**使っていても警告が出ない**。気づかず残りやすい。

| 用途 | 使うもの |
| --- | --- |
| 引数の検証（ユーザーの誤り） | `TORCH_CHECK(cond, "message")` |
| 内部不変条件 | `TORCH_INTERNAL_ASSERT(cond)` |
| CUDA API の戻り値 | `AT_CUDA_CHECK(cudaFoo(...))` |

`AT_ASSERT` のまま残すと、入力検証の失敗が `INTERNAL ASSERT FAILED ...
please report a bug to PyTorch` という誤ったメッセージになる。`TORCH_CHECK`
へ機械的に置換してよい。

```bash
grep -rn "AT_CHECK\|AT_ASSERT" --include=*.cu --include=*.cpp --include=*.h .
```

### その他の頻出

| 旧 | 新 |
| --- | --- |
| `x.type().is_cuda()` | `x.is_cuda()` |
| `x.data<float>()` | `x.data_ptr<float>()` |
| `at::Tensor::toType(...)` | `x.to(at::kFloat)` |
| `torch::jit::RegisterOperators` | `TORCH_LIBRARY` / `TORCH_LIBRARY_IMPL` |
| `THCState_getCurrentStream` | `at::cuda::getCurrentCUDAStream()` |

**カーネル起動には必ず `at::cuda::getCurrentCUDAStream()` を渡す。** 既定
ストリーム（`0`）へ流すと、torch 側が別ストリームを使っているときに同期が
壊れる。CUDA 12 以降で `cudaStreamPerThread` 周りの挙動が変わっているので、
古いコードほど踏みやすい。

## 2. nvcc のフラグ

### アーキテクチャ

`references/version-matrix.md` を参照。移行の主犯はここ。

### fatbin の圧縮

`-Xfatbin -compress-all` は CUDA 11 時代の書き方で、CUDA 12.4 以降は
`--compress-mode {none|speed|balance|size}` が用意されている。

実測では **CUDA 12.8 / 13.3 のどちらも両方の綴りを受け付ける**（`nvcc
-arch=sm_86 -Xfatbin -compress-all` も `--compress-mode size` も成功）。
古い綴りが直ちに壊れるわけではないが、新しい方へ寄せておく。

```python
if _cuda_major >= 13:
    _nvcc_args = ["-O3", "--compress-mode", "size"]
else:
    _nvcc_args = ["-O3", "-Xfatbin", "-compress-all"]
```

### C++ 標準

torch 2.x の `CUDAExtension` は `-std=c++17` を自分で足す。`setup.py` 側で
`-std=c++14` を明示していると衝突するので消す。CUDA 12.8 では

```
There are no c++ version bounds defined for CUDA version 12.8
```

という警告が torch から出るが、これは torch 側の表がその CUDA を知らない
だけで、ビルドには影響しない。

### ホストコンパイラ

上限は toolkit の `crt/host_config.h` に書いてある。実測:

```
/usr/local/cuda-12.8/.../crt/host_config.h:  #if __GNUC__ > 14  -> error
/usr/local/cuda-13.3/.../crt/host_config.h:  #if __GNUC__ > 15  -> error
```

新しすぎる GCC では `#error -- unsupported GNU version!` になる。その場合は
`CC` / `CXX` か `-ccbin` で古い GCC を指す（`-allow-unsupported-compiler`
での握り潰しは避ける）。自分の環境の上限は必ず上のファイルを見て確認する。
実測環境は GCC 13.3 + CUDA 12.8 / 13.3 で問題なくビルドできた。

## 3. CUDA ライブラリ側の変更

CUDA 11 → 12 で影響が出やすいもの。該当するコードがあるときだけ見ればよい。
以下は NVIDIA のリリースノートに基づく一覧で、Pointnet2 の事例では 1 つも
該当しなかった（この表だけは実測の裏付けが無い）。自分の対象に当てはまるかは
末尾の grep で確かめること。

| 変更 | 影響 |
| --- | --- |
| Thrust / CUB が `cuda::std` へ再編、名前空間が版で変わる | `thrust::` を直接使う拡張がコンパイルエラー。`ATen` のラッパへ寄せる |
| `cudaMemcpyToSymbol` の型チェック強化 | 暗黙変換に頼ったコードが落ちる |
| `cusparse` の汎用 API 化（旧 API 削除） | `cusparseScsrmv` 等を使うコードは全面書き換え |
| テクスチャ参照 API（`texture<>`）削除 | テクスチャオブジェクト API へ |
| `__shfl` / `__ballot` など sync なし版の削除 | `__shfl_sync` / `__ballot_sync` へ（CUDA 9 で非推奨、以降削除） |
| `cudaDeviceSynchronize` のデバイスコード側呼び出し削除 | CUDA 12 で完全に不可 |

CUDA 13 での追加変更:

| 変更 | 影響 |
| --- | --- |
| Maxwell / Pascal / Volta の削除 | 上記のアーキ問題 |
| `nvJitLink` / cuFFT などの再編 | 静的リンクしている場合のみ |
| `libcuda` スタブの配置は不変 | `$CUDA_HOME/lib64/stubs` のまま |

## 確認用の grep

移行の最初に、これだけ流しておくと作業量が読める。

```bash
grep -rn "THC\|AT_CHECK\|AT_ASSERT\|\.data<\|\.type()\.is_cuda\|__shfl[^_]\|__ballot[^_]\|texture<\|TORCH_CUDA_ARCH_LIST\|compress-all" \
  --include=*.cu --include=*.cuh --include=*.cpp --include=*.h --include=*.py .
```
