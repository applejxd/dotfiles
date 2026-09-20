#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from itertools import pairwise
from pathlib import Path
from typing import Any


def audit(spec: dict[str, Any]) -> dict[str, Any]:
    nodes = {str(node) for node in spec.get("nodes", []) if str(node)}
    entry = str(spec.get("entry", "")).strip()
    main_path = [str(node) for node in spec.get("main_path", [])]
    edges = spec.get("edges", [])
    findings: list[dict[str, Any]] = []

    def add(category: str, message: str) -> None:
        findings.append({"severity": "error", "category": category, "message": message})

    if not entry or entry not in nodes:
        add("entry", "A directed process diagram requires one declared entry node.")
    if not main_path or main_path[0] != entry:
        add("main-path", "main_path must begin at the declared entry node.")

    edge_pairs: set[tuple[str, str]] = set()
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, dict):
            add("edge", "Every edge must be an object.")
            continue
        source = str(edge.get("from", "")).strip()
        target = str(edge.get("to", "")).strip()
        if source not in nodes or target not in nodes:
            add("edge-node", f"Unknown edge endpoint: {source!r} -> {target!r}.")
            continue
        if source == target:
            add("self-loop", f"Self-loop at {source!r} requires explicit justification.")
        edge_pairs.add((source, target))
        outgoing[source].append(edge)
        adjacency[source].append(target)
        if edge.get("kind") == "return" and edge.get("route") != "outside":
            add(
                "return-route",
                f"Return edge {source!r} -> {target!r} must use route='outside'.",
            )

    for left, right in pairwise(main_path):
        if (left, right) not in edge_pairs:
            add("main-path", f"Missing main-path edge {left!r} -> {right!r}.")

    for source, source_edges in outgoing.items():
        if len(source_edges) <= 1:
            continue
        labels = [str(edge.get("label", "")).strip() for edge in source_edges]
        if any(not label for label in labels) or len(labels) != len(set(labels)):
            add(
                "branch-label",
                f"All outgoing edges from branch node {source!r} need unique labels.",
            )

    if entry in nodes:
        reachable = {entry}
        queue: deque[str] = deque([entry])
        while queue:
            source = queue.popleft()
            for target in adjacency[source]:
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        unreachable = sorted(nodes - reachable)
        if unreachable:
            add("reachability", f"Unreachable nodes: {', '.join(unreachable)}.")

    return {
        "passed": not findings,
        "errors": len(findings),
        "entry": entry,
        "main_path": main_path,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit process-diagram entry, branches, and return routes."
    )
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        report = audit(spec)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "passed": False,
            "errors": 1,
            "findings": [{"severity": "error", "category": "input", "message": str(exc)}],
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
