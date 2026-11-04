"""作業台帳の端から端まで (store → core → adapt → sched・digest) の統合試験。

各 feature の試験は単体で通っても、境界 (永続の欄・スケジューラと台帳の門・digest の入力) の食い違いは見つからない。
ここでは ``test/agents/pi/work_e2e_driver.mjs`` が実物どうしを接続し、結果を親 (この試験) が照合する。
node の型除去を使うので、22.18 未満の node では飛ばす。
see docs/spec/work/ledger.md#接続と統合試験
"""

from __future__ import annotations

import json
import signal
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "work_e2e_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def drive(*args: str) -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── a) store → core の再生 ────────────────────────────────────────────────

STAGES = ["planned", "ready", "full"]


@pytest.fixture(scope="module")
def replays(tmp_path_factory) -> dict[str, dict]:
    return {s: drive("replay", str(tmp_path_factory.mktemp(s) / "w"), s) for s in STAGES}


@pytest.mark.parametrize("stage", STAGES)
def test_replay_state_equals_memory_fold(replays, stage):
    assert replays[stage]["sameState"] is True


@pytest.mark.parametrize("stage", STAGES)
def test_replay_events_roundtrip_exactly(replays, stage):
    assert replays[stage]["sameEvents"] is True


@pytest.mark.parametrize("stage", STAGES)
def test_replay_keeps_invariants(replays, stage):
    r = replays[stage]
    assert r["violations"] == []
    assert r["violationsMem"] == []


@pytest.mark.parametrize("stage", STAGES)
def test_replay_keeps_source(replays, stage):
    r = replays[stage]
    assert r["sources"] == r["expectSources"]


@pytest.mark.parametrize("stage", STAGES)
def test_replay_keeps_holder(replays, stage):
    r = replays[stage]
    assert r["holders"] == r["expectHolders"]


@pytest.mark.parametrize("stage", STAGES)
def test_replay_seqs_are_contiguous(replays, stage):
    r = replays[stage]
    assert r["seqs"] == list(range(1, r["n"] + 1))


def test_replay_user_only_event_keeps_user_source(replays):
    r = replays["full"]
    assert r["sources"][3] == "user"  # plan.approved
    assert r["sources"][-1] == "user"  # budget.adjusted


def test_replay_restores_lease_owner(replays):
    assert replays["full"]["owner"]["holder"] == "holder-A"


def test_replay_clean_load(replays):
    for r in replays.values():
        assert r["recovered"] is False
        assert r["degraded"] is None


def test_replay_builds_expected_nodes(replays):
    assert replays["full"]["nodes"] == ["G", "T1", "T2", "T3", "T4", "R1"]


# ── f) ready の優先順位が永続→再生の前後で同じ ─────────────────────────────


def test_ready_order_same_before_and_after_persist(replays):
    r = replays["full"]
    assert r["readyMem"] == r["readyLoaded"]


def test_ready_order_same_at_ready_stage(replays):
    r = replays["ready"]
    assert r["readyMem"] == r["readyLoaded"]
    assert r["readyMem"]  # 空でない


def test_ready_excludes_unapproved_goal(replays):
    assert replays["planned"]["readyLoaded"] == []


def test_ready_skips_overlapping_and_blocked_tasks(replays):
    # T1 は done。T4 は T3 待ち。残る T2 (src/a/x.ts) と T3 (docs/**) は重ならない
    assert sorted(replays["full"]["readyLoaded"]) == ["T2", "T3"]


# ── b) kill -9 の後の再生 ────────────────────────────────────────────────


def _kill_after(root: Path, n_acks: int) -> list[tuple[int, int]]:
    proc = subprocess.Popen(
        [_node(), str(DRIVER), "child", str(root)],
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    acks: list[tuple[int, int]] = []
    try:
        assert proc.stdout is not None
        first = proc.stdout.readline().strip()
        assert first == "ready", first
        while len(acks) < n_acks:
            line = proc.stdout.readline()
            if not line:
                break
            parts = line.split()
            if len(parts) == 3 and parts[0] == "ack":
                acks.append((int(parts[1]), int(parts[2])))
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
    return acks


@pytest.mark.parametrize("n_acks", [3, 25, 80])
def test_kill9_keeps_every_acked_event(tmp_path, n_acks):
    root = tmp_path / "w"
    acks = _kill_after(root, n_acks)
    assert len(acks) == n_acks
    r = drive("recover", str(root))
    present = {n["seq"]: n["text"] for n in r["notes"]}
    for seq, i in acks:
        assert seq in present, f"ack 済みの seq {seq} が消えた"
        assert present[seq].startswith(f"n{i} ")


@pytest.mark.parametrize("n_acks", [3, 25, 80])
def test_kill9_replay_keeps_invariants(tmp_path, n_acks):
    root = tmp_path / "w"
    _kill_after(root, n_acks)
    r = drive("recover", str(root))
    assert r["violations"] == []
    assert r["degraded"] is None
    assert r["seqs"] == list(range(1, r["count"] + 1))


def test_kill9_replay_still_schedulable(tmp_path):
    root = tmp_path / "w"
    _kill_after(root, 10)
    r = drive("recover", str(root))
    assert "T3" in r["ready"]


# ── c) スケジューラへの接続 ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def sched() -> dict[str, dict]:
    return {v: drive("sched", v) for v in ["basic", "tinybudget", "slots1", "disjoint", "named"]}


def test_sched_starts_ready_tasks(sched):
    r = sched["basic"]
    assert r["starts"]
    assert set(r["starts"]) <= {"T1", "T3"}  # T2 は T1 と重なる・T4 は T1・T3 待ち


def test_sched_does_not_start_overlapping_writes_together(sched):
    r = sched["basic"]
    assert not ({"T1", "T2"} <= set(r["starts"]))


def test_sched_starts_are_accepted_by_ledger(sched):
    assert sched["basic"]["rejected"] == []
    assert sched["basic"]["violations"] == []


def test_sched_converts_all_tasks(sched):
    assert sched["basic"]["schedTasks"] == ["T1:ready", "T2:ready", "T3:ready", "T4:ready"]


def test_sched_budget_comes_from_goal(sched):
    assert sched["basic"]["schedBudget"]["usd"] == 100


def test_sched_never_starts_over_budget(sched):
    r = sched["tinybudget"]
    assert r["starts"] == []
    assert r["violations"] == []


def test_sched_respects_slots(sched):
    assert len(sched["slots1"]["starts"]) == 1


def test_sched_starts_disjoint_tasks_in_parallel(sched):
    r = sched["disjoint"]
    assert sorted(r["starts"]) == ["T1", "T2", "T3"]
    assert r["rejected"] == []


def test_sched_reserve_fits_goal_budget(sched):
    r = sched["disjoint"]
    assert sum(x["usd"] for x in r["reserves"]) <= 100


def test_sched_serializes_overlapping_named_globs(sched):
    r = sched["named"]
    assert not ({"T3", "T4"} <= set(r["starts"]))  # src/**/*.ts と src/a.ts


def test_sched_and_ledger_agree_on_slashless_glob(sched):
    assert sched["named"]["rejected"] == []


def test_sched_priority_matches_project_ready(sched):
    r = sched["basic"]
    order = [t for t in r["ready"] if t in r["starts"]]
    assert [t for t in r["starts"] if t in order] == order


# ── d) digest への接続 ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def digest() -> dict:
    return drive("digest")


def test_digest_model_text_within_limit(digest):
    assert digest["textLen"] <= 600


def test_digest_input_from_run_facts(digest):
    i = digest["input"]
    assert (i["id"], i["node"], i["status"]) == ("R1", "T1", "done")
    assert i["resultPath"] == "runs/R1.md"


def test_digest_input_uses_run_usage(digest):
    assert digest["input"]["usd"] == 0.5
    assert digest["input"]["dur"] == 1100


def test_digest_text_carries_conclusion(digest):
    assert "src/a を直した" in digest["text"]
    assert digest["status"] == "done"


def test_digest_one_line_not_empty(digest):
    assert "R1" in digest["line"]


def test_digest_input_none_for_non_run_or_unknown_or_live(digest):
    assert digest["nonRun"] is None
    assert digest["unknown"] is None
    assert digest["live"] is None


# ── e) 利用者専用イベントの偽装 ──────────────────────────────────────────


@pytest.fixture(scope="module")
def forge(tmp_path_factory) -> dict:
    return drive("forge", str(tmp_path_factory.mktemp("forge") / "w"))


@pytest.mark.parametrize(
    "name", ["approved_data_user", "approved_system", "budget_model", "resolved_user_model"]
)
def test_forged_user_only_event_is_refused_at_creation(forge, name):
    assert forge[name]["ok"] is False
    assert forge[name]["name"] == "EventError"


def test_data_source_and_holder_are_dropped(forge):
    e = forge["holder_in_data"]["event"]
    assert e["data"] == {"by": "llm", "text": "x"}
    assert e["source"] == "model"
    assert "holder" not in e


def test_forged_event_in_log_is_refused_on_replay(forge):
    assert forge["replayStrict"]["ok"] is False
    assert forge["replayStrict"]["name"] == "ReduceError"


def test_forged_event_replay_rejects_both_and_goal_stays_planned(forge):
    t = forge["replayTolerant"]
    assert t["rejected"] == ["4:plan.approved", "5:plan.approved"]
    assert t["goalState"] == "planned"
    assert t["violations"] == []
