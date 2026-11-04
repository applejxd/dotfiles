"""承認の時点の task だけをスケジューラが自動起動する (Node.approved) の試験。

承認済み goal へモデルが ``work add`` で足した task は、利用者の承認なしに自動起動してはならない。
シナリオは ``test/agents/pi/work_approve_driver.mjs`` が実物 (reduce・tool・adapt・sched・store) で実行し、結果をここで照合する。
node の型除去を使うので、22.18 未満の node では飛ばす。
see docs/spec/work/ledger.md#設計上の判断
"""

from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "work_approve_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

NOTE = "承認待ち（スケジューラは起動しない。/goal approve で承認）"


@functools.cache
def R() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── 承認で現存の task に approved が立つ ─────────────────────────────────


def test_approve_stamps_existing_tasks():
    a = R()["approve"]
    assert a["T1"] is True
    assert a["T2"] is True


def test_approve_does_not_stamp_before_approval():
    assert R()["approve"]["before"]["T1"] is None


def test_approve_does_not_stamp_goal():
    assert R()["approve"]["G"] is None


def test_approve_promotes_proposed_to_ready():
    a = R()["approve"]
    assert a["before"]["state"] == "proposed"
    assert a["s1"] == "ready"


def test_approved_tasks_are_scheduler_candidates():
    assert R()["approve"]["startsOf"] == ["T1", "T2"]


def test_approve_keeps_invariants():
    assert R()["approve"]["viol"] == []


# ── 承認の後に追加した task は起動候補にならない ──────────────────────────


def test_late_task_becomes_ready_without_approval():
    late = R()["late"]
    assert late["ok"] is True
    assert late["state"] == "ready"  # 遷移表は変えない
    assert late["approved"] is None


def test_late_task_is_not_started_by_scheduler():
    late = R()["late"]
    assert late["id"] not in late["starts"]
    assert late["starts"] == ["T1"]


def test_late_task_is_demoted_in_sched_state():
    assert R()["late"]["sched"] == {"T1": "ready", "n2": "proposed"}


def test_late_task_is_not_in_ready_of():
    assert R()["late"]["readyIds"] == ["T1"]


def test_project_ready_display_projection_is_unchanged():
    # 表示用の投影 (project.ready) は変えない。追加 task も出る
    assert R()["late"]["projectReady"] == ["T1", "n2"]


def test_late_add_keeps_invariants():
    assert R()["late"]["viol"] == []


def test_active_goal_cannot_be_reproposed_and_empty_reapprove_is_rejected():
    r = R()["reapprove"]
    assert "未定義の遷移" in r["e1"]  # plan.proposed は active では受け付けない
    assert "承認の対象" in r["e2"]  # 未承認の task が無い再承認は拒否 (空の承認を作らない)


def test_second_late_task_stays_unapproved():
    r = R()["reapprove"]
    assert r["approved"] is None
    assert r["id2"] not in r["starts"]
    assert r["id2"] not in r["readyIds"]


def test_reapprove_attempts_keep_invariants():
    assert R()["reapprove"]["viol"] == []


# ── 承認前の task は従来どおり候補にならない ──────────────────────────────


def test_before_approval_task_is_proposed_and_not_started():
    b = R()["beforeApprove"]
    assert b["state"] == "proposed"
    assert b["approved"] is None
    assert b["starts"] == []
    assert b["ready"] == []


# ── モデルのツール set は承認の有無にかかわらず従来どおり ─────────────────


def test_model_set_in_progress_and_done_still_works_for_late_task():
    s = R()["lateSet"]
    assert s["s1"] is True
    assert s["s2"] is True
    assert s["state"] == "done"


def test_model_set_does_not_stamp_approved():
    assert R()["lateSet"]["approved"] is None


def test_model_set_keeps_invariants():
    assert R()["lateSet"]["viol"] == []


# ── 終端の task との整合 ──────────────────────────────────────────────────


def test_approved_task_can_become_done():
    t = R()["terminal"]["afterEnd"]
    assert t["s1"] == "done"
    assert t["T1"] is True
    assert t["T2"] is True


def test_terminal_scenario_keeps_invariants():
    assert R()["terminal"]["viol"] == []


def test_done_task_is_not_started_and_approved_open_task_is():
    s = R()["terminal"]["sched"]
    assert s["T1"] == "done"
    assert s["T3"] == "ready"


# ── 利用者専用 (I10) ──────────────────────────────────────────────────────


def test_model_sourced_plan_approved_is_rejected():
    f = R()["forged"]
    assert "I10" in f["err"]
    assert "I10" in f["bad"]


def test_forged_approval_leaves_goal_planned_and_tasks_unapproved():
    f = R()["forged"]
    assert f["gState"] == "planned"
    assert f["approved"] is None


# ── 永続 → 再生 ───────────────────────────────────────────────────────────


def test_replay_gives_same_state():
    assert R()["replay"]["same"] is True


def test_replay_keeps_approved_for_existing_task():
    assert R()["replay"]["T1"] is True


def test_replay_keeps_late_task_unapproved():
    assert R()["replay"]["late"] is None


def test_serialized_state_contains_approved():
    assert R()["replay"]["ser"] is True


# ── add の注記 ────────────────────────────────────────────────────────────


def test_add_note_appears_for_active_goal():
    assert NOTE in R()["notes"]["active"]["text"]


@pytest.mark.parametrize("stage", ["draft", "planned", "paused"])
def test_add_note_absent_unless_active(stage):
    assert NOTE not in R()["notes"][stage]["text"]


@pytest.mark.parametrize("stage", ["draft", "planned", "active", "paused"])
def test_add_output_stays_under_limit(stage):
    n = R()["notes"][stage]
    assert n["ok"] is True
    assert n["len"] <= 1500


def test_add_note_for_child_of_task_in_active_goal():
    c = R()["childNote"]
    assert NOTE in c["text"]
    assert c["approved"] is None


# ── 乱数列の性質試験 ──────────────────────────────────────────────────────


def test_fuzz_ran_with_tasks():
    f = R()["fuzz"]
    assert f["runs"] == 40
    assert f["withTasks"] == 40


def test_fuzz_keeps_invariants():
    assert R()["fuzz"]["bad"] == []


def test_fuzz_never_starts_unapproved_tasks():
    assert R()["fuzz"]["unapproved"] == []


# ── 再承認: 承認後に足した task を、利用者が後から承認する ─────────────────


def test_reapprove_is_accepted_and_stamps_late_task():
    r = R()["reapproveOk"]
    assert r["err"] is None
    assert r["approved"] is True


def test_reapprove_keeps_goal_state_active():
    assert R()["reapproveOk"]["gState"] == "active"


def test_reapprove_makes_late_task_a_start_candidate():
    r = R()["reapproveOk"]
    id2 = R()["reapprove"]["id2"]
    assert id2 in r["starts"]
    assert id2 in r["readyIds"]
    assert r["sched"][id2] == "ready"


def test_reapprove_second_time_is_rejected_for_no_targets():
    assert "承認の対象" in R()["reapproveOk"]["again"]


def test_reapprove_keeps_approved_by_user():
    assert R()["reapproveOk"]["approvedBy"] == "user"


def test_reapprove_keeps_invariants():
    assert R()["reapproveOk"]["viol"] == []


def test_reapprove_paused_goal_by_user_only():
    r = R()["reapprovePaused"]
    assert "利用者専用" in r["byModel"]
    assert "利用者専用" in r["bySystem"]
    assert r["beforeOk"] is None
    assert r["byUser"] is None
    assert r["approved"] is True
    assert r["gState"] == "paused"
    assert r["viol"] == []


def test_wake_reason_all_done_before_late_task():
    assert R()["wake"]["allDone"] == ["all_done"]


def test_wake_reason_awaiting_approval_for_late_task():
    assert R()["wake"]["awaiting"] == ["awaiting_approval"]


def test_late_task_starts_after_reapprove():
    w = R()["wake"]
    assert w["starts"] == [w["id"]]
    assert w["viol"] == []
