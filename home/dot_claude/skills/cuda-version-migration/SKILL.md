---
name: cuda-version-migration
description: CUDA 11.x 時代に書かれた PyTorch の CUDA 拡張を CUDA 12.x / 13.x へ移行し、ビルドと数値検証まで通す。「CUDA 12 でビルドできない」「CUDA 13 に上げたい」「unsupported gpu architecture 'compute_37'」「no kernel image is available for execution on the device」「undefined symbol: _ZNK3c10...」「THC/THC.h が無い」「AT_CHECK が未定義」と言われたときに使う。torch を新しくするだけの作業や、CUDA バージョンを変えない依存整理（uv-migration スキルの領分）には使わない。
---

# CUDA version migration

CUDA 11 前提の PyTorch 拡張を CUDA 12.x / 13.x で動かす。ビルドを通すだけでは
終わらない。**間違った CUDA でビルドされた拡張は、import も成功し、実行も
成功したように見えることがある**ため、数値検証まで含めて完了とする。

依存管理そのもの（conda からの脱却、`no-build-isolation` の使い分け）は
`uv-migration` スキルの領分。こちらは「CUDA のバージョンを上げると何が壊れるか」
だけを扱う。

## 完了条件

1. 対象の toolkit で `.so` が生成される
2. `.so` が **実行するマシンの SM 向けコード**を含む（`cuobjdump` で確認）
3. `.so` が **ランタイムの torch と同じ ABI** でリンクされている
4. 全カーネルが純 PyTorch 参照実装と数値一致する
5. 上位モジュールで forward / backward が通り、学習が収束する

1 と 2 と 3 は別物である。1 だけ見て終わるのが最も多い失敗。

## 手順

### 1. 目標の組み合わせを先に決める

CUDA の版だけ決めても足りない。**toolkit・torch wheel・ドライバ・SM** の
4 つが揃って初めて決まる。決め方は `references/version-matrix.md`。

- `nvidia-smi` の `CUDA Version` は**ドライバが対応する上限**であって、
  入っている toolkit ではない
- torch の wheel が内蔵する CUDA（`torch.version.cuda`）と、拡張をビルドする
  `nvcc` の **major が一致していること**。ここがずれると cudart が二重になる
- ビルド対象の SM は `torch.cuda.get_device_capability()` で確認する

### 2. ソースを直す

CUDA 11 → 12 → 13 で実際に消えた API と、その置き換えは
`references/api-changes.md` に一覧がある。頻出は 3 つ。

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| `nvcc fatal: Unsupported gpu architecture 'compute_37'` | `setup.py` が古い `TORCH_CUDA_ARCH_LIST` を代入 | 環境変数を尊重する形に直す（下記） |
| `THC/THC.h: No such file` | THC は PyTorch 1.11 で削除 | `ATen/cuda/CUDAContext.h` と `TORCH_CHECK` へ |
| `AT_CHECK` / `AT_ASSERT` が未定義 or 非推奨 | c10 のエラー API 刷新 | `TORCH_CHECK` へ機械的に置換 |

**アーキ一覧のハードコードを消す。** 元コードはほぼ必ずこう書いてある。

```python
os.environ["TORCH_CUDA_ARCH_LIST"] = "3.7+PTX;5.0;6.0;6.1;6.2;7.0;7.5"
```

これを `setdefault` に変え、既定値は toolkit の世代で分岐させる。

```python
_cuda_major = int((torch.version.cuda or "0").split(".")[0])
if _cuda_major >= 13:
    _default = "7.5;8.0;8.6;8.9;9.0;10.0;12.0+PTX"   # Volta 以前は無い
else:
    _default = "5.0;6.0;6.1;7.0;7.5;8.0;8.6;8.9;9.0+PTX"  # Kepler は無い
os.environ.setdefault("TORCH_CUDA_ARCH_LIST", _default)
```

削除された世代の一覧と、実測したコンパイル可否は
`references/version-matrix.md` にある。

### 3. 失敗を隠す仕掛けを外す

移行で最も時間を溶かすのは、**壊れているのに動いて見える**状態である。
典型は 2 つで、どちらも移行の前に外す。

- **JIT フォールバック**: `try: import _ext / except ImportError: load(...)`。
  拡張のビルドが失敗しても import 時に再コンパイルへ落ちるので、
  「ビルドは失敗したのにテストは走る（そして遅い）」になる。素直に
  `import` だけ残す
- **`exit(-1)` によるエラー処理**: `cudaGetLastError()` を見て `exit(-1)`
  するマクロ。SM 不一致は実行時に初めて出るのに、pytest がプロセスごと死んで
  レポートが残らない。`TORCH_CHECK` へ置換して Python 例外にする

実測（RTX 3070 / sm_86 のマシンで `TORCH_CUDA_ARCH_LIST=9.0` としてビルド）:

```
# exit(-1) 版 … 4 件目で pytest が消える。サマリも出ない
...F

# TORCH_CHECK 版 … 全件が失敗として記録され、原因もわかる
E  RuntimeError: CUDA kernel failed : no kernel image is available for execution on the device
E  void furthest_point_sampling_kernel_wrapper(...) at L:228 in .../sampling_gpu.cu
23 failed, 7 passed
```

### 4. ビルドする

ビルド環境の作り方は `uv-migration` スキルに従う。CUDA の版を変える移行で
追加になる注意は 2 点だけ。

- **ビルド時の torch とランタイムの torch を一致させる**。ずれると
  `undefined symbol: _ZNK3c1010TensorImpl15incref_pyobjectEv` のような
  C++ マングル名で落ちる。uv なら `match-runtime = true`（要・静的メタデータ）
- **`CUDA_HOME` と `PATH` の nvcc を同じ版に揃える**。詳細は uv-migration
  スキルの `references/cuda-extensions.md`

### 5. 検証する

ビルドが通っただけでは何も言えない。2 段構えで見る。

**(a) 由来の検証** — `scripts/check_cuda_build.py` が機械的に見る。

```bash
uv run python ~/.claude/skills/cuda-version-migration/scripts/check_cuda_build.py pointnet2_ops._ext
```

- `.so` が site-packages にある（`torch_extensions/` なら JIT に落ちている）
- ランタイム torch と同じ ABI（import できる = リンクが解決した）
- `nvcc` の major と `torch.version.cuda` の major が一致
- fatbin に**このマシンの SM 向け SASS か、JIT 可能な PTX** がある

**(b) 数値の検証** — カーネルごとに純 PyTorch の参照実装と突き合わせる。
書き方は `references/testing-cuda-ops.md`。要点は「参照実装は `torch` の
プリミティブだけで書く」「インデックスを返すカーネルは完全一致で比較する」
「勾配は参照実装の autograd と比較する」「最後に小さな学習を回して収束を見る」。

## 参照

- `references/version-matrix.md` — CUDA 12 / 13 で削除された SM、toolkit と
  torch wheel とドライバの対応、実測したコンパイル可否
- `references/api-changes.md` — THC 削除、`AT_CHECK` 系、nvcc フラグ
  （`-Xfatbin -compress-all` → `--compress-mode`）、CUB / Thrust の変更
- `references/testing-cuda-ops.md` — CUDA カーネルの検証方法。参照実装、
  勾配、由来の検証、意図的に壊して落ちることを確かめる手順
- `references/case-study-pointnet2.md` — Pointnet2_PyTorch を CUDA 12.8 と
  CUDA 13.3 の両方へ移行した全差分と、踏んだエラーの実物
- `scripts/check_cuda_build.py` — 由来の検証を 1 コマンドで
