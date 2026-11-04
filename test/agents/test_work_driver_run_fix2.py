"""接着層 (work/driver-run.ts) の再 review 対応の試験 (fail-closed の canSpawn・終了時の close・shutdown 後の回収・hold・B2 の矛盾)。

driver は ``test_work_driver_run.py`` と同じ ``work_driver_run_driver.mjs``。see docs/spec/work/driver-run.md#安全条件
"""

from __future__ import annotations

import re

import pytest
from test_work_driver_run import HARNESS, SRC, case

DRIVER_TS = HARNESS / "work" / "driver.ts"

# ── (1) canSpawn を必須にし、fail-closed にする ──


@pytest.mark.parametrize("name", ["missing", "string", "object", "nul"])
def test_register_without_function_can_spawn_returns_null_and_starts_nothing(name):
    r = case("nocanspawn")[name]
    assert r == {"registered": False, "handlers": 0, "spawns": 0, "runs": 0}


@pytest.mark.parametrize(
    "name", ["undef", "throws", "empty", "nul", "str", "notbool", "one", "hold", "deny"]
)
def test_can_spawn_response_other_than_ok_true_starts_nothing(name):
    r = case("badgate")[name]
    assert r["spawns"] == 0 and r["live"] == 0


@pytest.mark.parametrize("name", ["lateUndef", "lateThrow", "lateEmpty"])
def test_can_spawn_bad_only_right_before_spawn_starts_nothing(name):
    r = case("badgate")[name]
    assert r["spawns"] == 0 and r["live"] == 0
    assert r["calls"] >= 2  # 事前の判定と起動直前の判定の両方が呼ばれた


def test_can_spawn_ok_true_still_starts():
    assert case("badgate")["allow"] == {"spawns": 1}


# ── (2) runtime が無い終了経路でも所有する子は close する ──


@pytest.mark.parametrize("how", ["done", "reject", "abort", "limit429"])
def test_child_is_closed_even_when_runtime_source_is_null(how):
    r = case("rtnull")[how]
    assert r["closed"][-1] is False  # 終了後の閉じ (force なし) が必ず入る
    assert r["live"] == 0


def test_isolated_job_waits_for_finalized_before_close_without_ledger():
    r = case("rtnull")["isolated"]
    assert "close" not in r["before"]
    assert r["after"] == ["finalized", "close"]


# ── (3) shutdown で取り消せなかった reserved は、再開後に回収される ──


def test_shutdown_with_null_source_does_not_spawn():
    r = case("shutdownNull")
    assert r["reservedBefore"] == 1
    assert r["spawnsDuring"] == 0


def test_orphan_reserved_remains_when_cancel_submit_failed():
    # 取得口が null・旧 runtime が閉じた後の取消は書けない (この試験の前提の確認)
    r = case("shutdownNull")
    assert ["r1", "reserved"] in r["r1Before"]


def test_reserved_orphan_is_reclaimed_by_new_runtime_reconcile():
    r = case("shutdownNull")
    assert r["orphans"] == []
    assert ["r1", "aborted"] in r["states"]


def test_driver_reconcile_closes_unspawned_reserved_run_as_aborted():
    r = case("reconcileReserved")
    assert r["before"] == "reserved" and r["rY"] == "aborted"
    assert r["violations"] == []


def test_driver_reconcile_reserved_does_not_count_as_failure_and_task_restarts():
    assert case("reconcileReserved")["spawns"] == 1


# ── (3-④) 別々の台帳への切り替えでも、別台帳へは書かない ──


def test_ledger_swap_writes_nothing_to_other_ledger():
    r = case("swapLedgers")
    assert r["seqB1"] == r["seqB0"] and r["bRuns"] == 0
    assert r["afterPoll"]["seqB"] == r["seqB0"]


def test_ledger_swap_poll_does_not_write_usage_to_origin_either():
    r = case("swapLedgers")
    assert r["afterPoll"]["seqA"] == r["seqA0"]


def test_ledger_swap_still_closes_child_after_finish():
    assert case("swapLedgers")["closed"] is True


def test_ledger_swap_leaves_origin_run_for_next_reconcile():
    assert case("swapLedgers")["runA"] == "started"


# ── (3-⑦) await の後にも世代を確認する ──


def test_shutdown_during_reconcile_submit_creates_no_new_reservation():
    r = case("afterReconcile")
    assert r["spawns"] == 0
    assert r["runs"] == ["rX"]


def test_shutdown_during_poll_submit_creates_no_new_reservation():
    r = case("afterPoll")
    assert r == {"spawns": 1, "runs": 0}


def test_source_rechecks_generation_after_await_reconcile_and_poll():
    src = SRC.read_text(encoding="utf-8")
    assert re.search(
        r"await submit\(rt, reconcile\([^\n]*\n[^\n]*\n\s*if \(!same\(\)\) return;", src
    )
    assert re.search(r"await poll\(rt, same\);\n\s*if \(!same\(\)\) return;", src)
    assert "rec.rt === rt.runtime && rec.gen === g" in src


def test_source_submit_is_pinned_to_the_runtime_of_the_caller():
    src = SRC.read_text(encoding="utf-8")
    assert "const submit = async (rt: { runtime: Runtime }, events" in src
    assert "opts.runtime()" not in src.split("const submit = async")[1].split("const release")[0]


# ── (4) hold は起動候補だけから外す ──


def test_permanent_hold_with_running_child_over_budget_still_aborts_child():
    r = case("holdMonitor")
    assert r["aborted"] is True


def test_held_task_is_not_started_while_monitoring_runs():
    r = case("holdMonitor")
    assert r["r2Runs"] == 0 and r["spawns"] == 1


def test_permanent_hold_does_not_starve_other_allowed_tasks():
    r = case("holdStarve")
    assert r["spawned"] == ["R2", "R3"]


def test_permanent_hold_keeps_task_ready_and_not_failed():
    r = case("holdStarve")
    assert r["r1"] == "ready" and r["r1runs"] == 0 and r["failed"] == 0


def test_allow_to_hold_during_late_submit_does_not_start():
    assert case("lateHold")["first"]["spawns"] == 0


def test_allow_to_hold_during_late_submit_is_not_recorded_as_failure():
    f = case("lateHold")["first"]
    assert f["task"] == "ready" and f["failures"] in (None, 0)
    assert "failed" not in f["runs"]


def test_allow_to_hold_during_late_submit_returns_to_ready_and_starts_after_allow():
    r = case("lateHold")
    assert r["first"]["runs"] == ["aborted"]
    assert r["second"]["spawns"] == 1


# ── (5) B2: node.kind と attrs.kind の矛盾は拒否 ──


@pytest.mark.parametrize("name", ["checkEdit", "checkRo", "checkBare", "taskCheck", "weirdNode"])
def test_planspawn_rejects_check_and_contradictory_kinds(name):
    r = case("contradiction")[name]
    assert r["ok"] is False and r["reason"]


def test_planspawn_check_node_with_edit_attr_is_not_isolated_worker():
    assert "role" not in case("contradiction")["checkEdit"]


def test_planspawn_consistent_task_kinds_still_allowed():
    c = case("contradiction")
    assert (c["taskEdit"]["role"], c["taskEdit"]["isolation"]) == ("worker", True)
    assert (c["taskRo"]["role"], c["taskRo"]["isolation"]) == ("explore", False)


# ── ソースの静的な確認 ──


def test_source_can_spawn_is_required_and_fail_closed():
    src = SRC.read_text(encoding="utf-8")
    assert "canSpawn: CanSpawn;" in src
    assert 'typeof opts.canSpawn !== "function") return null' in src
    assert "o.ok === true" in src
    assert "opts.canSpawn?." not in src


def test_driver_reconcile_source_handles_reserved():
    src = DRIVER_TS.read_text(encoding="utf-8")
    assert 'n.state !== "started" && n.state !== "reserved"' in src
