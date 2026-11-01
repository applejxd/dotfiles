"""要求側の保存 (``home/dot_config/pi/harness/pending-request.ts``。CHG-0055 の P8c)。

``test/agents/pi/pending_request_driver.mjs`` が ``requestApproval`` を使い捨てのリポジトリで動かす
(node の型除去を使うので、22.18 未満の node では飛ばす)。確かめるのは、検査順、保存だけで実行しないこと、
要求側のモジュールが承認・実行側を import しないこと。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_request_driver.mjs"
SOURCE = ROOT / "home" / "dot_config" / "pi" / "harness" / "pending-request.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_a_request_is_saved_with_reason_request_and_nothing_is_executed(table):
    r = table["ok"]
    assert (
        r["result"]["ok"] is True
        and r["result"]["duplicate"] is False
        and r["result"]["action"] == "git_integrate"
    )
    assert r["result"]["ref"] == f"refs/pi/pending/{r['result']['id']}"
    assert r["refs"] == 1 and len(r["records"]) == 1
    rec = r["records"][0]
    assert rec["reason"] == "request" and rec["action"] == "git_integrate"
    assert rec["params"] == {"source": "feature/x"} and rec["session"] == "session-1"
    assert rec["cwd"] is True and rec["worktree"] is True and rec["host"] == "host-1"
    assert r["unchanged"] is True  # HEAD・ブランチ・作業ツリーは不変 (保存だけ)


def test_the_same_request_is_a_duplicate(table):
    d = table["dup"]
    assert d["first"]["ok"] is True and d["first"]["duplicate"] is False
    assert d["second"]["ok"] is True and d["second"]["duplicate"] is True
    assert d["second"]["id"] == d["first"]["id"] and d["refs"] == 1


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("child", "child"),
        ("disabled", "disabled"),
        ("mode", "mode"),
        ("unsupported", "unsupported"),
        ("aborted", "aborted"),
        ("captureFails", "premise"),
        ("captureThrows", "premise"),
        ("saveFails", "save_failed"),
    ],
)
def test_each_refusal_has_its_code_and_saves_nothing(table, case, code):
    r = table[case]
    assert r["result"]["ok"] is False and r["result"]["code"] == code and r["result"]["reason"]
    assert r["refs"] == 0 and r["unchanged"] is True


def test_the_checks_run_in_order_before_capture(table):
    for case in ("child", "disabled", "mode", "unsupported", "aborted"):
        assert table[case]["captures"] == 0  # 前提を取る前に断る
    assert table["captureFails"]["captures"] == 1 and table["saveFails"]["saves"] == 1


def test_the_request_side_does_not_import_the_approval_or_execution_side():
    text = SOURCE.read_text(encoding="utf-8")
    imports = re.findall(r"""^\s*(?:import|export)\b[^;]*?from\s+["']([^"']+)["']""", text, re.M)
    assert imports, "import 文が読めていない"
    banned = ("pending-approve", "integrate-exec", "exclusive-lock", "integrate-action")
    assert [i for i in imports if any(b in i for b in banned)] == []
    assert all(
        i.startswith("node:") or i in ("./pending-ops.ts", "./actions.ts") for i in imports
    ), imports
