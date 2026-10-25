"""markdownlint.sh が `.tmp/` 配下を lint も自動修正もしないことの試験。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "home/dot_claude/hooks/executable_markdownlint.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash 無し")
def test_tmp_dir_is_skipped_and_left_untouched(tmp_path):
    work = tmp_path / ".tmp" / "research"
    work.mkdir(parents=True)
    md = work / "map.md"
    body = "# T\n\n```\nno lang\n```\n\n\n\ntrailing  \n"
    md.write_text(body, encoding="utf-8")
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"tool_input": {"file_path": str(md)}}),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0
    assert "markdownlint" not in proc.stdout + proc.stderr
    assert md.read_text(encoding="utf-8") == body
