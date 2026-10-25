"""markdownlint.sh が作業ツリー直下の `.tmp/` を lint も自動修正もしないことの試験。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "home/dot_claude/hooks/executable_markdownlint.sh"
BODY = "# T\n\n```\nno lang\n```\n\n\n\ntrailing  \n"


def _run(md: Path, cwd: Path, path_arg: str):
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"tool_input": {"file_path": path_arg}}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash 無し")
@pytest.mark.parametrize("relative", [True, False])
def test_tmp_under_the_workdir_is_skipped_and_left_untouched(tmp_path, relative):
    md = tmp_path / ".tmp" / "research" / "map.md"
    md.parent.mkdir(parents=True)
    md.write_text(BODY, encoding="utf-8")
    proc = _run(md, tmp_path, ".tmp/research/map.md" if relative else str(md))
    assert proc.returncode == 0
    assert "markdownlint" not in proc.stdout + proc.stderr
    assert md.read_text(encoding="utf-8") == BODY


@pytest.mark.skipif(shutil.which("markdownlint-cli2") is None, reason="markdownlint-cli2 無し")
def test_a_tmp_ancestor_outside_the_workdir_is_still_linted(tmp_path):
    # 作業ツリーの外の .tmp (pytest の一時領域など) は対象のまま
    md = tmp_path / ".tmp" / "proj" / "d.md"
    md.parent.mkdir(parents=True)
    md.write_text(BODY, encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    proc = _run(md, other, str(md))
    assert "[markdownlint] issues remain" in proc.stdout + proc.stderr
