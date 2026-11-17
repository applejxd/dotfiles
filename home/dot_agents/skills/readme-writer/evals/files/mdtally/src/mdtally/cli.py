"""コマンドラインの入口。"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

DEFAULT_WPM = 230  # 1 分あたりに読める語数(英語の目安)


def count_words(text: str) -> int:
    """コードブロックを除いて、英数字の語と、日本語の 1 文字を 1 語として数える。"""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    latin = len(re.findall(r"[A-Za-z0-9_']+", text))
    japanese = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text))
    return latin + japanese


def reading_minutes(words: int, wpm: int = DEFAULT_WPM) -> int:
    return max(1, math.ceil(words / wpm)) if words else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mdtally", description="Markdown の語数と読了時間を数える")
    parser.add_argument("files", nargs="+", type=Path, help="数える Markdown ファイル")
    parser.add_argument("--json", action="store_true", help="JSON で出力する")
    parser.add_argument("--wpm", type=int, default=DEFAULT_WPM, help=f"1 分あたりの語数(既定 {DEFAULT_WPM})")
    args = parser.parse_args(argv)
    if args.wpm <= 0:
        parser.error("--wpm は 1 以上にする")
    rows = []
    for path in args.files:
        try:
            words = count_words(path.read_text(encoding="utf-8"))
        except OSError as error:
            print(f"mdtally: {path}: {error.strerror}", file=sys.stderr)
            return 1
        rows.append({"file": str(path), "words": words, "minutes": reading_minutes(words, args.wpm)})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for row in rows:
            print(f"{row['file']}: {row['words']} 語 / 約 {row['minutes']} 分")
    return 0
