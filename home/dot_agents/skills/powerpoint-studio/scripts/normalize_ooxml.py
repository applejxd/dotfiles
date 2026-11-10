#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

try:
    from .validate_ooxml import ORDER_INDEX
except ImportError:
    from validate_ooxml import ORDER_INDEX


def normalize_presentation_xml(data: bytes) -> bytes:
    root = etree.fromstring(data)
    original = list(root)
    known_positions = [
        index for index, child in enumerate(original) if etree.QName(child).localname in ORDER_INDEX
    ]
    known_children = [original[index] for index in known_positions]
    known_children.sort(key=lambda child: ORDER_INDEX[etree.QName(child).localname])
    for position, child in zip(known_positions, known_children, strict=True):
        root.remove(original[position])
        root.insert(position, child)
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def normalize(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(input_path) as source, ZipFile(output_path, "w", ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "ppt/presentation.xml":
                data = normalize_presentation_xml(data)
            target.writestr(info, data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize presentation-level OOXML element ordering."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        raise SystemExit("Input and output must be different paths.")
    normalize(args.input, args.output)
    print(f"Wrote normalized PPTX: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
