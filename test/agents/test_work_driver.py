"""並列実行基盤のドライバ (work/driver.ts) の試験。

スケジューラの Action を台帳のイベントと効果に変換し、子の完了・失敗・429 を台帳へ戻す。
``test/agents/pi/work_driver_driver.mjs`` が偽の Spawner と実物の台帳・スケジューラを接続し、結果を親 (この試験) が照合する。
node の型除去を使うので、22.18 未満の node では飛ばす。
see docs/spec/work/driver.md
"""

from __future__ import annotations

import json
import subprocess
from functools import cache
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "work_driver_driver.mjs"
SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "work" / "driver.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def _run(*args: str) -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=150,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@cache
def case(name: str) -> dict:
    return _run(name)


# ── a) start → 予約 → spawn → started → finished → ended → 次の start (pipeline) ──


def test_flow_first_tick_reserves_then_spawns_two():
    t1 = case("flow")["t1"]
    assert t1["spawn"] == ["T1", "T2"]
    assert t1["events"] == ["run.reserved", "run.reserved"]


def test_flow_effects_are_spawns_only_at_first():
    assert case("flow")["t1"]["effects"] == ["spawn", "spawn"]


def test_flow_tasks_running_after_spawn_and_downstream_waits():
    states = case("flow")["t1"]["states"]
    assert states == {"T1": "running", "T2": "running", "T3": "ready", "T4": "ready"}


def test_flow_runs_started_after_onspawned():
    assert case("flow")["t1"]["runStates"] == ["started", "started"]


def test_flow_finish_moves_run_and_task():
    f = case("flow")["afterFin"]
    assert f["run"] == "done"
    assert f["T1"] == "done"


def test_flow_finish_event_order():
    assert case("flow")["afterFin"]["types"] == ["note.appended", "run.ended", "check.result"]


def test_flow_finish_makes_digest_input():
    d = case("flow")["afterFin"]["digest"]
    assert d["id"] == "r1"
    assert d["node"] == "T1"
    assert d["status"] == "done"
    assert "結論" in d["text"]


def test_flow_pipeline_next_stage_starts_without_waiting_for_siblings():
    t2 = case("flow")["t2"]
    assert t2["spawn"] == ["T3"]
    assert t2["T2"] == "running"
    assert t2["T3"] == "running"


def test_flow_join_starts_after_all_upstreams_done():
    assert case("flow")["t3"]["spawn"] == ["T4"]


def test_flow_all_done_wakes_parent():
    assert case("flow")["wakes"] == ["all_done"]


def test_flow_final_states_all_done():
    assert set(case("flow")["final"].values()) == {"done"}


def test_flow_no_rejections_and_invariants_hold():
    f = case("flow")
    assert f["rejected"] == []
    assert f["violations"] == []


def test_flow_replay_equals_memory():
    assert case("flow")["replayEqual"] is True


# ── b) 429: 失敗に数えず再キュー、AIMD が下がり、連続成功で戻る ──


def test_ratelimit_starts_at_initial_limit():
    r = case("ratelimit")
    assert r["limit0"] == 4
    assert r["live0"] == 4


def test_ratelimit_is_detected_from_error_text():
    r = case("ratelimit")
    assert r["rateLimited"] is True
    assert "429" in r["error"]


def test_ratelimit_run_ends_as_limit_not_failed():
    assert case("ratelimit")["runState"] == "limit"


def test_ratelimit_requeues_task_to_ready():
    assert case("ratelimit")["taskState"] == "ready"


def test_ratelimit_not_counted_as_task_failure():
    assert case("ratelimit")["failures"] == 0


def test_ratelimit_events_include_retry_verdict_and_aux():
    assert case("ratelimit")["typesAfter"] == [
        "note.appended",
        "run.ended",
        "resource.429",
        "verdict",
    ]


def test_ratelimit_aimd_halves_limit():
    assert case("ratelimit")["afterLimit"] == 2


def test_ratelimit_backs_off():
    r = case("ratelimit")
    assert r["pausedUntil"] > 1_000_000


def test_ratelimit_announces_pause_once():
    r = case("ratelimit")
    assert r["kinds1"] == ["pause_provider"]
    assert r["kinds2"] == []


def test_ratelimit_no_new_spawn_while_paused():
    assert case("ratelimit")["spawnedWhilePaused"] == 4


def test_ratelimit_resumes_after_backoff():
    assert case("ratelimit")["kinds3"] == ["resume_provider"]


def test_ratelimit_recovers_with_consecutive_successes():
    r = case("ratelimit")
    assert r["maxLimit"] > r["afterLimit"]
    assert r["finalLimit"] >= 3


def test_ratelimit_requeued_task_is_started_again():
    assert case("ratelimit")["requeuedStarted"] >= 2


def test_ratelimit_keeps_invariants_and_replays():
    r = case("ratelimit")
    assert r["violations"] == []
    assert r["replayEqual"] is True


def test_failcount_real_failure_is_counted():
    f = case("failcount")
    assert f["failures"] == 1
    assert f["taskState"] == "failed"


def test_failcount_real_failure_does_not_touch_aimd():
    f = case("failcount")
    assert f["aimdLimit"] == 4
    assert f["strikes"] == 0


def test_exhausted_pauses_goal_and_wakes_once():
    e = case("exhausted")
    assert e["exhausted"] is True
    assert e["goal"] == "paused"
    assert e["wake1"] == ["provider_exhausted"]
    assert e["wake2"] == []


def test_exhausted_events_and_invariants():
    e = case("exhausted")
    assert e["events1"] == ["resource.429", "goal.paused"]
    assert e["violations"] == []


# ── c) 予算 ──


def test_budget_tiny_budget_emits_no_start():
    b = case("budget")
    assert b["tinySpawn"] == 0
    assert b["tinyEvents"] == []


def test_budget_second_start_does_not_fit():
    assert case("budget")["oneSpawn"] == 1


def test_budget_no_steer_below_ratio():
    assert case("budget")["k0"] == []


def test_budget_steer_at_1_5x_once():
    b = case("budget")
    assert b["k15"] == ["steer"]
    assert b["steerRun"] == b["runId"]
    assert b["k15b"] == []


def test_budget_abort_at_2x_once():
    b = case("budget")
    assert b["k2"] == ["abort:usage-2x"]
    assert b["abortRun"] == b["runId"]
    assert b["k2b"] == []


def test_usage_sums_into_run_task_goal():
    u = case("usage")
    assert u["mid"]["tokens"] == 300
    for k in ("run", "task", "goal", "usedSched"):
        assert u[k] == {"usd": 0.5, "tokens": 500, "ms": 50}, k


def test_usage_reserved_is_released_to_actual_after_end():
    assert case("usage")["goalReserved"] == {"usd": 0.5, "tokens": 500, "ms": 50}


def test_usage_ignored_for_ended_or_unknown_run():
    u = case("usage")
    assert u["noop"] == 0
    assert u["zero"] == 0


# ── d) writes の重なり ──


def test_overlap_named_globs_start_only_one():
    o = case("overlap")
    assert o["namedSpawn"] == ["T1"]


def test_overlap_every_start_passes_ledger_gate():
    o = case("overlap")
    assert o["namedRejected"] == []
    assert o["disjointRejected"] == []
    assert o["sameViolations"] == []
    assert o["namedViolations"] == []


def test_overlap_disjoint_writes_start_together():
    assert case("overlap")["disjointSpawn"] == ["T1", "T2", "T3"]


def test_overlap_same_area_is_serialised():
    o = case("overlap")
    assert o["sameFirst"] == ["T1"]
    assert o["sameAll"] == ["T1", "T2"]


def test_gate_rejected_start_is_reported_not_spawned():
    g = case("gate")
    assert g["spawns"] == ["T2"]
    assert [r["task"] for r in g["rejected"]] == ["T1"]
    assert "予算超過" in g["rejected"][0]["reason"]
    assert g["T1"] == "ready"
    assert g["violations"] == []


# ── e) 子に work ツールを渡さない ──


def test_worktool_is_false_on_every_spawn():
    spawns = case("worktool")["spawns"]
    assert len(spawns) == 3
    for s in spawns:
        assert s["hasKey"] is True
        assert s["workTool"] is False


def test_worktool_prompt_forbids_the_ledger():
    for s in case("worktool")["spawns"]:
        assert "work ツールは使えない" in s["prompt"]


def test_spawn_has_worktree_only_for_isolated_edit():
    by = {s["task"]: s for s in case("worktool")["spawns"]}
    assert by["T1"]["worktree"] == "T1"
    assert by["T2"]["worktree"] is None


def test_source_pins_worktool_false():
    text = SRC.read_text(encoding="utf-8")
    assert "workTool: false" in text
    assert "workTool: true" not in text


def test_source_has_no_io_imports():
    text = SRC.read_text(encoding="utf-8")
    for bad in ("node:fs", "node:child_process", "@earendil-works", "Date.now", "Math.random"):
        assert bad not in text, bad


# ── f) 入力の不変と決定性 ──


def test_tick_does_not_mutate_inputs():
    assert case("purity")["unchangedTick"] is True


def test_tick_is_deterministic():
    assert case("purity")["same"] is True


def test_finish_does_not_mutate_inputs():
    assert case("purity")["unchangedFinish"] is True


def test_finish_is_deterministic():
    assert case("purity")["sameFinish"] is True


# ── h) 失敗の理由は null にならない ──


@pytest.mark.parametrize("i", [0, 1, 3])
def test_failure_reason_is_never_null(i):
    r = case("failure")["res"][i]
    assert isinstance(r["error"], str)
    assert r["error"].strip() != ""


def test_failure_keeps_given_reason():
    assert case("failure")["res"][2]["error"] == "テストが落ちた"


def test_failure_reason_is_written_as_run_note():
    for r in case("failure")["res"]:
        assert len(r["note"]) == 1
        assert r["note"][0].startswith("失敗: ")


def test_failure_marks_run_and_task():
    res = case("failure")["res"]
    assert [r["runState"] for r in res] == ["failed", "failed", "failed", "aborted"]
    assert all(r["taskState"] == "failed" for r in res)


def test_failure_makes_digest_for_every_end():
    assert [r["digest"] for r in case("failure")["res"]] == [
        "failed",
        "failed",
        "failed",
        "aborted",
    ]


def test_success_has_null_error():
    assert case("failure")["okError"] is None


def test_limit_without_reason_still_has_reason():
    f = case("failure")
    assert f["limitError"]
    assert f["limitRate"] is True


def test_failure_keeps_invariants():
    assert case("failure")["violations"] == []


# ── lost の回収 ──


def test_reconcile_closes_only_unknown_runs():
    r = case("reconcile")
    assert r["types"] == ["note.appended", "run.ended"]
    assert set(r["nodes"]) == {"r2"}
    assert r["runB"] == "lost"
    assert r["runA"] == "started"
    assert r["taskB"] == "failed"
    assert r["violations"] == []


# ── g) 性質試験 (seed 固定で 200 本) ──


@pytest.fixture(scope="module")
def props() -> dict:
    return _run("prop", "1", "200")


def test_property_ran_200_sequences(props):
    assert props["n"] == 200


def test_property_no_violation_at_all(props):
    assert props["bad"] == [], props["bad"]
    assert props["badCount"] == 0


def test_property_concurrency_actually_reached(props):
    assert props["peak"] >= 2


@pytest.mark.parametrize("seed0", [1000, 5000])
def test_property_other_seeds(seed0):
    r = _run("prop", str(seed0), "40")
    assert r["bad"] == [], r["bad"]


def test_property_is_deterministic():
    assert _run("prop", "7", "10") == _run("prop", "7", "10")


# ── 見積り (attrs.est) と無出力の見張り (onOutput) ──


def test_estimate_adapter_uses_attrs_est_after_overrun():
    c = case("estimate")
    assert c["reserve"] == c["est"]
    # 台帳の reserved は超過分で増えている (これが原因だった)
    assert c["ledgerReserved"]["usd"] > c["est"]["usd"]


def test_estimate_steer_after_overrun_once():
    c = case("estimate")
    assert c["k15"] == ["steer"] and c["k15b"] == []


def test_estimate_abort_at_2x():
    assert case("estimate")["k2"] == ["abort:usage-2x"]


def test_estimate_falls_back_to_ledger_reserved_without_attrs():
    assert case("estimate")["bareReserve"] == {"usd": 2, "tokens": 3, "ms": 4}


def test_estimate_ignores_malformed_attrs_est():
    assert case("estimate")["badReserve"] == {"usd": 2, "tokens": 3, "ms": 4}


def test_stall_no_steer_before_5min():
    assert case("stall")["at4"] == []


def test_stall_steer_at_5min_exactly_once():
    c = case("stall")
    assert c["at5"] == ["steer:"] and c["at5b"] == []


def test_stall_abort_at_10min():
    assert case("stall")["at10"] == ["abort:stall"]


def test_stall_output_resets_idle():
    assert case("stall")["quiet"] == []


def test_onoutput_records_time_and_aux_event():
    c = case("stall")
    assert c["auxTypes"] == ["notice"] and list(c["memoAt"].values()) == [1_000_000]


def test_onoutput_ignores_finished_run():
    c = case("stall")
    assert c["deadEvents"] == 0 and c["deadMemoSame"] is True


def test_adapter_reads_attrs_last_output_and_steered_at():
    assert case("stall")["attr"] == {"lastOutputAt": 123, "steered": True, "stallSteered": True}
