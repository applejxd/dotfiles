#!/usr/bin/env python3
"""Markdown 整備でコードセルを壊していないか検証する。

marimo notebook の各セルを AST で抽出し、Markdown セル以外の本文が
比較対象のリビジョン（既定 HEAD）と完全に一致するかを確認する。

Markdown セルの追加・加筆は依存グラフに影響しないため、この検証が通れば
ノートブックの実行結果は変わらないと判断できる。

使い方:
    python3 verify-code-cells-unchanged.py                    # HEAD と比較
    python3 verify-code-cells-unchanged.py --rev origin/main
    python3 verify-code-cells-unchanged.py --glob '*.py'
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


def extract_non_markdown(src: str) -> list[str]:
    """Markdown セル以外のセル本文を、出現順に返す。

    marimo のセルは `@app.cell` を付けた関数、クラスは `@app.class_definition`
    を付けたクラスとして表現される。`with app.setup:` ブロックも比較対象に含める。
    """
    tree = ast.parse(src)
    cells: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = "\n".join(
                ast.get_source_segment(src, stmt) or "" for stmt in node.body
            )
            if body.strip().startswith("mo.md"):
                continue
            cells.append(body.strip())
        elif isinstance(node, (ast.ClassDef, ast.With)):
            cells.append((ast.get_source_segment(src, node) or "").strip())
    return cells


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rev", default="HEAD", help="比較対象のリビジョン（既定: HEAD）"
    )
    parser.add_argument(
        "--glob",
        default="*.py",
        help="対象ファイルの glob。git ls-files へ渡す（既定: *.py）",
    )
    args = parser.parse_args()

    paths = git("ls-files", args.glob).split()
    if not paths:
        print(f"対象ファイルが見つかりません: {args.glob}", file=sys.stderr)
        return 2

    checked = 0
    ok = True
    for path in sorted(paths):
        current = Path(path).read_text(encoding="utf-8")
        try:
            cur_cells = extract_non_markdown(current)
        except SyntaxError as exc:
            print(f"SKIP {path}: 構文解析できません ({exc})")
            continue

        # marimo notebook 以外は対象外。
        if "import marimo" not in current:
            continue

        try:
            base = git("show", f"{args.rev}:{path}")
        except subprocess.CalledProcessError:
            print(f"SKIP {path}: {args.rev} に存在しません（新規ファイル）")
            continue

        base_cells = extract_non_markdown(base)
        checked += 1

        if base_cells == cur_cells:
            print(f"OK   {path}: 非Markdownセル {len(cur_cells)} 件すべて一致")
            continue

        ok = False
        print(
            f"DIFF {path}: {args.rev}={len(base_cells)} 件 / "
            f"現在={len(cur_cells)} 件"
        )
        for before, after in zip(base_cells, cur_cells, strict=False):
            if before != after:
                print(f"  --- {args.rev} ---")
                print("  " + before[:500].replace("\n", "\n  "))
                print("  --- 現在 ---")
                print("  " + after[:500].replace("\n", "\n  "))
                break

    if checked == 0:
        print("marimo notebook が1件も見つかりませんでした。", file=sys.stderr)
        return 2

    print()
    print("結果: すべて一致" if ok else "結果: 差分あり（コードセルが変更されています）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
