#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

VALID_MODES = {"focused", "overview"}
VALID_DETAIL_POLICIES = {"explain", "recognize", "reference"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("The plan root must be a JSON object.")
    return data


def audit(plan: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    meta = plan.get("meta")
    policy = meta.get("message_policy", {}) if isinstance(meta, dict) else {}
    enabled = isinstance(policy, dict) and policy.get("enabled") is True
    if not enabled:
        return {
            "enabled": False,
            "passed": True,
            "errors": 0,
            "warnings": 0,
            "findings": [],
        }

    focused_max = int(policy.get("focused_max_units", 5))
    overview_max = int(policy.get("overview_max_units", 7))
    claim_max = int(policy.get("claim_max_characters", 140))
    seconds_per_unit = {
        "explain": float(policy.get("explain_min_seconds_per_unit", 12)),
        "recognize": float(policy.get("recognize_min_seconds_per_unit", 6)),
        "reference": float(policy.get("reference_min_seconds_per_unit", 4)),
    }
    findings: list[dict[str, Any]] = []
    slides = plan.get("slides", [])
    if not isinstance(slides, list):
        slides = []

    def add(severity: str, slide: int, category: str, message: str) -> None:
        findings.append(
            {
                "severity": severity,
                "slide": slide,
                "category": category,
                "message": message,
            }
        )

    for number, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        claim = str(slide.get("claim", "")).strip()
        mode = str(slide.get("message_mode", "")).strip()
        detail = str(slide.get("detail_policy", "")).strip()
        units = slide.get("information_units")
        timing = slide.get("timing_seconds")

        if mode not in VALID_MODES:
            add(
                "error",
                number,
                "message-mode",
                f"message_mode must be one of {sorted(VALID_MODES)}.",
            )
        if detail not in VALID_DETAIL_POLICIES:
            add(
                "error",
                number,
                "detail-policy",
                f"detail_policy must be one of {sorted(VALID_DETAIL_POLICIES)}.",
            )
        if (
            not isinstance(units, list)
            or not units
            or not all(isinstance(item, str) and item.strip() for item in units)
        ):
            add(
                "error",
                number,
                "information-units",
                "information_units must be a non-empty list of audience-visible concepts.",
            )
            unit_count = 0
        else:
            unit_count = len(units)
            limit = overview_max if mode == "overview" else focused_max
            if unit_count > limit:
                add(
                    "error",
                    number,
                    "information-unit-cutoff",
                    (
                        f"{mode or 'focused'} slide has {unit_count} information units; "
                        f"the cutoff is {limit}."
                    ),
                )

        if mode == "overview" and not str(slide.get("reading_goal", "")).strip():
            add(
                "error",
                number,
                "overview-reading-goal",
                "Overview slides must state what to recognize and what detail is deferred.",
            )

        if len(claim) > claim_max:
            add(
                "warning",
                number,
                "claim-length",
                f"Claim contains {len(claim)} characters; the budget is {claim_max}.",
            )
        sentence_marks = len(re.findall(r"[。.!?！？]", claim.rstrip("。.!?！？")))
        if sentence_marks:
            add(
                "warning",
                number,
                "multiple-claim-sentences",
                "Claim appears to contain multiple sentences; verify that it is one message.",
            )

        if (
            unit_count
            and isinstance(timing, (int, float))
            and timing > 0
            and detail in seconds_per_unit
        ):
            actual = float(timing) / unit_count
            minimum = seconds_per_unit[detail]
            if actual < minimum:
                add(
                    "warning",
                    number,
                    "explanation-rate",
                    (
                        f"{actual:.1f}s per information unit is below the "
                        f"{minimum:g}s {detail} guideline."
                    ),
                )

    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    return {
        "enabled": True,
        "passed": errors == 0 and (warnings == 0 or not strict),
        "errors": errors,
        "warnings": warnings,
        "policy": {
            "focused_max_units": focused_max,
            "overview_max_units": overview_max,
            "claim_max_characters": claim_max,
            "seconds_per_unit": seconds_per_unit,
        },
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit one-message-per-slide and information density metadata."
    )
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    try:
        report = audit(load_json(args.plan), strict=args.strict)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "enabled": True,
            "passed": False,
            "errors": 1,
            "warnings": 0,
            "findings": [
                {
                    "severity": "error",
                    "slide": 0,
                    "category": "input",
                    "message": str(exc),
                }
            ],
        }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
