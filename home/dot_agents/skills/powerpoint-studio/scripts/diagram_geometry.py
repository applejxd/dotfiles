"""Shared geometry and PIL text layout for deterministic, explicitly routed diagrams.

Coordinates are SVG user units. Boxes reserve their entire rectangle, even when
drawn with rounded corners. Clearance is Euclidean, measured from painted strokes
and arrow polygons; label boxes include the root padding but have no background.
Only terminal contact with the declared endpoint node is exempt from clearance.
The supported numeric range is [0, 1e9], with positive dimensions greater than
1e-7 units; unrepresentable geometry is rejected rather than producing NaN.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any

from PIL import ImageFont

Point = tuple[float, float]
Box = tuple[float, float, float, float]
Segment = tuple[Point, Point]
EPSILON = 1e-7
STROKE_WIDTH = 2.0
ARROW_LENGTH = 10.0
ARROW_HALF_WIDTH = 4.0


def empty_report() -> dict[str, Any]:
    return {
        "passed": True,
        "errors": 0,
        "warnings": 0,
        "findings": [],
        "dimensions": {},
        "fonts": {},
        "measurements": {"nodes": [], "labels": [], "edges": []},
    }


def add_error(report: dict[str, Any], category: str, message: str, **details: Any) -> None:
    report["findings"].append(
        {
            "severity": "error",
            "category": category,
            "message": message,
            **details,
        }
    )
    report["errors"] += 1
    report["passed"] = False


def _number(value: Any, *, minimum: float = 0, strict: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return (
            math.isfinite(value)
            and value <= 1e9
            and (value > max(minimum, EPSILON) if strict else value >= minimum)
        )
    except OverflowError:
        return False


def _text(value: Any, *, blank: bool = False) -> bool:
    return (
        isinstance(value, str)
        and (blank or bool(value.strip()))
        and all(
            code == 9
            or code == 10
            or code == 13
            or 0x20 <= code <= 0xD7FF
            or 0xE000 <= code <= 0xFFFD
            or 0x10000 <= code <= 0x10FFFF
            for code in map(ord, value)
        )
    )


def _box(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(_number(item) for item in value[:2])
        and all(_number(item, strict=True) for item in value[2:])
        and value[0] + value[2] > value[0]
        and value[1] + value[3] > value[1]
    )


def _validate(data: Any, report: dict[str, Any]) -> bool:
    def check(valid: bool, message: str) -> None:
        if not valid:
            add_error(report, "input", message)

    if not isinstance(data, dict):
        add_error(report, "input", "Layout root must be an object.")
        return False
    for field in ("width", "height", "font_size", "line_height"):
        check(
            _number(data.get(field), strict=True),
            f"{field} must be finite, greater than 1e-7, and at most 1e9.",
        )
    for field in ("padding", "clearance"):
        check(_number(data.get(field)), f"{field} must be finite and in [0, 1e9].")
    for field in ("font_family", "font_path"):
        check(_text(data.get(field)), f"{field} must be a nonempty XML-safe string.")
    placement = data.get("placement")
    if not isinstance(placement, dict):
        check(False, "placement must be an object.")
    else:
        for field in ("width_inches", "height_inches", "min_font_pt"):
            check(
                _number(placement.get(field), strict=True),
                f"placement.{field} must be finite and positive.",
            )
    nodes, edges = data.get("nodes"), data.get("edges")
    check(isinstance(nodes, list) and bool(nodes), "nodes must be a nonempty list.")
    check(isinstance(edges, list), "edges must be a list (possibly empty).")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return False
    ids: set[str] = set()
    node_ids: set[str] = set()

    def identifier(item: dict[str, Any], context: str) -> None:
        value = item.get("id")
        check(_text(value), f"{context}.id must be a nonempty string.")
        if _text(value):
            check(value not in ids, f"Duplicate id {value!r}.")
            ids.add(value)

    def font_size(item: dict[str, Any], context: str) -> None:
        if "font_size" in item:
            check(
                _number(item["font_size"], strict=True),
                f"{context}.font_size must be finite and positive.",
            )

    def color(item: dict[str, Any], field: str, context: str) -> None:
        if field in item:
            value = item[field]
            check(
                isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None,
                f"{context}.{field} must be a #RRGGBB color.",
            )

    for index, node in enumerate(nodes):
        context = f"nodes[{index}]"
        if not isinstance(node, dict):
            check(False, f"{context} must be an object.")
            continue
        identifier(node, context)
        if _text(node.get("id")):
            node_ids.add(node["id"])
        check(
            _box(node.get("box")), f"{context}.box must be [x, y, positive width, positive height]."
        )
        shape = node.get("shape", "rect")
        check(shape in ("rect", "junction"), f"{context}.shape must be rect or junction.")
        lines = node.get("lines", [] if shape == "junction" else None)
        check(
            isinstance(lines, list)
            and all(
                _text(line) and "\n" not in line and "\r" not in line and "\t" not in line
                for line in lines
            ),
            f"{context}.lines must contain nonempty single-line strings.",
        )
        if isinstance(lines, list):
            check(
                not lines if shape == "junction" else bool(lines),
                f"{context}: junctions must have no lines; rectangles need text.",
            )
        font_size(node, context)
        color(node, "fill", context)
        color(node, "stroke", context)
    for index, edge in enumerate(edges):
        context = f"edges[{index}]"
        if not isinstance(edge, dict):
            check(False, f"{context} must be an object.")
            continue
        identifier(edge, context)
        for endpoint in ("from", "to"):
            value = edge.get(endpoint)
            check(
                isinstance(value, str) and value in node_ids,
                f"{context}.{endpoint} must reference a declared node.",
            )
        check(
            edge.get("kind") in ("main", "branch", "return"),
            f"{context}.kind must be main, branch, or return.",
        )
        color(edge, "color", context)
        points = edge.get("points")
        points_valid = (
            isinstance(points, list)
            and len(points) >= 2
            and all(
                isinstance(point, list)
                and len(point) == 2
                and all(_number(value) for value in point)
                for point in points
            )
        )
        check(points_valid, f"{context}.points needs at least two finite nonnegative [x,y] points.")
        if points_valid:
            for left, right in pairwise(points):
                check(
                    (left[0] == right[0]) != (left[1] == right[1]),
                    f"{context} segments must be orthogonal and nonzero.",
                )
                check(
                    math.dist(left, right) > EPSILON,
                    f"{context} segments must be longer than 1e-7 units.",
                )
        if "label" in edge:
            label = edge["label"]
            if not isinstance(label, dict):
                check(False, f"{context}.label must be an object.")
                continue
            text = label.get("text")
            check(
                _text(text) and not any(char in text for char in "\n\r\t"),
                f"{context}.label.text must be a nonempty single-line string.",
            )
            check(_box(label.get("box")), f"{context}.label.box must be a positive rectangle.")
            font_size(label, f"{context}.label")
    return report["passed"]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _same(a: Point, b: Point) -> bool:
    return math.dist(a, b) <= EPSILON


def segments(points: list[Point]) -> list[Segment]:
    return list(pairwise(points))


def _polygon_segments(points: list[Point]) -> list[Segment]:
    return segments(points + points[:1])


def _intersection(first: Segment, second: Segment) -> tuple[str, Point | None]:
    a, b = first
    c, d = second
    u, v, delta = _sub(b, a), _sub(d, c), _sub(c, a)
    determinant = _cross(u, v)
    if abs(determinant) > EPSILON:
        t, s = _cross(delta, v) / determinant, _cross(delta, u) / determinant
        if -EPSILON <= t <= 1 + EPSILON and -EPSILON <= s <= 1 + EPSILON:
            return "point", (a[0] + t * u[0], a[1] + t * u[1])
        return "none", None
    if abs(_cross(delta, u)) > EPSILON:
        return "none", None
    axis = 0 if abs(u[0]) >= abs(u[1]) else 1
    t0, t1 = (c[axis] - a[axis]) / u[axis], (d[axis] - a[axis]) / u[axis]
    low, high = max(0.0, min(t0, t1)), min(1.0, max(t0, t1))
    if low > high + EPSILON:
        return "none", None
    if high - low > EPSILON:
        return "overlap", None
    return "point", (a[0] + low * u[0], a[1] + low * u[1])


def _point_segment_distance(point: Point, segment: Segment) -> float:
    a, b = segment
    u, delta = _sub(b, a), _sub(point, a)
    length_squared = u[0] ** 2 + u[1] ** 2
    t = max(0.0, min(1.0, (u[0] * delta[0] + u[1] * delta[1]) / length_squared))
    return math.dist(point, (a[0] + t * u[0], a[1] + t * u[1]))


def _segment_distance(first: Segment, second: Segment) -> float:
    if _intersection(first, second)[0] != "none":
        return 0.0
    return min(
        *(_point_segment_distance(p, second) for p in first),
        *(_point_segment_distance(p, first) for p in second),
    )


def _corners(box: Box) -> list[Point]:
    x, y, width, height = box
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def _inside(point: Point, polygon: list[Point], *, strict: bool = False) -> bool:
    # All polygons used here are convex (rectangles and arrow triangles).
    values = [_cross(_sub(b, a), _sub(point, a)) for a, b in _polygon_segments(polygon)]
    if strict:
        return all(value > EPSILON for value in values) or all(value < -EPSILON for value in values)
    return all(value >= -EPSILON for value in values) or all(value <= EPSILON for value in values)


def _segment_polygon_distance(segment: Segment, polygon: list[Point]) -> float:
    if any(_inside(p, polygon) for p in segment):
        return 0.0
    return min(_segment_distance(segment, side) for side in _polygon_segments(polygon))


def _polygon_distance(first: list[Point], second: list[Point]) -> float:
    if any(_inside(p, second) for p in first) or any(_inside(p, first) for p in second):
        return 0.0
    return min(
        _segment_distance(a, b) for a in _polygon_segments(first) for b in _polygon_segments(second)
    )


def _on_boundary(point: Point, box: Box) -> bool:
    return any(
        _point_segment_distance(point, side) <= EPSILON for side in _polygon_segments(_corners(box))
    )


def _terminal_contact(segment: Segment, box: Box, point: Point) -> bool:
    polygon = _corners(box)
    if any(_inside(p, polygon, strict=True) for p in segment):
        return False
    for side in _polygon_segments(polygon):
        kind, hit = _intersection(segment, side)
        if kind == "overlap" or (kind == "point" and not _same(hit, point)):
            return False
    return True


def _too_close(distance: float, required: float) -> bool:
    return distance <= EPSILON or distance < required - EPSILON


def arrowhead(points: list[Point]) -> list[Point]:
    previous, tip = points[-2:]
    length = math.dist(previous, tip)
    dx, dy = (tip[0] - previous[0]) / length, (tip[1] - previous[1]) / length
    base = tip[0] - ARROW_LENGTH * dx, tip[1] - ARROW_LENGTH * dy
    return [
        tip,
        (base[0] - ARROW_HALF_WIDTH * dy, base[1] + ARROW_HALF_WIDTH * dx),
        (base[0] + ARROW_HALF_WIDTH * dy, base[1] - ARROW_HALF_WIDTH * dx),
    ]


def _measure_lines(
    lines: list[str], box: Box, font: ImageFont.FreeTypeFont, line_height: float
) -> list[dict[str, Any]]:
    if not lines:
        return []
    boxes = [font.getbbox(text, anchor="ls") for text in lines]
    top = min(bounds[1] + index * line_height for index, bounds in enumerate(boxes))
    bottom = max(bounds[3] + index * line_height for index, bounds in enumerate(boxes))
    origin_y = box[1] + (box[3] - (bottom - top)) / 2 - top
    measured = []
    for index, (text, (left, upper, right, lower)) in enumerate(zip(lines, boxes, strict=False)):
        x = box[0] + (box[2] - (right - left)) / 2 - left
        y = origin_y + index * line_height
        measured.append(
            {
                "text": text,
                "x": x,
                "y": y,
                "bbox": [x + left, y + upper, right - left, lower - upper],
                "font_bbox": [left, upper, right, lower],
                "advance": font.getlength(text),
            }
        )
    return measured


def audit(data: Any) -> dict[str, Any]:
    """Audit a layout dict without mutation, returning only JSON-safe measurements."""
    report = empty_report()
    if not _validate(data, report):
        return report
    width, height = float(data["width"]), float(data["height"])
    placement = data["placement"]
    scale = min(72 * placement["width_inches"] / width, 72 * placement["height_inches"] / height)
    if not math.isfinite(scale) or scale <= 0:
        add_error(report, "input", "Placement scale must be finite and positive.")
        return report
    report["dimensions"] = {
        "width": width,
        "height": height,
        "scale_pt_per_unit": scale,
        "expected_width_inches": width * scale / 72,
        "expected_height_inches": height * scale / 72,
        "stroke_width": STROKE_WIDTH,
        "arrow_length": ARROW_LENGTH,
        "arrow_half_width": ARROW_HALF_WIDTH,
    }
    sizes = {float(data["font_size"])}
    sizes.update(float(node.get("font_size", data["font_size"])) for node in data["nodes"])
    sizes.update(
        float(edge["label"].get("font_size", data["font_size"]))
        for edge in data["edges"]
        if "label" in edge
    )
    fonts = {}
    try:
        for size in sorted(sizes):
            fonts[size] = ImageFont.truetype(str(Path(data["font_path"])), size=size)
    except (OSError, ValueError, OverflowError) as exc:
        add_error(report, "font", f"Cannot load the specified font: {exc}")
        return report
    actual_family = fonts[float(data["font_size"])].getname()[0]
    if actual_family != data["font_family"]:
        add_error(
            report,
            "font-family",
            f"font_path contains {actual_family!r}, "
            f"not declared font_family {data['font_family']!r}.",
        )
    used_sizes: list[float] = []
    measurements = report["measurements"]
    padding, clearance = float(data["padding"]), float(data["clearance"])

    def bounds(points: list[Point], radius: float, context: str) -> None:
        if any(
            x - radius < -EPSILON
            or y - radius < -EPSILON
            or x + radius > width + EPSILON
            or y + radius > height + EPSILON
            for x, y in points
        ):
            add_error(
                report, "canvas-bounds", f"{context} extends beyond the canvas.", object=context
            )

    def text_record(item: dict[str, Any], lines: list[str], identifier: str) -> dict[str, Any]:
        size = float(item.get("font_size", data["font_size"]))
        box = tuple(float(value) for value in item["box"])
        record = {"id": identifier, "box": list(box), "font_size": size, "lines": []}
        if lines:
            used_sizes.append(size)
        try:
            record["lines"] = _measure_lines(lines, box, fonts[size], float(data["line_height"]))
        except (ValueError, OverflowError) as exc:
            add_error(report, "font", f"Cannot measure {identifier}: {exc}", object=identifier)
            return record
        for line in record["lines"]:
            x, y, w, h = line["bbox"]
            if (
                x < box[0] + padding - EPSILON
                or y < box[1] + padding - EPSILON
                or (
                    x + w > box[0] + box[2] - padding + EPSILON
                    or y + h > box[1] + box[3] - padding + EPSILON
                )
            ):
                add_error(
                    report,
                    "text-containment",
                    f"{identifier}: text {line['text']!r} exceeds its {padding:g}-unit inset.",
                    object=identifier,
                    text_bbox=line["bbox"],
                )
        for first, second in combinations(record["lines"], 2):
            a, b = first["bbox"], second["bbox"]
            if min(a[0] + a[2], b[0] + b[2]) > max(a[0], b[0]) + EPSILON and (
                min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1]) + EPSILON
            ):
                add_error(
                    report,
                    "text-overlap",
                    f"{identifier}: line bounding boxes overlap.",
                    object=identifier,
                )
        return record

    for node in data["nodes"]:
        record = text_record(node, node.get("lines", []), node["id"])
        record.update(
            shape=node.get("shape", "rect"),
            fill=node.get("fill", "#FFFFFF"),
            stroke=node.get("stroke", "#14213D"),
        )
        measurements["nodes"].append(record)
        bounds(_corners(record["box"]), STROKE_WIDTH / 2, f"node:{node['id']}")
    for edge in data["edges"]:
        points = [tuple(float(value) for value in point) for point in edge["points"]]
        arrow = arrowhead(points)
        record = {
            "id": edge["id"],
            "from": edge["from"],
            "to": edge["to"],
            "kind": edge["kind"],
            "points": points,
            "arrowhead": arrow,
            "color": edge.get("color", "#5E6B78"),
        }
        measurements["edges"].append(record)
        bounds(points, STROKE_WIDTH / 2, f"edge:{edge['id']}")
        bounds(arrow, 0, f"arrow:{edge['id']}")
        if math.dist(*points[-2:]) < ARROW_LENGTH + STROKE_WIDTH - EPSILON:
            add_error(
                report,
                "arrowhead-length",
                f"{edge['id']}: final segment must be at least "
                f"{ARROW_LENGTH + STROKE_WIDTH:g} units.",
                edge=edge["id"],
            )
        if "label" in edge:
            label = text_record(edge["label"], [edge["label"]["text"]], f"label:{edge['id']}")
            label["edge"] = edge["id"]
            measurements["labels"].append(label)
            bounds(_corners(label["box"]), 0, label["id"])

    report["fonts"] = {
        "font_family": data["font_family"],
        "font_path": data["font_path"],
        "measured_family": actual_family,
        "font_sizes": sorted(set(used_sizes)),
        "minimum_apparent_font_pt": min(used_sizes) * scale if used_sizes else None,
        "apparent_font_sizes_pt": [size * scale for size in sorted(set(used_sizes))],
    }
    for size in sorted(set(used_sizes)):
        if size * scale < placement["min_font_pt"] - EPSILON:
            add_error(
                report,
                "minimum-font-size",
                f"Font {size:g} appears at {size * scale:g}pt; "
                f"declared minimum is {placement['min_font_pt']:g}pt.",
            )

    nodes, labels, edges = measurements["nodes"], measurements["labels"], measurements["edges"]
    node_by_id = {node["id"]: node for node in nodes}
    for first, second in combinations(nodes, 2):
        distance = _polygon_distance(_corners(first["box"]), _corners(second["box"]))
        if _too_close(distance, clearance + STROKE_WIDTH):
            add_error(
                report,
                "node-clearance",
                f"Nodes {first['id']} and {second['id']} have "
                f"{distance - STROKE_WIDTH:g} units painted clearance.",
                nodes=[first["id"], second["id"]],
            )
    for label in labels:
        for node in nodes:
            distance = _polygon_distance(_corners(label["box"]), _corners(node["box"]))
            if _too_close(distance, clearance + STROKE_WIDTH / 2):
                add_error(report, "label-node", f"{label['id']} is too close to node {node['id']}.")
    for first, second in combinations(labels, 2):
        if _too_close(
            _polygon_distance(_corners(first["box"]), _corners(second["box"])), clearance
        ):
            add_error(
                report,
                "label-label",
                f"{first['id']} and {second['id']} overlap or lack clearance.",
            )

    for edge in edges:
        points, arrow = edge["points"], edge["arrowhead"]
        parts = segments(points)
        for end, point in (("from", points[0]), ("to", points[-1])):
            if not _on_boundary(point, node_by_id[edge[end]]["box"]):
                add_error(
                    report,
                    "endpoint-attachment",
                    f"{edge['id']}: {end} point is not on node {edge[end]}'s boundary.",
                    edge=edge["id"],
                )
        for node in nodes:
            box = node["box"]
            polygon = _corners(box)
            collisions = []
            for index, segment in enumerate(parts):
                terminal = (
                    segment[0]
                    if index == 0 and node["id"] == edge["from"]
                    else segment[1]
                    if index == len(parts) - 1 and node["id"] == edge["to"]
                    else None
                )
                if terminal is not None and _on_boundary(terminal, box):
                    bad = not _terminal_contact(segment, box, terminal)
                else:
                    bad = _too_close(
                        _segment_polygon_distance(segment, polygon), clearance + STROKE_WIDTH
                    )
                if bad:
                    collisions.append(index)
            if node["id"] == edge["to"] and _on_boundary(points[-1], box):
                arrow_bad = any(
                    not _terminal_contact(side, box, points[-1])
                    for side in _polygon_segments(arrow)
                )
            else:
                arrow_bad = _too_close(
                    _polygon_distance(arrow, polygon), clearance + STROKE_WIDTH / 2
                )
            if collisions or arrow_bad:
                add_error(
                    report,
                    "edge-node",
                    f"Edge {edge['id']} intersects or lacks clearance from node {node['id']}.",
                    edge=edge["id"],
                    node=node["id"],
                    segments=collisions,
                    arrowhead=arrow_bad,
                )
        for label in labels:
            polygon = _corners(label["box"])
            distance = min(_segment_polygon_distance(part, polygon) for part in parts)
            if _too_close(distance, clearance + STROKE_WIDTH / 2) or _too_close(
                _polygon_distance(arrow, polygon), clearance
            ):
                add_error(
                    report,
                    "edge-label",
                    f"Edge {edge['id']} intersects or lacks clearance from {label['id']}.",
                )
        for (i, first), (j, second) in combinations(enumerate(parts), 2):
            kind, point = _intersection(first, second)
            if j == i + 1 and kind == "point" and _same(point, first[1]):
                continue
            if kind == "none":
                if _segment_distance(first, second) > STROKE_WIDTH + EPSILON:
                    continue
                kind = "stroke contact"
            add_error(
                report,
                "edge-overlap" if kind == "overlap" else "edge-crossing",
                f"Edge {edge['id']} intersects itself at segments {i} and {j}.",
            )
        for index, part in enumerate(parts[:-1]):
            if _segment_polygon_distance(part, arrow) <= STROKE_WIDTH / 2 - EPSILON:
                add_error(
                    report,
                    "edge-crossing",
                    f"Edge {edge['id']} segment {index} intersects its own arrowhead.",
                )
    for first, second in combinations(edges, 2):
        _audit_edge_pair(report, first, second)
    return report


def _shared_endpoint(first: dict[str, Any], second: dict[str, Any], point: Point) -> bool:
    return any(
        first[end_a] == second[end_b]
        and _same(point, first["points"][index_a])
        and _same(point, second["points"][index_b])
        for end_a, index_a in (("from", 0), ("to", -1))
        for end_b, index_b in (("from", 0), ("to", -1))
    )


def _terminal_part(edge: dict[str, Any], index: int, point: Point) -> bool:
    return (index == 0 and _same(point, edge["points"][0])) or (
        index == len(edge["points"]) - 2 and _same(point, edge["points"][-1])
    )


def _audit_edge_pair(report: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> None:
    for i, a in enumerate(segments(first["points"])):
        for j, b in enumerate(segments(second["points"])):
            kind, point = _intersection(a, b)
            if kind == "none":
                if _segment_distance(a, b) > STROKE_WIDTH + EPSILON:
                    continue
                kind = (
                    "overlap"
                    if abs(_cross(_sub(a[1], a[0]), _sub(b[1], b[0]))) <= EPSILON
                    else "stroke contact"
                )
            if (
                kind == "point"
                and _shared_endpoint(first, second, point)
                and (_terminal_part(first, i, point) and _terminal_part(second, j, point))
            ):
                continue
            add_error(
                report,
                "edge-overlap" if kind == "overlap" else "edge-crossing",
                f"Edges {first['id']} and {second['id']} intersect ({kind}).",
                edges=[first["id"], second["id"]],
            )
    # Arrowheads participate in QA rather than being invisible SVG markers.
    for owner, other in ((first, second), (second, first)):
        arrow = owner["arrowhead"]
        for index, part in enumerate(segments(other["points"])):
            bad = any(_inside(point, arrow, strict=True) for point in part)
            for side in _polygon_segments(arrow):
                kind, point = _intersection(side, part)
                if kind == "overlap" or (
                    kind == "point" and not _shared_endpoint(owner, other, point)
                ):
                    bad = True
            shared_tip = _shared_endpoint(owner, other, arrow[0]) and _terminal_part(
                other, index, arrow[0]
            )
            if (
                not shared_tip
                and _segment_polygon_distance(part, arrow) <= STROKE_WIDTH / 2 + EPSILON
            ):
                bad = True
            if bad:
                add_error(
                    report,
                    "edge-crossing",
                    f"Arrowhead of {owner['id']} intersects edge {other['id']}.",
                )
    a, b = first["arrowhead"], second["arrowhead"]
    bad = any(_inside(point, b, strict=True) for point in a) or any(
        _inside(point, a, strict=True) for point in b
    )
    for side_a in _polygon_segments(a):
        for side_b in _polygon_segments(b):
            kind, point = _intersection(side_a, side_b)
            if kind == "overlap" or (
                kind == "point" and not _shared_endpoint(first, second, point)
            ):
                bad = True
    if bad:
        add_error(
            report, "edge-crossing", f"Arrowheads of {first['id']} and {second['id']} intersect."
        )


def _n(value: float) -> str:
    return f"{value:.9f}".rstrip("0").rstrip(".") if value else "0"


def svg_from_report(report: dict[str, Any]) -> str:
    """Render audited measurements; hashing this module binds geometry and SVG output."""
    if not report["passed"]:
        raise ValueError("Cannot render a failed geometry report.")
    dimensions = report["dimensions"]
    root = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": _n(dimensions["width"]),
            "height": _n(dimensions["height"]),
            "viewBox": f"0 0 {_n(dimensions['width'])} {_n(dimensions['height'])}",
            "font-family": report["fonts"]["font_family"],
            "font-weight": "normal",
            "font-style": "normal",
        },
    )
    edges = ET.SubElement(root, "g", {"id": "edges"})
    for edge in report["measurements"]["edges"]:
        ET.SubElement(
            edges,
            "polyline",
            {
                "points": " ".join(f"{_n(x)},{_n(y)}" for x, y in edge["points"]),
                "fill": "none",
                "stroke": edge["color"],
                "stroke-width": _n(STROKE_WIDTH),
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            },
        )
        ET.SubElement(
            edges,
            "polygon",
            {
                "points": " ".join(f"{_n(x)},{_n(y)}" for x, y in edge["arrowhead"]),
                "fill": edge["color"],
            },
        )

    def text(parent: ET.Element, item: dict[str, Any]) -> None:
        for line in item["lines"]:
            element = ET.SubElement(
                parent,
                "text",
                {
                    "x": _n(line["x"]),
                    "y": _n(line["y"]),
                    "font-size": _n(item["font_size"]),
                    "fill": "#14213D",
                    "xml:space": "preserve",
                },
            )
            element.text = line["text"]

    nodes = ET.SubElement(root, "g", {"id": "nodes"})
    for node in report["measurements"]["nodes"]:
        x, y, width, height = node["box"]
        ET.SubElement(
            nodes,
            "rect",
            {
                "x": _n(x),
                "y": _n(y),
                "width": _n(width),
                "height": _n(height),
                "rx": _n(min(6, width / 4, height / 4)),
                "fill": node["fill"],
                "stroke": node["stroke"],
                "stroke-width": _n(STROKE_WIDTH),
            },
        )
        text(nodes, node)
    labels = ET.SubElement(root, "g", {"id": "labels"})
    for label in report["measurements"]["labels"]:
        text(labels, label)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
