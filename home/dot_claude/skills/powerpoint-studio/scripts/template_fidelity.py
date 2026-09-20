#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from lxml import etree

PART_PATTERNS = {
    "theme": re.compile(r"ppt/theme/theme\d+\.xml"),
    "master": re.compile(r"ppt/slideMasters/slideMaster\d+\.xml"),
    "layout": re.compile(r"ppt/slideLayouts/slideLayout\d+\.xml"),
}
PML = "http://schemas.openxmlformats.org/presentationml/2006/main"


def canonical_hash(data: bytes) -> str:
    root = etree.fromstring(data)
    canonical = etree.tostring(root, method="c14n", with_comments=False)
    return hashlib.sha256(canonical).hexdigest()


def package_fingerprint(path: Path) -> dict[str, Any]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
        size = presentation.find(f"{{{PML}}}sldSz")
        if size is None:
            raise ValueError(f"{path} has no p:sldSz")
        parts: dict[str, list[dict[str, str]]] = {}
        for kind, pattern in PART_PATTERNS.items():
            matching = sorted(name for name in names if pattern.fullmatch(name))
            parts[kind] = [
                {"name": name, "sha256": canonical_hash(archive.read(name))} for name in matching
            ]
    return {
        "slide_size_emu": {
            "width": int(size.get("cx", "0")),
            "height": int(size.get("cy", "0")),
        },
        "parts": parts,
    }


def compare(template: Path, output: Path) -> dict[str, Any]:
    reference = package_fingerprint(template)
    candidate = package_fingerprint(output)
    findings: list[dict[str, str]] = []

    if reference["slide_size_emu"] != candidate["slide_size_emu"]:
        findings.append(
            {
                "severity": "error",
                "category": "slide-size",
                "message": (
                    f"Slide size changed from {reference['slide_size_emu']} "
                    f"to {candidate['slide_size_emu']}."
                ),
            }
        )

    for kind in ("theme", "master", "layout"):
        expected = reference["parts"][kind]
        actual = candidate["parts"][kind]
        if len(actual) < len(expected):
            findings.append(
                {
                    "severity": "error",
                    "category": kind,
                    "message": (
                        f"Output contains {len(actual)} {kind} parts; "
                        f"template contains {len(expected)}."
                    ),
                }
            )
        expected_hashes = {item["sha256"] for item in expected}
        actual_hashes = {item["sha256"] for item in actual}
        missing_hashes = expected_hashes - actual_hashes
        if missing_hashes:
            findings.append(
                {
                    "severity": "warning",
                    "category": kind,
                    "message": (
                        f"{len(missing_hashes)} original {kind} definitions changed. "
                        "Confirm the change is intentional."
                    ),
                }
            )

    errors = sum(item["severity"] == "error" for item in findings)
    return {
        "template": str(template.resolve()),
        "output": str(output.resolve()),
        "passed": errors == 0,
        "errors": errors,
        "warnings": sum(item["severity"] == "warning" for item in findings),
        "findings": findings,
        "template_fingerprint": reference,
        "output_fingerprint": candidate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check template fidelity of a PPTX.")
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        report = compare(args.template, args.output)
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        print(f"Template comparison failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output_report:
        args.output_report.parent.mkdir(parents=True, exist_ok=True)
        args.output_report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["errors"]:
        return 1
    if args.strict and report["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
