#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from lxml import etree

XLINK = "http://www.w3.org/1999/xlink"
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(left: tuple, right: tuple) -> tuple:
    a, b, c, d, e, f = left
    g, h, i, j, k, offset_y = right
    result = (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * offset_y + e,
        b * k + d * offset_y + f,
    )
    if not all(math.isfinite(value) for value in result):
        raise ValueError("Transform produces non-finite coordinates.")
    return result


def transform_matrix(value: str) -> tuple:
    matrix = IDENTITY
    end = 0
    for match in TRANSFORM.finditer(value):
        if value[end : match.start()].strip(" ,\t\r\n"):
            raise ValueError(f"Invalid transform syntax: {value!r}")
        name, arguments = match.groups()
        numbers = list(NUMBER.finditer(arguments))
        cursor = 0
        for index, number in enumerate(numbers):
            separator = arguments[cursor : number.start()]
            if separator.strip(" ,\t\r\n") or (
                index and not separator and number.group(0)[0] not in "+-"
            ):
                raise ValueError(f"Invalid transform arguments: {arguments!r}")
            cursor = number.end()
        if arguments[cursor:].strip(" ,\t\r\n"):
            raise ValueError(f"Invalid transform arguments: {arguments!r}")
        values = [float(number.group(0)) for number in numbers]
        if not all(math.isfinite(number) for number in values):
            raise ValueError("Transform arguments must be finite.")
        if name == "matrix" and len(values) == 6:
            operation = tuple(values)
        elif name == "translate" and len(values) in (1, 2):
            operation = (1, 0, 0, 1, values[0], values[1] if len(values) == 2 else 0)
        elif name == "scale" and len(values) in (1, 2):
            operation = (values[0], 0, 0, values[1] if len(values) == 2 else values[0], 0, 0)
        elif name == "rotate" and len(values) in (1, 3):
            angle = math.radians(values[0])
            cosine, sine = math.cos(angle), math.sin(angle)
            x, y = values[1:] if len(values) == 3 else (0, 0)
            operation = (
                cosine,
                sine,
                -sine,
                cosine,
                x - cosine * x + sine * y,
                y - sine * x - cosine * y,
            )
        elif name in ("skewX", "skewY") and len(values) == 1:
            angle = math.radians(values[0])
            if abs(math.cos(angle)) < 1e-12:
                raise ValueError("Undefined skew angle.")
            tangent = math.tan(angle)
            operation = (1, 0, tangent, 1, 0, 0) if name == "skewX" else (1, tangent, 0, 1, 0, 0)
        else:
            raise ValueError(f"Unsupported transform or argument count: {match.group(0)!r}")
        matrix = multiply(matrix, operation)
        end = match.end()
    if value[end:].strip(" ,\t\r\n"):
        raise ValueError(f"Invalid transform syntax: {value!r}")
    return matrix


def transformed_origin(element) -> tuple[float | None, float | None]:
    x, y = numeric(element.get("x")), numeric(element.get("y"))
    matrix = IDENTITY
    transformed = False
    for ancestor in [*reversed(list(element.iterancestors())), element]:
        transform = ancestor.get("transform")
        if transform:
            matrix = multiply(matrix, transform_matrix(transform))
            transformed = True
    if not transformed:
        return x, y
    x, y = 0.0 if x is None else x, 0.0 if y is None else y
    a, b, c, d, e, f = matrix
    result = (a * x + c * y + e, b * x + d * y + f)
    if not all(math.isfinite(value) for value in result):
        raise ValueError("Transformed text origin is not finite.")
    return result


def numeric(value: str | None) -> float | None:
    if not value:
        return None
    match = NUMBER.match(value.strip())
    if not match:
        return None
    result = float(match.group(0))
    return result if math.isfinite(result) else None


def validate(path: Path) -> dict:
    root = etree.parse(str(path)).getroot()
    findings: list[dict[str, str]] = []
    view_box = root.get("viewBox")
    if not view_box:
        findings.append(
            {
                "severity": "error",
                "category": "viewbox",
                "message": "SVG has no viewBox and may crop or scale unpredictably.",
            }
        )
        bounds = None
    else:
        values = [numeric(item) for item in re.split(r"[,\s]+", view_box.strip())]
        if len(values) != 4 or any(value is None for value in values):
            findings.append(
                {
                    "severity": "error",
                    "category": "viewbox",
                    "message": f"Invalid viewBox: {view_box!r}",
                }
            )
            bounds = None
        else:
            x, y, width, height = (float(value) for value in values)
            bounds = (x, y, width, height)
            if width <= 0 or height <= 0:
                findings.append(
                    {
                        "severity": "error",
                        "category": "viewbox",
                        "message": "SVG viewBox width and height must be positive.",
                    }
                )

    for element in root.xpath(".//*[@href or @xlink:href]", namespaces={"xlink": XLINK}):
        href = element.get("href") or element.get(f"{{{XLINK}}}href") or ""
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https", "file"} or (
            href and not href.startswith(("#", "data:"))
        ):
            findings.append(
                {
                    "severity": "error",
                    "category": "asset",
                    "message": f"SVG contains an external reference: {href}",
                }
            )

    for element in root.xpath(".//*[local-name()='text']"):
        text = "".join(element.itertext()).strip()
        size = numeric(element.get("font-size"))
        if size is not None and size < 10:
            findings.append(
                {
                    "severity": "warning",
                    "category": "typography",
                    "message": f"Small SVG label ({size:g}px): {text[:80]!r}",
                }
            )
        if bounds:
            try:
                x, y = transformed_origin(element)
            except ValueError as exc:
                findings.append({"severity": "error", "category": "transform", "message": str(exc)})
                continue
            if x is not None and not bounds[0] - 1e-9 <= x <= bounds[0] + bounds[2] + 1e-9:
                findings.append(
                    {
                        "severity": "error",
                        "category": "bounds",
                        "message": f"Text x={x:g} lies outside the viewBox: {text[:80]!r}",
                    }
                )
            if y is not None and not bounds[1] - 1e-9 <= y <= bounds[1] + bounds[3] + 1e-9:
                findings.append(
                    {
                        "severity": "error",
                        "category": "bounds",
                        "message": f"Text y={y:g} lies outside the viewBox: {text[:80]!r}",
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
    parser = argparse.ArgumentParser(description="Validate SVG assets before PPTX embedding.")
    parser.add_argument("svg", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = []
    try:
        reports = [validate(path) for path in args.svg]
    except (OSError, etree.XMLSyntaxError, ValueError) as exc:
        print(f"SVG validation failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(reports, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if any(not report["passed"] for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
