"""保留の承認 (CHG-0055) の owner 判定 (``home/dot_config/pi/harness/pending-owner.ts``)。

``test/agents/pi/pending_owner_driver.mjs`` が実プロセスで動かして結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。PID だけでは再利用と区別できないので、
起動時刻も照合することを確かめる。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_owner_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_own_process_is_alive(table):
    assert table["self"]["state"]["state"] == "alive"


def test_child_is_alive_then_gone_after_kill(table):
    assert table["child_alive"]["state"] == "alive"
    assert table["child_gone"]["state"] == "gone"


def test_changed_start_time_means_pid_reuse(table):
    assert table["child_start_changed"]["state"] == "gone"


def test_missing_recorded_start_is_unknown(table):
    assert table["child_start_null"]["state"] == "unknown"


def test_other_host_is_unknown(table):
    assert table["other_host"]["state"] == "unknown"


def test_invalid_pids_are_unknown(table):
    assert set(table["bad_pid"].values()) == {"unknown"}
    assert len(table["bad_pid"]) == 5


def test_unsupported_platform_is_unknown(table):
    assert table["win32"]["state"] == "unknown"


def test_reasons_are_one_line_without_control_characters(table):
    for key in (
        "child_alive",
        "child_gone",
        "child_start_changed",
        "child_start_null",
        "other_host",
        "win32",
    ):
        reason = table[key]["reason"]
        assert reason and all(c.isprintable() for c in reason)


def test_parse_linux_stat_handles_odd_command_names(table):
    p = table["parse"]
    assert p["odd_name"] == "424242"
    assert p["broken"] is None and p["short"] is None
