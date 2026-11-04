"""scripts/<名>.py の転送: 本体 (home/dot_claude/skills/feature-orchestration/scripts/) と同じ出力・終了コードを返す。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BODY_DIR = ROOT / "home" / "dot_claude" / "skills" / "feature-orchestration" / "scripts"
NAMES = ["wt_owner", "wt_clean", "parallel_check", "feature_gate", "bundle", "prs"]


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("args", [("--help",), ("--no-such-option-zz",)])
def test_forwarder_matches_body(name, args):
    body = _run(BODY_DIR / f"{name}.py", *args)
    fwd = _run(ROOT / "scripts" / f"{name}.py", *args)
    assert (fwd.returncode, fwd.stdout, fwd.stderr.replace(f"{name}.py", "X")) == (
        body.returncode,
        body.stdout,
        body.stderr.replace(f"{name}.py", "X"),
    )


@pytest.mark.parametrize("name", NAMES)
def test_forwarder_is_thin_and_points_to_body(name):
    text = (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
    assert f"home/dot_claude/skills/feature-orchestration/scripts/{name}.py" in text
    assert len(text.splitlines()) < 30
    assert (BODY_DIR / f"{name}.py").is_file()
