"""承認の確認画面の本文 (approveBody・pendingApproval) の単体試験。

題を work ツールの検証へ通さず、画面を作る関数へ直接渡す (または reducer へ直接足す)。そのため題が拒否されて
試験が空振りすることはない。driver は ``work_approve_body_driver.mjs``。see docs/spec/work/goal-run.md
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_approve_body_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

SECRET_SK = "sk-" + "A" * 24
SECRET_GH = "ghp_" + "B" * 30
SECRET_AWS = "AKIA" + "C" * 16
# 画面に生で残してはならない文字 (C0 [改行・タブを除く]・DEL・C1・方向制御・ZW 系・BOM)
FORBIDDEN = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")
HOSTILE = [
    "c0\x01\x07\x08\x1b[31mred\x1b[0m",
    "c1\x85\x9b31mend\x9d0;t\x9c",
    "bidi\u202eevil\u202a\u202b\u202c\u202d\u2066\u2067\u2068\u2069x",
    "zw\u200b\u200c\u200d\u200e\u200f\u2060\ufeffend",
    "z" + "\u0301" * 40 + "end",
    f"key {SECRET_SK} end",
    f"gh {SECRET_GH} end",
    f"aws {SECRET_AWS} end",
    "multi\nline\r\ntitle\ttab",
]


def run(payload):
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip("\n").split("\n")[-1])


def direct(titles, goal="目標", total=None, ids=None):
    return run(
        {
            "mode": "direct",
            "goal": goal,
            "total": len(titles) if total is None else total,
            "titles": titles,
            "ids": ids if ids is not None else [f"t{i}" for i in range(len(titles))],
        }
    )["body"]


def clean(body):
    assert not FORBIDDEN.search(body), repr(body)
    for s in (SECRET_SK, SECRET_GH, SECRET_AWS):
        assert s not in body
    assert "\u0301" * 3 not in body


@pytest.mark.parametrize("title", HOSTILE)
def test_direct_title_leaves_no_raw_control_or_secret(title):
    body = direct([title])
    clean(body)
    assert "[t0]" in body and "1 件" in body


@pytest.mark.parametrize("title", HOSTILE)
def test_direct_goal_title_is_sanitized(title):
    clean(direct(["通常の題"], goal=title))


def test_direct_secret_titles_are_redacted_but_listed():
    body = direct([f"a {SECRET_SK}", f"b {SECRET_GH}", f"c {SECRET_AWS}"])
    assert body.count("[伏字") == 3 and body.count("\n- [") == 3 and "3 件" in body


def test_direct_keeps_total_more_and_ids_with_hostile_titles():
    titles = [f"タスク{i:02d} {HOSTILE[i % len(HOSTILE)]}" for i in range(10)]
    body = direct(titles, total=13)
    clean(body)
    assert "13 件" in body and "ほか 3 件" in body and body.count("\n- [") == 10
    assert all(f"[t{i}]" in body for i in range(10))


def test_direct_no_more_line_when_total_equals_shown():
    assert "ほか" not in direct(["a", "b"])


def test_direct_hostile_id_is_sanitized_too():
    body = direct(["題"], ids=["t\u202e1\x1b[31m"])
    clean(body)


def test_direct_first_approval_without_pending_has_goal_only():
    body = run({"mode": "direct", "goal": "目標\u202e"})["body"]
    clean(body)
    assert "承認しますか" in body and "task が" not in body


def test_direct_wide_title_is_clipped():
    line = next(x for x in direct(["あ" * 100]).split("\n") if x.startswith("- "))
    assert len(line) < 90


def test_ledger_path_lists_pending_ids_and_titles_without_raw_chars():
    out = run({"mode": "ledger", "goal": "目標", "titles": [f"t {x}" for x in HOSTILE]})
    assert out["setup"] and all(out["adds"])  # 台帳へ入った (拒否されて空振りしていない)
    assert out["pending"]["total"] == len(HOSTILE)
    clean(out["body"])
    assert "ほか" not in out["body"] and out["body"].count("\n- [") == len(HOSTILE)


def test_ledger_path_limits_to_ten_and_keeps_total():
    out = run(
        {"mode": "ledger", "goal": "目標", "titles": [f"n{i} {SECRET_SK}" for i in range(12)]}
    )
    assert all(out["adds"]) and out["pending"]["total"] == 12 and len(out["pending"]["ids"]) == 12
    assert (
        "12 件" in out["body"] and "ほか 2 件" in out["body"] and out["body"].count("\n- [") == 10
    )
    clean(out["body"])
