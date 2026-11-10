#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def choose(spec: dict[str, Any]) -> dict[str, Any]:
    nodes = int(spec.get("nodes", 0))
    edges = int(spec.get("edges", 0))
    branch_points = int(spec.get("branch_points", 0))
    loops = int(spec.get("loops", 0))
    nested_groups = int(spec.get("nested_groups", 0))
    swimlanes = int(spec.get("swimlanes", 0))
    score = 0
    reasons = []

    if nodes >= 10:
        score += 3
        reasons.append("10 or more nodes")
    elif nodes >= 7:
        score += 2
        reasons.append("7-9 nodes")
    elif nodes >= 5:
        score += 1
        reasons.append("5-6 nodes")

    if edges >= 13:
        score += 3
        reasons.append("13 or more edges")
    elif edges >= 9:
        score += 2
        reasons.append("9-12 edges")
    elif edges >= 6:
        score += 1
        reasons.append("6-8 edges")

    if branch_points >= 3:
        score += 2
        reasons.append("multiple branch points")
    elif branch_points:
        score += 1
        reasons.append("branching")
    if loops >= 2:
        score += 2
        reasons.append("multiple loops")
    elif loops:
        score += 1
        reasons.append("loop")
    if nested_groups:
        score += 2
        reasons.append("nested subgraphs")
    if swimlanes:
        score += 2
        reasons.append("swimlanes")
    if spec.get("edge_crossing_risk"):
        score += 2
        reasons.append("edge crossing risk")
    if spec.get("long_labels"):
        score += 1
        reasons.append("long labels")
    if spec.get("exact_topology_required"):
        score += 1
        reasons.append("exact topology required")
    if spec.get("automatic_layout_required"):
        score += 3
        reasons.append("automatic layout required")
    if int(spec.get("return_edges", 0)) > 0:
        score += 2
        reasons.append("return edges need outside routing")
    if int(spec.get("exception_branches", 0)) > 0:
        score += 1
        reasons.append("exception branches should leave the main path")
    if spec.get("frequent_powerpoint_editing"):
        score -= 2
        reasons.append("frequent PowerPoint editing favors native shapes")

    score = max(0, score)
    if score <= 3:
        recommendation = "native"
    elif score <= 6:
        recommendation = "hybrid"
    else:
        recommendation = "external"
    if spec.get("native_render_failed"):
        recommendation = "external"
        reasons.append("native rendering already failed")

    return {
        "score": score,
        "recommendation": recommendation,
        "reasons": reasons,
        "preferred_external_tools": ["Graphviz", "D2", "Mermaid", "PlantUML"],
        "preferred_embedding": "SVG, or PNG >= 2400px wide when compatibility requires raster",
        "layout_guidance": [
            "Keep the main path straight and monotonic.",
            "Place exception branches perpendicular to the main path.",
            "Route return edges around the outside, never through the main path.",
            "Put branch labels on clear segments near the decision node.",
            "Use explicit entry and terminal nodes for process diagrams.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Choose a diagram rendering strategy.")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = choose(json.loads(args.spec.read_text(encoding="utf-8")))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
