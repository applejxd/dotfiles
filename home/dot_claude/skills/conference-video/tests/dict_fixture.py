"""試験用: 状態ファイル(yomi.json / assets.json)をそのまま書く。窓口(state_store)を通さない、上書きの補助。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import yomi  # noqa: E402


def _write(path, entries):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"schema": 1, "entries": entries}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return p


def write_dict(path, words):
    """words: {表記: "ス'ラム"} か {表記: (読み, 状態, メモ)}。既存のファイルは上書きする。"""
    entries = {}
    for surface, v in words.items():
        reading, status, note = (v, yomi.CONFIRMED, "") if isinstance(v, str) else v
        entries[surface] = yomi.make_entry(reading, status, note)
    return _write(path, entries)


def write_assets(path, entries):
    """entries: {ファイル: {出典URL, 作者, ...}}(そのまま書く)。既存のファイルは上書きする。"""
    return _write(path, entries)
