#!/usr/bin/env python3
"""Markdown 解説の網羅状況を集計する。

marimo notebook のセル構成を調べ、直前に Markdown セルが無いコードセルを
一覧する。フェーズ3（Markdown整備）の作業対象を洗い出すために使う。

「直前に Markdown が無い」ことは必ずしも欠陥ではない。些細なセルは直前の
まとまった Markdown でまとめて言及する運用でよい。その場合も、この一覧で
「意図してグルーピングしたのか、単に書き漏らしたのか」を確認できる。

使い方:
    python3 audit-markdown-coverage.py                 # git 管理下の *.py
    python3 audit-markdown-coverage.py notebook.py
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


def classify_cells(src: str) -> list[tuple[int, str, str]]:
    """(行番号, 種別, 本文) のリストを出現順に返す。種別は MD / CODE。"""
    tree = ast.parse(src)
    cells: list[tuple[int, str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = "\n".join(
                ast.get_source_segment(src, stmt) or "" for stmt in node.body
            )
            kind = "MD" if body.strip().startswith("mo.md") else "CODE"
            cells.append((node.lineno, kind, body))
        elif isinstance(node, ast.ClassDef):
            cells.append((node.lineno, "CODE", ast.get_source_segment(src, node) or ""))
    return cells


def first_line(body: str, width: int = 75) -> str:
    for line in body.strip().splitlines():
        if line.strip():
            return line.strip()[:width]
    return ""


def audit(path: Path) -> int:
    src = path.read_text(encoding="utf-8")
    if "import marimo" not in src:
        return 0

    cells = classify_cells(src)
    md = sum(1 for _, kind, _ in cells if kind == "MD")
    code = len(cells) - md

    orphans = []
    for i, (lineno, kind, body) in enumerate(cells):
        if kind != "CODE":
            continue
        previous = cells[i - 1][1] if i > 0 else None
        if previous != "MD":
            orphans.append((lineno, first_line(body)))

    print(
        f"=== {path}: セル計{len(cells)} "
        f"(Markdown {md} / コード {code})  直前にMarkdownが無いコードセル: {len(orphans)}"
    )
    for lineno, snippet in orphans:
        print(f"    L{lineno}: {snippet}")
    print()
    return len(orphans)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="対象ファイル（省略時は git 管理下の *.py）")
    args = parser.parse_args()

    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        listed = subprocess.run(
            ["git", "ls-files", "*.py"], capture_output=True, text=True, check=True
        ).stdout.split()
        paths = [Path(p) for p in listed]

    if not paths:
        print("対象ファイルが見つかりません。", file=sys.stderr)
        return 2

    total = 0
    for path in sorted(paths):
        if path.exists():
            total += audit(path)

    print(f"直前にMarkdownが無いコードセル: 合計 {total} 件")
    print("（グルーピングで直前Markdownがまとめて言及していれば問題ありません）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
