#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REVIEW_LENS_KEYS = ("builds", "why_next", "takeaway", "caveat")
NON_BODY_ROLES = {"title", "agenda", "summary", "close"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("The plan root must be a JSON object.")
    return data


def audit(plan: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    meta = plan.get("meta")
    policy = meta.get("source_review", {}) if isinstance(meta, dict) else {}
    enabled = isinstance(policy, dict) and policy.get("enabled") is True
    if not enabled:
        return {
            "enabled": False,
            "passed": True,
            "errors": 0,
            "warnings": 0,
            "findings": [],
        }

    findings: list[dict[str, Any]] = []

    def add(severity: str, category: str, message: str, slide: int = 0) -> None:
        findings.append(
            {
                "severity": severity,
                "slide": slide,
                "category": category,
                "message": message,
            }
        )

    if not str(policy.get("review_label", "")).strip():
        add("error", "review-framing", "source_review.review_label is required.")

    works = policy.get("works")
    if not isinstance(works, list) or not works:
        add("error", "source-works", "source_review.works must be a non-empty list.")
        works = []
    work_defs: dict[str, dict[str, Any]] = {}
    for work in works:
        if not isinstance(work, dict):
            continue
        work_id = str(work.get("id", "")).strip()
        sections = work.get("sections")
        if not work_id or not isinstance(sections, list) or not sections:
            add(
                "error",
                "source-works",
                "Each source work requires an id and ordered sections.",
            )
            continue
        work_defs[work_id] = work

    omissions = policy.get("omissions", [])
    omitted: set[tuple[str, str]] = set()
    if isinstance(omissions, list):
        for omission in omissions:
            if not isinstance(omission, dict):
                continue
            work = str(omission.get("work", "")).strip()
            section = str(omission.get("section", "")).strip()
            reason = str(omission.get("reason", "")).strip()
            if work and section and reason:
                omitted.add((work, section))
            else:
                add(
                    "error",
                    "source-omission",
                    "Every omission requires work, section, and a reason.",
                )

    slides = plan.get("slides", [])
    if not isinstance(slides, list):
        slides = []
    mapped: dict[tuple[str, str], int] = {}
    review_slides: dict[str, set[int]] = {work_id: set() for work_id in work_defs}
    body_count = 0
    direct_body_count = 0
    max_sections = int(policy.get("max_sections_per_slide", 6))

    for number, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        role = str(slide.get("role", "")).strip()
        refs = slide.get("source_sections")
        if role not in NON_BODY_ROLES:
            body_count += 1
        if not refs:
            continue
        if role not in NON_BODY_ROLES:
            direct_body_count += 1
        if not isinstance(refs, list):
            add(
                "error",
                "source-sections",
                "source_sections must be a list.",
                number,
            )
            continue

        lens = slide.get("review_lens")
        if not isinstance(lens, dict) or any(
            not str(lens.get(key, "")).strip() for key in REVIEW_LENS_KEYS
        ):
            add(
                "error",
                "review-lens",
                (
                    "Source-mapped slides require builds, why_next, takeaway, "
                    "and caveat review lenses."
                ),
                number,
            )

        section_count = 0
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            work_id = str(ref.get("work", "")).strip()
            sections = ref.get("sections")
            if work_id not in work_defs or not isinstance(sections, list):
                add(
                    "error",
                    "source-sections",
                    "Unknown work or invalid sections list.",
                    number,
                )
                continue
            section_count += len(sections)
            review_slides[work_id].add(number)
            for section in sections:
                section_name = str(section).strip()
                if section_name not in work_defs[work_id]["sections"]:
                    add(
                        "error",
                        "source-sections",
                        f"Unknown section {work_id}:{section_name}.",
                        number,
                    )
                else:
                    mapped.setdefault((work_id, section_name), number)
        if section_count > max_sections:
            add(
                "error",
                "over-summary",
                (
                    f"Slide maps {section_count} source sections; cutoff is "
                    f"{max_sections}. Split or justify omissions."
                ),
                number,
            )

    for work_id, work in work_defs.items():
        previous_slide = 0
        for section in work["sections"]:
            key = (work_id, str(section))
            if key not in mapped and key not in omitted:
                add(
                    "error",
                    "source-coverage",
                    f"Source section {work_id}:{section} is neither reviewed nor omitted.",
                )
            if key in mapped:
                current_slide = mapped[key]
                if current_slide < previous_slide:
                    add(
                        "error",
                        "source-order",
                        f"Source section {work_id}:{section} appears out of order.",
                        current_slide,
                    )
                previous_slide = current_slide
        minimum = int(work.get("minimum_review_slides", 1))
        if len(review_slides[work_id]) < minimum:
            add(
                "error",
                "minimum-review-slides",
                (
                    f"{work_id} appears on {len(review_slides[work_id])} review slides; "
                    f"minimum is {minimum}."
                ),
            )

    minimum_ratio = float(policy.get("minimum_direct_slide_ratio", 0.6))
    ratio = direct_body_count / body_count if body_count else 0.0
    if ratio < minimum_ratio:
        add(
            "error",
            "direct-slide-ratio",
            (
                f"Only {ratio:.1%} of body slides map directly to source sections; "
                f"minimum is {minimum_ratio:.1%}."
            ),
        )

    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    return {
        "enabled": True,
        "passed": errors == 0 and (warnings == 0 or not strict),
        "errors": errors,
        "warnings": warnings,
        "direct_body_slide_ratio": ratio,
        "mapped_sections": len(mapped),
        "omitted_sections": len(omitted),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit source-flow fidelity for review presentations."
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
