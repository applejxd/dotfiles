"""``tables.toml`` (検査に使うデータ) を読み込む層。

表そのものは ``home/dot_config/pi/harness/judge/tables.toml`` にある (TS 版の判定器と共有。
置き場の探し方は ``_find_path``)。守りたいファイル名や
検査したいオプションを足すだけなら、Python ではなく TOML を編集すればよい。

型は呼び出し側で明示する。``str.endswith()`` は tuple しか受け付けないなど、
使う側で型が決まっているため (``as_tuple`` / ``as_set`` / ``as_list``)。

読み込みに失敗した場合は例外を送出する。hook は fail-closed が原則で、
表が欠けた状態で検査を通してしまうより、起動に失敗して拒否される方が安全。
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

_NAME = "tables.toml"


def _find_path() -> Path:
    """表の置き場を探す。最初に見つかったものを使い、無ければ例外 (fail-closed)。

    1. このファイルと同じディレクトリ (hook 一式を複製して表を差し替える試験用)
    2. リポジトリのソース (``home/dot_config/pi/harness/judge/``。ソースから直接動かすとき)
    3. 配備先 (``~/.config/pi/harness/judge/``。配備した hook が読む。Unix のみ)
    """
    here = Path(__file__).resolve().parent
    candidates = [here / _NAME]
    if len(here.parents) > 4:
        candidates.append(
            here.parents[4].joinpath("home", "dot_config", "pi", "harness", "judge", _NAME)
        )
    candidates.append(Path.home() / ".config" / "pi" / "harness" / "judge" / _NAME)
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(f"{_NAME} が見つからない: " + ", ".join(str(c) for c in candidates))


_PATH = _find_path()


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    with _PATH.open("rb") as fh:
        return tomllib.load(fh)


def _raw(section: str, key: str) -> Any:
    try:
        return _data()[section][key]
    except KeyError as exc:  # pragma: no cover - 設定ミスは起動時に気付きたい
        raise KeyError(f"{_PATH.name} に [{section}] {key} がありません") from exc


def as_set(section: str, key: str) -> set[str]:
    return set(_raw(section, key))


def as_tuple(section: str, key: str) -> tuple[str, ...]:
    return tuple(_raw(section, key))


def as_list(section: str, key: str) -> list[str]:
    return list(_raw(section, key))


def as_dict(section: str, key: str) -> dict[str, list[str]]:
    return dict(_raw(section, key))
