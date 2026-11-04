"""モデル向けツール ``work`` の純関数 (``home/dot_config/pi/harness/work/tool.ts``) の試験。

``test/agents/pi/work_tool_driver.mjs`` に JSON を渡して ``handleWork`` を呼ぶ (node の型除去を使うので、22.18 未満の node では飛ばす)。
どの step でも、入力 state の不変・決定性・不変条件 (I1〜I10) を一緒に確かめる。

see docs/spec/work/tool.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_tool_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

USER_ONLY = {"plan.approved", "budget.adjusted", "goal.resumed"}


def drive(payload):
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=240,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(proc.stdout)


def ev(type_, node, data=None, source=None):
    e = {"type": type_, "node": node, "data": data or {}}
    if source:
        e["source"] = source
    return e


def task(id_, title="t", after=None, parent="g1"):
    return ev(
        "node.added",
        id_,
        {"node": {"kind": "task", "parent": parent, "title": title, "after": after or []}},
    )


def active(*tasks):
    """承認済み (active) の goal g1 と、ready の task 群 (既定は n1 と、n1 に依存する n2)"""
    ts = list(tasks) or [task("n1"), task("n2", after=["n1"])]
    return [
        ev("goal.created", "g1", {"title": "G"}),
        *ts,
        ev("plan.proposed", "g1", {"hash": "h"}),
        ev("plan.approved", "g1", {"hash": "h"}, "user"),
    ]


def draft(*tasks):
    return [ev("goal.created", "g1", {"title": "G"}), *tasks]


def play(setup, *steps, now=5000, holder="h1"):
    """steps を順に流し、各 step の結果を返す。共通の性質 (不変・決定・不変条件) はここで確かめる"""
    steps_out = drive(
        {"cases": [{"setup": setup, "steps": list(steps), "now": now, "holder": holder}]}
    )["cases"][0]["steps"]
    for s in steps_out:
        assert s["unchanged"], "入力の state を変更した"
        assert s["deterministic"], "同じ入力で結果が違う"
        assert s["applyError"] is None, s["applyError"]
        assert s["violations"] == [], s["violations"]
        assert all(e["type"] not in USER_ONLY for e in s["result"]["events"])
        assert all(e["source"] == "model" for e in s["result"]["events"])
        if not s["result"]["ok"]:
            assert s["result"]["events"] == []
        assert len(s["result"]["text"]) <= 1500
    return steps_out


def one(setup, args):
    return play(setup, args)[0]


def ok(setup, args):
    s = one(setup, args)
    assert s["result"]["ok"], s["result"]["text"]
    return s


def rejected(setup, args):
    s = one(setup, args)
    assert not s["result"]["ok"], s["result"]
    assert s["result"]["events"] == []
    return s["result"]["text"]


# ── 禁止 op ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "op",
    [
        "spawn",
        "approve",
        "budget",
        "resume",
        "adjust",
        "approve_plan",
        "plan_approve",
        "budget.adjust",
        "run",
        "delegate",
        "ADD",
        "add ",
        "",
        None,
        5,
        ["add"],
    ],
)
def test_forbidden_or_unknown_op_rejected(op):
    text = rejected(active(), {"op": op, "id": "n1"})
    assert "拒否" in text


def test_missing_op_and_non_object_args_rejected():
    for a in (None, [], "list", 3, {}):
        rejected(active(), a)


def test_schema_has_exactly_six_ops():
    sch = drive({"schema": True})["schema"]
    ops = sorted(b["properties"]["op"]["const"] for b in sch["oneOf"])
    assert ops == ["add", "cancel", "list", "note", "plan", "set"]
    for b in sch["oneOf"]:
        assert b["additionalProperties"] is False
    blob = json.dumps(sch)
    for w in ("spawn", "approve", "budget", "resume"):
        assert w not in blob


# ── 厳格な型検査 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "args",
    [
        {"op": "add", "title": "x", "extra": 1},
        {"op": "set", "id": "n1", "status": "done", "extra": 1},
        {"op": "note", "id": "n1", "text": "x", "by": "user"},
        {"op": "list", "extra": 1},
        {"op": "plan", "goal": "g", "tasks": [{"title": "t"}], "approve": True},
        {"op": "plan", "goal": "g", "tasks": [{"title": "t", "state": "ready"}]},
        {"op": "cancel", "id": "n1", "reason": "r", "force": True},
        {"op": "add", "title": "x", "wait": {"on": "time", "ref": "r", "extra": 1}},
        {"op": "set", "id": "n1", "status": "done", "source": "user"},
    ],
)
def test_extra_keys_rejected(args):
    assert "余計なキー" in rejected(active(), args)


@pytest.mark.parametrize(
    "args",
    [
        {"op": "add", "title": 5},
        {"op": "add", "title": ""},
        {"op": "add", "title": "x" * 201},
        {"op": "add", "title": "a\nb"},
        {"op": "add", "title": "x", "kind": "run"},
        {"op": "add", "title": "x", "kind": "goal"},
        {"op": "add", "title": "x", "writes": "a"},
        {"op": "add", "title": "x", "writes": [1]},
        {"op": "add", "title": "x", "writes": ["a"] * 21},
        {"op": "add", "title": "x", "deps": "n1"},
        {"op": "add", "title": "x", "deps": [1]},
        {"op": "add", "title": "x", "deps": ["n1"] * 21},
        {"op": "add", "title": "x", "parent": "../g"},
        {"op": "add", "title": "x", "wait": "time"},
        {"op": "add", "title": "x", "wait": {"on": "run", "ref": "r"}},
        {"op": "add", "title": "x", "wait": {"on": "time"}},
        {"op": "add", "title": "x", "wait": {"on": "user", "ref": "r"}},
        {"op": "add", "title": "x", "wait": {"on": "user", "ref": "r", "prompt": "あ" * 24}},
        {"op": "set", "id": "n1"},
        {"op": "set", "id": "n1", "status": "approved"},
        {"op": "set", "id": "n1", "status": "ready"},
        {"op": "set", "id": "n1", "status": "running"},
        {"op": "set", "id": "n1", "status": 1},
        {"op": "note", "id": "n1", "text": ""},
        {"op": "note", "id": "n1", "text": "x" * 301},
        {"op": "note", "id": "n1", "text": 5},
        {"op": "list", "filter": "all"},
        {"op": "list", "filter": 1},
        {"op": "plan", "goal": "g", "tasks": []},
        {"op": "plan", "goal": "g", "tasks": "x"},
        {"op": "plan", "goal": "", "tasks": [{"title": "t"}]},
        {"op": "plan", "goal": "g", "tasks": [{"title": "t"}] * 31},
        {"op": "plan", "goal": "g", "tasks": [{"title": "t", "deps": [0]}]},
        {"op": "plan", "goal": "g", "tasks": [{"title": "t"}, {"title": "u", "deps": [1.5]}]},
        {"op": "plan", "goal": "g", "tasks": [{"title": "t"}, {"title": "u", "deps": [-1]}]},
        {"op": "plan", "goal": "g", "tasks": ["t"]},
        {"op": "cancel", "id": "n1"},
        {"op": "cancel", "id": "n1", "reason": ""},
        {"op": "cancel", "id": "n1", "reason": "x" * 201},
    ],
)
def test_type_errors_rejected(args):
    rejected(active(), args)


@pytest.mark.parametrize(
    "bad_id", [" n1", "1a", "n1;rm", "", "n" * 41, "n 1", "n1\n", None, 5, "../n1", "n/1"]
)
def test_bad_id_forms_rejected(bad_id):
    for op in (
        {"op": "set", "id": bad_id, "status": "done"},
        {"op": "note", "id": bad_id, "text": "x"},
        {"op": "cancel", "id": bad_id, "reason": "r"},
    ):
        rejected(active(), op)


def test_boundary_lengths_accepted():
    ok(active(), {"op": "add", "title": "x" * 200})
    ok(active(), {"op": "note", "id": "n1", "text": "x" * 300})
    ok(active(), {"op": "cancel", "id": "n1", "reason": "x" * 200})


# ── add ──────────────────────────────────────────────────


def test_add_to_active_goal_is_ready():
    s = ok(active(), {"op": "add", "title": "新しい作業"})
    assert s["eventTypes"] == ["node.added"]
    assert s["nodes"]["n3"]["state"] == "ready"
    assert s["nodes"]["n3"]["parent"] == "g1"
    assert "n3" in s["result"]["text"]


def test_add_without_goal_creates_goal_and_is_proposed():
    s = ok([], {"op": "add", "title": "作業"})
    assert s["eventTypes"] == ["goal.created", "node.added"]
    assert s["nodes"]["n2"]["state"] == "proposed"


def test_add_to_draft_goal_stays_proposed():
    s = ok(draft(), {"op": "add", "title": "x"})
    assert s["nodes"]["n2"]["state"] == "proposed"


def test_add_with_deps_and_parent_and_kind():
    s = ok(
        active(),
        {"op": "add", "title": "検査", "kind": "check", "parent": "n1", "deps": ["n1", "n2"]},
    )
    n = s["nodes"]["n3"]
    assert n["kind"] == "check" and n["parent"] == "n1" and n["after"] == ["n1", "n2"]


def test_add_unknown_dep_or_parent_rejected():
    rejected(active(), {"op": "add", "title": "x", "deps": ["n99"]})
    rejected(active(), {"op": "add", "title": "x", "parent": "n99"})


def test_add_dep_on_goal_rejected():
    rejected(active(), {"op": "add", "title": "x", "deps": ["g1"]})


def test_add_to_finished_goal_rejected():
    setup = [*active(), ev("verdict", "g1", {"verdict": "cancel", "reason": "r"})]
    text = rejected(setup, {"op": "add", "title": "x", "parent": "g1"})
    assert "足せない" in text


def test_add_with_time_wait_goes_waiting():
    s = ok(active(), {"op": "add", "title": "待つ", "wait": {"on": "time", "ref": "t1"}})
    assert s["nodes"]["n3"]["state"] == "waiting"
    assert s["eventTypes"] == ["node.added", "run.reserved", "run.started", "wait.opened"]


def test_add_with_user_wait_needs_prompt_and_waits():
    s = ok(
        active(),
        {
            "op": "add",
            "title": "確認待ち",
            "wait": {"on": "user", "ref": "q", "prompt": "どちらにしますか"},
        },
    )
    assert s["nodes"]["n3"]["state"] == "waiting"


def test_add_wait_in_unapproved_goal_rejected_atomically():
    text = rejected(draft(), {"op": "add", "title": "x", "wait": {"on": "time", "ref": "t"}})
    assert "承認" in text


def test_add_ids_are_unique_over_calls():
    r = play(active(), *[{"op": "add", "title": f"t{i}"} for i in range(5)])
    ids = [
        next(
            k
            for k in s["nodes"]
            if k not in {"g1", "n1", "n2"} and s["nodes"][k]["title"] == f"t{i}"
        )
        for i, s in enumerate(r)
    ]
    assert len(set(ids)) == 5


# ── set ──────────────────────────────────────────────────


def test_set_in_progress_starts_run():
    s = ok(active(), {"op": "set", "id": "n1", "status": "in_progress"})
    assert s["nodes"]["n1"]["state"] == "running"
    assert s["eventTypes"] == ["run.reserved", "run.started"]


def test_set_in_progress_is_idempotent():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "in_progress"},
        {"op": "set", "id": "n1", "status": "in_progress"},
    )
    assert r[1]["result"]["ok"] and r[1]["result"]["events"] == []


def test_set_in_progress_unapproved_rejected():
    text = rejected(draft(task("n1")), {"op": "set", "id": "n1", "status": "in_progress"})
    assert "承認は利用者だけ" in text


def test_set_in_progress_with_unfinished_dep_rejected():
    assert "未完了" in rejected(active(), {"op": "set", "id": "n2", "status": "in_progress"})


def test_set_done_full_path_and_unlocks_dependent():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "set", "id": "n2", "status": "in_progress"},
        {"op": "set", "id": "n2", "status": "done"},
    )
    assert r[0]["nodes"]["n1"]["state"] == "done"
    assert r[0]["eventTypes"] == ["run.reserved", "run.started", "run.ended", "check.result"]
    assert [s["result"]["ok"] for s in r] == [True, True, True]
    assert r[2]["nodes"]["n2"]["state"] == "done"


def test_set_done_from_running():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "in_progress"},
        {"op": "set", "id": "n1", "status": "done"},
    )
    assert r[1]["nodes"]["n1"]["state"] == "done"
    assert r[1]["eventTypes"] == ["run.ended", "check.result"]


def test_set_done_twice_rejected():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "set", "id": "n1", "status": "done"},
    )
    assert not r[1]["result"]["ok"]


def test_set_done_in_unapproved_rejected():
    rejected(draft(task("n1")), {"op": "set", "id": "n1", "status": "done"})


def test_set_blocked_then_pending_then_in_progress():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "blocked"},
        {"op": "set", "id": "n1", "status": "pending"},
        {"op": "set", "id": "n1", "status": "in_progress"},
    )
    assert [s["nodes"]["n1"]["state"] for s in r] == ["blocked", "ready", "running"]


def test_set_in_progress_from_blocked_retries():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "blocked"},
        {"op": "set", "id": "n1", "status": "in_progress"},
    )
    assert r[1]["nodes"]["n1"]["state"] == "running"
    assert r[1]["eventTypes"][0] == "verdict"


def test_set_pending_on_ready_is_noop():
    s = ok(active(), {"op": "set", "id": "n1", "status": "pending"})
    assert s["result"]["events"] == []


def test_set_pending_on_running_rejected():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "in_progress"},
        {"op": "set", "id": "n1", "status": "pending"},
    )
    assert not r[1]["result"]["ok"]


def test_set_cancelled_ready_and_running():
    r = play(
        active(task("n1"), task("n2")),
        {"op": "set", "id": "n1", "status": "cancelled"},
        {"op": "set", "id": "n2", "status": "in_progress"},
        {"op": "set", "id": "n2", "status": "cancelled"},
    )
    assert r[0]["nodes"]["n1"]["state"] == "cancelled"
    assert r[2]["nodes"]["n2"]["state"] == "cancelled"
    assert r[2]["eventTypes"] == ["run.ended", "verdict"]


def test_set_unknown_or_non_task_rejected():
    rejected(active(), {"op": "set", "id": "n99", "status": "done"})
    assert "task でない" in rejected(active(), {"op": "set", "id": "g1", "status": "done"})


def test_set_on_waiting_task_rejected():
    setup = active()
    r = play(
        setup,
        {"op": "add", "title": "w", "wait": {"on": "time", "ref": "t"}},
        {"op": "set", "id": "n3", "status": "done"},
        {"op": "set", "id": "n3", "status": "in_progress"},
    )
    assert not r[1]["result"]["ok"] and not r[2]["result"]["ok"]


def test_failed_set_leaves_no_partial_events():
    s = one(active(), {"op": "set", "id": "n2", "status": "done"})
    assert s["result"]["events"] == [] and s["eventTypes"] == []


# ── 循環 ─────────────────────────────────────────────────


def chain(n):
    return active(*[task("n1")] + [task(f"n{i}", after=[f"n{i - 1}"]) for i in range(2, n + 1)])


def test_cycle_self_rejected():
    assert "自分" in rejected(active(), {"op": "set", "id": "n1", "deps": ["n1"]})


def test_cycle_two_rejected():
    assert "循環" in rejected(active(), {"op": "set", "id": "n1", "deps": ["n2"]})


def test_cycle_three_rejected():
    assert "循環" in rejected(chain(3), {"op": "set", "id": "n1", "deps": ["n3"]})


def test_cycle_hundred_rejected():
    assert "循環" in rejected(chain(100), {"op": "set", "id": "n1", "deps": ["n100"]})


def test_cycle_hundred_accepts_non_cycle():
    s = ok(chain(100), {"op": "set", "id": "n100", "deps": ["n1"]})
    assert s["eventTypes"] == ["edge.added"]


def test_edge_added_and_dedup():
    r = play(
        active(task("n1"), task("n2")),
        {"op": "set", "id": "n2", "deps": ["n1"]},
        {"op": "set", "id": "n2", "deps": ["n1"]},
    )
    assert r[0]["nodes"]["n2"]["after"] == ["n1"]
    assert r[1]["result"]["ok"] and r[1]["result"]["events"] == []


def test_cycle_in_second_of_two_deps_is_atomic():
    s = one(chain(3), {"op": "set", "id": "n1", "deps": ["n3", "n2"]})
    assert not s["result"]["ok"] and s["result"]["events"] == []
    assert s["nodes"]["n1"]["after"] == []


def test_edge_on_running_task_rejected():
    r = play(
        active(task("n1"), task("n2")),
        {"op": "set", "id": "n2", "status": "in_progress"},
        {"op": "set", "id": "n2", "deps": ["n1"]},
    )
    assert not r[1]["result"]["ok"]


def test_edge_with_status_in_one_call():
    s = ok(
        active(task("n1"), task("n2")),
        {"op": "set", "id": "n2", "deps": ["n1"], "status": "pending"},
    )
    assert s["nodes"]["n2"]["after"] == ["n1"]


# ── note ─────────────────────────────────────────────────


def test_note_appends_only():
    r = play(
        active(), {"op": "note", "id": "n1", "text": "a"}, {"op": "note", "id": "n1", "text": "b"}
    )
    assert [s["nodes"]["n1"]["notes"] for s in r] == [1, 2]
    assert r[0]["eventTypes"] == ["note.appended"]


def test_note_body_not_in_text_or_details():
    secret = "SECRET-TOKEN-123"
    r = play(active(), {"op": "note", "id": "n1", "text": secret}, {"op": "list"})
    for s in r:
        blob = json.dumps(s["result"]["text"]) + json.dumps(s["result"]["details"])
        assert secret not in blob


def test_note_unknown_node_rejected():
    rejected(active(), {"op": "note", "id": "n99", "text": "x"})


def test_note_on_goal_and_done_task_allowed():
    ok(active(), {"op": "note", "id": "g1", "text": "x"})
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "note", "id": "n1", "text": "x"},
    )
    assert r[1]["result"]["ok"]


def test_note_event_is_llm_authored():
    s = one(active(), {"op": "note", "id": "n1", "text": "x"})
    assert s["result"]["events"][0]["data"]["by"] == "llm"


# ── cancel ───────────────────────────────────────────────


def test_cancel_ready():
    s = ok(active(), {"op": "cancel", "id": "n1", "reason": "不要"})
    assert s["nodes"]["n1"]["state"] == "cancelled" and s["eventTypes"] == ["verdict"]


def test_cancel_running_aborts_run_first():
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "in_progress"},
        {"op": "cancel", "id": "n1", "reason": "不要"},
    )
    assert r[1]["eventTypes"] == ["run.ended", "verdict"]


def test_cancel_twice_or_done_rejected():
    r = play(
        active(),
        {"op": "cancel", "id": "n1", "reason": "r"},
        {"op": "cancel", "id": "n1", "reason": "r"},
    )
    assert not r[1]["result"]["ok"]
    r = play(
        active(),
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "cancel", "id": "n1", "reason": "r"},
    )
    assert not r[1]["result"]["ok"]


def test_cancel_goal_rejected():
    assert "task でない" in rejected(active(), {"op": "cancel", "id": "g1", "reason": "r"})


def test_cancel_unknown_rejected():
    rejected(active(), {"op": "cancel", "id": "zz", "reason": "r"})


def test_cancel_proposed_allowed():
    s = ok(draft(task("n1")), {"op": "cancel", "id": "n1", "reason": "r"})
    assert s["nodes"]["n1"]["state"] == "cancelled"


# ── plan ─────────────────────────────────────────────────


def test_plan_proposes_goal_and_tasks_only():
    s = ok(
        [],
        {
            "op": "plan",
            "goal": "目標",
            "tasks": [
                {"title": "a"},
                {"title": "b", "deps": [0]},
                {"title": "c", "deps": [0, 1], "kind": "check"},
            ],
        },
    )
    assert s["eventTypes"] == [
        "goal.created",
        "node.added",
        "node.added",
        "node.added",
        "plan.proposed",
    ]
    assert s["nodes"]["g1"]["state"] == "planned"
    assert all(s["nodes"][i]["state"] == "proposed" for i in ("n2", "n3", "n4"))
    assert s["nodes"]["n4"]["after"] == ["n2", "n3"]
    assert s["result"]["details"]["hash"]
    assert "承認は利用者だけ" in s["result"]["text"]


def test_plan_hash_deterministic_and_content_sensitive():
    a = one([], {"op": "plan", "goal": "g", "tasks": [{"title": "a"}]})["result"]["details"]["hash"]
    b = one([], {"op": "plan", "goal": "g", "tasks": [{"title": "a"}]})["result"]["details"]["hash"]
    c = one([], {"op": "plan", "goal": "g", "tasks": [{"title": "b"}]})["result"]["details"]["hash"]
    assert a == b != c


def test_plan_tasks_cannot_run_until_user_approves():
    r = play(
        [],
        {"op": "plan", "goal": "g", "tasks": [{"title": "a"}]},
        {"op": "set", "id": "n2", "status": "in_progress"},
    )
    assert not r[1]["result"]["ok"]


def test_plan_alongside_existing_goal_gets_new_ids():
    s = ok(active(), {"op": "plan", "goal": "g", "tasks": [{"title": "a"}]})
    assert s["result"]["details"]["goal"] == "g3" and s["result"]["details"]["tasks"] == ["n4"]


def test_plan_max_tasks_accepted():
    ok(
        [],
        {
            "op": "plan",
            "goal": "g",
            "tasks": [{"title": f"t{i}", "deps": [i - 1] if i else []} for i in range(30)],
        },
    )


# ── list ─────────────────────────────────────────────────


def test_list_counts_and_lines():
    r = play(
        active(task("n1", "一つ目"), task("n2", "二つ目"), task("n3", "三つ目")),
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "set", "id": "n2", "status": "in_progress"},
        {"op": "list"},
    )
    c = r[2]["result"]["details"]["counts"]
    assert (c["ready"], c["running"], c["waiting"], c["done"]) == (1, 1, 0, 1)
    t = r[2]["result"]["text"]
    assert "n3 [待機] 三つ目" in t and "n2 [実行] 二つ目" in t and "n1 [完了] 一つ目" in t
    assert r[2]["result"]["events"] == []


def test_list_filter_shows_only_group():
    r = play(
        active(task("n1", "A"), task("n2", "B")),
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "list", "filter": "done"},
    )
    t = r[1]["result"]["text"]
    assert "n1" in t and "n2" not in t.split("\n", 1)[1]


def test_list_caps_each_group_at_ten():
    s = one(active(*[task(f"n{i}", f"t{i}") for i in range(1, 16)]), {"op": "list"})
    t = s["result"]["text"]
    assert t.count("[待機]") == 10 and "ほか 5 件" in t
    assert s["result"]["details"]["counts"]["ready"] == 15


def test_list_empty():
    s = ok([], {"op": "list"})
    assert s["result"]["text"].startswith("ready 0")


def test_list_waiting_group_includes_blocked_and_waiting():
    r = play(
        active(task("n1"), task("n2")),
        {"op": "set", "id": "n1", "status": "blocked"},
        {"op": "add", "title": "w", "wait": {"on": "time", "ref": "t"}},
        {"op": "list"},
    )
    assert r[2]["result"]["details"]["counts"]["waiting"] == 2


def test_list_output_is_capped_and_truncated():
    n = 40
    tasks = [task(f"n{i}", f"{i:02d}" + "x" * 80) for i in range(1, n + 1)]
    steps = [{"op": "set", "id": f"n{i}", "status": "in_progress"} for i in range(1, 12)]
    steps += [{"op": "set", "id": f"n{i}", "status": "done"} for i in range(12, 24)]
    steps += [{"op": "set", "id": f"n{i}", "status": "blocked"} for i in range(24, 36)]
    r = play(active(*tasks), *steps, {"op": "list"})
    t = r[-1]["result"]["text"]
    assert len(t) <= 1500
    assert t.endswith("…（全文は /work）")


def test_list_line_width_clipped():
    s = one(active(task("n1", "あ" * 100)), {"op": "list"})
    line = next(x for x in s["result"]["text"].split("\n") if x.startswith("n1"))
    assert line.endswith("…") and len(line) < 50


def test_text_strips_control_chars_in_titles_from_ledger():
    s = one(active(task("n1", "a\x1b[31mred\nline")), {"op": "list"})
    assert "\x1b" not in s["result"]["text"] and "\nline" not in s["result"]["text"]


# ── 入力の不変・決定性・全体の性質 ─────────────────────────


def test_long_random_session_keeps_invariants():
    ids = [f"n{i}" for i in range(1, 7)]
    steps = [{"op": "add", "title": f"extra{i}"} for i in range(2)]
    steps += [
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "set", "id": "n2", "status": "blocked"},
    ]
    steps += [
        {"op": "cancel", "id": "n3", "reason": "r"},
        {"op": "note", "id": "n4", "text": "x"},
        {"op": "set", "id": "n5", "deps": ["n6"]},
    ]
    steps += [
        {"op": "set", "id": "n6", "deps": ["n5"]},
        {"op": "set", "id": "n2", "status": "pending"},
        {"op": "list"},
    ]
    r = play(active(*[task(i) for i in ids]), *steps)
    assert len(r) == len(steps)


def test_ctx_now_is_used_for_wait_since():
    s = one(active(), {"op": "add", "title": "w", "wait": {"on": "time", "ref": "t"}})
    # since は台帳へ入る (イベントの内容で確かめる)
    ev_wait = next(e for e in s["result"]["events"] if e["type"] == "wait.opened")
    assert ev_wait["data"]["wait"]["since"] == 5000
    s2 = drive(
        {
            "cases": [
                {
                    "setup": active(),
                    "steps": [{"op": "add", "title": "w", "wait": {"on": "time", "ref": "t"}}],
                    "now": 9000,
                }
            ]
        }
    )["cases"][0]["steps"][0]
    assert (
        next(e for e in s2["result"]["events"] if e["type"] == "wait.opened")["data"]["wait"][
            "since"
        ]
        == 9000
    )


def test_user_wait_is_not_auto():
    s = one(
        active(), {"op": "add", "title": "w", "wait": {"on": "user", "ref": "q", "prompt": "確認"}}
    )
    w = next(e for e in s["result"]["events"] if e["type"] == "wait.opened")["data"]["wait"]
    assert w["auto"] is False and w["on"] == "user"


def test_no_user_only_events_in_any_path():
    steps = [
        {"op": "add", "title": "a"},
        {"op": "plan", "goal": "g", "tasks": [{"title": "x"}]},
        {"op": "set", "id": "n1", "status": "done"},
        {"op": "cancel", "id": "n2", "reason": "r"},
        {"op": "add", "title": "w", "wait": {"on": "user", "ref": "q", "prompt": "確認"}},
    ]
    play(active(), *steps)  # play が全 step で USER_ONLY を検査する


# ── todo との対応 ─────────────────────────────────────────

# todo の操作 → work の操作 (docs/spec/work/tool.md の表と同じ。clear は cancel の列)
TODO_MAP = {
    "add": {"op": "add", "title": "T"},
    "set pending": {"op": "set", "id": "n1", "status": "pending"},
    "set in_progress": {"op": "set", "id": "n1", "status": "in_progress"},
    "set done": {"op": "set", "id": "n1", "status": "done"},
    "list": {"op": "list"},
    "clear": {"op": "cancel", "id": "n1", "reason": "clear"},
}


@pytest.mark.parametrize("name", sorted(TODO_MAP))
def test_todo_equivalents_exist(name):
    ok(active(), TODO_MAP[name])


def test_todo_clear_for_all_tasks_is_a_cancel_column():
    ids = ["n1", "n2", "n3"]
    r = play(
        active(*[task(i) for i in ids]),
        *[{"op": "cancel", "id": i, "reason": "clear"} for i in ids],
        {"op": "list"},
    )
    assert r[-1]["result"]["details"]["counts"]["cancelled"] == 3
