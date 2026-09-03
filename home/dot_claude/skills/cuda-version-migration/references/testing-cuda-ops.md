# CUDA カーネルの検証方法

移行後の拡張は「import できた」「例外が出なかった」では検証にならない。
CUDA のバージョンを変えたときに起きる壊れ方は 4 種類あり、それぞれ別の
方法でしか捕まらない。

| 壊れ方 | 症状 | 捕まえ方 |
| --- | --- | --- |
| ビルドが縮退した | import は成功し、GPU カーネルだけ無い | `_ext` の `.so` の実在確認 |
| ABI 不一致 | `undefined symbol: _ZNK3c10...` | import できるかどうか |
| SM 不一致 | `no kernel image is available for execution on the device` | `cuobjdump` と、実際に 1 回起動する |
| 数値が壊れた | 何も言わずに違う値を返す | 純 PyTorch の参照実装との比較 |

上 3 つは `scripts/check_cuda_build.py` で機械的に見る。4 つ目だけは
テストを書く必要がある。

## 1. 参照実装と突き合わせる

**参照実装は `torch` のプリミティブだけで書く。** NumPy でも Python ループ
でもよいが、検証対象の拡張を一切使わないことが条件。

```python
def ref_group_points(features, idx):
    # features (B, C, N), idx (B, npoint, nsample) -> (B, C, npoint, nsample)
    b, c, _ = features.shape
    npoint, nsample = idx.shape[1], idx.shape[2]
    index = idx.long().reshape(b, 1, npoint * nsample).expand(-1, c, -1)
    return torch.gather(features, 2, index).reshape(b, c, npoint, nsample)
```

比較の厳しさはカーネルの性質で決める。

| カーネルが返すもの | 比較 |
| --- | --- |
| インデックス（`int32`） | `torch.equal` で**完全一致** |
| gather / scatter 系（値をコピーするだけ） | `torch.equal` で完全一致 |
| 浮動小数の演算を伴う | `torch.allclose(atol=1e-5, rtol=1e-4)` |

インデックスを返すカーネルを `allclose` で比較してはいけない。argmax の
順序ずれのような、まさに検証したい差異を見逃す。

### 参照実装はカーネルを読んで書く

「論文どおり」ではなく「実装どおり」に書く。移植元の実装には、論文に書いて
いない挙動がほぼ必ずある。Pointnet2 で実際に見つけたもの:

- `furthest_point_sampling` は **必ずインデックス 0 から始める**（乱択でない）
- 同カーネルは `|p|^2 <= 1e-3` の点を候補から**除外する**
- `ball_query` は距離順ではなく**インデックス順**に先頭 `nsample` 個を取り、
  足りない分は**最初に見つけた点で埋める**
- 1 個も見つからなければ行は**ゼロのまま**（`torch::zeros` の初期値）
- `three_nn` の CUDA 側は**二乗距離**を返し、Python ラッパが `sqrt` する

最後の 1 つは、参照実装を書いていなければ絶対に気づかない。実際に
`allclose` が落ちて発覚した（0.1578 に対して 0.0249 = 0.1578²）。

### 入力の作り方に注意する

カーネルの分岐を偶然踏まないデータを作る。上の「原点近傍を除外」の例なら、
点群を原点から離す。

```python
def make_xyz(b, n, device, spread=1.0, offset=2.0):
    return torch.rand(b, n, 3, device=device) * spread + offset
```

原点中心のデータを使うと、参照実装と CUDA のどちらが正しいのか判断できない
テストになる。

## 2. 勾配を検証する

`torch.autograd.gradcheck` は倍精度前提なので、`float` 専用の拡張には
そのまま使えない。2 通りで代替する。

**(a) 参照実装の autograd と比較**（主。全パラメータを一度に見る）

```python
feats = torch.randn(b, c, n, device=device, requires_grad=True)
ref   = feats.detach().clone().requires_grad_(True)
out, want = pu.grouping_operation(feats, idx), ref_group_points(ref, idx)
g = torch.randn_like(out)
out.backward(g); want.backward(g)
assert torch.allclose(feats.grad, ref.grad, atol=1e-5, rtol=1e-4)
```

**(b) 中心差分**（従。参照実装の backward 自体が疑わしいとき）

`eps` は float32 の丸めに埋もれない大きさ（`1e-2` 程度）にし、許容誤差も
緩める。小さいテンソルでだけ回す。

## 3. 上位モジュールまで通す

op 単体が合っていても、autograd の接続、dtype、メモリレイアウト、
ストリームの扱いは別問題。実際のモジュールで forward / backward を回す。

さらに**小さな学習を 1 本回して loss が下がることを見る**。これが最も安く、
勾配が「符号だけ逆」のような壊れ方まで捕まる。

```python
# 2 つに分離した点群の分類。30 step で loss が半分未満になること
assert losses[-1] < losses[0] * 0.5
```

`torch.autocast` 下の forward も 1 本入れておく。ABI がずれた拡張は
autocast のディスパッチで先に落ちることが多い。

## 4. 由来を検証する（数値以外）

```bash
uv run python .github/skills/cuda-version-migration/scripts/check_cuda_build.py pointnet2_ops._ext
```

pytest に組み込む場合の要点は 4 つ。

- `.so` のパスに `torch_extensions` が含まれていないこと（JIT フォールバック
  に落ちていない）
- `nvcc --version` の major と `torch.version.cuda` の major が一致すること
- `cuobjdump --list-elf` の SASS に、このマシンの SM が含まれること。
  無い場合でも `--list-ptx` に**それ以下の** PTX があれば JIT で動く
- 拡張を import できること（＝ ABI が合っている）

## 5. テストが本当に効くか確かめる

**わざと壊してテストが落ちることを確認する。** 実測（sm_86 のマシンで
`TORCH_CUDA_ARCH_LIST=9.0` としてビルド）:

```
FAILED tests_ops/test_build_provenance.py::test_fatbin_contains_code_for_this_gpu
FAILED tests_ops/test_ops_correctness.py::test_furthest_point_sampling[1-128-16]
...
23 failed, 7 passed
```

このとき、拡張のエラー処理が `exit(-1)` のままだと pytest ごと死ぬ。

```
# exit(-1) 版
...F                      <- 4 件目で消える。サマリも終了コードも残らない

# TORCH_CHECK 版
E  RuntimeError: CUDA kernel failed : no kernel image is available for
   execution on the device
E  void furthest_point_sampling_kernel_wrapper(...) at L:228 in .../sampling_gpu.cu
23 failed, 7 passed in 3.66s
```

**テストを書く前に `exit(-1)` を潰しておくこと。** そうしないと、移行の
最中に一番知りたい情報が出ない。

## 6. 再現性

最後に `.venv` を消してロックから作り直し、同じテストを通す。

```bash
rm -rf .venv && uv sync --locked && uv run pytest tests_ops -q
```

拡張のビルドは uv のキャッシュに乗るので、**ソースを直したら
`uv sync --reinstall-package <pkg>` を打つ**。ただの `uv sync` では
キャッシュ済みの wheel が再利用され、直したはずのコードが反映されない。
