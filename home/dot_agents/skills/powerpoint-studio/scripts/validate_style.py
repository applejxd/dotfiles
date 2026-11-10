#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from lxml import etree

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def normalize_color(value: str) -> str:
    value = value.strip().lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", value):
        raise ValueError(f"Invalid RGB color: {value!r}")
    return value


def validate(pptx_path: Path, policy_path: Path) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    surface = normalize_color(policy.get("surface_color", policy["base_color"]))
    base = normalize_color(policy["base_color"])
    main = normalize_color(policy["main_color"])
    accent = normalize_color(policy["accent_color"])
    neutrals = {normalize_color(value) for value in policy.get("neutral_colors", [])}
    allowed = {surface, base, main, accent, *neutrals}
    allowed_backgrounds = {
        normalize_color(value) for value in policy.get("allowed_background_colors", [surface])
    }
    findings: list[dict[str, Any]] = []
    color_counts: Counter[str] = Counter()
    backgrounds: dict[int, str] = {}

    with ZipFile(pptx_path) as archive:
        slide_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda name: int(re.search(r"(\d+)", name).group(1)),
        )
        for slide_number, name in enumerate(slide_names, start=1):
            root = etree.fromstring(archive.read(name))
            for color in root.xpath(".//a:srgbClr/@val", namespaces=NS):
                normalized = normalize_color(color)
                color_counts[normalized] += 1
                if normalized not in allowed:
                    findings.append(
                        {
                            "severity": "error",
                            "slide": slide_number,
                            "category": "palette",
                            "message": f"Unapproved color {normalized} is used.",
                        }
                    )
            background = root.xpath(
                "./p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr/@val",
                namespaces=NS,
            )
            background_color = normalize_color(background[0]) if background else "FFFFFF"
            backgrounds[slide_number] = background_color
            if background_color not in allowed_backgrounds:
                findings.append(
                    {
                        "severity": "error",
                        "slide": slide_number,
                        "category": "background",
                        "message": (
                            f"Background {background_color} is outside the allowed "
                            f"set {sorted(allowed_backgrounds)}."
                        ),
                    }
                )

    unique_backgrounds = set(backgrounds.values())
    max_backgrounds = int(policy.get("max_background_colors", 1))
    if len(unique_backgrounds) > max_backgrounds:
        findings.append(
            {
                "severity": "error",
                "slide": 0,
                "category": "background",
                "message": (
                    f"Deck uses {len(unique_backgrounds)} background colors; "
                    f"maximum is {max_backgrounds}."
                ),
            }
        )

    errors = sum(item["severity"] == "error" for item in findings)
    return {
        "pptx": str(pptx_path.resolve()),
        "policy": str(policy_path.resolve()),
        "passed": errors == 0,
        "errors": errors,
        "warnings": sum(item["severity"] == "warning" for item in findings),
        "palette": {
            "surface": surface,
            "base": base,
            "main": main,
            "accent": accent,
            "neutrals": sorted(neutrals),
        },
        "backgrounds": backgrounds,
        "color_usage": dict(color_counts.most_common()),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate deck color-system consistency.")
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate(args.pptx, args.policy)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Style validation failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
