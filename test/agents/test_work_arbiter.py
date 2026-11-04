"""継続の調停 (``home/dot_config/pi/harness/work/arbiter.ts``) の純関数の試験。

``test/agents/pi/work_arbiter_driver.mjs`` に JSON を渡して ``arbitrate`` / 提案者を呼ぶ (node の型除去を使うので、
22.18 未満の node では飛ばす)。優先順位表は Python 側に独立した仕様 (``spec``) を持ち、事実の直積と driver の結果を照合する。

see docs/spec/work/arbiter.md
"""

from __future__ import annotations

import copy
import itertools
import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_arbiter_driver.mjs"

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


BASE = {
    "trigger": "settle",
    "mode": "interactive",
    "child": False,
    "outcome": "completed",
    "phase": "idle",
    "compacting": False,
    "userInput": False,
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


def F(**kw):
    """BASE に上書きした事実を作る。キーは ``checkpoint__percent`` のように入れ子を ``__`` で指す"""
    f = copy.deepcopy(BASE)
    for k, v in kw.items():
        ks = k.split("__")
        d = f
        for p in ks[:-1]:
            d = d[p]
        d[ks[-1]] = v
    return f


def settle(**kw):
    return drive({"settle": {"facts": F(**kw)}})["decision"]


def kinds(d, kind):
    return [e for e in d["effects"] if e["kind"] == kind]


# ── 独立した仕様 (優先順位表) ──
def spec(f):
    """(continue, row, wake, compact) を返す。driver の提案者の実装を見ずに表から導く"""
    if f["child"] or f["mode"] != "interactive":
        return (0, 0, 0, 0)
    if f["outcome"] == "aborted":
        return (0, 1, 0, 0)
    if f["compacting"] or f["phase"] in ("compacting", "plan"):
        return (0, 2, 0, 0)
    if f["userInput"]:
        return (0, 3, 0, 0)
    if f["outcome"] == "error":
        return (0, 3, 0, int(f["phase"] == "saving" and f["trigger"] == "settle"))
    if f["streak"] >= f["maxStreak"]:
        return (0, 3, 0, 0)
    settle_ = f["trigger"] == "settle"
    c = f["checkpoint"]
    cands = []
    if settle_ and not c["disabled"]:
        hit = (
            f["phase"] == "idle"
            and not c["cooldown"]
            and c["percent"] is not None
            and c["percent"] >= c["threshold"]
        )
        if f["phase"] == "saving" or (hit and not c["llmStep"]):
            return (0, 4, 0, 1)
        if hit:
            cands.append(4)
    g = f["goal"]
    if g["active"]:
        if f["budgetExhausted"]:
            if g["claim"]:
                cands.append(5)
        elif g["unapproved"] >= 2:
            cands.append(6)
        elif g["claim"] or g["stall"]:
            cands.append(8)
        else:
            cands.append(7)
    t = f["todo"]
    if settle_ and not t["disabled"]:
        if t["doing"]:
            if not t["nudged"]:
                cands.append(7)
        elif t["blocked"] and t["queued"] and not t["nudgedWaiting"]:
            cands.append(7)
    ch = f["children"]
    if ch["failed"] > 0:
        cands.append(6)
    elif ch["newUserWait"]:
        pass
    elif ch["parentStep"]:
        cands.append(7)
    if not settle_:
        cands = [p for p in cands if 5 <= p <= 8]
    if f["budgetExhausted"]:
        cands = [p for p in cands if p in (4, 5)]
    if not cands:
        return (0, 9, 0, 0)
    return (1, min(cands), 0, 0) if settle_ else (0, min(cands), 1, 0)


AXES = [
    ["phase", ["idle", "saving", "compacting", "goal", "plan"]],
    ["outcome", ["completed", "aborted", "error"]],
    ["compacting", [False, True]],
    ["userInput", [False, True]],
    ["trigger", ["settle", "resume"]],
    ["budgetExhausted", [False, True]],
    ["checkpoint.percent", [50, 90]],
    ["checkpoint.llmStep", [True, False]],
    ["todo.doing", [[], ["#1 作業"]]],
    ["todo.blocked", [[], ["#2 待ち"]]],
    ["goal.active", [False, True]],
    ["goal.claim", [False, True]],
    ["goal.unapproved", [0, 2]],
    ["children.failed", [0, 1]],
    ["children.parentStep", [False, True]],
]


def _expand(axes):
    names = [a[0] for a in axes]
    for combo in itertools.product(*[a[1] for a in axes]):
        f = copy.deepcopy(BASE)
        f["todo"]["queued"] = ["#3 未着手"]
        for n, v in zip(names, combo, strict=True):
            d = f
            ks = n.split(".")
            for p in ks[:-1]:
                d = d[p]
            d[ks[-1]] = v
        yield f


def test_priority_table_exhaustive():
    """事実の直積 (約 12 万通り) で、driver の (継続・行・wake・直接圧縮) が独立した仕様と全て一致する"""
    base = copy.deepcopy(BASE)
    base["todo"]["queued"] = ["#3 未着手"]
    rows = drive({"grid": {"base": base, "axes": AXES}})["rows"]
    cases = list(_expand(AXES))
    assert len(rows) == len(cases) > 100_000
    bad = []
    for f, r in zip(cases, rows, strict=True):
        got = (r[0], r[1], r[3], r[5])
        want = spec(f)
        if got != want:
            bad.append((got, want, f))
        # entries は 0 または 1 件。継続したときだけ 1 件、wake があれば entries は無い
        assert r[2] == r[0]
        assert r[2] <= 1
        assert r[3] <= 1
        if r[0]:
            assert 0 < r[4] <= max(600, len(f["checkpoint"]["prompt"]))
    assert not bad, bad[:3]
    assert {r[1] for r in rows} == {
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
    }  # 行 0 (子・print・json) は test_safe_stops


@pytest.mark.parametrize("seed", range(1, 9))
def test_fuzz_properties(seed):
    """乱数の事実で、entries≤1・決定性・入力の不変・安全側・wake の置き場・予算と連続上限を検査する"""
    out = drive({"fuzz": {"seed": seed, "runs": 3000}})
    assert out["bad"] == [], out["bad"][:2]
    assert out["stats"]["continued"] > 100 and out["stats"]["wakes"] > 20


# ── 優先順位: 2 つの提案が同時に当たったときの勝敗 ──
SIDES = {
    "checkpoint": {"checkpoint__percent": 90},
    "todo": {"todo__doing": ["#1 作業"]},
    "goal": {"goal__active": True},
    "goal-claim": {"goal__active": True, "goal__claim": True},
    "goal-triage": {"goal__active": True, "goal__unapproved": 2},
    "children-fail": {"children__failed": 1},
    "children-step": {"children__parentStep": True},
}
ROW = {
    "checkpoint": 4,
    "todo": 7,
    "goal": 7,
    "goal-claim": 8,
    "goal-triage": 6,
    "children-fail": 6,
    "children-step": 7,
}


PAIRS = [(a, b) for a, b in itertools.combinations(SIDES, 2) if a.split("-")[0] != b.split("-")[0]]


@pytest.mark.parametrize("a,b", PAIRS)
def test_pairwise_winner(a, b):
    d = settle(**SIDES[a], **SIDES[b])
    assert d["continue"] is True
    assert len(d["entries"]) == 1
    assert d["row"] == min(ROW[a], ROW[b])


@pytest.mark.parametrize("name", list(SIDES))
def test_single_proposer(name):
    d = settle(**SIDES[name])
    assert d["continue"] is True and d["row"] == ROW[name] and len(d["entries"]) == 1


# ── 安全側の停止 ──
BUSY = {
    "goal__active": True,
    "todo__doing": ["#1 作業"],
    "children__failed": 1,
    "checkpoint__percent": 90,
}


@pytest.mark.parametrize(
    "stop,row",
    [
        ({"outcome": "aborted"}, 1),
        ({"outcome": "error"}, 3),
        ({"compacting": True}, 2),
        ({"phase": "compacting"}, 2),
        ({"phase": "plan"}, 2),
        ({"userInput": True}, 3),
        ({"streak": 10}, 3),
        ({"streak": 11}, 3),
        ({"child": True}, 0),
        ({"mode": "print"}, 0),
        ({"mode": "json"}, 0),
    ],
)
def test_safe_stops(stop, row):
    d = settle(**BUSY, **stop)
    assert d["continue"] is False and d["entries"] == [] and d["row"] == row
    assert kinds(d, "wake") == []


@pytest.mark.parametrize(
    "stop",
    [{"outcome": "aborted"}, {"compacting": True}, {"userInput": True}, {"outcome": "error"}],
)
def test_resume_also_safe(stop):
    d = settle(trigger="resume", **BUSY, **stop)
    assert kinds(d, "wake") == [] and d["continue"] is False


def test_abort_pauses_goal_and_cancels_checkpoint():
    d = settle(outcome="aborted", phase="saving", goal__active=True)
    assert {"kind": "checkpoint", "action": "cancel"} in d["effects"]
    assert any(e["kind"] == "append_event" and e["name"] == "goal.paused" for e in d["effects"])


def test_error_is_notified_not_continued():
    d = settle(outcome="error", goal__active=True)
    n = kinds(d, "notify")
    assert d["continue"] is False and n and n[0]["event"] == "run.failed" and n[0]["show"] == "line"


def test_streak_limit_alerts():
    d = settle(streak=10, goal__active=True)
    n = kinds(d, "notify")
    assert d["continue"] is False and n[0]["show"] == "alert"


# ── 現状 3 者の回帰 (autocheckpoint / todo / goal) ──
def test_autocheckpoint_save_then_compact():
    d = settle(checkpoint__percent=85)
    assert d["continue"] and d["entries"][0]["customType"] == "autocheckpoint"
    assert d["entries"][0]["content"] == "保存してください"
    assert {"kind": "append_event", "name": "checkpoint.saving"} in d["effects"]
    d2 = settle(phase="saving")
    assert d2["continue"] is False and {"kind": "checkpoint", "action": "compact"} in d2["effects"]


def test_autocheckpoint_threshold_and_cooldown():
    assert settle(checkpoint__percent=79)["continue"] is False
    assert settle(checkpoint__percent=80)["continue"] is True
    assert settle(checkpoint__percent=95, checkpoint__cooldown=True)["continue"] is False
    assert settle(checkpoint__percent=95, checkpoint__disabled=True)["continue"] is False
    assert settle(checkpoint__percent=None)["continue"] is False


def test_autocheckpoint_mechanical_compacts_directly():
    d = settle(checkpoint__percent=90, checkpoint__llmStep=False, todo__doing=["#1 作業"])
    assert d["continue"] is False and {"kind": "checkpoint", "action": "compact"} in d["effects"]
    assert d["row"] == 4


def test_autocheckpoint_saving_with_error_still_compacts():
    d = settle(phase="saving", outcome="error")
    assert {"kind": "checkpoint", "action": "compact"} in d["effects"] and d["continue"] is False


def test_todo_in_progress_reminder():
    d = settle(todo__doing=["#1 作業"])
    assert d["continue"] and d["entries"][0]["customType"] == "todo-reminder"
    assert "#1 作業" in d["entries"][0]["content"]
    assert {"kind": "append_event", "name": "todo.nudged"} in d["effects"]
    assert settle(todo__doing=["#1 作業"], todo__nudged=True)["continue"] is False


def test_todo_waiting_and_queued_reminder():
    d = settle(todo__blocked=["#2 待ち"], todo__queued=["#3 未着手"])
    assert d["continue"] and {"kind": "append_event", "name": "todo.nudgedWaiting"} in d["effects"]
    assert (
        settle(todo__blocked=["#2 待ち"], todo__queued=["#3 未着手"], todo__nudgedWaiting=True)[
            "continue"
        ]
        is False
    )
    assert settle(todo__blocked=["#2 待ち"])["continue"] is False
    assert settle(todo__queued=["#3 未着手"])["continue"] is False


def test_todo_disabled_and_noncompleted():
    assert settle(todo__doing=["#1 作業"], todo__disabled=True)["continue"] is False
    assert settle(todo__doing=["#1 作業"], outcome="error")["continue"] is False


def test_goal_continue_claim_stall():
    assert settle(goal__active=True)["row"] == 7
    assert settle(goal__active=True, goal__claim=True)["row"] == 8
    assert settle(goal__active=True, goal__stall=True)["row"] == 8
    assert settle(goal__active=True, goal__unapproved=2)["row"] == 6
    assert settle(goal__active=False, goal__claim=True)["continue"] is False


def test_goal_budget_evaluates_claim_first():
    d = settle(goal__active=True, goal__claim=True, budgetExhausted=True)
    assert d["continue"] and d["row"] == 5
    d = settle(goal__active=True, budgetExhausted=True, todo__doing=["#1 作業"], children__failed=1)
    assert d["continue"] is False
    n = kinds(d, "notify")
    assert n and n[0]["event"] == "budget.paused" and n[0]["show"] == "line"


def test_children_failure_and_wait():
    d = settle(children__failed=2)
    assert d["continue"] and d["row"] == 6 and kinds(d, "notify")[0]["event"] == "run.failed"
    d = settle(children__newUserWait=True)
    assert d["continue"] is False and d["row"] == 9
    n = kinds(d, "notify")
    assert n[0]["event"] == "wait.confirm" and n[0]["show"] == "alert"


def test_three_providers_same_settle_one_entry():
    """C7 の再発: checkpoint・todo・goal が同じ settle で出しても entries は 1 件で、置換で上書きされない"""
    d = settle(checkpoint__percent=90, todo__doing=["#1 作業"], goal__active=True)
    assert len(d["entries"]) == 1 and d["row"] == 4
    assert d["entries"][0]["customType"] == "autocheckpoint"
    assert "作業中" not in d["entries"][0]["content"]


def test_lower_rows_are_merged_not_replaced():
    d = settle(
        todo__doing=["#1 作業"], goal__active=True, goal__claim=True, children__parentStep=True
    )
    assert len(d["entries"]) == 1
    c = d["entries"][0]["content"]
    assert "作業中" in c and "完了の申告" in c and "子が完了" in c and len(c) <= 600
    # 取り込まれた提案の効果 (todo の nudged) も残る
    assert {"kind": "append_event", "name": "todo.nudged"} in d["effects"]


def test_merge_is_clipped():
    long = [f"#{i} " + "あ" * 80 for i in range(1, 12)]
    d = settle(todo__doing=long, goal__active=True)
    assert len(d["entries"]) == 1 and len(d["entries"][0]["content"]) <= 600


# ── 再開 (圧縮の完了後)・wake の置き場 ──
def test_resume_wakes_only_with_work():
    d = settle(trigger="resume", goal__active=True)
    w = kinds(d, "wake")
    assert d["continue"] is False and d["entries"] == [] and len(w) == 1 and d["row"] == 7
    d = settle(trigger="resume", children__newUserWait=True)
    assert kinds(d, "wake") == [] and d["row"] == 9
    assert kinds(settle(trigger="resume", todo__doing=["#1 作業"]), "wake") == []
    assert kinds(settle(trigger="resume", checkpoint__percent=95), "wake") == []


def test_wake_not_present_on_settle():
    d = settle(goal__active=True, todo__doing=["#1 作業"], children__failed=1)
    assert d["continue"] and kinds(d, "wake") == []


def test_provider_cannot_emit_wake():
    prop = {
        "by": "todo",
        "want": "continue",
        "priority": 7,
        "entry": {"customType": "x", "content": "c"},
        "effects": [{"kind": "wake", "content": "w"}, {"kind": "append_event", "name": "n"}],
        "reason": "r",
    }
    d = drive({"arbitrate": {"facts": F(), "proposals": [prop]}})["decision"]
    assert d["continue"] and kinds(d, "wake") == [] and len(d["entries"]) == 1


# ── 不正な入力は閉じる ──
@pytest.mark.parametrize(
    "facts",
    [
        None,
        {},
        {**BASE, "trigger": "x"},
        {**BASE, "streak": None},
        {**BASE, "phase": "zzz"},
        {**BASE, "outcome": None},
        {**BASE, "mode": 1},
    ],
)
def test_bad_facts_close(facts):
    d = drive({"arbitrate": {"facts": facts, "proposals": []}})["decision"]
    assert d["continue"] is False and d["entries"] == []


def _p(**kw):
    p = {
        "by": "todo",
        "want": "continue",
        "priority": 7,
        "entry": {"customType": "x", "content": "c"},
        "effects": [],
        "reason": "r",
    }
    p.update(kw)
    return p


def test_proposal_without_entry_is_ignored():
    d = drive({"arbitrate": {"facts": F(), "proposals": [_p(entry=None)]}})["decision"]
    assert d["continue"] is False and d["row"] == 9


def test_unknown_notice_closes():
    bad = _p(want="alert", effects=[{"kind": "notify", "event": "no.such", "text": "t"}])
    d = drive({"arbitrate": {"facts": F(), "proposals": [bad]}})["decision"]
    assert d["continue"] is False and d["entries"] == []


def test_bad_priority_ignored():
    d = drive({"arbitrate": {"facts": F(), "proposals": [_p(priority=None)]}})["decision"]
    assert d["continue"] is False


def test_tie_prefers_earlier_proposal():
    ps = [
        _p(by="goal", entry={"customType": "first", "content": "1"}),
        _p(entry={"customType": "second", "content": "2"}),
    ]
    d = drive({"arbitrate": {"facts": F(), "proposals": ps}})["decision"]
    assert d["entries"][0]["customType"] == "first" and d["entries"][0]["content"] == "1\n2"


def test_stay_compact_beats_continue():
    ps = [
        _p(),
        _p(
            want="stay",
            priority=4,
            entry=None,
            effects=[{"kind": "checkpoint", "action": "compact"}],
        ),
    ]
    d = drive({"arbitrate": {"facts": F(), "proposals": ps}})["decision"]
    assert d["continue"] is False and d["entries"] == [] and d["row"] == 4


def test_conflicting_continue_and_stay_is_unique():
    """continue を望む提案と stay を望む提案が同時にあっても、表で一意に決まる (continue が勝つ。stay は効果だけ)"""
    ps = [
        _p(want="stay", priority=7, entry=None, effects=[{"kind": "append_event", "name": "s"}]),
        _p(),
    ]
    d1 = drive({"arbitrate": {"facts": F(), "proposals": ps}})["decision"]
    d2 = drive({"arbitrate": {"facts": F(), "proposals": ps[::-1]}})["decision"]
    assert d1["continue"] is True and d2["continue"] is True and len(d1["entries"]) == 1
    assert d1["entries"] == d2["entries"]


# ── 通知は select を通る ──
@pytest.mark.parametrize(
    "kw,event,show",
    [
        ({"outcome": "error"}, "run.failed", "line"),
        ({"streak": 10}, "goal.stopped", "alert"),
        ({"children__newUserWait": True}, "wait.confirm", "alert"),
        ({"goal__active": True, "budgetExhausted": True}, "budget.paused", "line"),
        ({"children__failed": 1}, "run.failed", "line"),
        ({"checkpoint__percent": 90}, "autosave", "line"),
        ({"checkpoint__percent": 90, "checkpoint__llmStep": False}, "autosave", "silent"),
    ],
)
def test_notices_go_through_select(kw, event, show):
    n = [e for e in kinds(settle(**kw), "notify") if e["event"] == event]
    assert n and all(e["show"] == show and e["why"] for e in n)


# ── 純関数性 ──
def test_deterministic_and_input_untouched():
    f = F(todo__doing=["#1 作業"], goal__active=True)
    a = drive({"settle": {"facts": f}})
    b = drive({"settle": {"facts": f}})
    assert a == b


def test_batch_matches_single():
    cases = [F(todo__doing=["#1 作業"]), F(goal__active=True), F(userInput=True)]
    batch = drive({"batch": [{"settle": {"facts": c}} for c in cases]})["results"]
    assert [b["decision"] for b in batch] == [
        drive({"settle": {"facts": c}})["decision"] for c in cases
    ]
