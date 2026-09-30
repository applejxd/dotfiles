#!/bin/bash
# routine (commit) の作業用リポジトリを作る。使い方: mkscn.sh <scenario> <dest>
# shellcheck disable=SC2016  # バッククォートは Markdown の文字
set -eu
SCENARIOS="multi new delete long newdir"
if [ "$#" -ne 2 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  echo "usage: $0 <scenario> <dest>   scenario: $SCENARIOS" >&2
  exit 2
fi
SCN="$1"
REPO="$2"
case " $SCENARIOS " in
*" $SCN "*) ;;
*)
  echo "unknown scenario: $SCN" >&2
  exit 2
  ;;
esac
rm -rf "$REPO"
mkdir -p "$REPO/src/calc" "$REPO/tests"
cd "$REPO"
git init -q -b main
git config user.name probe
git config user.email probe@example.invalid
git config commit.gpgSign false

cat > README.md <<'EOF'
# calc

A tiny calculator library.

## Usage

```python
from calc import add, sub
print(add(1, 2))
```

The `legacy` module keeps the old `total()` helper for compatibilty.
EOF
cat > pyproject.toml <<'EOF'
[project]
name = "calc"
version = "0.3.0"
requires-python = ">=3.10"
EOF
cat > CHANGELOG.md <<'EOF'
# Changelog

## 0.3.0

- Add `sub`.
EOF
cat > src/calc/__init__.py <<'EOF'
from .core import add, div, sub
from .legacy import total

__all__ = ["add", "div", "sub", "total"]
EOF
cat > src/calc/core.py <<'EOF'
def add(a: float, b: float) -> float:
    return a + b


def sub(a: float, b: float) -> float:
    return a - b


def div(a: float, b: float) -> float:
    return a / b
EOF
cat > src/calc/legacy.py <<'EOF'
from .core import add


def total(values):
    result = 0
    for v in values:
        result = add(result, v)
    return result
EOF
cat > tests/test_core.py <<'EOF'
from calc import add, div, sub


def test_add():
    assert add(1, 2) == 3


def test_sub():
    assert sub(3, 1) == 2


def test_div():
    assert div(6, 3) == 2
EOF
git add -A
git -c core.hooksPath=/dev/null commit -qm "chore: initial import"

case "$SCN" in
multi)
  # 機能追加 (core + tests) と、無関係な README の誤字修正
  cat >> src/calc/core.py <<'EOF'


def mul(a: float, b: float) -> float:
    return a * b
EOF
  sed -i 's/from .core import add, div, sub/from .core import add, div, mul, sub/; s/"add", "div", "sub"/"add", "div", "mul", "sub"/' src/calc/__init__.py
  sed -i 's/from calc import add, div, sub/from calc import add, div, mul, sub/' tests/test_core.py
  cat >> tests/test_core.py <<'EOF'


def test_mul():
    assert mul(2, 3) == 6
EOF
  sed -i 's/compatibilty/compatibility/' README.md
  ;;
new)
  # 新規モジュールとテスト (未追跡) と、範囲外の個人メモ
  cat > src/calc/stats.py <<'EOF'
from statistics import median as _median


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean() of empty list")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    return _median(values)
EOF
  cat > tests/test_stats.py <<'EOF'
import pytest

from calc.stats import mean, median


def test_mean():
    assert mean([1, 2, 3]) == 2


def test_mean_empty():
    with pytest.raises(ValueError):
        mean([])


def test_median():
    assert median([3, 1, 2]) == 2
EOF
  cat > scratch-notes.txt <<'EOF'
TODO (personal): ask about release date. do not commit.
EOF
  ;;
delete)
  # legacy の削除と参照の更新
  git rm -q src/calc/legacy.py
  cat > src/calc/__init__.py <<'EOF'
from .core import add, div, sub

__all__ = ["add", "div", "sub"]
EOF
  sed -i '/legacy/d; /compatibilty/d' README.md
  printf 'Use `sum()` from the standard library instead of the removed `total()`.\n' >> README.md
  git reset -q
  ;;
long)
  # 振る舞いの変更。理由と影響を本文に書く必要がある
  cat > src/calc/core.py <<'EOF'
import math


def add(a: float, b: float) -> float:
    return a + b


def sub(a: float, b: float) -> float:
    return a - b


def div(a: float, b: float) -> float:
    """Divide a by b.

    Division by zero returns +/-inf (or nan for 0/0) instead of raising,
    to match NumPy semantics used by downstream dashboards.
    """
    if b == 0:
        if a == 0:
            return math.nan
        return math.copysign(math.inf, a)
    return a / b
EOF
  cat >> tests/test_core.py <<'EOF'


def test_div_by_zero_returns_inf():
    import math

    assert div(1, 0) == math.inf
    assert div(-1, 0) == -math.inf
    assert math.isnan(div(0, 0))
EOF
  sed -i 's/version = "0.3.0"/version = "0.4.0"/' pyproject.toml
  cat > CHANGELOG.md <<'EOF'
# Changelog

## 0.4.0

- **Breaking**: `div(x, 0)` no longer raises `ZeroDivisionError`. It returns
  `inf` / `-inf`, or `nan` for `0 / 0`.

## 0.3.0

- Add `sub`.
EOF
  ;;
newdir)
  # 未追跡のディレクトリ 2 つ (status --short には ?? dir/ としか出ない)
  GUIDE=docs/guide
  mkdir -p src/calc/io "$GUIDE"
  printf 'from .csv import read_csv\nfrom .jsonio import read_json\n' > src/calc/io/__init__.py
  cat > src/calc/io/csv.py <<'EOF'
import csv


def read_csv(path: str) -> list[float]:
    with open(path, newline="") as f:
        return [float(row[0]) for row in csv.reader(f) if row]
EOF
  cat > src/calc/io/jsonio.py <<'EOF'
import json


def read_json(path: str) -> list[float]:
    with open(path) as f:
        return [float(v) for v in json.load(f)]
EOF
  printf '# Loading data\n\nUse `calc.io.read_csv` or `calc.io.read_json`.\n' > "$GUIDE/loading.md"
  printf '# Guide\n\n- [Loading data](loading.md)\n' > "$GUIDE/index.md"
  printf '\nSee `docs/guide/` for more.\n' >> README.md
  ;;
*)
  echo "unknown scenario: $SCN" >&2
  exit 2
  ;;
esac
