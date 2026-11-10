#!/usr/bin/env python3
"""Validate a translated paper PDF and its TeX log with common CLI tools."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

FATAL_PATTERNS = {
    "missing glyph": re.compile(r"Missing character"),
    "undefined citation": re.compile(r"Citation .* undefined"),
    "undefined reference": re.compile(r"Reference .* undefined|undefined references"),
    "fatal TeX error": re.compile(r"Fatal error|Emergency stop|Undefined control sequence"),
}


def run(*command: str) -> str:
    result = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--text-output", type=Path)
    args = parser.parse_args()

    pdf = args.pdf.resolve()
    if not pdf.is_file():
        raise SystemExit(f"PDF がありません: {pdf}")

    info = run("pdfinfo", str(pdf))
    pages = re.search(r"^Pages:\s+(\d+)$", info, re.MULTILINE)
    if not pages or int(pages.group(1)) < 1:
        raise SystemExit("PDF のページ数を確認できません")

    text_output = (args.text_output or pdf.with_suffix(".txt")).resolve()
    subprocess.run(["pdftotext", str(pdf), str(text_output)], check=True)
    text = text_output.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 100:
        raise SystemExit("PDF から十分な本文テキストを抽出できません")
    if "\ufffd" in text:
        raise SystemExit("抽出テキストに置換文字 U+FFFD があります")

    failures: list[str] = []
    if args.log:
        log = args.log.resolve().read_text(encoding="utf-8", errors="replace")
        failures = [name for name, pattern in FATAL_PATTERNS.items() if pattern.search(log)]

    print(f"pages={pages.group(1)}")
    print(f"text_chars={len(text)}")
    if failures:
        print("failures=" + ", ".join(failures))
        sys.exit(1)
    print("fatal_log_issues=none")


if __name__ == "__main__":
    main()
