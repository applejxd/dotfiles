#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QA summary matches current files.")
    parser.add_argument("summary", type=Path)
    args = parser.parse_args()
    report = json.loads(args.summary.read_text(encoding="utf-8"))
    hashes = report.get("sha256", {})
    paths = {
        "pptx": report.get("pptx"),
        "plan": report.get("plan"),
        "source": report.get("source"),
        "template": report.get("template"),
        "style_policy": report.get("style_policy"),
    }
    failures = []
    for key, raw_path in paths.items():
        expected = hashes.get(key)
        if not raw_path or expected is None:
            continue
        path = Path(raw_path)
        actual = sha256(path)
        if actual != expected:
            failures.append(f"{key}: expected {expected}, got {actual}")
    layout_report = report.get("layout_groups_report")
    layout_hash = hashes.get("layout_groups_report")
    if layout_report is not None or layout_hash is not None:
        if (
            not isinstance(layout_report, str)
            or not layout_report
            or not isinstance(layout_hash, str)
        ):
            failures.append("layout_groups_report: both report path and hash are required.")
        else:
            try:
                actual = sha256(Path(layout_report))
                if actual != layout_hash:
                    failures.append(f"layout_groups_report: expected {layout_hash}, got {actual}")
            except OSError as exc:
                failures.append(f"layout_groups_report: {exc}")
    geometry_reports = report.get("diagram_geometry_reports", [])
    if not isinstance(geometry_reports, list):
        failures.append("diagram_geometry_reports must be a list.")
        geometry_reports = []
    for index, geometry in enumerate(geometry_reports, start=1):
        if not isinstance(geometry, dict) or not isinstance(geometry.get("sha256"), dict):
            failures.append(f"diagram geometry {index}: missing artifact hashes.")
            continue
        for key in ("layout", "image", "report", "provenance", "svg", "renderer"):
            raw_path = geometry.get(key)
            expected = geometry["sha256"].get(key)
            if not isinstance(raw_path, str) or not isinstance(expected, str):
                failures.append(f"diagram geometry {index}: missing {key} path/hash.")
                continue
            try:
                actual = sha256(Path(raw_path))
            except OSError as exc:
                failures.append(f"diagram geometry {index} {key}: {exc}")
                continue
            if actual != expected:
                failures.append(
                    f"diagram geometry {index} {key}: expected {expected}, got {actual}"
                )
    if failures:
        print("QA summary is stale:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("QA summary matches current artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
