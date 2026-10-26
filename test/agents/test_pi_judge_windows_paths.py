"""判定器のパス処理が Windows (Git Bash の MSYS 形式を含む) でも効くこと。

platform を引数で差し替えた node のドライバで、Linux 上から win32 を模擬する。
Windows 実機の試験ではない。

see docs/spec/guard/pi-decide.md#ts-版への移植
"""

from __future__ import annotations

import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "windows_paths_driver.mjs"


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_home_fixed_globs_and_rm_match_every_windows_path_form():
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "checks ok" in proc.stdout
