"""``tables.toml`` (検査に使うデータ) を読み込む層。

表そのものは同じディレクトリの ``tables.toml`` にある。守りたいファイル名や
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

_PATH = Path(__file__).resolve().parent / "tables.toml"


@lru_cache(maxsize=1)
def _data() -> dict:
    with _PATH.open("rb") as fh:
        return tomllib.load(fh)


def _raw(section: str, key: str):
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


def as_dict(section: str, key: str) -> dict[str, str]:
    return dict(_raw(section, key))
