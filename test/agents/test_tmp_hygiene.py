"""試験が一時領域 (``TMPDIR``) に残骸を残さないことの固定。

``.tmp/`` が 31 GB に膨らんだ原因のうち、試験が作るもの (CHG-0042 段 4):

- ``tools-ext-*``: ``test/agents/pi/tools_ext_driver.mjs`` が後始末をしていなかった (1 回 約 35 MB)
- ``agents-config-*``: ``agents_common.agents_config_dir`` が ``atexit`` だけに頼っていた。
  pytest-xdist のワーカーは ``os._exit`` で終わるので ``atexit`` が走らず、ワーカーの数だけ残った
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DRIVER = HERE / "pi" / "tools_ext_driver.mjs"


def _run(argv: list[str], tmp: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=ROOT,
        timeout=120,
        check=False,
    )


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_tools_ext_driver_removes_its_temp_dir(tmp_path: Path) -> None:
    proc = _run([_node(), str(DRIVER)], tmp_path)
    assert proc.returncode == 0, proc.stderr[-1000:]
    assert list(tmp_path.glob("tools-ext-*")) == []


def test_agents_config_dir_is_removed_by_cleanup(tmp_path: Path) -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(HERE)!r}); import agents_common as a; "
        "p = a.agents_config_dir(); print(p.exists()); a.cleanup_agents_config_dirs(); print(p.exists())"
    )
    proc = _run([sys.executable, "-c", code], tmp_path)
    assert proc.returncode == 0, proc.stderr[-1000:]
    assert proc.stdout.split() == ["True", "False"]
    assert list(tmp_path.glob("agents-config-*")) == []


def test_agents_config_dir_is_removed_without_atexit(tmp_path: Path) -> None:
    """xdist のワーカーのように ``os._exit`` で終わっても、``cleanup_agents_config_dirs`` を呼べば残らない。"""
    code = (
        f"import os, sys; sys.path.insert(0, {str(HERE)!r}); import agents_common as a; "
        "a.agents_config_dir(); a.cleanup_agents_config_dirs(); os._exit(0)"
    )
    proc = _run([sys.executable, "-c", code], tmp_path)
    assert proc.returncode == 0, proc.stderr[-1000:]
    assert list(tmp_path.glob("agents-config-*")) == []
