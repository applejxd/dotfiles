"""並列実行基盤の接着層 (work/driver-run.ts) の試験。

偽の spawnChild・偽の Jobs と、実物の runtime (tmp ディレクトリ) を ``test/agents/pi/work_driver_run_driver.mjs`` で接続し、
結果を親 (この試験) が照合する。node の型除去を使うので、22.18 未満の node では飛ばす。
see docs/spec/work/driver-run.md
"""

from __future__ import annotations

import json
import re
import subprocess
from functools import cache
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "work_driver_run_driver.mjs"
HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"
SRC = HARNESS / "work" / "driver-run.ts"
INDEX = HARNESS / "index.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def _run(*args: str) -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=170,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@cache
def case(name: str) -> dict:
    return _run(name)


# ── a) 旗・子・PI_WORK=0: 既定は何も登録せず、何も起動しない ──


@pytest.mark.parametrize("name", ["noflag", "flag0", "off", "child", "childEnv"])
def test_gating_disabled_registers_and_spawns_nothing(name):
    r = case("gating")[name]
    assert r == {"registered": False, "handlers": [], "spawns": 0, "timers": 0}


def test_gating_flag_on_registers_handlers_and_starts_eligible_task():
    r = case("gating")["on"]
    assert r["registered"] is True
    assert r["handlers"] == ["session_start", "session_shutdown"]
    assert r["timers"] == 1
    assert r["spawns"] == 1


# ── b) 承認済みの goal の ready な task だけが起動する ──


def test_approved_only_ready_task_is_spawned():
    r = case("approved")
    assert r["first"] is True
    assert r["runs"] == ["T1"]
    assert r["states"] == {"T1": "running", "T2": "ready"}


def test_approved_run_is_started_in_ledger_and_live():
    r = case("approved")
    assert r["started"] == ["started"]
    assert r["live"] == ["r1"]


def test_approved_spawn_goes_through_spawnchild_with_session_ctx_and_owner():
    r = case("approved")
    assert r["ctxCwdOk"] is True
    c = r["calls"][0]
    assert c["agent"] == "worker"
    assert c["owner"]["role"] == "worker"
    assert c["model"] is None
    assert c["effort"] is None
    assert c["cwdArg"] is None


def test_approved_prompt_carries_title_and_writes_and_has_round_timeout():
    r = case("approved")
    assert "# task T1" in r["prompt"]
    assert "a/**" in r["prompt"]
    assert r["timeoutMs"] == 30 * 60_000


def test_unapproved_plan_starts_nothing():
    r = case("unapproved")
    assert r["calls"] == 0
    assert r["runs"] == []
    assert r["goal"] == "planned"
    assert r["T1"] == "proposed"


# ── c) 安全条件 ──


def test_no_work_tool_is_registered_for_children_or_parent():
    assert case("notool")["tools"] == []


def test_prompt_tells_child_not_to_use_work_tool():
    assert "work ツールは使えない" in case("notool")["prompt"]


def test_spawnchild_gets_only_five_positional_args():
    # agent, ctx, owner, model(undefined), isolation。effort・cwd の経路は使わない
    assert case("notool")["argc"] == 5


def test_single_path_only_spawnchild_with_defaults():
    r = case("singlepath")
    assert r["jobsMade"] == 2
    assert all(c[1:4] == [None, None, None] for c in r["calls"])


def test_source_has_no_tool_registration_or_process_spawn():
    src = SRC.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )
    assert "registerTool" not in code
    assert "child_process" not in code
    assert "execFile" not in code
    assert "spawnSync" not in code
    assert not re.search(r"\bspawn\(\s*[\"']", code)


def test_source_does_not_touch_permission_env():
    code = SRC.read_text(encoding="utf-8")
    for name in ("PI_HARNESS_ROLE", "PI_HARNESS_WRITE_ROOT", "PI_HARNESS_BYPASS", "--no-approve"):
        assert name not in code


def test_index_wires_with_one_import_and_one_call_inside_register_task():
    src = INDEX.read_text(encoding="utf-8")
    assert len(re.findall(r"^import .*work/driver-run\.ts", src, re.M)) == 1
    calls = [m.start() for m in re.finditer(r"registerDriverRun\(", src)]
    assert len(calls) == 1
    assert calls[0] > src.index("function registerTask(")
    block = src[calls[0] : calls[0] + 1500]
    assert all(k in block for k in ("spawnChild", "jobs", "child: CHILD", "canSpawn"))
    assert (
        'decide("task"' in block
        and "planModeRefusal(spec.role)" in block
        and "__piPlanMode" in block
    )


# ── d) 書き込み集合の排他・同時数 ──


def test_overlap_tasks_not_started_together():
    r = case("overlap")
    assert r["first"] == ["T1", "T3"]


def test_overlap_task_starts_after_blocking_run_finishes():
    r = case("overlap")
    assert "T2" in r["after"]
    assert r["violations"] == []


def test_slots_capped_by_jobs_max():
    assert case("slots")["two"] == {"spawned": 2, "live": 2}


def test_slots_subtract_children_started_by_others():
    assert case("slots")["others"] == {"spawned": 1, "live": 1}


def test_slots_zero_when_other_children_fill_the_cap():
    assert case("slots")["full"] == {"spawned": 0, "live": 0}


def test_slots_default_cap_is_six():
    assert case("slots")["six"]["live"] == 6


# ── e) pipeline・検査 ──


def test_pipeline_next_stage_starts_right_after_child_finishes():
    assert case("pipeline")["steps"] == [["T1"], ["T1", "T2"], ["T1", "T2", "T3"]]


def test_pipeline_tasks_reach_done_without_invariant_violation():
    r = case("pipeline")
    assert r["states"] == ["done", "done", "done"]
    assert r["violations"] == []


def test_without_check_hook_task_stays_checking_and_downstream_waits():
    r = case("nocheck")
    assert r["T1"] == "checking"
    assert r["runs"] == ["T1"]


# ── f) 429 ──


def test_ratelimit_requeues_task_instead_of_failing():
    r = case("ratelimit")
    assert r["T1"] == "ready"
    assert r["runs"] == ["limit"]


def test_ratelimit_pauses_new_spawns():
    r = case("ratelimit")
    assert r["afterCalls"] == r["before"]


# ── g) 予算 ──


def test_budget_no_steer_below_estimate():
    assert case("budget")["mid"] == {"steers": 0, "closed": 0}


def test_budget_steer_once_at_1_5x():
    assert case("budget")["steered"] == {"steers": 1, "closed": 0}


def test_budget_abort_at_2x_via_force_close_without_second_steer():
    r = case("budget")["aborted"]
    assert r["closed"] == [True, False]  # 終了後の閉じ (M1) が追加で 1 回入る
    assert r["steers"] == 1


def test_budget_usage_is_summed_into_run_and_goal():
    r = case("budget")
    assert r["spent"]["usd"] == pytest.approx(r["goalSpent"]["usd"])
    assert r["spent"]["usd"] > 0
    assert r["runState"] == "aborted"


# ── h) 停止・読み取り専用・runtime なし ──


def test_shutdown_aborts_every_child_with_force():
    r = case("shutdown")
    assert r["before"] == 3
    assert r["closed"] == [[True, False], [True, False], [True, False]]
    assert r["after"] == 0


def test_shutdown_stops_timer_and_nothing_starts_afterwards():
    r = case("shutdown")
    assert r["timers"] == 1
    assert r["noMore"] is True


@pytest.mark.parametrize("mode", ["readonly", "off", "degraded"])
def test_non_driver_runtime_starts_nothing(mode):
    assert case("readonly")[mode] == {"calls": 0}


def test_without_shared_runtime_nothing_happens():
    r = case("noruntime")
    assert r["spawned"] == 0
    assert r["registry"] is None


def test_rejected_reservation_never_spawns():
    r = case("rejectsubmit")
    assert r["spawns"] == 0
    assert r["submits"] == 1


# ── i) 失敗の写像 ──


def test_spawnchild_error_closes_run_as_failed():
    r = case("spawnerror")
    assert r["runs"] == ["failed"]
    assert r["live"] == 0


@pytest.mark.parametrize("name", ["blocked", "failed", "limit"])
def test_child_failure_kinds_fail_the_run_and_task(name):
    # 子の "limit" は時間切れ。ドライバの 429 (limit) には写さず失敗として扱う
    assert case("mapping")[name] == {"run": "failed", "task": "failed"}


def test_child_closed_maps_to_aborted_run():
    assert case("mapping")["closed"]["run"] == "aborted"


def test_reconcile_closes_runs_of_dead_processes_as_lost():
    r = case("reconcile")
    assert r["sub"] is True
    assert r["rX"] == "lost"


# ── j) 性質試験 (seed 固定の乱数列。不変条件・同時数・予算) ──


@pytest.mark.parametrize("start", [1, 26, 51, 76])
def test_property_random_runs_keep_invariants_slots_and_budget(start):
    r = _run("prop", str(start), "25")
    assert r["bad"] == []
    assert r["seeds"] == 25
    assert r["started"] > 0


# ── i) 起動制約 (B1: canSpawn・B2: 役割と隔離の対応表・M1: 枠の解放・M2: 世代) ──

_ISO_OK = ("none", "shared", "worktree")


def _expected(row: dict) -> dict:
    """対応表の期待値を、実装とは独立に書く"""
    if row["kind"] == "missing":
        return {"ok": False}
    if row["iso"] not in _ISO_OK or row["kind"] == "bogus":
        return {"ok": False}
    k = row["kind"]
    # 仕様: node.kind が check なら attrs.kind が何でも拒否。attrs.kind が check も拒否 (矛盾)
    if row["nk"] == "check" or row["kind"] == "check":
        return {"ok": False}
    eff = k if k in ("ro", "edit") else ("edit" if row["writes"] else "ro")
    if eff == "ro":
        return (
            {"ok": not row["writes"], "role": "explore", "isolation": False}
            if not row["writes"]
            else {"ok": False}
        )
    return {"ok": True, "role": "worker", "isolation": True} if row["writes"] else {"ok": False}


@pytest.mark.parametrize("kind", [None, "ro", "task", "edit", "check", "bogus"])
@pytest.mark.parametrize("writes", [0, 1])
def test_role_isolation_table_all_combinations(kind, writes):
    rows = [r for r in case("table") if r["kind"] == kind and r["writes"] == writes]
    assert len(rows) == 2 * 4 * 3  # node.kind × 隔離 × attrs.role
    for r in rows:
        exp = _expected(r)
        plan = r["plan"]
        assert plan["ok"] is exp["ok"], r
        if exp["ok"]:
            # 属性の role (evil など) は効かない。編集は必ず worktree 隔離 (strategy が none・shared でも)
            assert (plan["role"], plan["isolation"]) == (exp["role"], exp["isolation"]), r
        else:
            assert plan["reason"], r


def test_table_missing_task_is_rejected():
    assert [r["plan"]["ok"] for r in case("table") if r["kind"] == "missing"] == [False]


def test_plan_mode_starts_no_writable_child():
    r = case("planmode")
    assert r["manual"] == [False, True]  # 手動経路 (guarded_task) と同じ関数の形
    assert r["edits"] == 0
    assert r["agents"] == ["explore"]


def test_can_spawn_deny_starts_nothing():
    assert case("gate")["deny"] == {"spawns": 0, "live": 0}


def test_can_spawn_ask_holds_task_ready_without_run():
    assert case("gate")["hold"] == {"spawns": 0, "state": "ready", "runs": 0}


def test_can_spawn_hold_resumes_when_allowed():
    assert case("gate")["resumed"] == {"spawns": 1, "runs": 1}


def test_editing_child_always_isolated_worker_and_reading_child_explorer():
    r = case("roles")
    assert r["calls"] == [["worker", True], ["explore", False]]


def test_check_and_inconsistent_tasks_start_no_child():
    r = case("roles")
    assert len(r["calls"]) == 2  # E1 と R1 だけ
    assert r["states"] == {"C1": ["failed"], "X1": ["failed"], "B1": ["failed"]}


def test_no_isolation_available_rejects_without_fallback():
    r = case("noisolation")
    assert r["calls"] == [["worker", True]]  # 隔離を要求し、作れなかった。隔離なしで再試行しない
    assert r["jobs"] == 0 and r["runs"] == ["failed"]


def test_normally_finished_job_is_closed_and_slot_released():
    r = case("slotsrelease")
    assert r["closed"] == [True, True]


def test_third_task_starts_after_two_finished_with_max_two():
    r = case("slotsrelease")
    assert (r["first"], r["total"]) == (2, 3)
    assert r["t3"] == ["R1", "R2", "R3"]


@pytest.mark.parametrize("how", ["shutdown", "restart", "swap"])
def test_late_submit_after_shutdown_generation_or_runtime_change_spawns_nothing(how):
    r = case("lateSubmit")[how]
    assert r["spawns"] == 0 and r["live"] == 0
    assert r["runStates"] and all(s == "aborted" for s in r["runStates"])  # 予約は取り消す


def test_late_submit_without_interference_still_spawns():
    r = case("lateSubmit")["none"]
    assert r["spawns"] == 2 and r["live"] == 2


def test_driver_run_source_has_generation_and_trusted_role_table():
    src = SRC.read_text(encoding="utf-8")
    assert "gen++" in src and "const same = " in src
    assert 'READ_ROLE = "explore"' in src and 'EDIT_ROLE = "worker"' in src
