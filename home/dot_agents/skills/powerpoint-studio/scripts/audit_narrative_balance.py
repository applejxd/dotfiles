#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

LAYERS = {"why", "what", "how", "proof", "operate", "action"}


def audit(plan: dict[str, Any]) -> dict[str, Any]:
    meta = plan.get("meta", {})
    if not meta.get("technical_tutorial"):
        return {
            "enabled": False,
            "passed": True,
            "errors": 0,
            "warnings": 0,
            "findings": [],
        }
    policy = meta.get("narrative_policy", {})
    how_operate_min = float(policy.get("how_operate_min_ratio", 0.45))
    why_max = float(policy.get("why_max_ratio", 0.25))
    proof_min = float(policy.get("proof_min_ratio", 0.10))
    findings = []
    seconds: dict[str, float] = defaultdict(float)
    slide_counts: dict[str, int] = defaultdict(int)

    for index, slide in enumerate(plan.get("slides", []), start=1):
        layer = slide.get("narrative_layer")
        if layer not in LAYERS:
            findings.append(
                {
                    "severity": "error",
                    "slide": index,
                    "category": "narrative",
                    "message": f"Missing or invalid narrative_layer: {layer!r}",
                }
            )
            continue
        timing = float(slide.get("timing_seconds", 0) or 0)
        seconds[layer] += timing
        slide_counts[layer] += 1

    total = sum(seconds.values())
    ratios = {layer: (seconds[layer] / total if total else 0.0) for layer in sorted(LAYERS)}
    how_operate = ratios["how"] + ratios["operate"]
    if how_operate < how_operate_min:
        findings.append(
            {
                "severity": "error",
                "slide": 0,
                "category": "narrative",
                "message": (
                    f"How + Operate is {how_operate:.1%}; minimum is {how_operate_min:.1%}."
                ),
            }
        )
    if ratios["why"] > why_max:
        findings.append(
            {
                "severity": "warning",
                "slide": 0,
                "category": "narrative",
                "message": f"Why is {ratios['why']:.1%}; maximum is {why_max:.1%}.",
            }
        )
    if ratios["proof"] < proof_min:
        findings.append(
            {
                "severity": "error",
                "slide": 0,
                "category": "narrative",
                "message": (f"Proof is {ratios['proof']:.1%}; minimum is {proof_min:.1%}."),
            }
        )
    if slide_counts["action"] == 0:
        findings.append(
            {
                "severity": "error",
                "slide": 0,
                "category": "narrative",
                "message": "Technical tutorial has no action slide.",
            }
        )

    errors = sum(item["severity"] == "error" for item in findings)
    return {
        "enabled": True,
        "passed": errors == 0,
        "errors": errors,
        "warnings": sum(item["severity"] == "warning" for item in findings),
        "seconds_by_layer": dict(seconds),
        "slides_by_layer": dict(slide_counts),
        "ratios": ratios,
        "how_operate_ratio": how_operate,
        "policy": {
            "how_operate_min_ratio": how_operate_min,
            "why_max_ratio": why_max,
            "proof_min_ratio": proof_min,
        },
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Why/What/How balance.")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(json.loads(args.plan.read_text(encoding="utf-8")))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
