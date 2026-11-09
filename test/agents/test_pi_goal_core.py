"""`/goal` の中核 (``home/dot_config/pi/harness/goal-core.ts``) の純関数の表駆動の試験。

``test/agents/pi/goal_core_driver.mjs`` に JSON を渡して関数を呼ぶ (node の型除去を使うので、22.18 未満の node では飛ばす)。
driver は引数を deep freeze して渡すので、入力の状態を変更する実装は失敗する (状態の不変性の試験を兼ねる)。

see docs/change/closed/0062-pr-hub-simplify.md (goal-core の履歴は docs/change-history/0062.md)
"""

from __future__ import annotations

import copy
import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "goal_core_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def drive(payload):
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(proc.stdout)


def call(fn, *args):
    return drive({"calls": [{"fn": fn, "args": list(args)}]})["results"][0]


def chain(state, steps):
    return drive({"chain": {"state": state, "steps": steps}})["steps"]


def state(**kw):
    """B1 の既定の状態 (active・20 回・90 分)。used / counters / budget は辞書で部分上書きできる"""
    s = {
        "v": 1,
        "id": "g-test",
        "text": "テストを全部通す",
        "status": "active",
        "budget": {"rounds": 20, "minutes": 90},
        "used": {"rounds": 0, "runMs": 0, "tokens": 0, "evalCalls": 0, "evalTokens": 0},
        "lifetime": {"rounds": 0, "tokens": 0, "evalCalls": 0, "evalTokens": 0, "resumes": 0},
        "counters": {"noTool": 0, "same": 0, "unapproved": 0, "evalFail": 0, "sameReason": 0},
        "audit": False,
        "createdAt": 0,
        "updatedAt": 0,
    }
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return s


_seq = iter(range(1, 10**6))


def facts(**kw):
    """B2 の事実。run の text は毎回変えて、同一内容の停滞を起こさない"""
    run = {
        "toolCalls": 1,
        "unapproved": 0,
        "text": f"進捗 {next(_seq)}",
        "tokens": 100,
        "claim": None,
    }
    run.update(kw.pop("run", {}))
    f = {
        "mode": "tui",
        "outcome": "completed",
        "compacting": False,
        "planMode": False,
        "pending": False,
        "bgBusy": 0,
        "runMs": 60_000,
        "now": 1000,
    }
    f.update(kw)
    f["run"] = run
    return f


def settle(s, **kw):
    cfg = kw.pop("cfg", {"evalMode": "claim"})
    return chain(s, [{"op": "settle", "facts": facts(**kw), "cfg": cfg}])[0]


CLAIM_OK = {"kind": "complete", "detail": ""}


# ---------- parseGoalArgs ----------


@pytest.mark.parametrize(
    "args",
    [
        "--foo x",
        "-x 目標",
        "--rounds",
        "--rounds abc 目標",
        "--rounds 0 目標",
        "--rounds 201 目標",
        "--rounds 1.5 目標",
        "--rounds -3 目標",
        "--minutes 0 目標",
        "--minutes 1441 目標",
        "--minutes x 目標",
        "--tokens 0 目標",
        "--tokens abc 目標",
        "--tokens 5g 目標",
        "--tokens 1.5k 目標",
        "--tokens= 目標",
        "--rounds 5",
        "--rounds 5 --rounds 6 目標",
        "--audit=1 目標",
        "status 目標",
        "pause now",
        "resume x",
        "clear all",
        "draft",
        "budget",
        "budget --audit",
        "budget foo",
        "budget --rounds 0",
        "budget --rounds 5 余分",
        "--rounds 5 pause",
        "resume を実装する",
        "--",
        "a" * 1501,
    ],
)
def test_parse_args_errors(args):
    r = call("parseGoalArgs", args)
    assert r["kind"] == "error" and r["message"], args


@pytest.mark.parametrize(
    ("args", "expect"),
    [
        ("", {"kind": "status"}),
        ("   ", {"kind": "status"}),
        ("status", {"kind": "status"}),
        ("pause", {"kind": "pause"}),
        ("resume", {"kind": "resume"}),
        ("clear", {"kind": "clear"}),
        ("draft メモ  です", {"kind": "draft", "text": "メモ  です"}),
        (
            "budget --rounds 5 --tokens 2k",
            {"kind": "budget", "budget": {"rounds": 5, "tokens": 2000}},
        ),
        ("budget --minutes=30", {"kind": "budget", "budget": {"minutes": 30}}),
        ("テストを直す", {"kind": "set", "text": "テストを直す", "budget": {}, "audit": False}),
        (
            "--rounds 5 --minutes 10 直す",
            {"kind": "set", "text": "直す", "budget": {"rounds": 5, "minutes": 10}, "audit": False},
        ),
        (
            "--rounds=7 直す",
            {"kind": "set", "text": "直す", "budget": {"rounds": 7}, "audit": False},
        ),
        (
            "--tokens 1m 直す",
            {"kind": "set", "text": "直す", "budget": {"tokens": 1_000_000}, "audit": False},
        ),
        (
            "--tokens 300K 直す",
            {"kind": "set", "text": "直す", "budget": {"tokens": 300_000}, "audit": False},
        ),
        (
            "--audit --minutes 30 -- status をやる",
            {"kind": "set", "text": "status をやる", "budget": {"minutes": 30}, "audit": True},
        ),
        ("-- --foo を直す", {"kind": "set", "text": "--foo を直す", "budget": {}, "audit": False}),
        (
            "fix --rounds 3  x",
            {"kind": "set", "text": "fix --rounds 3  x", "budget": {}, "audit": False},
        ),
        (
            "--rounds 200 --minutes 1440 x",
            {
                "kind": "set",
                "text": "x",
                "budget": {"rounds": 200, "minutes": 1440},
                "audit": False,
            },
        ),
        (
            "--rounds 1 --minutes 1 x",
            {"kind": "set", "text": "x", "budget": {"rounds": 1, "minutes": 1}, "audit": False},
        ),
        ("a" * 1500, {"kind": "set", "text": "a" * 1500, "budget": {}, "audit": False}),
        ("😀" * 1500, {"kind": "set", "text": "😀" * 1500, "budget": {}, "audit": False}),
    ],
)
def test_parse_args_ok(args, expect):
    assert call("parseGoalArgs", args) == expect


# ---------- newGoal ----------


def test_new_goal_defaults_and_deterministic_id():
    a = call("newGoal", "  目標  ", {}, 123456, {})
    b = call("newGoal", "目標", {}, 123456, {})
    assert a == b
    assert a["text"] == "目標" and a["status"] == "active" and a["v"] == 1
    assert a["budget"] == {"rounds": 20, "minutes": 90}
    assert a["id"].startswith("g-") and a["audit"] is False
    assert (
        a["used"] == state()["used"]
        and a["lifetime"] == state()["lifetime"]
        and a["counters"] == state()["counters"]
    )
    assert a["createdAt"] == a["updatedAt"] == 123456


def test_new_goal_opts_and_budget():
    g = call("newGoal", "x", {"rounds": 5, "tokens": 5000}, 1, {"audit": True, "id": "g-fixed"})
    assert (
        g["id"] == "g-fixed"
        and g["audit"] is True
        and g["budget"] == {"rounds": 5, "minutes": 90, "tokens": 5000}
    )


@pytest.mark.parametrize(
    ("text", "budget"),
    [
        ("", {}),
        ("   ", {}),
        ("a" * 1501, {}),
        ("x", {"rounds": 0}),
        ("x", {"rounds": 201}),
        ("x", {"rounds": 1.5}),
        ("x", {"minutes": 0}),
        ("x", {"minutes": 1441}),
        ("x", {"tokens": 0}),
    ],
)
def test_new_goal_rejects(text, budget):
    assert "error" in call("newGoal", text, budget, 1, {})


# ---------- parseClaim ----------


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("やった\nGOAL_STATUS: complete", {"kind": "complete", "detail": ""}),
        ("やった\nGOAL_STATUS: complete\n\n\n", {"kind": "complete", "detail": ""}),
        ("やった\r\nGOAL_STATUS: complete  \r\n", {"kind": "complete", "detail": ""}),
        ("GOAL_STATUS: complete", {"kind": "complete", "detail": ""}),
        ("goal_status: COMPLETE", {"kind": "complete", "detail": ""}),
        ("```\nx\n```\nGOAL_STATUS: complete", {"kind": "complete", "detail": ""}),
        ("x\nGOAL_STATUS: blocked: 判断が要る", {"kind": "blocked", "detail": "判断が要る"}),
        ("x\nGOAL_STATUS: Blocked:   理由 あり  ", {"kind": "blocked", "detail": "理由 あり"}),
        ("x\nGOAL_STATUS: blocked:", {"kind": "blocked", "detail": ""}),
        ("x\nGOAL_STATUS: blocked", {"kind": "blocked", "detail": ""}),
    ],
)
def test_parse_claim_accepts(text, expect):
    assert call("parseClaim", text) == expect


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n\n",
        "やった",
        "GOAL_STATUS: complete\nまだ続ける",
        "```\nGOAL_STATUS: complete\n```",
        "```\nGOAL_STATUS: complete",
        "~~~\nGOAL_STATUS: complete\n~~~",
        "```text\nGOAL_STATUS: blocked: x\n```\n",
        "> GOAL_STATUS: complete",
        "**GOAL_STATUS: complete**",
        "`GOAL_STATUS: complete`",
        "GOAL_STATUS: complete.",
        "GOAL_STATUS: complete soon",
        "GOAL_STATUS:",
        "GOAL_STATUS: done",
        "- GOAL_STATUS: complete",
        "xGOAL_STATUS: complete",
    ],
)
def test_parse_claim_rejects(text):
    assert call("parseClaim", text) is None


# ---------- summarizeRun / detectReview ----------


def user(t="指示"):
    return {"type": "message", "message": {"role": "user", "content": t}}


def asst(text="", tools=0, usage=None, name="bash", args=None):
    content = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "toolCall", "id": f"t{i}", "name": name, "arguments": args or {}}
        for i in range(tools)
    ]
    m = {"role": "assistant", "content": content}
    if usage is not None:
        m["usage"] = usage
    return {"type": "message", "message": m}


def tool_result(text):
    return {
        "type": "message",
        "message": {
            "role": "toolResult",
            "toolName": "bash",
            "content": [{"type": "text", "text": text}],
        },
    }


def test_summarize_run_counts_after_last_boundary():
    branch = [
        user(),
        asst("古い", tools=5, usage={"input": 1000, "output": 1000}),
        {"type": "custom_message", "customType": "goal-continue", "content": "続けて"},
        asst("", tools=2, usage={"input": 100, "output": 20, "cacheRead": 99999}),
        tool_result("not approved: 拒否された"),
        tool_result("ok"),
        asst("終わり\nGOAL_STATUS: complete", usage={"input": 10, "output": 5}),
    ]
    r = call("summarizeRun", branch)
    assert r["toolCalls"] == 2 and r["unapproved"] == 1
    assert r["tokens"] == 135 and r["text"] == "終わり\nGOAL_STATUS: complete"
    assert r["claim"] == CLAIM_OK


def test_summarize_run_non_goal_custom_message_is_not_a_boundary():
    branch = [
        user(),
        asst("a", tools=1),
        {"type": "custom_message", "customType": "autocheckpoint", "content": "x"},
        asst("b", tools=1),
    ]
    assert call("summarizeRun", branch)["toolCalls"] == 2


def test_summarize_run_empty_and_no_assistant():
    for b in ([], [user()]):
        assert call("summarizeRun", b) == {
            "toolCalls": 0,
            "unapproved": 0,
            "text": "",
            "tokens": 0,
            "claim": None,
        }


def test_summarize_run_unapproved_only_counts_prefix_in_tool_results():
    branch = [
        user(),
        tool_result("  not approved: x"),
        tool_result("これは not approved: ではない"),
        asst("a"),
    ]
    assert call("summarizeRun", branch)["unapproved"] == 1


def test_summarize_run_claim_in_fence_is_ignored():
    branch = [user(), asst("```\nGOAL_STATUS: complete\n```")]
    assert call("summarizeRun", branch)["claim"] is None


def test_detect_review():
    assert (
        call(
            "detectReview",
            [user(), asst("", tools=1, name="guarded_task", args={"agent": "review"})],
        )
        is True
    )
    assert (
        call(
            "detectReview",
            [user(), asst("", tools=1, name="guarded_task", args={"agent": "worker"})],
        )
        is False
    )
    assert (
        call("detectReview", [user(), asst("", tools=1, name="bash", args={"agent": "review"})])
        is False
    )
    assert call("detectReview", []) is False


# ---------- decideSettle: skip ----------


@pytest.mark.parametrize(
    ("override", "why"),
    [
        ({"compacting": True}, "compacting"),
        ({"planMode": True}, "plan"),
        ({"pending": True}, "pending"),
        ({"bgBusy": 2}, "background"),
        ({"mode": "print"}, "non-interactive"),
        ({"mode": "json"}, "non-interactive"),
        ({"compacting": True, "outcome": "aborted"}, "compacting"),
    ],
)
def test_settle_skip_does_not_count(override, why):
    s = state(used={"rounds": 3}, counters={"noTool": 1})
    r = settle(s, **override, run={"toolCalls": 0, "unapproved": 1})
    assert r["decision"] == {"kind": "skip", "why": why}
    assert r["next"] == s


@pytest.mark.parametrize("status", ["paused", "done"])
def test_settle_skip_when_not_active(status):
    s = state(status=status)
    r = settle(s)
    assert r["decision"]["kind"] == "skip" and r["next"] == s


def test_settle_rpc_mode_runs():
    assert settle(state(), mode="rpc")["decision"] == {"kind": "continue"}


# ---------- decideSettle: 2 (error / aborted) ----------


def test_settle_error_pauses_even_with_background():
    r = settle(state(), outcome="error", bgBusy=1, compacting=True)
    assert r["decision"] == {"kind": "pause", "reason": "run-error"}
    assert r["next"]["status"] == "paused" and r["next"]["pause"] == {"reason": "run-error"}


def test_settle_aborted_pauses_interrupted():
    r = settle(state(), outcome="aborted")
    assert r["decision"] == {"kind": "pause", "reason": "interrupted"}


def test_settle_aborted_beats_pending():
    assert settle(state(), outcome="aborted", pending=True)["decision"]["reason"] == "interrupted"


# ---------- decideSettle: 4 (計上) ----------


def test_settle_counts_a_round():
    r = settle(state(), run={"tokens": 250}, runMs=30_000, now=5000)
    assert r["decision"] == {"kind": "continue"}
    n = r["next"]
    assert n["used"]["rounds"] == 1 and n["used"]["tokens"] == 250 and n["used"]["runMs"] == 30_000
    assert (
        n["lifetime"]["rounds"] == 1 and n["lifetime"]["tokens"] == 250 and n["updatedAt"] == 5000
    )
    assert n["counters"]["noTool"] == 0


# ---------- decideSettle: 5 (予算) ----------


def test_budget_rounds_boundary():
    assert settle(state(budget={"rounds": 3}, used={"rounds": 1}))["decision"] == {
        "kind": "continue"
    }
    r = settle(state(budget={"rounds": 3}, used={"rounds": 2}))
    assert r["decision"] == {"kind": "pause", "reason": "rounds", "detail": "3/3"}
    assert r["next"]["status"] == "paused" and r["next"]["pause"]["reason"] == "rounds"


def test_budget_minutes_boundary():
    s = state(budget={"minutes": 1})
    assert settle(s, runMs=59_999)["decision"] == {"kind": "continue"}
    assert settle(s, runMs=60_000)["decision"]["reason"] == "minutes"


def test_budget_minutes_accumulates():
    s = state(budget={"minutes": 2}, used={"runMs": 90_000})
    assert settle(s, runMs=30_000)["decision"]["reason"] == "minutes"


def test_budget_tokens_optional():
    big = {"tokens": 10**9}
    assert settle(state(), run=big)["decision"] == {"kind": "continue"}
    s = state(budget={"tokens": 1000}, used={"tokens": 400})
    assert settle(s, run={"tokens": 599})["decision"] == {"kind": "continue"}
    assert settle(s, run={"tokens": 600})["decision"]["reason"] == "tokens"


def test_budget_rounds_beats_minutes_and_tokens():
    s = state(budget={"rounds": 1, "minutes": 1, "tokens": 1})
    assert settle(s, runMs=10**7, run={"tokens": 10**6})["decision"]["reason"] == "rounds"


# ---------- decideSettle: 優先順位の衝突 ----------


def test_priority_budget_beats_claim():
    s = state(budget={"rounds": 1})
    assert settle(s, run={"claim": CLAIM_OK})["decision"]["kind"] == "pause"


def test_priority_unapproved_beats_stall():
    s = state(counters={"unapproved": 1, "noTool": 1})
    r = settle(s, run={"toolCalls": 0, "unapproved": 1})
    assert r["decision"]["reason"] == "unapproved"
    assert r["next"]["counters"]["unapproved"] == 2


def test_priority_unapproved_beats_claim():
    s = state(counters={"unapproved": 1})
    assert settle(s, run={"unapproved": 1, "claim": CLAIM_OK})["decision"]["reason"] == "unapproved"


def test_priority_claim_beats_stall():
    s = state(counters={"noTool": 1})
    r = settle(s, run={"toolCalls": 0, "claim": CLAIM_OK})
    assert r["decision"] == {"kind": "evaluate", "why": "claim", "claim": CLAIM_OK}


def test_priority_every_mode_evaluates_without_claim():
    r = settle(state(), cfg={"evalMode": "every"})
    assert r["decision"] == {"kind": "evaluate", "why": "claim", "claim": None}


def test_priority_every_mode_still_after_budget_and_unapproved():
    s = state(counters={"unapproved": 1})
    assert (
        settle(s, cfg={"evalMode": "every"}, run={"unapproved": 1})["decision"]["reason"]
        == "unapproved"
    )
    assert (
        settle(state(budget={"rounds": 1}), cfg={"evalMode": "every"})["decision"]["reason"]
        == "rounds"
    )


def test_priority_error_beats_budget_and_claim():
    s = state(budget={"rounds": 1})
    assert settle(s, outcome="error", run={"claim": CLAIM_OK})["decision"]["reason"] == "run-error"


# ---------- decideSettle: 停滞 ----------


def test_stall_no_tool_two_in_a_row():
    r1, r2 = chain(
        state(),
        [
            {"op": "settle", "facts": facts(run={"toolCalls": 0}), "cfg": {"evalMode": "claim"}},
            {"op": "settle", "facts": facts(run={"toolCalls": 0}), "cfg": {"evalMode": "claim"}},
        ],
    )
    assert r1["decision"] == {"kind": "continue"} and r1["next"]["counters"]["noTool"] == 1
    assert (
        r2["decision"]["kind"] == "evaluate"
        and r2["decision"]["why"] == "stall"
        and r2["decision"]["claim"] is None
    )
    assert "ツール呼び出しなし 2 回" in r2["decision"]["detail"]


def test_stall_no_tool_resets_with_a_tool_call():
    steps = [
        {"op": "settle", "facts": facts(run={"toolCalls": 0}), "cfg": {"evalMode": "claim"}},
        {"op": "settle", "facts": facts(run={"toolCalls": 1}), "cfg": {"evalMode": "claim"}},
        {"op": "settle", "facts": facts(run={"toolCalls": 0}), "cfg": {"evalMode": "claim"}},
    ]
    out = chain(state(), steps)
    assert [o["decision"]["kind"] for o in out] == ["continue"] * 3
    assert out[2]["next"]["counters"]["noTool"] == 1


def test_stall_same_text_three_in_a_row():
    same = {"op": "settle", "facts": facts(run={"text": "同じ応答"}), "cfg": {"evalMode": "claim"}}
    out = chain(state(), [same, same, same])
    assert [o["decision"]["kind"] for o in out] == ["continue", "continue", "evaluate"]
    assert out[2]["decision"]["why"] == "stall" and "同じ内容 3 回" in out[2]["decision"]["detail"]
    assert out[2]["next"]["counters"]["same"] == 3


def test_stall_same_text_is_normalized_and_reset_by_a_different_one():
    def st(t):
        return {"op": "settle", "facts": facts(run={"text": t}), "cfg": {"evalMode": "claim"}}

    out = chain(state(), [st("A  b"), st(" A b "), st("別"), st("A b"), st("A b")])
    assert [o["decision"]["kind"] for o in out] == ["continue"] * 5
    assert [o["next"]["counters"]["same"] for o in out] == [1, 2, 1, 1, 2]


def test_stall_empty_text_is_not_same():
    out = chain(
        state(),
        [{"op": "settle", "facts": facts(run={"text": ""}), "cfg": {"evalMode": "claim"}}] * 3,
    )
    assert all(o["decision"]["kind"] == "continue" for o in out)
    assert out[2]["next"]["counters"]["same"] == 0


def test_unapproved_resets_after_a_clean_settle():
    steps = [
        {"op": "settle", "facts": facts(run={"unapproved": 1}), "cfg": {"evalMode": "claim"}},
        {"op": "settle", "facts": facts(), "cfg": {"evalMode": "claim"}},
        {"op": "settle", "facts": facts(run={"unapproved": 1}), "cfg": {"evalMode": "claim"}},
    ]
    out = chain(state(), steps)
    assert [o["decision"]["kind"] for o in out] == ["continue"] * 3
    assert out[2]["next"]["counters"]["unapproved"] == 1


# ---------- applyVerdict ----------


def verdict(s, v, f=None, now=2000):
    return chain(s, [{"op": "verdict", "v": v, "now": now, "f": f or {"auditSeen": False}}])[0]


def test_verdict_done():
    r = verdict(
        state(),
        {"verdict": "done", "reason": "全部通った"},
        {"auditSeen": False, "evalTokens": 500},
    )
    assert r["decision"] == {"kind": "done"} and r["next"]["status"] == "done"
    assert r["next"]["used"]["evalCalls"] == 1 and r["next"]["used"]["evalTokens"] == 500
    assert r["next"]["lifetime"]["evalTokens"] == 500 and r["next"]["used"]["tokens"] == 500
    assert r["next"]["lastVerdict"] == {"verdict": "done", "reason": "全部通った", "at": 2000}


def test_verdict_done_with_audit_requires_review():
    s = state(audit=True)
    r = verdict(s, {"verdict": "done", "reason": "ok"})
    assert r["decision"]["kind"] == "continue" and "review" in r["decision"]["reason"]
    assert r["next"]["status"] == "active"
    r2 = verdict(s, {"verdict": "done", "reason": "ok"}, {"auditSeen": True})
    assert r2["decision"] == {"kind": "done"} and r2["next"]["status"] == "done"


def test_verdict_done_without_audit_ignores_audit_seen():
    assert (
        verdict(state(), {"verdict": "done", "reason": "ok"}, {"auditSeen": False})["next"][
            "status"
        ]
        == "done"
    )


def test_verdict_continue_carries_reason():
    r = verdict(state(), {"verdict": "continue", "reason": "テスト 2 件が未達"})
    assert r["decision"] == {"kind": "continue", "reason": "テスト 2 件が未達"}
    assert r["next"]["counters"]["sameReason"] == 1 and r["next"]["status"] == "active"


def test_verdict_same_reason_three_times_stalls():
    c = {
        "op": "verdict",
        "v": {"verdict": "continue", "reason": "同じ"},
        "now": 1,
        "f": {"auditSeen": False},
    }
    out = chain(state(), [c, c, c])
    assert [o["decision"]["kind"] for o in out] == ["continue", "continue", "pause"]
    assert (
        out[2]["decision"]["reason"] == "stalled" and out[2]["next"]["pause"]["reason"] == "stalled"
    )


def test_verdict_different_reasons_do_not_stall():
    def c(r):
        return {
            "op": "verdict",
            "v": {"verdict": "continue", "reason": r},
            "now": 1,
            "f": {"auditSeen": False},
        }

    out = chain(state(), [c("a"), c("a"), c("b"), c("b"), c("a")])
    assert all(o["decision"]["kind"] == "continue" for o in out)


def test_verdict_continue_for_stall_pauses():
    r = verdict(
        state(),
        {"verdict": "continue", "reason": "進んでいない"},
        {"auditSeen": False, "why": "stall"},
    )
    assert r["decision"] == {"kind": "pause", "reason": "stalled", "detail": "進んでいない"}


def test_verdict_blocked():
    r = verdict(state(), {"verdict": "blocked", "reason": "鍵が要る"})
    assert r["decision"] == {"kind": "pause", "reason": "blocked", "detail": "鍵が要る"}
    assert r["next"]["status"] == "paused" and r["next"]["lastVerdict"]["verdict"] == "blocked"


def test_verdict_eval_failure_twice_pauses():
    out = chain(
        state(), [{"op": "verdict", "v": None, "now": 1}, {"op": "verdict", "v": None, "now": 2}]
    )
    assert (
        out[0]["decision"] == {"kind": "continue"} and out[0]["next"]["counters"]["evalFail"] == 1
    )
    assert out[1]["decision"]["kind"] == "pause" and out[1]["decision"]["reason"] == "eval-failed"
    assert out[1]["next"]["used"]["evalCalls"] == 2


def test_verdict_eval_failure_resets_after_success():
    steps = [
        {"op": "verdict", "v": None, "now": 1},
        {"op": "verdict", "v": {"verdict": "continue", "reason": "x"}, "now": 2},
        {"op": "verdict", "v": None, "now": 3},
    ]
    out = chain(state(), steps)
    assert [o["decision"]["kind"] for o in out] == ["continue"] * 3
    assert out[2]["next"]["counters"]["evalFail"] == 1


def test_verdict_eval_tokens_can_exhaust_token_budget():
    s = state(budget={"tokens": 1000}, used={"tokens": 800})
    r = verdict(s, {"verdict": "continue", "reason": "x"}, {"auditSeen": False, "evalTokens": 300})
    assert r["decision"]["reason"] == "tokens"
    assert r["next"]["used"]["tokens"] == 1100


# ---------- 操作 (pause / resume / budget) ----------


def test_resume_resets_used_and_counters_but_not_lifetime():
    s0 = state()
    out = chain(
        s0,
        [
            {
                "op": "settle",
                "facts": facts(run={"toolCalls": 0, "tokens": 300}),
                "cfg": {"evalMode": "claim"},
            },
            {
                "op": "settle",
                "facts": facts(run={"toolCalls": 0, "tokens": 300}),
                "cfg": {"evalMode": "claim"},
            },
            {
                "op": "verdict",
                "v": {"verdict": "blocked", "reason": "b"},
                "now": 5,
                "f": {"auditSeen": False, "evalTokens": 50},
            },
            {"op": "resume", "now": 9},
        ],
    )
    n = out[-1]["next"]
    assert n["status"] == "active" and "pause" not in n
    assert n["used"] == s0["used"] and n["counters"] == s0["counters"]
    assert n["lifetime"] == {
        "rounds": 2,
        "tokens": 650,
        "evalCalls": 1,
        "evalTokens": 50,
        "resumes": 1,
    }
    assert n["updatedAt"] == 9


def test_resume_does_not_revive_done():
    assert chain(state(status="done"), [{"op": "resume", "now": 1}])[0]["next"]["status"] == "done"


def test_pause_goal_sets_reason_and_ignores_done():
    n = chain(state(), [{"op": "pause", "reason": "input", "now": 7}])[0]["next"]
    assert n["status"] == "paused" and n["pause"] == {"reason": "input"} and n["updatedAt"] == 7
    assert (
        chain(state(status="done"), [{"op": "pause", "reason": "user"}])[0]["next"]["status"]
        == "done"
    )


def test_budget_update_only_given_axes_and_validates():
    n = chain(
        state(budget={"rounds": 5, "minutes": 10}),
        [{"op": "budget", "budget": {"minutes": 30}, "now": 3}],
    )[0]["next"]
    assert n["budget"] == {"rounds": 5, "minutes": 30} and n["updatedAt"] == 3
    r = chain(state(), [{"op": "budget", "budget": {"rounds": 0}}])[0]
    assert r["decision"]["kind"] == "error" and r["next"] == state()
    t = chain(state(), [{"op": "budget", "budget": {"tokens": 5000}}])[0]["next"]
    assert t["budget"] == {"rounds": 20, "minutes": 90, "tokens": 5000}


# ---------- restore ----------


def goal_entry(data):
    return {"type": "custom", "customType": "goal-state", "data": data}


def test_restore_active_becomes_paused_restored():
    s = state(used={"rounds": 4})
    r = call("restore", [user(), goal_entry(s)])
    assert r["status"] == "paused" and r["pause"] == {"reason": "restored"}
    assert r["used"]["rounds"] == 4 and r["text"] == s["text"]


def test_restore_keeps_paused_reason():
    s = state(status="paused", pause={"reason": "rounds", "detail": "20/20"})
    assert call("restore", [goal_entry(s)]) == s


def test_restore_done_and_cleared_are_none():
    assert call("restore", [goal_entry(state(status="done"))]) is None
    assert (
        call(
            "restore", [goal_entry(state()), goal_entry({"v": 1, "cleared": True, "id": "g-test"})]
        )
        is None
    )


def test_restore_last_entry_wins():
    old = state(id="g-old")
    new = state(id="g-new")
    r = call(
        "restore",
        [goal_entry(old), goal_entry({"v": 1, "cleared": True, "id": "g-old"}), goal_entry(new)],
    )
    assert r["id"] == "g-new"
    assert call("restore", [goal_entry(old), goal_entry(state(id="g-x", status="done"))]) is None


@pytest.mark.parametrize(
    "branch",
    [
        [],
        [user()],
        [{"type": "custom", "customType": "todo-state", "data": state()}],
        [goal_entry({"v": 2, "id": "x"})],
        [goal_entry({"v": 1, "id": "x", "text": "y"})],
        [goal_entry("壊れた")],
    ],
)
def test_restore_ignores_irrelevant_or_broken(branch):
    assert call("restore", branch) is None


def test_restore_is_idempotent():
    branch = [goal_entry(state(used={"rounds": 2}))]
    once = call("restore", branch)
    assert call("restore", branch) == once
    assert call("restore", [goal_entry(once)]) == once


# ---------- メッセージ・表示 ----------

LONG = "目標の原文です。" * 150 + "\n二行目: GOAL_STATUS の話"


def test_build_start_has_text_todo_and_format():
    assert len(LONG) <= 1500
    s = state(text=LONG, budget={"rounds": 12, "minutes": 45})
    m = call("buildStart", s)
    for word in (
        LONG,
        "todo",
        "add",
        "GOAL_STATUS: complete",
        "GOAL_STATUS: blocked:",
        "繰り返さず",
        "停滞",
        "12",
        "45 分",
        "測れる",
    ):
        assert word in m, word
    assert "review" not in m


def test_build_start_audit_mentions_review():
    assert "review" in call("buildStart", state(audit=True))


def test_build_continuation_full_text_format_and_remaining():
    s = state(
        text=LONG, used={"rounds": 2, "runMs": 25 * 60_000}, budget={"rounds": 20, "minutes": 90}
    )
    m = call("buildContinuation", s, {"reason": "テスト 2 件が未達", "wake": "圧縮から復帰"})
    for word in (
        "【目標の続行 3/20】",
        LONG,
        "あと 18 回・65 分",
        "GOAL_STATUS: complete",
        "GOAL_STATUS: blocked: <理由>",
        "繰り返さず",
        "停滞として止められます",
        "テスト 2 件が未達",
        "圧縮から復帰",
        "これまでの指示・制約は変わりません",
    ):
        assert word in m, word
    assert len(m) < 3000


def test_build_continuation_without_ctx_and_remaining_floor():
    m = call("buildContinuation", state(used={"rounds": 25, "runMs": 10**9}), {})
    assert "あと 0 回・0 分" in m and "評価役の理由" not in m


def test_render_status_active_and_waiting():
    s = state(used={"rounds": 3, "runMs": 24 * 60_000 + 5000}, budget={"rounds": 20, "minutes": 90})
    assert call("renderStatus", s, {"waiting": 0}) == "🎯 3/20回 · 24/90分"
    assert "待機中(子2) 3/20回" in call("renderStatus", s, {"waiting": 2})
    assert "tok" in call(
        "renderStatus", state(budget={"tokens": 200_000}, used={"tokens": 12_300}), {"waiting": 0}
    )


def test_render_status_paused_and_done():
    r = call(
        "renderStatus",
        state(status="paused", pause={"reason": "rounds"}, used={"rounds": 20}),
        {"waiting": 0},
    )
    assert "一時停止" in r and "回数の上限 20/20" in r and "/goal budget" in r
    st = call(
        "renderStatus",
        state(status="paused", pause={"reason": "stalled", "detail": "ツール呼び出しなし 2 回"}),
        {"waiting": 0},
    )
    assert st == "🎯 一時停止: 停滞(ツール呼び出しなし 2 回)"
    assert call("renderStatus", state(status="done"), {"waiting": 0}) == "🎯 完了 ✓"


@pytest.mark.parametrize(
    "reason",
    [
        "user",
        "input",
        "interrupted",
        "restored",
        "rounds",
        "minutes",
        "tokens",
        "stalled",
        "blocked",
        "unapproved",
        "run-error",
        "eval-failed",
    ],
)
def test_render_status_every_pause_reason_has_a_label(reason):
    r = call(
        "renderStatus",
        state(status="paused", pause={"reason": reason}, budget={"tokens": 1000}),
        {"waiting": 0},
    )
    assert r.startswith("🎯 一時停止: ") and "理由不明" not in r


def test_render_detail():
    s = state(
        id="g-k3x9",
        used={"rounds": 3, "runMs": 24 * 60_000, "evalCalls": 2, "evalTokens": 5100},
        lastVerdict={"verdict": "continue", "reason": "テスト 2 件が未達", "at": 1},
    )
    d = call("renderDetail", s, {"bypass": True})
    for word in (
        "g-k3x9",
        "(active)",
        "目標: テストを全部通す",
        "続行 3/20",
        "作業 24/90 分",
        "上限なし",
        "評価役: 2 回",
        "5.1k",
        "continue「テスト 2 件が未達」",
        "/goal pause",
        "/goal clear",
        "bypass: ON",
    ):
        assert word in d, word
    assert "bypass: OFF" in call("renderDetail", s, {"bypass": False})


# ---------- 性質 (seed 固定の乱数列) ----------


@pytest.mark.parametrize("seed", [1, 2, 3, 20260101])
def test_property_used_and_lifetime_are_monotonic(seed):
    out = drive({"fuzz": {"seed": seed, "runs": 40, "steps": 80}})
    assert out["bad"] == []


def test_inputs_are_never_mutated_by_any_function():
    # driver が引数を deep freeze するので、変更すれば TypeError で落ちる。全関数を 1 回ずつ呼ぶ
    s = state(used={"rounds": 1})
    f = facts()
    calls = [
        ("parseGoalArgs", ["--rounds 3 x"]),
        ("newGoal", ["x", {"rounds": 3}, 1, {}]),
        ("parseClaim", ["a\nGOAL_STATUS: complete"]),
        ("summarizeRun", [[user(), asst("a", tools=1)]]),
        ("detectReview", [[user()]]),
        ("decideSettle", [s, f, {"evalMode": "claim"}]),
        ("applyVerdict", [s, {"verdict": "done", "reason": "x"}, 1, {"auditSeen": False}]),
        ("applyVerdict", [s, None, 1, {"auditSeen": False}]),
        ("pauseGoal", [s, "user", 1]),
        ("resumeGoal", [s, 1]),
        ("setBudget", [s, {"rounds": 3}, 1]),
        ("buildStart", [s]),
        ("buildContinuation", [s, {}]),
        ("renderStatus", [s, {"waiting": 0}]),
        ("renderDetail", [s, {"bypass": False}]),
        ("restore", [[goal_entry(s)]]),
    ]
    before = copy.deepcopy(s)
    res = drive({"calls": [{"fn": fn, "args": args} for fn, args in calls]})["results"]
    assert len(res) == len(calls)
    assert s == before
