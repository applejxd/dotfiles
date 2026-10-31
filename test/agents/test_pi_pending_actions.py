"""非同期承認の保留への接続 (``home/dot_config/pi/harness/actions.ts`` の ``executeAction``。CHG-0055 の P4)。

``test/agents/pi/pending_actions_driver.mjs`` が、偽の ctx で ``executeAction`` を直接動かして結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。確かめるのは、アダプタを登録した操作だけが
「あとで」・時間切れ・不在・UI なしで保留に回り (実行はしない)、それ以外の形は従来どおりであること。
承認して実行する側 (``/pending approve``) は P5 以降。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_actions_driver.mjs"
APPROVE, EDIT, LATER, REJECT = "承認して実行", "編集して承認", "あとで (保留)", "拒否"

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


@pytest.mark.parametrize(
    ("case", "reason"),
    [("later", "later"), ("timeout", "timeout"), ("absent", "absent"), ("no_ui", "no_ui")],
)
def test_an_unapproved_operation_with_an_adapter_is_saved_not_executed(table, case, reason):
    r = table[case]
    assert r["ok"] is False and r["text"].startswith(
        "not approved:"
    )  # モデルには「未実行」として返る (isError)
    assert r["executed"] is False  # 実行する経路が無い
    assert r["refs"] == 1 and len(r["records"]) == 1
    rec = r["records"][0]
    assert (
        rec["reason"] == reason
        and rec["action"] == "fake_op"
        and rec["session"] == "session-1"
        and rec["cwd"] is True
    )
    assert set(rec["params"]) == {"target"} and rec["premiseKeys"] == ["head", "target"]
    assert r["saved"] == [{"action": "fake_op", "reason": reason, "duplicate": False}]
    assert "保留" in r["text"] and "再試行しない" in r["text"] and "未実行" in r["text"]


def test_the_later_option_appears_only_for_operations_with_an_adapter(table):
    assert table["later"]["selects"] == [[APPROVE, EDIT, LATER, REJECT]]
    assert table["approve"]["selects"] == [[APPROVE, EDIT, LATER, REJECT]]
    for case in (
        "no_adapter",
        "disabled",
        "no_pending_deps",
        "mode_not_listed",
        "capture_fails",
        "capture_throws",
    ):
        assert table[case]["selects"] == [[APPROVE, EDIT, REJECT]], case


def test_approval_still_executes_and_saves_nothing(table):
    a = table["approve"]
    assert a["ok"] is True and a["executed"] is True and a["refs"] == 0 and a["saved"] == []


def test_a_rejection_is_not_saved(table):
    r = table["reject"]
    assert r["ok"] is False and r["executed"] is False and r["refs"] == 0 and r["saved"] == []


def test_a_timeout_marks_the_user_absent_and_the_next_request_is_saved_without_asking(table):
    assert table["timeout"]["absent"] is True
    a = table["absent"]
    assert (
        a["selects"] == [] and a["records"][0]["reason"] == "absent"
    )  # 不在なら、待たずに保留する


def test_choosing_later_is_not_absence(table):
    assert table["later"]["absent"] is False


@pytest.mark.parametrize(
    "case",
    [
        "no_adapter",
        "disabled",
        "no_pending_deps",
        "mode_not_listed",
        "capture_fails",
        "capture_throws",
    ],
)
def test_without_pending_support_everything_is_as_before(table, case):
    r = table[case]
    # 時間切れは今までどおり拒否で、何も残さない
    assert r["ok"] is False and "時間内に無かったので拒否した" in r["text"]
    assert r["executed"] is False and r["refs"] == 0 and r["saved"] == []
    assert r["absent"] is True  # 不在の状態は、今までどおり立つ


def test_without_a_ui_an_operation_without_an_adapter_is_refused_as_before(table):
    r = table["no_ui_without_adapter"]
    assert "確認できない実行" in r["text"] and r["refs"] == 0 and r["executed"] is False


def test_the_same_request_is_not_saved_twice(table):
    d = table["duplicate"]
    assert (
        "同じ要求が、すでに保留中" not in d["first"] and "同じ要求が、すでに保留中" in d["second"]
    )
    assert d["refs"] == 1 and d["savedSecond"][0]["duplicate"] is True


def test_when_saving_fails_the_operation_is_refused_and_not_executed(table):
    r = table["save_fails"]
    assert (
        r["executed"] is False
        and r["refs"] == 0
        and "保留も作れなかった (保留が上限に達している)" in r["text"]
    )


def test_a_child_agent_can_neither_run_nor_save(table):
    c = table["child"]
    assert (
        "子エージェントは guarded_action を使えない" in c["text"]
        and c["refs"] == 0
        and c["selects"] == []
    )


def test_the_legacy_git_commit_deferral_is_unchanged(table):
    g = table["git_commit_unchanged"]
    # 保留が有効でも、git_commit は従来の退避 (旧形式)。「あとで」は出さない
    assert g["kind"] == "legacy" and g["refs"] == 1 and g["pendingRecords"] == 0
    assert "退避した" in g["text"] and g["selects"] == [[APPROVE, "全文を見る", EDIT, REJECT]]
