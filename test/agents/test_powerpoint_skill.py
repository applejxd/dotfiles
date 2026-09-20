from fnmatch import fnmatch
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREFIX = ".claude/skills/powerpoint-studio"
SKILL = ROOT / "home/dot_claude/skills/powerpoint-studio"


@pytest.mark.parametrize(
    "directory",
    [
        ".venv",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        ".tmp",
        "evals/files",
        "evals/runs",
        "evals/blind",
        "evals/final-verification",
    ],
)
def test_powerpoint_runtime_artifacts_are_ignored_by_chezmoi(directory):
    patterns = [
        line.strip()
        for line in (ROOT / "home/.chezmoiignore.tmpl").read_text().splitlines()
        if line.startswith(f"{PREFIX}/")
    ]
    for target in (f"{PREFIX}/{directory}", f"{PREFIX}/{directory}/generated/file"):
        assert any(fnmatch(target, pattern) for pattern in patterns), target


@pytest.mark.parametrize(
    "relative",
    [
        "SKILL.md",
        "scripts/diagram_geometry.py",
        "scripts/audit_layout_groups.py",
        "scripts/validate_svg.py",
        "scripts/literal_create_montage.py",
        "package-lock.json",
        "uv.lock",
    ],
)
def test_powerpoint_managed_payload_preserves_entrypoints(relative):
    assert (SKILL / relative).is_file()
