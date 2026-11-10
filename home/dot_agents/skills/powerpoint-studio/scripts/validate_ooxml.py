#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import posixpath
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
PRESENTATION_ORDER = [
    "sldMasterIdLst",
    "notesMasterIdLst",
    "handoutMasterIdLst",
    "sldIdLst",
    "sldSz",
    "notesSz",
    "smartTags",
    "embeddedFontLst",
    "custShowLst",
    "photoAlbum",
    "custDataLst",
    "kinsoku",
    "defaultTextStyle",
    "modifyVerifier",
    "extLst",
]
ORDER_INDEX = {name: index for index, name in enumerate(PRESENTATION_ORDER)}


def source_part_for_relationships(path: str) -> PurePosixPath:
    rel_path = PurePosixPath(path)
    if path == "_rels/.rels":
        return PurePosixPath("")
    parent = rel_path.parent
    if parent.name != "_rels":
        raise ValueError(f"Unexpected relationship path: {path}")
    filename = rel_path.name.removesuffix(".rels")
    return parent.parent / filename


def resolved_target(rel_path: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    source = source_part_for_relationships(rel_path)
    return posixpath.normpath(str(source.parent / target))


def validate(path: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    with ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            findings.append(
                {
                    "severity": "error",
                    "category": "zip",
                    "message": f"CRC failure in {bad_member}.",
                }
            )
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml"}
        for missing in sorted(required - names):
            findings.append(
                {
                    "severity": "error",
                    "category": "package",
                    "message": f"Required OOXML part is missing: {missing}",
                }
            )

        for name in sorted(names):
            if name.endswith((".xml", ".rels")):
                try:
                    etree.fromstring(archive.read(name))
                except etree.XMLSyntaxError as exc:
                    findings.append(
                        {
                            "severity": "error",
                            "category": "xml",
                            "message": f"{name}: {exc}",
                        }
                    )

        for rel_path in sorted(name for name in names if name.endswith(".rels")):
            root = etree.fromstring(archive.read(rel_path))
            for relationship in root.findall(f"{{{REL_NS}}}Relationship"):
                if relationship.get("TargetMode") == "External":
                    continue
                target = relationship.get("Target")
                if not target:
                    continue
                resolved = resolved_target(rel_path, target)
                if resolved not in names:
                    findings.append(
                        {
                            "severity": "error",
                            "category": "relationship",
                            "message": (
                                f"{rel_path} points to missing part {resolved} (target={target!r})."
                            ),
                        }
                    )

        if "ppt/presentation.xml" in names:
            root = etree.fromstring(archive.read("ppt/presentation.xml"))
            children = [etree.QName(child).localname for child in root]
            known = [name for name in children if name in ORDER_INDEX]
            if known != sorted(known, key=ORDER_INDEX.__getitem__):
                findings.append(
                    {
                        "severity": "error",
                        "category": "schema-order",
                        "message": (
                            "ppt/presentation.xml child order is invalid: " + " -> ".join(children)
                        ),
                    }
                )

    errors = sum(item["severity"] == "error" for item in findings)
    return {
        "path": str(path.resolve()),
        "passed": errors == 0,
        "errors": errors,
        "warnings": sum(item["severity"] == "warning" for item in findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate core OOXML package invariants.")
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate(args.pptx)
    except (OSError, BadZipFile, ValueError, etree.XMLSyntaxError) as exc:
        print(f"OOXML validation failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
