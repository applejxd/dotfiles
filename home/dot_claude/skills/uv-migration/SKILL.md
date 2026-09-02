---
name: uv-migration
description: conda / pip ベースの Python プロジェクトを uv 管理（pyproject.toml のみ）へ移行する。「conda をやめたい」「environment.yml を uv に」「requirements.txt を pyproject に」「install.sh をやめて uv sync だけにしたい」「PyTorch / CUDA 拡張を uv で入れたい」と言われたときに使う。torch の CUDA ホイール選択、no-build-isolation が必要な CUDA 拡張、mise による CUDA_HOME / TORCH_CUDA_ARCH_LIST の固定を含む。単なる `uv add` 1 回で済む依存追加や、CUDA を含まない新規プロジェクト作成には使わない。
---

# uv migration

conda / pip / シェルインストーラで管理されたプロジェクトを、`pyproject.toml` +
`uv.lock` だけで再現できる形へ移行する。

## 完了条件

移行が終わった状態とは、次を全て満たすことをいう。

- `conda` / `environment.yml` / `requirements.txt` / `install.sh` が不要
- クローン直後に `mise run sync`（= `uv sync` を規定回数）だけで環境が揃う
- `pip install` を人手で打つ手順がドキュメントに残っていない
- `uv.lock` がコミットされ、CUDA 拡張を含めてバージョンが固定されている

`no-build-isolation` と 2 段階 `uv sync`、extra / dependency-group の分割は
許容する。これらは pyproject の中で完結する。

## 手順

### 1. 依存の棚卸し

移行前に、次を全部読んで「何がどこから入るか」を表にする。ここを飛ばすと
必ず後段のビルドで詰まる。

| 見る場所 | 取り出すもの |
| --- | --- |
| `environment.yml` | conda パッケージ / pip セクション / channel |
| `requirements*.txt` | ピン / `-f` `--extra-index-url` などの入手元 |
| `setup.py` / `pyproject.toml` | 既存の宣言、`ext_modules`、build backend |
| `install.sh` などの手順スクリプト | `pip install` の引数、git clone、apt パッケージ |
| README / INSTALL.md | torch と CUDA の組み合わせ、対応 Python |
| `import` 文 | 実際に使われている拡張（宣言だけで未使用のものを見分ける） |

**宣言されているが未使用の依存を落とす**。実際に `import` されているかを
必ず確認する。例: BUFFER-X の `cpp_wrappers/`（`grid_subsampling`,
`radius_neighbors`）は `compile_wrappers.sh` でビルドされるが、どの Python
モジュールからも import されていないため移行対象から外せる。

**入手元の許可範囲**: PyPI 以外（git ソース、直 URL wheel、flat index）を
`pyproject.toml` に書いてよいのは、**元リポジトリの手順に記載がある URL に
限る**。自分で見つけてきたミラーやフォークを勝手に足さない。同様に、元の
依存リストに無いパッケージを勝手に追加しない（ビルドバックエンドなど、
移行そのものに必要なものだけが例外で、その理由をコメントに書く）。

### 2. Python バージョンを決める

CUDA 拡張のプリビルド wheel や open3d の対応が上限を決める。`requires-python`
は範囲で書き、実際に使う 1 つを `mise.toml` の `[tools]` で固定する。

複数プロジェクトを移行するときは Python バージョンを揃えると、巨大な torch
wheel を uv のキャッシュで共有できる（数 GB の再ダウンロードを避けられる）。

### 3. torch を pyproject で解決する

詳細と分岐は `references/torch-cuda.md` を読むこと。要点だけ:

```toml
[project]
dependencies = ["torch>=2.10,<2.11"]

[tool.uv.sources]
torch = { index = "pytorch-cu128" }

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true
```

`explicit = true` が必須。これが無いと PyPI 上の他パッケージまで PyTorch の
インデックスから解決しようとして壊れる。

### 4. CUDA 拡張は no-build-isolation で建てる

`setup.py` の冒頭で `from torch.utils.cpp_extension import CUDAExtension` を
する類のパッケージは、uv 既定のビルド分離下では torch が見えず失敗する。
手順と落とし穴は `references/cuda-extensions.md` に全部書いてある。

### 5. CUDA 環境変数を mise で固定する

NVIDIA が公式に定めているのは `PATH`（必須）と `LD_LIBRARY_PATH`（runfile
インストール時のみ）の 2 つだけで、`CUDA_HOME` / `LIBRARY_PATH` /
`TORCH_CUDA_ARCH_LIST` は PyTorch 側の都合である。この区別と、それぞれの
決め方は `references/mise-env.md` を読むこと。

いずれもマシン依存の絶対パスを含むので、`pyproject.toml` ではなく
`mise.toml` の `[env]` に置く。

### 6. 検証する

`scripts/verify_migration.py` が機械的に確認できる部分を見る。

```bash
uv run python ~/.claude/skills/uv-migration/scripts/verify_migration.py <PROJECT_DIR>
```

- レガシーファイル（`environment.yml`, `requirements*.txt`, `install*.sh`）が消えている
- torch が `explicit = true` のインデックス経由で解決されている
- `uv.lock` が最新（`uv lock --check`）
- コンパイル済み拡張の `.so` が実在する
- `torch.cuda.is_available()` が `True`

これに加えて手で確認する。

- `.venv` を消してから `uv sync --locked` で再現できること
- 拡張が **実際に CUDA カーネルを持っている**こと（import が通るだけでは
  不十分。`references/cuda-extensions.md` の「静かに壊れる」を参照）
- リポジトリの smoke test / demo が GPU 上で走ること
- 点群系なら Open3D のデモデータ（`o3d.data.DemoICPPointClouds`）で
  実データを通すこと。データセットも学習済み重みも要らない

### 7. 後始末

移行が通ってから、置き換えられた成果物を消す。**検証の前に消さない。**

- `environment.yml`, `requirements*.txt`, `install*.sh`
- README / INSTALL.md の conda・pip 手順を `mise run sync` に差し替え、
  「apt で入れるもの」と「`uv sync` で入るもの」を分けて書く
- CUDA 関連のエラー（`cannot find -lcuda` など）を Troubleshooting に残す
- `.gitignore` に `.venv/` を追加し、`uv.lock` は **コミットする**

## 参照

- `references/torch-cuda.md` — torch の CUDA ホイール選択、index 設定、
  ドライバとの対応
- `references/cuda-extensions.md` — no-build-isolation と
  extra-build-dependencies の使い分け、ビルド失敗の典型パターン
- `references/mise-env.md` — CUDA 環境変数。NVIDIA 公式ガイドが定めるもの
  （PATH / LD_LIBRARY_PATH）と PyTorch 側の都合（CUDA_HOME / LIBRARY_PATH /
  TORCH_CUDA_ARCH_LIST / MAX_JOBS）の区別
- `references/conda-mapping.md` — environment.yml と requirements.txt の
  各項目を uv 側の何に対応させるか
- `references/case-studies.md` — 実際に移行して GPU 上で検証した 2 つの
  リポジトリ（conda + install.sh 型、pip + requirements.txt 型）の完全な
  pyproject.toml と、そこで踏んだ問題
- `scripts/verify_migration.py` — 移行結果の自動チェック
