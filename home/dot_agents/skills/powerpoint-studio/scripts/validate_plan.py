#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROLES = {
    "title",
    "agenda",
    "hook",
    "context",
    "evidence",
    "mechanism",
    "decision",
    "action",
    "close",
    "summary",
}
VISUAL_TYPES = {
    "chart",
    "diagram",
    "screenshot",
    "photo",
    "table",
    "native-shapes",
    "none",
}
VISUAL_OPTIONAL_ROLES = {"title", "agenda", "hook", "close"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("The plan root must be a JSON object.")
    return data


def validate_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    meta = plan.get("meta")
    slides = plan.get("slides")
    if not isinstance(meta, dict):
        errors.append("/meta must be an object")
    else:
        for key in ("title", "audience", "objective", "language"):
            if not str(meta.get(key, "")).strip():
                errors.append(f"/meta/{key} is required")
        duration = meta.get("duration_minutes")
        if not isinstance(duration, (int, float)) or duration <= 0:
            errors.append("/meta/duration_minutes must be a positive number")

    if not isinstance(slides, list) or not slides:
        return [*errors, "/slides must be a non-empty array"]

    ids: set[str] = set()
    timing_present = any(
        isinstance(slide, dict) and slide.get("timing_seconds") is not None for slide in slides
    )
    timing_total = 0.0
    previous_role = ""
    consecutive_layout = 0
    previous_layout = ""
    for index, slide in enumerate(slides, start=1):
        base = f"/slides/{index - 1}"
        if not isinstance(slide, dict):
            errors.append(f"{base} must be an object")
            continue

        slide_id = str(slide.get("id", "")).strip()
        if not slide_id:
            errors.append(f"{base}/id is required")
        elif slide_id in ids:
            errors.append(f"{base}/id duplicates {slide_id!r}")
        ids.add(slide_id)

        role = str(slide.get("role", "")).strip()
        if role not in ROLES:
            errors.append(f"{base}/role must be one of {sorted(ROLES)}")
        title = str(slide.get("title", "")).strip()
        claim = str(slide.get("claim", "")).strip()
        if not title:
            errors.append(f"{base}/title is required")
        if not claim:
            errors.append(f"{base}/claim is required")
        if len(title) > 100:
            errors.append(f"{base}/title exceeds the 100-character budget")
        if len(claim) > 220:
            errors.append(f"{base}/claim exceeds the 220-character budget")

        evidence = slide.get("evidence")
        if role in {"evidence", "decision"} and (
            not isinstance(evidence, list) or not any(str(item).strip() for item in evidence)
        ):
            errors.append(f"{base}/evidence is required for role {role!r}")

        visual = slide.get("visual")
        if not isinstance(visual, dict):
            errors.append(f"{base}/visual must be an object")
        else:
            visual_type = str(visual.get("type", "")).strip()
            if visual_type not in VISUAL_TYPES:
                errors.append(f"{base}/visual/type must be one of {sorted(VISUAL_TYPES)}")
            if visual_type == "none" and role not in VISUAL_OPTIONAL_ROLES:
                errors.append(f"{base}/visual/type cannot be 'none' for a {role!r} slide")
            if visual_type != "none" and not str(visual.get("purpose", "")).strip():
                errors.append(f"{base}/visual/purpose is required")

        layout = str(slide.get("layout", "")).strip()
        if not layout:
            errors.append(f"{base}/layout is required")
        if layout == previous_layout:
            consecutive_layout += 1
        else:
            consecutive_layout = 1
            previous_layout = layout
        if consecutive_layout >= 3:
            errors.append(f"{base}/layout repeats {layout!r} for three consecutive slides")

        for key in ("speaker_goal", "transition"):
            if not str(slide.get(key, "")).strip():
                errors.append(f"{base}/{key} is required")

        if timing_present:
            timing = slide.get("timing_seconds")
            if not isinstance(timing, (int, float)) or timing <= 0:
                errors.append(f"{base}/timing_seconds must be a positive number")
            else:
                timing_total += float(timing)
            optional_cut = slide.get("optional_cut_seconds", 0)
            if not isinstance(optional_cut, (int, float)) or optional_cut < 0:
                errors.append(f"{base}/optional_cut_seconds must be a non-negative number")
            elif isinstance(timing, (int, float)) and optional_cut > timing:
                errors.append(f"{base}/optional_cut_seconds cannot exceed timing_seconds")

        long_form = (
            isinstance(meta, dict)
            and isinstance(meta.get("session_duration_minutes"), (int, float))
            and meta["session_duration_minutes"] >= 15
        )
        if index == 1 and long_form and role != "title":
            errors.append("/slides/0/role must be 'title' for a long-form talk")
        elif index == 1 and not long_form and role not in {"title", "hook", "context"}:
            errors.append("/slides/0/role should be 'title', 'hook', or 'context'")
        if index == 2 and long_form and role != "agenda":
            errors.append("/slides/1/role must be 'agenda' for a long-form talk")
        if previous_role in {"close", "summary"}:
            errors.append(f"{base} appears after a terminal slide")
        previous_role = role

    last_role = str(slides[-1].get("role", "")) if isinstance(slides[-1], dict) else ""
    long_form = (
        isinstance(meta, dict)
        and isinstance(meta.get("session_duration_minutes"), (int, float))
        and meta["session_duration_minutes"] >= 15
    )
    if long_form and last_role != "summary":
        errors.append("The final slide must be a summary for a long-form talk")
    elif not long_form and last_role not in {"decision", "action", "close", "summary"}:
        errors.append("The final slide must be a decision, action, or close slide")
    if timing_present and isinstance(meta, dict):
        duration = meta.get("duration_minutes")
        if isinstance(duration, (int, float)) and abs(timing_total - duration * 60) > 5:
            errors.append(
                f"Slide timing totals {timing_total:.0f}s but "
                f"meta.duration_minutes is {duration:g}m"
            )
        session_duration = meta.get("session_duration_minutes")
        buffer_minutes = meta.get("buffer_minutes", 0)
        if (
            isinstance(session_duration, (int, float))
            and isinstance(buffer_minutes, (int, float))
            and timing_total > max(0, session_duration - buffer_minutes) * 60
        ):
            errors.append("Slide timing exceeds session duration after the required buffer")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a PowerPoint deck plan.")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        errors = validate_plan(load_json(args.plan))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]

    result = {"valid": not errors, "errors": errors}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Deck plan validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print(f"Deck plan is valid: {args.plan}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
