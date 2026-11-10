#!/usr/bin/env python3
"""marimo Markdown が確実に描画できない数式記法を検出する。

marimo の `mo.md()` は KaTeX で描画するため、Jupyter (MathJax) で通っていた
`\\[...\\]` や `\\begin{equation}` が生テキストとして表示される。書式上の問題を
コミット前に機械的に落とすための検査。

使い方:
    check-display-math.py [PATH ...]

PATH はファイルでもディレクトリでもよい（省略時は `notebooks`）。
ディレクトリは `*.py` を再帰的に走査する。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

UNSUPPORTED = re.compile(
    r"(?<!\\)\\\[|(?<!\\)\\\]|"
    r"\\(?:begin|end)\{"
    r"(?:equation\*?|align\*?|alignat\*?|split|gather\*?|multline\*?|eqnarray\*?)"
    r"\}"
)
DISPLAY_DELIMITER = re.compile(r"^\s*\$\$\s*$")
MARKDOWN_LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+\.)\s")
CODE_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+).*?\1")


def markdown_strings(path: Path) -> list[tuple[int, str]]:
    """`mo.md(...)` の第1引数に渡された文字列を (行番号, 本文) で返す。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "md"
            and node.args
        ):
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            markdown = argument.value
        elif isinstance(argument, ast.JoinedStr):
            # f-string は差し込み部分を無害な定数へ潰してから検査する。
            markdown = "".join(
                part.value if isinstance(part, ast.Constant) else "EXPR"
                for part in argument.values
            )
        else:
            continue
        values.append((argument.lineno, markdown))
    return values


def prose_lines(markdown: str) -> tuple[list[tuple[int, str, str]], int | None]:
    """コードフェンス内とインラインコードを除いた行を返す。

    戻り値は (行の一覧, 閉じていないフェンスの開始オフセット)。
    行は (オフセット, 生の行, インラインコードを除去した行)。
    """
    lines: list[tuple[int, str, str]] = []
    fence: str | None = None
    fence_offset: int | None = None
    for offset, line in enumerate(markdown.splitlines()):
        if match := CODE_FENCE.match(line):
            marker = match.group(1)
            if fence is None:
                fence = marker
                fence_offset = offset
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
                fence_offset = None
            continue
        if fence is None:
            lines.append((offset, line, INLINE_CODE.sub("", line)))
    return lines, fence_offset


def check(path: Path, display: Path) -> list[str]:
    failures: list[str] = []
    for line, markdown in markdown_strings(path):
        lines, fence_offset = prose_lines(markdown)
        if fence_offset is not None:
            failures.append(
                f"{display}:{line + fence_offset}: unclosed Markdown code fence"
            )
        for offset, _, markdown_line in lines:
            if match := UNSUPPORTED.search(markdown_line):
                failures.append(
                    f"{display}:{line + offset}: unsupported display math "
                    f"delimiter {match.group(0)!r}; use $$...$$ and aligned"
                )
        delimiter_lines = [offset for offset, _, text in lines if "$$" in text]
        if sum(text.count("$$") for _, _, text in lines) % 2:
            failures.append(
                f"{display}:{line + delimiter_lines[-1]}: unbalanced $$ delimiters"
            )
        inside_display = False
        for offset, raw_line, markdown_line in lines:
            if "$$" in markdown_line:
                if not DISPLAY_DELIMITER.fullmatch(raw_line):
                    failures.append(
                        f"{display}:{line + offset}: put $$ on a line by itself"
                    )
                if markdown_line.count("$$") % 2:
                    inside_display = not inside_display
            elif inside_display and MARKDOWN_LIST_ITEM.match(markdown_line):
                failures.append(
                    f"{display}:{line + offset}: display math line resembles a "
                    "Markdown list item; remove the space after its leading operator"
                )
    return failures


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        elif path.suffix == ".py":
            files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("notebooks")])
    args = parser.parse_args()

    files = collect(args.paths or [Path("notebooks")])
    if not files:
        print("No notebook sources were found.", file=sys.stderr)
        return 1

    failures: list[str] = []
    for path in files:
        try:
            display = path.relative_to(Path.cwd())
        except ValueError:
            display = path
        try:
            failures.extend(check(path, display))
        except SyntaxError as error:
            failures.append(f"{display}: could not parse ({error})")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Display math is valid in {len(files)} notebooks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
