"""調停の接着層 (``home/dot_config/pi/harness/work/settle.ts``) の試験。

``test/agents/pi/work_settle_driver.mjs`` が偽の pi・偽の ctx に登録し、ハンドラを呼ぶ。
``arbiter.ts`` の直接呼び出し (driver が別に組んだ事実) と結果が一致すること、
登録の条件・べき等・entries の保持・effects の扱い・例外で継続しないこと・journal への記録を確かめる。

see docs/spec/work/settle.md
"""

from __future__ import annotations

import copy
import itertools
import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_settle_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


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


SNAP = {
    "phase": "idle",
    "streak": 0,
    "maxStreak": 10,
    "budgetExhausted": False,
    "checkpoint": {
        "percent": 10,
        "threshold": 80,
        "cooldown": False,
        "llmStep": True,
        "disabled": False,
        "prompt": "保存してください",
    },
    "todo": {
        "disabled": False,
        "doing": [],
        "blocked": [],
        "queued": [],
        "nudged": False,
        "nudgedWaiting": False,
    },
    "goal": {"active": False, "claim": False, "stall": False, "unapproved": 0},
    "children": {"failed": 0, "parentStep": False, "newUserWait": False},
}
ON = {"enabled": True, "child": False}
PREV = [
    {
        "type": "custom_message",
        "customType": "前",
        "content": "前のハンドラの entries",
        "display": True,
    }
]


def snap(**kw):
    s = copy.deepcopy(SNAP)
    for k, v in kw.items():
        ks = k.split("__")
        d = s
        for p in ks[:-1]:
            d = d[p]
        d[ks[-1]] = v
    return s


def case(snapshot=None, opts=ON, event=None, ctx=None, **kw):
    return {
        "opts": opts,
        "snapshot": snapshot or snap(),
        "event": event or {},
        "ctx": ctx or {},
        **kw,
    }


def one(**kw):
    return drive({"cases": [case(**kw)]})["results"][0]


# --- 登録の条件 ---


@pytest.mark.parametrize(
    "opts",
    [
        {"enabled": False, "child": False},
        {"enabled": False, "child": True},
        {"enabled": True, "child": True},
    ],
)
def test_not_registered(opts):
    r = one(opts=opts)
    assert r["registered"] == [False, None]
    assert r["handlers"] == []


def test_registered_once_on_agent_before_settle():
    r = one()
    assert r["registered"] == [True, None]
    assert r["handlers"] == ["agent_before_settle"]


def test_idempotent_two_calls_one_handler():
    r = one(twice=True)
    assert r["registered"] == [True, True]
    assert r["handlers"] == ["agent_before_settle"]


# --- 調停の結果が arbiter.ts の直接呼び出しと一致 (表) ---

TODO_DOING = {"doing": ["#1 作業中"], "queued": ["#2 次"]}
GRID = [
    (outcome, phase, pending, high, todo)
    for outcome, phase, pending, high, todo in itertools.product(
        ["completed", "aborted", "error"],
        ["idle", "saving", "goal"],
        [False, True],
        [False, True],
        [False, True],
    )
]


def _grid_case(p):
    outcome, phase, pending, high, todo = p
    s = snap(
        phase=phase,
        checkpoint__percent=95 if high else 10,
        **({"todo__doing": ["#1 作業中"]} if todo else {}),
    )
    return case(snapshot=s, event={"outcome": outcome, "entries": PREV}, ctx={"pending": pending})


_GRID_RESULTS = None


def grid_results():
    global _GRID_RESULTS
    if _GRID_RESULTS is None:
        _GRID_RESULTS = drive({"cases": [_grid_case(p) for p in GRID]})["results"]
    return _GRID_RESULTS


def check_matches(r, prev):
    d = r["direct"]
    if d["continue"]:
        assert r["result"] == {"entries": prev + d["entries"], "continue": True}
    else:
        assert r["result"] == {}
    c = r["calls"]
    fx = d["effects"]
    assert [x for x in c["wake"]] == [
        [x["content"], {"customType": x["customType"], "why": x["why"]}]
        for x in fx
        if x["kind"] == "wake"
    ]
    assert c["notify"] == [[x["show"], x["text"]] for x in fx if x["kind"] == "notify"]
    assert c["checkpoint"] == [x["action"] for x in fx if x["kind"] == "checkpoint"]
    assert len(c["submit"]) == len([x for x in fx if x["kind"] == "append_event"])
    assert len(c["journal"]) == 1


@pytest.mark.parametrize("i", range(len(GRID)))
def test_matches_arbiter(i):
    check_matches(grid_results()[i], PREV)


def test_grid_is_wide_enough_and_varied():
    rs = grid_results()
    assert len(rs) >= 30
    assert any(r["direct"]["continue"] for r in rs)
    assert any(not r["direct"]["continue"] for r in rs)
    assert len({r["direct"]["row"] for r in rs}) >= 4


# --- entries の保持 ---


def test_entries_preserve_previous_and_append_own():
    r = one(snapshot=snap(todo__doing=["#1 作業中"]), event={"entries": PREV})
    assert r["result"]["continue"] is True
    assert r["result"]["entries"][0] == PREV[0]
    assert len(r["result"]["entries"]) == 2
    assert r["result"]["entries"][1]["customType"] == "todo-reminder"


def test_entries_without_previous():
    r = one(snapshot=snap(todo__doing=["#1 作業中"]))
    assert len(r["result"]["entries"]) == 1 and r["result"]["continue"] is True


def test_no_continue_returns_empty_not_replacing_previous():
    r = one(event={"entries": PREV})
    assert r["result"] == {}


# --- wake・notify の経路 ---


def test_wake_never_called_in_settle():
    rs = grid_results()
    assert all(r["calls"]["wake"] == [] for r in rs)
    assert all(r["pi"] == {"send": 0, "trigger": 0} for r in rs)


def test_wake_only_via_effects():
    out = drive(
        {"effects": [{"kind": "wake", "content": "起きて", "customType": "x", "why": "w"}]}
    )["calls"]
    assert out["wake"] == [["起きて", {"customType": "x", "why": "w"}]]


def test_wake_at_most_once_per_effects():
    w = {"kind": "wake", "content": "a", "customType": "x", "why": "w"}
    assert len(drive({"effects": [w, w, w]})["calls"]["wake"]) == 1


def test_notify_uses_select_unknown_event_dropped():
    out = drive(
        {"effects": [{"kind": "notify", "event": "bogus.event", "show": "line", "text": "x"}]}
    )["calls"]
    assert out["notify"] == []


def test_notify_known_event_passes():
    out = drive(
        {"effects": [{"kind": "notify", "event": "autosave", "show": "line", "text": "保存"}]}
    )["calls"]
    assert out["notify"] == [["line", "保存"]]


def test_effects_append_and_checkpoint():
    fx = [
        {"kind": "append_event", "name": "goal.paused", "data": {"reason": "aborted"}},
        {"kind": "checkpoint", "action": "cancel"},
    ]
    out = drive({"effects": fx})["calls"]
    assert out["checkpoint"] == ["cancel"]
    assert out["submit"][0][0]["data"] == {"reason": "aborted"}
    assert out["submit"][0][0]["type"] == "goal.paused"


def test_effects_failure_does_not_stop_others():
    out = drive(
        {
            "effects": [
                {"kind": "notify", "event": "x.y", "show": "line", "text": "t"},
                {"kind": "checkpoint", "action": "compact"},
            ]
        }
    )["calls"]
    assert out["checkpoint"] == ["compact"]


def test_notify_goes_through_handler_for_error():
    r = one(event={"outcome": "error"})
    assert r["calls"]["notify"] == [["line", "エラー応答"]]


def test_budget_exhausted_alert_notifies():
    r = one(snapshot=snap(budgetExhausted=True, goal__active=True))
    assert any(n[1] == "予算が尽きた" for n in r["calls"]["notify"])
    assert r["result"] == {}


# --- 安全側 ---


@pytest.mark.parametrize("outcome", ["aborted", "error"])
def test_bad_outcome_no_continue(outcome):
    r = one(snapshot=snap(todo__doing=["#1 x"]), event={"outcome": outcome})
    assert r["result"] == {}


def test_compacting_no_continue_snapshot():
    snapshot = snap(todo__doing=["#1 x"])
    snapshot["compacting"] = True
    assert one(snapshot=snapshot)["result"] == {}


def test_compacting_no_continue_ctx():
    assert one(snapshot=snap(todo__doing=["#1 x"]), ctx={"compacting": True})["result"] == {}


def test_compacting_phase_no_continue():
    assert one(snapshot=snap(phase="compacting", todo__doing=["#1 x"]))["result"] == {}


def test_user_input_no_continue():
    assert one(snapshot=snap(todo__doing=["#1 x"]), ctx={"pending": True})["result"] == {}


@pytest.mark.parametrize("mode", ["print", "json"])
def test_print_json_no_continue(mode):
    assert one(snapshot=snap(todo__doing=["#1 x"]), ctx={"mode": mode})["result"] == {}


def test_streak_limit_no_continue():
    assert one(snapshot=snap(streak=10, todo__doing=["#1 x"]))["result"] == {}


def test_snapshot_throw_returns_empty():
    r = one(fail={"snapshot": True})
    assert r["result"] == {}
    assert r["calls"]["journal"] == []


def test_journal_throw_does_not_break_continue():
    r = one(snapshot=snap(todo__doing=["#1 x"]), fail={"journal": True})
    assert r["result"]["continue"] is True


def test_no_runtime_no_journal_ok():
    r = one(snapshot=snap(checkpoint__percent=95), noRuntime=True, noJournal=True)
    assert r["result"]["continue"] is True


# --- journal ---


def test_journal_records_outcome_and_winner():
    r = one(snapshot=snap(todo__doing=["#1 x"]))
    ((typ, data),) = r["calls"]["journal"]
    assert typ == "settle"
    assert (
        data["continue"] is True
        and data["by"] == "todo-reminder"
        and data["outcome"] == "completed"
    )
    assert data["source"] == "arbiter" and isinstance(data["why"], str) and data["row"] == 7


def test_journal_records_error_outcome():
    r = one(event={"outcome": "error"})
    assert r["calls"]["journal"][0][1]["outcome"] == "error"
    assert r["calls"]["journal"][0][1]["continue"] is False


# --- 1 回の settle で起こしは高々 1 回 ---


def test_checkpoint_beats_todo_single_entry():
    r = one(snapshot=snap(checkpoint__percent=95, todo__doing=["#1 x"]))
    assert len(r["result"]["entries"]) == 1
    assert r["result"]["entries"][0]["customType"] == "autocheckpoint"


def test_at_most_one_wake_or_send_per_settle():
    for r in grid_results():
        assert r["pi"]["send"] + r["pi"]["trigger"] == 0
        assert len(r["calls"]["wake"]) <= 1
        assert len(r["result"].get("entries", [])) <= len(PREV) + 1


def test_saving_phase_compacts_via_checkpoint_effect():
    r = one(snapshot=snap(phase="saving"))
    assert r["calls"]["checkpoint"] == ["compact"]
    assert r["result"] == {}
