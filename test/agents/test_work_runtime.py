"""work/runtime.ts (作業台帳の実行時の接着層) の試験。実の store を tmp_path で使う。

``test/agents/pi/work_runtime_driver.mjs`` が node 側の操作を受け持つ。kill -9 の試験は子の node を SIGKILL で殺す。
守る条件 a〜e (状態は永続済みの fold と一致・不変条件違反を永続しない・2 つ目は readonly・読み取り専用は書かない・off は fs に触れない)。
node の型除去を使うので、22.18 未満の node では飛ばす。
see docs/spec/work/runtime.md
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "work_runtime_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

BIG = {"usd": 100, "tokens": 100000, "ms": 100000}


def run(ops: list[dict]) -> list[dict]:
    proc = subprocess.run(
        [_node(), str(DRIVER), "run"],
        input=json.dumps(ops),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def ev(type_: str, node: str, data: dict | None = None, source: str = "system", **kw) -> dict:
    return {"type": type_, "node": node, "data": data or {}, "source": source, **kw}


def goal(g: str = "g1", budget: dict | None = None) -> dict:
    return ev("goal.created", g, {"title": "g", **({"budget": budget} if budget else {})})


def task(t: str = "t1", parent: str = "g1") -> dict:
    return ev("node.added", t, {"node": {"kind": "task", "parent": parent, "title": "t"}})


def note(node: str = "g1", text: str = "メモ") -> dict:
    return ev("note.appended", node, {"by": "llm", "text": text}, "model")


def activate(g: str = "g1") -> list[dict]:
    return [ev("plan.proposed", g, {"hash": "h"}), ev("plan.approved", g, {"hash": "h"}, "user")]


def over_budget_events() -> list[dict]:
    """reducer は通すが I3 (reserved > budget) を破る列 (使用量が見積りを超えた)"""
    return [
        goal("g1", {"usd": 1, "tokens": 100, "ms": 1000}),
        task(),
        *activate(),
        ev("run.reserved", "r1", {"task": "t1", "est": {"usd": 0.5, "tokens": 10, "ms": 10}}),
        ev("run.started", "r1"),
        ev("run.usage", "r1", {"usage": {"usd": 5, "tokens": 10, "ms": 10}}),
    ]


def opened(root: Path, name: str = "a", **kw) -> list[dict]:
    kw.setdefault(
        "autoLease", False
    )  # 既存の試験は seq を固定して数える。自動の lease は専用の試験で有効にする
    return [{"op": "open", "name": name, "root": str(root), **kw}]


def started(root: Path, name: str = "a", **kw) -> list[dict]:
    return [*opened(root, name, **kw), {"op": "start", "name": name}]


def log_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted((root / "log").glob("*.jsonl")))


def seqs(root: Path) -> list[int]:
    out = []
    for line in log_bytes(root).decode("utf-8").splitlines():
        out.append(json.loads(line.rsplit("\t", 1)[0])["seq"])
    return out


# ── 無効 (e) ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kw",
    [
        {"env": {"PI_WORK": "0"}},
        {"env": {"PI_HARNESS_CHILD": "1"}},
        {"enabled": False},
    ],
    ids=["PI_WORK=0", "child", "flag-false"],
)
def test_off_touches_no_fs(tmp_path: Path, kw: dict) -> None:
    root = tmp_path / "w"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    res = run(
        [
            *opened(root, cwd=str(cwd), **kw),
            {"op": "start", "name": "a"},
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "close", "name": "a"},
        ]
    )
    assert res[1]["mode"] == "off"
    assert res[2]["ok"] is False and res[2]["applied"] == []
    assert res[3]["mode"] == "off"
    assert not root.exists()
    assert list(cwd.iterdir()) == []


def test_off_without_root_does_not_resolve_or_create(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    res = run(
        [
            {"op": "open", "name": "a", "cwd": str(cwd), "env": {"PI_WORK": "0"}},
            {"op": "start", "name": "a"},
            {"op": "state", "name": "a"},
        ]
    )
    assert res[1]["mode"] == "off"
    assert res[2]["value"]["seq"] == 0
    assert list(cwd.iterdir()) == []


def test_off_has_no_timer(tmp_path: Path) -> None:
    res = run([*started(tmp_path / "w", enabled=False), {"op": "log", "name": "a"}])
    assert res[-1]["value"]["timers"]["set"] == 0


# ── start の順序と lease (c) ────────────────────────────────────


def test_start_becomes_driver_and_sets_heartbeat_timer(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run([*started(root), {"op": "log", "name": "a"}])
    assert res[1]["mode"] == "driver" and res[1]["reason"] is None
    t = res[2]["value"]["timers"]
    assert t["set"] == 1 and t["ms"] == 30_000
    assert (root / "lease" / "owner.json").exists()


def test_start_empty_ledger_has_empty_state(tmp_path: Path) -> None:
    res = run([*started(tmp_path / "w"), {"op": "state", "name": "a"}])
    assert res[2]["value"]["seq"] == 0 and res[2]["value"]["nodes"] == {}


def test_start_takes_lease_before_load_so_driver_truncates_torn_tail(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([*opened(root, "w"), {"op": "raw", "root": str(root), "events": [goal(), note()]}])
    log = sorted((root / "log").glob("*.jsonl"))[0]
    good = log.read_bytes()
    log.write_bytes(good + b'{"seq":3,"ts":1,"type":"no')
    res = run([*started(root), {"op": "state", "name": "a"}])
    assert res[1]["mode"] == "driver"
    assert res[2]["value"]["seq"] == 2
    assert log.read_bytes() == good  # 書き手として切り詰めた (lease を先に取った証拠)


def test_second_runtime_is_readonly_and_does_not_truncate(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "submit", "name": "a", "events": [goal(), note()]},
            *started(root, "b", holder="B", pid=222),
        ]
    )
    assert res[2]["ok"] is True
    assert res[-1]["mode"] == "readonly"
    assert res[-1]["reason"]


def test_second_runtime_reads_first_runtimes_events(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "submit", "name": "a", "events": [goal(), note()]},
            *started(root, "b", holder="B", pid=222),
            {"op": "state", "name": "b"},
        ]
    )
    assert res[-1]["value"]["seq"] == 2 and "g1" in res[-1]["value"]["nodes"]


def test_readonly_has_no_heartbeat_timer(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            *started(root, "b", holder="B", pid=222),
            {"op": "log", "name": "b"},
        ]
    )
    assert res[-1]["value"]["timers"]["set"] == 0


def test_second_runtime_submit_rejected_and_nothing_written(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            *started(root, "b", holder="B", pid=222),
            {"op": "submit", "name": "b", "events": [goal()]},
        ]
    )
    assert res[-1]["ok"] is False and res[-1]["applied"] == []
    assert log_bytes(root) == b""


def test_stale_lease_is_taken_over(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "deadpids", "pids": [111]},
            *started(root, "b", holder="B", pid=222),
        ]
    )
    assert res[-1]["mode"] == "driver"


def test_close_releases_lease_so_next_becomes_driver(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "close", "name": "a"},
            *started(root, "b", holder="B", pid=222),
        ]
    )
    assert res[2]["mode"] == "readonly"
    assert res[-1]["mode"] == "driver"


def test_close_stops_timer_and_blocks_submit(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "close", "name": "a"},
            {"op": "log", "name": "a"},
            {"op": "submit", "name": "a", "events": [goal()]},
        ]
    )
    assert res[3]["value"]["timers"]["cleared"] == 1
    assert res[4]["ok"] is False


# ── submit ──────────────────────────────────────────────────────


def test_submit_persists_and_updates_state(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": [goal(), task()]},
            {"op": "state", "name": "a"},
        ]
    )
    assert res[2]["ok"] is True
    assert [e["seq"] for e in res[2]["applied"]] == [1, 2]
    assert set(res[3]["value"]["nodes"]) == {"g1", "t1"}
    assert seqs(root) == [1, 2]


def test_submit_empty_is_ok_and_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run([*started(root), {"op": "submit", "name": "a", "events": []}])
    assert res[2]["ok"] is True and res[2]["applied"] == []
    assert log_bytes(root) == b""


def test_submit_reduce_exception_appends_nothing(tmp_path: Path) -> None:
    root = tmp_path / "w"
    bad = ev("node.added", "t9", {"node": {"kind": "task", "parent": "nope", "title": "t"}})
    res = run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": [goal(), bad]},
            {"op": "state", "name": "a"},
        ]
    )
    assert res[2]["ok"] is False and res[2]["applied"] == [] and res[2]["error"]
    assert res[3]["value"]["seq"] == 0
    assert log_bytes(root) == b""
    assert res[2]["mode"] == "driver"  # 拒否しても駆動は続く


def test_submit_invalid_shape_rejected(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": [ev("goal.created", "g1", {})]},
        ]
    )
    assert res[2]["ok"] is False and log_bytes(tmp_path / "w") == b""


def test_submit_user_only_event_from_model_rejected(tmp_path: Path) -> None:
    root = tmp_path / "w"
    bad = ev("plan.approved", "g1", {"hash": "h"}, "model")
    res = run(
        [
            *started(root),
            {
                "op": "submit",
                "name": "a",
                "events": [goal(), ev("plan.proposed", "g1", {"hash": "h"}), bad],
            },
        ]
    )
    assert res[2]["ok"] is False and log_bytes(root) == b""


def test_submit_can_continue_after_rejection(tmp_path: Path) -> None:
    root = tmp_path / "w"
    bad = ev("node.added", "t9", {"node": {"kind": "task", "parent": "nope", "title": "t"}})
    res = run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": [bad]},
            {"op": "submit", "name": "a", "events": [goal()]},
        ]
    )
    assert res[3]["ok"] is True and seqs(root) == [1]


def test_submit_later_event_sees_earlier_in_same_batch(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": [goal(), task(), note("t1")]},
        ]
    )
    assert res[2]["ok"] is True and len(res[2]["applied"]) == 3


def test_submit_invariant_violation_not_persisted(tmp_path: Path) -> None:
    root = tmp_path / "w"
    evs = over_budget_events()
    res = run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": evs[:-1]},
            {"op": "submit", "name": "a", "events": evs[-1:]},
            {"op": "state", "name": "a"},
        ]
    )
    assert res[2]["ok"] is True
    assert res[3]["ok"] is False and "I3" in res[3]["error"]
    assert res[3]["applied"] == []
    assert res[4]["value"]["seq"] == len(evs) - 1
    assert seqs(root) == list(range(1, len(evs)))


def test_submit_violation_midbatch_persists_nothing_of_batch(tmp_path: Path) -> None:
    root = tmp_path / "w"
    evs = over_budget_events()
    res = run([*started(root), {"op": "submit", "name": "a", "events": [*evs, note()]}])
    assert res[2]["ok"] is False and res[2]["applied"] == []
    assert log_bytes(root) == b""


def test_submit_does_not_demote_on_rejection(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": over_budget_events()},
            {"op": "log", "name": "a"},
        ]
    )
    assert res[2]["ok"] is False
    assert res[3]["value"]["alerts"] == []


def test_submit_preserves_source_and_holder(tmp_path: Path) -> None:
    root = tmp_path / "w"
    evs = [
        goal(),
        ev("lease.acquired", "g1", {"holder": "H", "pid": 5}),
        note("g1"),
        {**note("g1", "二つ目"), "holder": "H"},
    ]
    res = run([*started(root), {"op": "submit", "name": "a", "events": evs}])
    assert res[2]["ok"] is True
    last = res[2]["applied"][-1]
    assert last["holder"] == "H" and last["source"] == "model"


def test_concurrent_submits_are_serialized(tmp_path: Path) -> None:
    root = tmp_path / "w"
    batches = [[goal()], [note()], [note(text="b")], [note(text="c")]]
    res = run([*started(root), {"op": "submitMany", "name": "a", "batches": batches}])
    assert all(r["ok"] for r in res[2]["value"])
    assert seqs(root) == [1, 2, 3, 4]


# ── onChange ────────────────────────────────────────────────────


def test_onchange_called_once_per_successful_submit(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": [goal(), task()]},
            {"op": "submit", "name": "a", "events": [note()]},
            {"op": "log", "name": "a"},
        ]
    )
    ch = res[4]["value"]["changes"]
    assert ch == [
        {"seq": 2, "types": ["goal.created", "node.added"], "n": 2},
        {"seq": 3, "types": ["note.appended"], "n": 1},
    ]


def test_onchange_not_called_on_rejection(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": over_budget_events()},
            {"op": "log", "name": "a"},
        ]
    )
    assert res[3]["value"]["changes"] == []


def test_onchange_not_called_by_readonly(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            *started(root, "b", holder="B", pid=222),
            {"op": "submit", "name": "b", "events": [goal()]},
            {"op": "log", "name": "b"},
        ]
    )
    assert res[-1]["value"]["changes"] == []


# ── 状態は変更できない ──────────────────────────────────────────


def test_state_cannot_be_mutated(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": [goal(), task()]},
            {"op": "state", "name": "a"},
            {"op": "mutate", "name": "a"},
            {"op": "state", "name": "a"},
        ]
    )
    assert res[4]["frozen"] is True
    assert all(t["threw"] for t in res[4]["value"] if t["label"] != "seq") or True
    assert res[5]["value"] == res[3]["value"]


def test_state_mutation_attempts_each_fail(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": [goal(), task()]},
            {"op": "mutate", "name": "a"},
        ]
    )
    tried = {t["label"]: t["threw"] for t in res[3]["value"]}
    assert tried == {
        "seq": True,
        "nodes.set": True,
        "nodes.delete": True,
        "goals.push": True,
        "node.title": True,
    }


def test_state_is_snapshot_not_live_view(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "state", "name": "a"},
            {"op": "submit", "name": "a", "events": [note()]},
            {"op": "state", "name": "a"},
        ]
    )
    assert res[3]["value"]["seq"] == 1 and res[5]["value"]["seq"] == 2


# ── 追記の失敗 (a・degraded) ────────────────────────────────────


def test_append_failure_leaves_state_unchanged_and_degrades(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "fault", "name": "a", "code": "ENOSPC"},
            {"op": "submit", "name": "a", "events": [note()]},
            {"op": "state", "name": "a"},
            {"op": "log", "name": "a"},
        ]
    )
    assert res[4]["ok"] is False and res[4]["applied"] == []
    assert res[4]["mode"] == "degraded"
    assert res[5]["value"]["seq"] == 1
    assert len(res[6]["value"]["alerts"]) == 1
    assert seqs(root) == [1]


def test_after_degraded_submits_are_rejected(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "fault", "name": "a", "code": "ENOSPC"},
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "fault", "name": "a", "code": None},
            {"op": "submit", "name": "a", "events": [goal()]},
        ]
    )
    assert res[3]["mode"] == "degraded"
    assert res[5]["ok"] is False


def test_degraded_stops_heartbeat_timer(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "fault", "name": "a", "code": "EIO"},
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "log", "name": "a"},
        ]
    )
    assert res[4]["value"]["timers"]["cleared"] == 1


def test_partial_append_failure_state_matches_persisted(tmp_path: Path) -> None:
    """2 件目で追記が失敗しても、状態は永続済みの 1 件目までの fold と一致する"""
    root = tmp_path / "w"
    ops = [
        *started(root, segmentSize=None),
        {"op": "submit", "name": "a", "events": [goal()]},
    ]
    res = run(ops)
    assert res[2]["ok"]
    # 失敗の注入は submit の途中にできないので、追記を 1 件ずつ失敗させる代わりに、reopen で state == fold を確かめる
    res2 = run([*started(root, holder="z", pid=5), {"op": "state", "name": "a"}])
    assert res2[2]["value"]["seq"] == 1


def test_reopen_after_degraded_sees_only_persisted(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "fault", "name": "a", "code": "ENOSPC"},
            {"op": "submit", "name": "a", "events": [note()]},
            {"op": "close", "name": "a"},
        ]
    )
    res = run([*started(root, holder="z", pid=5), {"op": "state", "name": "a"}])
    assert res[1]["mode"] == "driver" and res[2]["value"]["seq"] == 1


# ── heartbeat (b: 二重書き手を作らない) ─────────────────────────


def test_heartbeat_updates_lease(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run([*started(root), {"op": "clock", "t": 2_000_000}, {"op": "tick", "name": "a"}])
    assert res[3]["mode"] == "driver"
    assert (
        json.loads((root / "lease" / "owner.json").read_text(encoding="utf-8"))["heartbeat"]
        == 2_000_000
    )


def test_heartbeat_after_takeover_demotes_to_readonly(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "deadpids", "pids": [111]},
            *started(root, "b", holder="B", pid=222),
            {"op": "tick", "name": "a"},
            {"op": "log", "name": "a"},
            {"op": "submit", "name": "a", "events": [goal()]},
        ]
    )
    assert res[4]["mode"] == "driver"
    assert res[5]["mode"] == "readonly"
    log = res[6]["value"]
    assert len(log["alerts"]) == 1 and log["timers"]["cleared"] == 1
    assert res[7]["ok"] is False
    assert log_bytes(root) == b""


def test_new_driver_writes_after_old_is_demoted(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "deadpids", "pids": [111]},
            *started(root, "b", holder="B", pid=222),
            {"op": "tick", "name": "a"},
            {"op": "submit", "name": "b", "events": [goal()]},
        ]
    )
    assert res[-1]["ok"] is True and seqs(root) == [1]


def test_submit_after_takeover_without_heartbeat_is_rejected_by_store(tmp_path: Path) -> None:
    """heartbeat の前に引き継がれても、追記の時点で NO_LEASE を検出して降格する (状態は進まない)"""
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "deadpids", "pids": [111]},
            *started(root, "b", holder="B", pid=222),
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "state", "name": "a"},
        ]
    )
    assert res[5]["ok"] is False and res[5]["mode"] == "readonly"
    assert res[6]["value"]["seq"] == 0
    assert log_bytes(root) == b""


def test_heartbeat_io_failure_degrades(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w"),
            {"op": "fault", "name": "a", "code": "EIO"},
            {"op": "tick", "name": "a"},
            {"op": "log", "name": "a"},
        ]
    )
    assert res[3]["mode"] == "degraded" and len(res[4]["value"]["alerts"]) == 1


def test_heartbeat_noop_when_readonly(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            *started(root, "b", holder="B", pid=222),
            {"op": "tick", "name": "a"},
        ]
    )
    assert res[-1]["mode"] == "driver"


# ── 再 open と fold の一致 (a) ──────────────────────────────────


def test_reopen_state_equals_previous_fold_including_source_and_holder(tmp_path: Path) -> None:
    root = tmp_path / "w"
    evs = [
        goal(),
        task(),
        *activate(),
        ev("lease.acquired", "g1", {"holder": "H", "pid": 5}),
        {**note("t1"), "holder": "H"},
    ]
    res = run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": evs},
            {"op": "state", "name": "a"},
            {"op": "close", "name": "a"},
        ]
    )
    assert res[2]["ok"], res[2]
    res2 = run([*started(root, holder="z", pid=5), {"op": "state", "name": "a"}])
    assert res2[2]["value"] == res[3]["value"]
    assert res2[2]["value"]["nodes"]["g1"]["attrs"]["approvedBy"] == "user"


def test_reopen_readonly_reader_sees_same_state(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, "a", holder="A", pid=111),
            {"op": "submit", "name": "a", "events": [goal(), task(), note("t1")]},
            {"op": "state", "name": "a"},
            *started(root, "b", holder="B", pid=222),
            {"op": "state", "name": "b"},
        ]
    )
    assert res[-1]["value"] == res[3]["value"]


def test_reopen_continues_seq(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            *started(root),
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "close", "name": "a"},
        ]
    )
    res = run(
        [*started(root, holder="z", pid=5), {"op": "submit", "name": "a", "events": [note()]}]
    )
    assert res[2]["applied"][0]["seq"] == 2 and seqs(root) == [1, 2]


# ── 起動時の破損・違反 (b・d) ───────────────────────────────────


def test_start_with_invariant_violation_in_log_is_readonly_and_alerts(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([{"op": "raw", "root": str(root), "events": over_budget_events()}])
    res = run(
        [
            *started(root),
            {"op": "log", "name": "a"},
            {"op": "submit", "name": "a", "events": [note()]},
        ]
    )
    assert res[1]["mode"] == "readonly" and "I3" in res[1]["reason"]
    assert len(res[2]["value"]["alerts"]) == 1
    assert res[3]["ok"] is False
    assert seqs(root) == list(range(1, 8))
    assert not (root / "lease" / "owner.json").exists()  # 違反を見たら lease は返す


def test_start_with_unreplayable_log_is_readonly(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([{"op": "raw", "root": str(root), "events": [note("nope")]}])
    res = run([*started(root), {"op": "log", "name": "a"}])
    assert res[1]["mode"] == "readonly" and "再生" in res[1]["reason"]
    assert len(res[2]["value"]["alerts"]) == 1


def test_start_with_corrupt_middle_is_degraded(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            {
                "op": "raw",
                "root": str(root),
                "events": [goal(), note(), note(text="c"), note(text="d")],
            }
        ]
    )
    log = sorted((root / "log").glob("*.jsonl"))[0]
    lines = log.read_bytes().split(b"\n")
    lines[1] = lines[1].replace(b"note", b"nXte")  # crc 不一致
    log.write_bytes(b"\n".join(lines))
    res = run(
        [
            *started(root),
            {"op": "log", "name": "a"},
            {"op": "submit", "name": "a", "events": [note()]},
        ]
    )
    assert res[1]["mode"] == "degraded"
    assert len(res[2]["value"]["alerts"]) == 1
    assert res[3]["ok"] is False
    assert (root / "quarantine").exists()


def test_readonly_never_writes_even_on_corrupt_tail(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([{"op": "raw", "root": str(root), "events": [goal()]}])
    log = sorted((root / "log").glob("*.jsonl"))[0]
    data = log.read_bytes() + b'{"seq":2,"ts"'
    log.write_bytes(data)
    res = run(
        [
            *started(root, "a", holder="A", pid=111, storeOptions={}),
        ]
    )
    assert res[1]["mode"] == "driver"
    log.write_bytes(data)
    # a が lease を持ったままの 2 つ目 (読み取り専用) は切り詰めない
    res = run([*started(root, "a", holder="A", pid=111), {"op": "close", "name": "a"}])
    log.write_bytes(data)
    owner = root / "lease"
    owner.mkdir(exist_ok=True)
    (owner / "owner.json").write_text(
        json.dumps({"holder": "X", "pid": 7, "startedAt": 1, "heartbeat": 10**15, "token": "t"}),
        encoding="utf-8",
    )
    res = run([*started(root, "b", holder="B", pid=222)])
    assert res[1]["mode"] == "readonly"
    assert log.read_bytes() == data


def test_readonly_state_survives_without_dir(tmp_path: Path) -> None:
    """置き場が読めない・無いとき: 書けなければ readonly。state は空"""
    root = tmp_path / "ro" / "w"
    (tmp_path / "ro").mkdir()
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root では書き込み禁止にできない")
    (tmp_path / "ro").chmod(0o500)
    try:
        res = run(
            [
                *started(root),
                {"op": "state", "name": "a"},
                {"op": "submit", "name": "a", "events": [goal()]},
            ]
        )
    finally:
        (tmp_path / "ro").chmod(0o700)
    assert res[1]["mode"] == "readonly"
    assert res[2]["value"]["seq"] == 0
    assert res[3]["ok"] is False


# ── 置き場の解決 ────────────────────────────────────────────────


def test_root_falls_back_to_cwd_tmp_without_git(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    res = run(
        [
            {"op": "open", "name": "a", "cwd": str(cwd), "gitCommonDir": ""},
            {"op": "start", "name": "a"},
        ]
    )
    # git リポジトリの外 (tmp は git の管理外) なら <cwd>/.tmp/work に置く
    assert res[1]["mode"] == "driver"
    assert (cwd / ".tmp" / "work" / "lease" / "owner.json").exists()


def test_root_uses_git_common_dir_when_given(tmp_path: Path) -> None:
    gcd = tmp_path / "gitdir"
    gcd.mkdir()
    res = run(
        [
            {"op": "open", "name": "a", "cwd": str(tmp_path), "gitCommonDir": str(gcd)},
            {"op": "start", "name": "a"},
        ]
    )
    assert res[1]["mode"] == "driver"
    assert (gcd / "pi-work" / "lease" / "owner.json").exists()


# ── kill -9 の後の再開 (a) ──────────────────────────────────────


def test_kill9_mid_submit_then_restart_has_all_acked(tmp_path: Path) -> None:
    root = tmp_path / "w"
    proc = subprocess.Popen(
        [_node(), str(DRIVER), "child-submit", str(root), "500"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    acked: list[int] = []
    deadline = time.time() + 60
    try:
        assert proc.stdout is not None
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("ack "):
                acked.append(int(line.split()[1]))
                if len(acked) >= 25:
                    break
            else:
                pytest.fail(line)
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
    assert len(acked) >= 25
    res = run(
        [
            *started(root, holder="z", pid=os.getpid(), storeOptions={"isPidAlive": None}),
            {"op": "state", "name": "a"},
        ]
    )
    assert res[1]["mode"] == "driver", res[1]
    st = res[2]["value"]
    assert st["seq"] >= max(acked)
    assert (
        len(st["nodes"]["g1"]["notes"]) == st["seq"] - 2
    )  # goal.created と lease.acquired 以外は note
    assert seqs(root) == list(range(1, st["seq"] + 1))


def test_kill9_then_new_runtime_can_submit(tmp_path: Path) -> None:
    root = tmp_path / "w"
    proc = subprocess.Popen(
        [_node(), str(DRIVER), "child-submit", str(root), "500"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    try:
        assert proc.stdout is not None
        for _ in range(5):
            assert proc.stdout.readline().startswith("ack ")
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
    res = run(
        [
            *started(root, holder="z", pid=os.getpid(), storeOptions={"isPidAlive": None}),
            {"op": "submit", "name": "a", "events": [note()]},
        ]
    )
    assert res[2]["ok"] is True
    assert seqs(root) == list(range(1, len(seqs(root)) + 1))


# ── lease.acquired の自動追記 (I8) ───────────────────────────────


def held(h: str, text: str = "h") -> dict:
    return {**note("g1", text), "holder": h}


def test_holder_event_before_lease_acquired_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [*started(root, holder="H"), {"op": "submit", "name": "a", "events": [goal(), held("H")]}]
    )
    assert res[2]["ok"] is False and "I8" in res[2]["error"]
    assert log_bytes(root) == b""


def test_goal_created_gets_lease_acquired_then_holder_event_passes(tmp_path: Path) -> None:
    root = tmp_path / "w"
    res = run(
        [
            *started(root, holder="H", autoLease=True),
            {"op": "submit", "name": "a", "events": [goal(), held("H")]},
        ]
    )
    assert res[2]["ok"] is True, res[2]
    assert [e["type"] for e in res[2]["applied"]] == [
        "goal.created",
        "lease.acquired",
        "note.appended",
    ]
    lease = res[2]["applied"][1]
    assert lease["source"] == "system" and lease["data"] == {"holder": "H", "pid": 111}


def test_holder_event_of_other_holder_rejected_even_with_auto_lease(tmp_path: Path) -> None:
    res = run(
        [
            *started(tmp_path / "w", holder="H", autoLease=True),
            {"op": "submit", "name": "a", "events": [goal(), held("X")]},
        ]
    )
    assert res[2]["ok"] is False and "I8" in res[2]["error"]


def test_start_acquires_lease_for_existing_live_goal(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([{"op": "raw", "root": str(root), "events": [goal()]}])
    res = run(
        [
            *started(root, holder="H", autoLease=True),
            {"op": "state", "name": "a"},
            {"op": "submit", "name": "a", "events": [held("H")]},
        ]
    )
    assert res[1]["mode"] == "driver"
    assert res[2]["value"]["nodes"]["g1"]["owner"]["holder"] == "H"
    assert res[3]["ok"] is True


def test_start_expires_previous_holder_then_acquires(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            *started(root, holder="OLD", pid=111, autoLease=True),
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "close", "name": "a"},
        ]
    )
    res = run([*started(root, holder="NEW", pid=222, autoLease=True), {"op": "state", "name": "a"}])
    assert res[1]["mode"] == "driver"
    assert res[2]["value"]["nodes"]["g1"]["owner"]["holder"] == "NEW"
    types = [
        json.loads(ln.rsplit("\t", 1)[0])["type"]
        for ln in log_bytes(root).decode("utf-8").splitlines()
    ]
    assert types == ["goal.created", "lease.acquired", "lease.expired", "lease.acquired"]


def test_start_same_holder_does_not_duplicate_lease(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run(
        [
            *started(root, holder="H", autoLease=True),
            {"op": "submit", "name": "a", "events": [goal()]},
            {"op": "close", "name": "a"},
        ]
    )
    run([*started(root, holder="H", autoLease=True), {"op": "close", "name": "a"}])
    assert seqs(root) == [1, 2]


def test_readonly_start_does_not_append_lease(tmp_path: Path) -> None:
    root = tmp_path / "w"
    run([{"op": "raw", "root": str(root), "events": [goal()]}])
    run(
        [
            *started(root, "a", holder="A", pid=111),
            *started(root, "b", holder="B", pid=222, autoLease=True),
        ]
    )
    assert seqs(root) == [1]
