#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], env: dict[str, str], stdout_path: Path | None = None) -> None:
    print("+", " ".join(str(part) for part in command))
    if stdout_path:
        with stdout_path.open("w", encoding="utf-8") as handle:
            subprocess.run(command, check=True, env=env, stdout=handle)
    else:
        subprocess.run(command, check=True, env=env)


def run_diagram_layout_audits(
    plan: dict,
    plan_path: Path,
    pptx_path: Path,
    output_dir: Path,
    env: dict[str, str],
) -> list[dict]:
    """Run geometry bindings separately from the existing topology specs.

    Each meta.diagram_layouts entry requires path, image, provenance, 1-based
    slide, and shape. Artifact paths are relative to the plan, not the PPTX or cwd.
    Returned records can be stored verbatim in qa-summary.diagram_geometry_reports.
    """
    entries = plan.get("meta", {}).get("diagram_layouts", [])
    if not isinstance(entries, list):
        raise ValueError("meta.diagram_layouts must be a list.")
    reports = []
    for index, entry in enumerate(entries, start=1):
        if (
            not isinstance(entry, dict)
            or any(
                not isinstance(entry.get(key), str) or not entry[key].strip()
                for key in ("path", "image", "provenance", "shape")
            )
            or isinstance(entry.get("slide"), bool)
            or not isinstance(entry.get("slide"), int)
            or entry["slide"] < 1
        ):
            raise ValueError(
                f"diagram_layouts[{index - 1}] needs path, image, provenance, shape, "
                "and a positive integer slide."
            )
        layout_path = (plan_path.resolve().parent / entry["path"]).resolve()
        image_path = (plan_path.resolve().parent / entry["image"]).resolve()
        provenance_path = (plan_path.resolve().parent / entry["provenance"]).resolve()
        report_path = output_dir / f"diagram-geometry-{index}.json"
        run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "audit_diagram_geometry.py"),
                str(layout_path),
                "--image",
                str(image_path),
                "--pptx",
                str(pptx_path),
                "--provenance",
                str(provenance_path),
                "--slide",
                str(entry["slide"]),
                "--shape",
                entry["shape"],
                "--plan",
                str(plan_path),
                "--output",
                str(report_path),
            ],
            env,
        )
        geometry = json.loads(report_path.read_text(encoding="utf-8"))
        if not geometry.get("passed"):
            raise ValueError(f"Geometry audit did not pass: {report_path}")
        reports.append(
            {
                "report": str(report_path.resolve()),
                "layout": str(layout_path),
                "image": str(image_path),
                "slide": entry["slide"],
                "shape": entry["shape"],
                "provenance": geometry["provenance"],
                "svg": geometry["svg"],
                "renderer": geometry["renderer"],
                "sha256": {**geometry["sha256"], "report": sha256(report_path)},
            }
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete PowerPoint QA gate.")
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--style-policy", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("./.tmp/powerpoint-qa"))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    output_dir = args.output_dir.resolve()
    render_dir = output_dir / "rendered"
    local_tmp = output_dir / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)
    local_tmp.mkdir(parents=True, exist_ok=True)
    for old_render in render_dir.glob("slide-*.png"):
        old_render.unlink()
    env = os.environ.copy()
    env["TMPDIR"] = str(local_tmp)

    if not args.pptx.exists():
        print(f"PPTX does not exist: {args.pptx}", file=sys.stderr)
        return 2
    if args.source and not args.source.exists():
        print(f"Authoring source does not exist: {args.source}", file=sys.stderr)
        return 2

    audit_command = [
        sys.executable,
        str(script_dir / "quality_gate.py"),
        str(args.pptx),
        "--output",
        str(output_dir / "quality-report.json"),
    ]
    if args.plan:
        audit_command += ["--plan", str(args.plan)]
    if args.policy:
        audit_command += ["--policy", str(args.policy)]
    if args.strict:
        audit_command.append("--fail-on-warnings")

    try:
        diagram_geometry_reports = []
        if args.plan:
            plan_data = json.loads(args.plan.read_text(encoding="utf-8"))
            run(
                [
                    sys.executable,
                    str(script_dir / "audit_layout_groups.py"),
                    str(args.pptx),
                    "--plan",
                    str(args.plan),
                    "--output",
                    str(output_dir / "layout-groups-report.json"),
                ],
                env,
            )
            run(
                [sys.executable, str(script_dir / "validate_plan.py"), str(args.plan)],
                env,
            )
            run(
                [
                    sys.executable,
                    str(script_dir / "audit_narrative_balance.py"),
                    str(args.plan),
                    "--output",
                    str(output_dir / "narrative-report.json"),
                ],
                env,
            )
            message_command = [
                sys.executable,
                str(script_dir / "audit_message_density.py"),
                str(args.plan),
                "--output",
                str(output_dir / "message-density-report.json"),
            ]
            if args.strict:
                message_command.append("--strict")
            run(message_command, env)
            source_review_command = [
                sys.executable,
                str(script_dir / "audit_source_review.py"),
                str(args.plan),
                "--output",
                str(output_dir / "source-review-report.json"),
            ]
            if args.strict:
                source_review_command.append("--strict")
            run(source_review_command, env)
            run(
                [
                    sys.executable,
                    str(script_dir / "audit_slide_chrome.py"),
                    str(args.pptx),
                    "--plan",
                    str(args.plan),
                    "--output",
                    str(output_dir / "slide-chrome-report.json"),
                ],
                env,
            )
            diagram_reports = []
            diagram_specs = plan_data.get("meta", {}).get("diagram_specs", [])
            for index, raw_spec in enumerate(diagram_specs, start=1):
                spec_path = Path(raw_spec)
                if not spec_path.is_absolute():
                    spec_path = args.plan.resolve().parent / spec_path
                report_path = output_dir / f"diagram-topology-{index}.json"
                run(
                    [
                        sys.executable,
                        str(script_dir / "audit_diagram_topology.py"),
                        str(spec_path),
                        "--output",
                        str(report_path),
                    ],
                    env,
                )
                diagram_reports.append(str(report_path))
            diagram_geometry_reports = run_diagram_layout_audits(
                plan_data,
                args.plan,
                args.pptx,
                output_dir,
                env,
            )
            run(
                [
                    sys.executable,
                    str(script_dir / "audit_typography_system.py"),
                    str(args.pptx),
                    "--plan",
                    str(args.plan),
                    "--output",
                    str(output_dir / "typography-system-report.json"),
                ],
                env,
            )
            run(
                [
                    sys.executable,
                    str(script_dir / "validate_timing.py"),
                    str(args.pptx),
                    "--plan",
                    str(args.plan),
                    "--output",
                    str(output_dir / "timing-report.json"),
                ],
                env,
            )
        run(
            [
                sys.executable,
                str(script_dir / "validate_ooxml.py"),
                str(args.pptx),
                "--output",
                str(output_dir / "ooxml-report.json"),
            ],
            env,
        )
        run(audit_command, env)
        if args.style_policy:
            run(
                [
                    sys.executable,
                    str(script_dir / "validate_style.py"),
                    str(args.pptx),
                    "--policy",
                    str(args.style_policy),
                    "--output",
                    str(output_dir / "style-report.json"),
                ],
                env,
            )
        if args.template:
            template_command = [
                sys.executable,
                str(script_dir / "template_fidelity.py"),
                str(args.template),
                str(args.pptx),
                "--output-report",
                str(output_dir / "template-report.json"),
            ]
            if args.strict:
                template_command.append("--strict")
            run(template_command, env)
        run(
            [
                sys.executable,
                str(script_dir / "render_slides.py"),
                str(args.pptx),
                "--output_dir",
                str(render_dir),
                "--width",
                "1920",
                "--height",
                "1080",
            ],
            env,
        )
        run(
            [
                sys.executable,
                str(script_dir / "create_montage.py"),
                "--input_dir",
                str(render_dir),
                "--output_file",
                str(output_dir / "montage.png"),
                "--label_mode",
                "filename",
            ],
            env,
        )
        run(
            [sys.executable, str(script_dir / "slides_test.py"), str(args.pptx)],
            env,
        )
        run(
            [
                sys.executable,
                str(script_dir / "detect_font.py"),
                str(args.pptx),
                "--json",
            ],
            env,
            output_dir / "font-report.json",
        )
    except subprocess.CalledProcessError as exc:
        print(f"QA gate failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode or 1
    except ValueError as exc:
        print(f"QA gate failed: {exc}", file=sys.stderr)
        return 1

    font_report = json.loads((output_dir / "font-report.json").read_text(encoding="utf-8"))
    missing_fonts = font_report.get("font_missing_overall", [])
    substituted_fonts = font_report.get("font_substituted_overall", [])
    if missing_fonts:
        print(
            "QA gate failed: missing fonts: " + ", ".join(missing_fonts),
            file=sys.stderr,
        )
        return 1
    if args.strict and substituted_fonts:
        print(
            "QA gate failed in strict mode: substituted fonts: " + ", ".join(substituted_fonts),
            file=sys.stderr,
        )
        return 1

    quality_report = json.loads((output_dir / "quality-report.json").read_text(encoding="utf-8"))
    rendered_files = sorted(render_dir.glob("slide-*.png"))
    if len(rendered_files) != quality_report["slide_count"]:
        print(
            (
                f"QA gate failed: rendered {len(rendered_files)} PNGs for "
                f"{quality_report['slide_count']} slides."
            ),
            file=sys.stderr,
        )
        return 1

    report = {
        "pptx": str(args.pptx.resolve()),
        "plan": str(args.plan.resolve()) if args.plan else None,
        "source": str(args.source.resolve()) if args.source else None,
        "template": str(args.template.resolve()) if args.template else None,
        "style_policy": (str(args.style_policy.resolve()) if args.style_policy else None),
        "rendered_dir": str(render_dir),
        "montage": str(output_dir / "montage.png"),
        "quality_report": str(output_dir / "quality-report.json"),
        "ooxml_report": str(output_dir / "ooxml-report.json"),
        "timing_report": (str(output_dir / "timing-report.json") if args.plan else None),
        "narrative_report": (str(output_dir / "narrative-report.json") if args.plan else None),
        "message_density_report": (
            str(output_dir / "message-density-report.json") if args.plan else None
        ),
        "source_review_report": (
            str(output_dir / "source-review-report.json") if args.plan else None
        ),
        "slide_chrome_report": (
            str(output_dir / "slide-chrome-report.json") if args.plan else None
        ),
        "typography_system_report": (
            str(output_dir / "typography-system-report.json") if args.plan else None
        ),
        "layout_groups_report": (
            str(output_dir / "layout-groups-report.json") if args.plan else None
        ),
        "diagram_topology_reports": diagram_reports if args.plan else [],
        "diagram_geometry_reports": diagram_geometry_reports,
        "font_report": str(output_dir / "font-report.json"),
        "template_report": (str(output_dir / "template-report.json") if args.template else None),
        "style_report": (str(output_dir / "style-report.json") if args.style_policy else None),
        "font_substitutions": substituted_fonts,
        "sha256": {
            "pptx": sha256(args.pptx),
            "plan": sha256(args.plan),
            "source": sha256(args.source),
            "template": sha256(args.template),
            "style_policy": sha256(args.style_policy),
            "layout_groups_report": (
                sha256(output_dir / "layout-groups-report.json") if args.plan else None
            ),
        },
        "passed": True,
    }
    (output_dir / "qa-summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(f"QA gate passed. Review artifacts: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
