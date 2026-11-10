#!/usr/bin/env python3
"""marimo がエクスポートしたHTMLを、Unicodeエスケープを解いてから検索する。

`marimo export html` はセル内容をJSONとしてHTMLへ埋め込むため、非ASCII文字は
`\\u3053\\u306e...` の形式でエスケープされる。生の日本語で grep しても
一致しないため、デコードしてから照合する必要がある。

使い方:
    python3 grep-exported-html.py site/*.html -- 検索文字列 [検索文字列...]
    python3 grep-exported-html.py site/nb.html -- 共通部品 インメモリ

`--` の前がファイル、後ろが検索文字列。
終了コードは、すべての検索文字列がすべてのファイルで1件以上見つかれば0、
1つでも0件があれば1。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def decode_escapes(text: str) -> str:
    """HTML中の \\uXXXX を実文字へ復元する。"""
    return ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)


def main() -> int:
    argv = sys.argv[1:]
    if "--" not in argv:
        print(__doc__, file=sys.stderr)
        return 2

    sep = argv.index("--")
    files = [Path(p) for p in argv[:sep]]
    needles = argv[sep + 1 :]

    if not files or not needles:
        print(__doc__, file=sys.stderr)
        return 2

    missing = 0
    for path in files:
        if not path.exists():
            print(f"{path}: ファイルがありません", file=sys.stderr)
            missing += 1
            continue

        decoded = decode_escapes(path.read_text(encoding="utf-8"))
        counts = {needle: decoded.count(needle) for needle in needles}
        summary = "  ".join(f"{k}={v}" for k, v in counts.items())
        print(f"{path.name:44} {summary}")
        missing += sum(1 for v in counts.values() if v == 0)

    if missing:
        print(f"\n0件だった項目: {missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
