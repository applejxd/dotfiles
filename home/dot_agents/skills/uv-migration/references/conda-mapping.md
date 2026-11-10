# environment.yml を uv に対応させる

## 対応表

| conda 側 | uv 側 | 注意 |
| --- | --- | --- |
| `name: myenv` | `[project] name` | conda の env 名は venv 名にならない。`.venv` 固定 |
| `channels:` | `[[tool.uv.index]]` | conda-forge に相当する PyPI は無い。個別に代替を探す |
| `dependencies: - python=3.11` | `requires-python` + `mise.toml` の `[tools]` | 範囲は pyproject、実体は 1 つに固定 |
| `dependencies:` の pip 以外 | `[project] dependencies` | **PyPI 上の名前が違うことがある**（下記） |
| `- pip:` セクション | `[project] dependencies` | ほぼそのまま移せる |
| `- pytorch::pytorch` | `[tool.uv.sources] torch = { index = ... }` | `references/torch-cuda.md` |
| `- cudatoolkit=11.8` | 依存にしない | `mise.toml` の `CUDA_HOME` で外部 toolkit を指す |
| `- cudnn` | 依存にしない | torch の wheel が `nvidia-cudnn-cu12` を連れてくる |
| `variables:` | `mise.toml` の `[env]` | |
| `conda activate` | `uv run` / `mise` の自動有効化 | |

## 名前が違うパッケージ

conda のパッケージ名をそのまま書いても PyPI に無いことがある。移行時に
必ず `uv add` で解決を確認する。

| conda | PyPI |
| --- | --- |
| `pytorch` | `torch` |
| `opencv` | `opencv-python` |
| `pillow-simd` | `pillow` |
| `faiss-gpu` | `faiss-gpu-cu12` |
| `pyyaml` | `PyYAML`（同義。正規化されるので気にしなくてよい） |

## PyPI に等価物が無いもの

conda の強みは**非 Python のバイナリ**を配れることなので、ここだけは
素直に移せない。順に検討する。

1. **wheel が実は存在する**: `pytorch3d`, `open3d`, `pyvista` などは PyPI
   にもある。まず探す。
2. **OS のパッケージマネージャに逃がす**: `libeigen3-dev`, `libtbb-dev`,
   `libgl1` などのシステムライブラリは apt / brew の前提条件として
   README に書く。`mise` の `[tasks]` に確認用タスクを置くとよい。
3. **ソースからビルドする**: `references/cuda-extensions.md`。
4. **mise で入れる**: `cmake`, `ninja`, `node` などのツールは `mise` の
   `[tools]` に置ける。

移行後の README には「apt で入れるもの」と「`mise run sync` で入るもの」を
分けて書く。この 2 つが混ざっているのが conda 時代の手順書の常態なので、
そこを整理するのが移行の実質的な成果になる。

## requirements.txt の場合

pip ベースならほぼ機械的に移せるが、次の行は pyproject の別の場所へ行く。

| requirements.txt の行 | 移行先 |
| --- | --- |
| `--index-url <url>` | `[[tool.uv.index]]`（`default = true`） |
| `--extra-index-url <url>` | `[[tool.uv.index]]` |
| `-f <url>` / `--find-links` | `[[tool.uv.index]]` に `format = "flat"` |
| `-e .` | 何も書かない（uv はプロジェクト自身を editable で入れる） |
| `-r other.txt` | 展開して 1 つの `dependencies` にまとめる |
| `git+https://...` | `[tool.uv.sources]` の `{ git = ..., rev = ... }` |
| `# コメントアウトされた依存` | **消す**。conda で入れていた名残であることが多い |

コメントアウトされた行は要注意。`# pytorch # for anaconda, please refer to
pytorch.org` のような行は「pip では入れられなかったもの」の記録であり、
まさに移行で解決すべき対象を指している。

## 開発用依存の置き場所

conda では `environment-dev.yml` を分けることが多い。uv では
`[dependency-groups]` を使う。`[project.optional-dependencies]`（extra）
との使い分けは、

- **`dependency-groups`**: そのプロジェクトを開発する人だけが要るもの。
  pytest, ruff, pre-commit。配布物のメタデータに入らない。
- **`optional-dependencies`**: そのプロジェクトを**使う**人が選ぶもの。
  `pip install foo[hub]` のように外から指定される。

`uv sync` は既定で `dev` グループを入れる。他のグループも既定で入れたい
なら `[tool.uv] default-groups` に列挙する。

## 移行後に消すもの

`uv sync` が通り、テストが通ってから消す。

- `environment*.yml`
- `requirements*.txt`
- `install*.sh` / `setup_env.sh` など
- README の `conda create` / `conda activate` / `pip install` の手順

`uv.lock` は**コミットする**。conda 時代の「environment.yml は緩い、実際の
環境は誰も再現できない」問題がこれで消える。
