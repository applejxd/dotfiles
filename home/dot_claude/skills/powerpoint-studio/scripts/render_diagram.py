#!/usr/bin/env python3
"""Render an audited *.layout.json to deterministic SVG without automatic routing.

PIL and SVG both use the declared font face, size, and absolute alphabetic
baselines. Install that same font on the SVG consumer; no fallback font is used
by the audit. --report records the exact layout hash and all measured geometry.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

if __package__:
    from .audit_diagram_geometry import audit_file, write_report
    from .diagram_geometry import add_error, svg_from_report
else:
    from audit_diagram_geometry import audit_file, write_report
    from diagram_geometry import add_error, svg_from_report


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    paths = [args.layout.resolve(), args.output.resolve()]
    if args.report:
        paths.append(args.report.resolve())
    if len(paths) != len(set(paths)):
        parser.exit(1, "Layout, SVG output, and report must use distinct paths.\n")
    report = audit_file(args.layout)
    try:
        if report["passed"]:
            svg = svg_from_report(report)
            # Finish reporting before committing output; any failure preserves the old SVG.
            if args.report:
                write_report(report, args.report)
            _atomic_write(args.output, svg)
        else:
            write_report(report, args.report)
    except (OSError, ValueError) as exc:
        add_error(report, "output", f"Cannot render SVG: {exc}")
        write_report(report, None)
        return 1
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
