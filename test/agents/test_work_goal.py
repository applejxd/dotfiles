"""`/goal` の台帳への接着 (``home/dot_config/pi/harness/work/goal.ts``) の試験。

``test/agents/pi/work_goal_driver.mjs`` に JSON を渡して、コマンド → 利用者専用イベントの変換・導出・差分試験を呼ぶ
(node の型除去を使うので、22.18 未満の node では飛ばす)。

see docs/spec/work/goal.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_goal_driver.mjs"

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


def run(*cmds):
    return drive({"run": {"cmds": list(cmds)}})["steps"]


def types(step):
    return [e["type"] for e in step["events"]]


# ── コマンドごとの変換 ──
def test_set_emits_created_proposed_approved_as_user():
    s = run("調査して直す")[0]
    assert s["ok"]
    assert types(s) == ["goal.created", "plan.proposed", "plan.approved"]
    assert {e["source"] for e in s["events"]} == {"user"}


def test_set_derives_active_goal_with_default_budget():
    g = run("調査して直す")[0]["goal"]
    assert g["status"] == "active"
    assert g["text"] == "調査して直す"
    assert g["budget"] == {"rounds": 20, "minutes": 90}
    assert g["audit"] is False


def test_set_with_budget_flags():
    g = run("--rounds 5 --minutes 30 --tokens 2k 作業")[0]["goal"]
    assert g["budget"] == {"rounds": 5, "minutes": 30, "tokens": 2000}


def test_set_with_audit():
    assert run("--audit 作業")[0]["goal"]["audit"] is True


def test_set_ledger_budget_is_finite_money():
    s = run("作業")[0]
    created = s["events"][0]["data"]["budget"]
    assert created["ms"] == 90 * 60_000
    assert created["rounds"] == 20
    assert all(
        isinstance(created[k], (int, float)) and created[k] < float("inf")
        for k in ("usd", "tokens", "ms", "rounds")
    )


def test_set_id_derives_from_now():
    g = run("作業")[0]["goal"]
    assert g["id"] == "g-" + base36(1000)
    assert g["createdAt"] == 1000


def base36(n):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out or "0"


def test_status_without_goal_emits_no_events():
    s = run("")[0]
    assert s["ok"] and s["events"] == []
    assert "目標はありません" in s["text"]


def test_status_with_goal_emits_no_events_and_text():
    s = run("作業", "status")[1]
    assert s["ok"] and s["events"] == []
    assert "作業" in s["text"] and "active" in s["text"]


def test_status_blank_equals_status():
    assert run("作業", "")[1]["text"] == run("作業", "status")[1]["text"]


def test_pause_emits_goal_paused_as_user():
    s = run("作業", "pause")[1]
    assert types(s) == ["goal.paused"]
    assert s["events"][0]["source"] == "user"
    assert s["goal"]["status"] == "paused"
    assert s["goal"]["pause"] == {"reason": "user"}


def test_pause_twice_is_noop():
    s = run("作業", "pause", "pause")[2]
    assert s["ok"] and s["events"] == []
    assert s["goal"]["status"] == "paused"


def test_resume_emits_goal_resumed_as_user():
    s = run("作業", "pause", "resume")[2]
    assert types(s) == ["goal.resumed"]
    assert s["events"][0]["source"] == "user"
    assert s["goal"]["status"] == "active"
    assert s["goal"]["lifetime"]["resumes"] == 1
    assert "pause" not in s["goal"]


def test_resume_active_is_noop():
    s = run("作業", "resume")[1]
    assert s["ok"] and s["events"] == []
    assert s["goal"]["lifetime"]["resumes"] == 0


def test_resume_counts_accumulate():
    g = run("作業", "pause", "resume", "pause", "resume")[4]["goal"]
    assert g["lifetime"]["resumes"] == 2


def test_budget_emits_budget_adjusted_as_user():
    s = run("作業", "budget --rounds 7")[1]
    assert types(s) == ["budget.adjusted"]
    assert s["events"][0]["source"] == "user"
    assert s["goal"]["budget"] == {"rounds": 7, "minutes": 90}


def test_budget_merges_partial_axes():
    g = run("--minutes 10 作業", "budget --rounds 3", "budget --tokens 5k")[2]["goal"]
    assert g["budget"] == {"rounds": 3, "minutes": 10, "tokens": 5000}


def test_budget_while_paused():
    g = run("作業", "pause", "budget --minutes 5")[2]["goal"]
    assert g["status"] == "paused" and g["budget"]["minutes"] == 5


def test_budget_without_goal_fails():
    s = run("budget --rounds 3")[0]
    assert not s["ok"] and s["events"] == [] and s["error"]


def test_clear_cancels_goal_and_derives_null():
    s = run("作業", "clear")[1]
    assert types(s) == ["verdict"]
    assert s["events"][0]["data"]["verdict"] == "cancel"
    assert s["events"][0]["source"] == "user"
    assert s["goal"] is None


def test_clear_without_goal_is_noop():
    s = run("clear")[0]
    assert s["ok"] and s["events"] == []


def test_clear_paused_goal():
    assert run("作業", "pause", "clear")[2]["goal"] is None


def test_set_after_clear_makes_new_goal():
    steps = run("一つ目", "clear", "二つ目")
    assert steps[2]["ok"]
    assert steps[2]["goal"]["text"] == "二つ目"
    assert steps[2]["goal"]["lifetime"]["resumes"] == 0


def test_set_while_goal_exists_fails():
    s = run("一つ目", "二つ目")[1]
    assert not s["ok"] and s["events"] == []
    assert s["goal"]["text"] == "一つ目"


def test_set_while_paused_goal_exists_fails():
    assert not run("一つ目", "pause", "二つ目")[2]["ok"]


def test_draft_emits_no_events_and_returns_memo():
    s = run("draft メモ")[0]
    assert s["ok"] and s["events"] == [] and s["draft"] == "メモ"
    assert s["goal"] is None


def test_goal_state_is_null_without_goal():
    assert run("status")[0]["goal"] is None


# ── 検査と error ──
@pytest.mark.parametrize(
    "args",
    [
        "--rounds 0 x",
        "--rounds 201 x",
        "--minutes 0 x",
        "--minutes 1441 x",
        "--tokens 0 x",
        "--rounds abc x",
        "--rounds x",
    ],
)
def test_set_rejects_out_of_range_budget(args):
    s = run(args)[0]
    assert not s["ok"] and s["events"] == [] and s["error"]
    assert s["goal"] is None


@pytest.mark.parametrize(
    "args",
    [
        "budget --rounds 0",
        "budget --rounds 201",
        "budget --minutes 1441",
        "budget --tokens 1000000001",
    ],
)
def test_budget_rejects_out_of_range_and_keeps_state(args):
    steps = run("作業", args)
    assert not steps[1]["ok"] and steps[1]["events"] == []
    assert steps[1]["goal"]["budget"] == {"rounds": 20, "minutes": 90}


@pytest.mark.parametrize(
    "args",
    [
        "--bogus x",
        "--rounds 3 --bogus x",
        "-x 作業",
        "budget --audit",
        "budget",
        "budget extra",
        "pause now",
    ],
)
def test_unknown_flags_return_parse_error_as_is(args):
    steps = run("作業", args)
    parsed = steps[1]["cmd"]
    assert parsed["kind"] == "error"
    assert steps[1]["ok"] is False
    assert steps[1]["error"] == parsed["message"]
    assert steps[1]["events"] == []


def test_empty_goal_text_is_error():
    assert run("--rounds 3")[0]["error"] == "目標が空です"


def test_too_long_text_is_error():
    s = run("あ" * 1501)[0]
    assert not s["ok"] and "長すぎ" in s["error"]


def test_reserved_word_without_dashdash_is_error():
    assert not run("status 作業")[0]["ok"]


def test_dashdash_allows_reserved_word_text():
    g = run("-- status を調べる")[0]
    assert g["ok"] and g["goal"]["text"] == "status を調べる"


def test_budget_tokens_can_shrink_when_nothing_reserved():
    # 予約済みの下回りは、子の run を立てる配線後の統合試験で見る (ここでは予約が 0)
    out = run("--tokens 100 作業", "budget --tokens 50")
    assert out[1]["ok"] and out[1]["goal"]["budget"]["tokens"] == 50


# ── モデル・system の出所 ──
@pytest.fixture(scope="module")
def model():
    return drive({"model": True})


@pytest.mark.parametrize("src", ["model", "system"])
@pytest.mark.parametrize("etype", ["plan.approved", "budget.adjusted", "goal.resumed"])
def test_non_user_source_cannot_make_user_only_events(model, src, etype):
    msg = model[src][etype]
    assert msg.startswith("EventError") and "利用者専用" in msg


def test_model_created_goal_is_not_active(model):
    assert model["modelPlanned"] == {"state": "planned", "derived": None}


def test_reducer_rejects_model_plan_approval(model):
    assert model["reduceModelApproved"].startswith("ReduceError")


def test_reducer_rejects_model_resume_and_goal_stays_paused(model):
    assert model["reduceModelResume"].startswith("ReduceError")
    assert model["pausedAfter"] == "paused"


def test_converter_emits_only_user_source():
    steps = run("作業", "pause", "resume", "budget --rounds 5", "clear")
    for s in steps:
        assert all(e["source"] == "user" for e in s["events"])


# ── 差分試験: goal-core 直接 ≡ 変換 → reduce → 導出 ──
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_differential_against_goal_core(seed):
    r = drive({"diff": {"seed": seed, "runs": 220, "steps": 16}})
    assert r["nMismatch"] == 0, r["mismatches"]
    assert r["compared"] >= 1000
    for k in ("set", "pause", "resume", "budget", "clear"):
        assert r["applied"][k] > 0, r["applied"]


def test_differential_has_enough_command_sequences():
    r = drive({"diff": {"seed": 99, "runs": 220, "steps": 16}})
    assert r["nMismatch"] == 0, r["mismatches"]
    assert r["applied"]["rejected"] > 0


# ── 入力を変更せず決定的 ──
def test_pure_and_deterministic():
    cmds = [
        "作業",
        "status",
        "pause",
        "pause",
        "resume",
        "budget --rounds 4",
        "budget --rounds 0",
        "draft x",
        "clear",
        "clear",
    ]
    res = drive({"pure": {"cmds": cmds}})["res"]
    assert len(res) == len(cmds)
    assert all(r["same"] and r["unchanged"] and r["gsSame"] for r in res)


# ── arbiter の Facts の goal 部分 ──
def facts(cmds, **f):
    return drive({"facts": {"cmds": cmds, "facts": f}})


def test_facts_inactive_without_goal():
    r = facts([], claim=True)
    assert r == {
        "goal": {"active": False, "claim": False, "stall": False, "unapproved": 0},
        "budgetExhausted": False,
    }


def test_facts_inactive_when_paused():
    assert facts(["作業", "pause"], claim=True)["goal"]["active"] is False


def test_facts_active_passes_claim():
    r = facts(["作業"], claim=True)
    assert r["goal"] == {"active": True, "claim": True, "stall": False, "unapproved": 0}
    assert r["budgetExhausted"] is False


def test_facts_stall_and_unapproved_override():
    r = facts(["作業"], claim=False, stall=True, unapproved=2)
    assert r["goal"]["stall"] is True and r["goal"]["unapproved"] == 2


def test_facts_stall_from_counters():
    rt = {"counters": {"noTool": 2, "same": 0, "unapproved": 1, "evalFail": 0, "sameReason": 0}}
    r = facts(["作業"], claim=False, rt=rt)
    assert r["goal"]["stall"] is True and r["goal"]["unapproved"] == 1


def test_facts_budget_exhausted_by_rounds():
    rt = {"used": {"rounds": 3, "runMs": 0, "tokens": 0, "evalCalls": 0, "evalTokens": 0}}
    assert facts(["--rounds 3 作業"], claim=False, rt=rt)["budgetExhausted"] is True


def test_facts_budget_not_exhausted_below_limit():
    rt = {"used": {"rounds": 2, "runMs": 0, "tokens": 0, "evalCalls": 0, "evalTokens": 0}}
    assert facts(["--rounds 3 作業"], claim=False, rt=rt)["budgetExhausted"] is False


def test_facts_budget_exhausted_by_minutes_and_tokens():
    used = {"rounds": 0, "runMs": 60_000, "tokens": 0, "evalCalls": 0, "evalTokens": 0}
    assert facts(["--minutes 1 作業"], claim=False, rt={"used": used})["budgetExhausted"] is True
    used = {"rounds": 0, "runMs": 0, "tokens": 1000, "evalCalls": 0, "evalTokens": 0}
    assert facts(["--tokens 1000 作業"], claim=False, rt={"used": used})["budgetExhausted"] is True


# ── pauseReason・rounds・goal cancel の出所 (台帳の核との食い違いの解消) ──
def raw(*events):
    return drive({"raw": {"events": list(events)}})


def _active():
    b = {"usd": 5, "tokens": 5000, "ms": 600000, "rounds": 7}
    return [
        {
            "type": "goal.created",
            "node": "g1",
            "data": {"title": "x", "budget": b},
            "source": "user",
        },
        {"type": "plan.proposed", "node": "g1", "data": {"hash": "h"}, "source": "user"},
        {"type": "plan.approved", "node": "g1", "data": {"hash": "h"}, "source": "user"},
    ]


@pytest.mark.parametrize(
    "reason", ["rounds", "minutes", "tokens", "stalled", "blocked", "unapproved"]
)
def test_paused_reason_is_derived_from_ledger(reason):
    out = raw(
        *_active(),
        {"type": "goal.paused", "node": "g1", "data": {"reason": reason}, "source": "system"},
    )
    assert out["goal"]["status"] == "paused"
    assert out["goal"]["pause"]["reason"] == reason


def test_resume_clears_derived_pause():
    out = raw(
        *_active(),
        {"type": "goal.paused", "node": "g1", "data": {"reason": "rounds"}, "source": "system"},
        {"type": "goal.resumed", "node": "g1", "data": {}, "source": "user"},
    )
    assert out["goal"]["status"] == "active"
    assert "pause" not in out["goal"]


def test_user_pause_command_derives_user_reason():
    s = run("調査", "pause")[1]
    assert s["goal"]["pause"]["reason"] == "user"


def test_derived_budget_rounds_comes_from_ledger_money():
    out = raw(*_active())
    assert out["goal"]["budget"]["rounds"] == 7
    assert out["node"]["budget"]["rounds"] == 7


def test_model_goal_cancel_is_rejected_and_goal_stays_active():
    out = raw(
        *_active(),
        {
            "type": "verdict",
            "node": "g1",
            "data": {"verdict": "cancel", "reason": "r"},
            "source": "model",
        },
    )
    assert out["steps"][-1]["ok"] is False
    assert "I10" in out["steps"][-1]["error"]
    assert out["goal"]["status"] == "active"


def test_user_goal_cancel_derives_null():
    out = raw(
        *_active(),
        {
            "type": "verdict",
            "node": "g1",
            "data": {"verdict": "cancel", "reason": "r"},
            "source": "user",
        },
    )
    assert out["steps"][-1]["ok"] is True
    assert out["goal"] is None


# ── /goal approve (active / paused の再承認) ──
APPROVE = {"kind": "approve"}


def late(title="後から"):
    return {"task": title}


def test_approve_active_with_late_task_emits_user_plan_approved():
    s = run("作業", late(), APPROVE)[2]
    assert s["ok"] and types(s) == ["plan.approved"]
    assert {e["source"] for e in s["events"]} == {"user"}
    assert s["approval"] == {"total": 1, "titles": ["後から"]}


def test_approve_active_keeps_goal_active():
    s = run("作業", late(), APPROVE)[2]
    assert s["goal"]["status"] == "active"


def test_approve_paused_with_late_task_ok():
    s = run("作業", "pause", late(), APPROVE)[3]
    assert s["ok"] and types(s) == ["plan.approved"]
    assert s["goal"]["status"] == "paused"


def test_approve_active_without_task_fails():
    s = run("作業", APPROVE)[1]
    assert not s["ok"] and s["events"] == []
    assert "承認待ちの計画はありません" in s["error"]


def test_approve_paused_without_task_fails():
    s = run("作業", "pause", APPROVE)[2]
    assert not s["ok"] and s["events"] == []


def test_approve_without_goal_fails():
    s = run(APPROVE)[0]
    assert not s["ok"] and s["events"] == []


def test_approve_after_clear_fails():
    s = run("作業", late(), "clear", APPROVE)[3]
    assert not s["ok"]


def test_approve_twice_second_fails():
    s = run("作業", late(), APPROVE, APPROVE)[3]
    assert not s["ok"] and s["events"] == []


def test_approve_late_task_after_approve_needs_new_approval():
    steps = run("作業", late("一つ目"), APPROVE, late("二つ目"), APPROVE)
    assert steps[4]["ok"] and steps[4]["approval"] == {"total": 1, "titles": ["二つ目"]}


def test_approve_lists_at_most_ten_titles_and_total():
    steps = run("作業", *[{"task": f"t{i:02d}", "id": f"x{i}"} for i in range(12)], APPROVE)
    a = steps[-1]["approval"]
    assert a["total"] == 12 and len(a["titles"]) == 10
    assert a["titles"][0] == "t00"


def test_approve_lists_all_titles_when_few():
    steps = run("作業", late("A"), {"task": "B", "id": "xb"}, APPROVE)
    assert steps[-1]["approval"] == {"total": 2, "titles": ["A", "B"]}


def test_approve_does_not_change_other_commands():
    # 既存コマンドの変換は変わらない (approve の追加で status の出力が崩れない)
    s = run("作業", "status")[1]
    assert s["ok"] and s["events"] == []
