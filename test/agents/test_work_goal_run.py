"""`/goal` の pi への接着 (``home/dot_config/pi/harness/work/goal-run.ts``) の試験。

``test/agents/pi/work_goal_run_driver.mjs`` に偽の pi・偽の ctx を渡し、実の runtime を tmp ディレクトリで動かして見る
(node の型除去を使うので、22.18 未満の node では飛ばす)。

see docs/spec/work/goal-run.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_goal_run_driver.mjs"
GOAL_RUN = ROOT / "home" / "dot_config" / "pi" / "harness" / "work" / "goal-run.ts"
INDEX = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

ON = {"PI_WORK_GOAL": "1"}
BOTH = {"PI_WORK_GOAL": "1", "PI_WORK_TOOL": "1"}
START = {"ev": "session_start"}


def run(tmp_path, steps, **kw):
    scenario = {"dir": str(tmp_path), "steps": steps, **kw}
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(scenario),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def goal(arg, **kw):
    return {"goal": arg, **kw}


def goals(out, i=-1):
    return out["results"][i]["snap"]["goals"]


def last(out):
    return goals(out)[-1]


def msgs(out):
    return [n["message"] for n in out["notices"]]


# ── 旗・子・無効 ──
@pytest.mark.parametrize(
    ("env", "child"),
    [
        ({}, False),
        ({"PI_WORK_GOAL": "0"}, False),
        ({"PI_WORK_TOOL": "1"}, False),
        ({"PI_WORK_GOAL": "1", "PI_WORK": "0"}, False),
        ({"PI_WORK_GOAL": "1", "PI_HARNESS_CHILD": "1"}, False),
        ({"PI_WORK_GOAL": "1"}, True),
    ],
)
def test_registers_nothing_unless_enabled(tmp_path, env, child):
    out = run(tmp_path, [], env=env, child=child)
    assert out["handle"] is False
    assert "goal" not in out["registered"]["commands"]
    assert "input" not in out["registered"]["handlers"]


def test_registers_command_and_handlers_when_enabled(tmp_path):
    out = run(tmp_path, [], env=ON)
    assert out["handle"] is True
    assert out["registered"]["commands"] == ["goal"]
    assert {"session_start", "session_shutdown", "input"} <= set(out["registered"]["handlers"])
    assert out["registered"]["tools"] == []


def test_goal_alone_does_not_register_work_tool(tmp_path):
    assert run(tmp_path, [], env=ON)["hasTool"] is False


# ── /goal <目標> ──
def test_set_creates_active_goal_via_user_events(tmp_path):
    out = run(tmp_path, [START, goal("作業A")], env=ON)
    g = last(out)
    assert g["state"] == "active"  # plan.approved は利用者専用なので、active なら出所は user
    assert g["title"] == "作業A"


def test_set_budget_is_default_finite(tmp_path):
    b = last(run(tmp_path, [START, goal("作業A")], env=ON))["budget"]
    assert b["rounds"] == 20
    assert b["ms"] == 90 * 60_000
    assert all(
        isinstance(b[k], int) and b[k] < float("inf") for k in ("usd", "tokens", "ms", "rounds")
    )


def test_set_with_flags(tmp_path):
    b = last(run(tmp_path, [START, goal("--rounds 5 --minutes 30 --tokens 2k 作業")], env=ON))[
        "budget"
    ]
    assert (b["rounds"], b["ms"], b["tokens"]) == (5, 30 * 60_000, 2000)


def test_set_reports_notice(tmp_path):
    out = run(tmp_path, [START, goal("作業A")], env=ON)
    assert any("記録しました" in m for m in msgs(out))


def test_set_rejected_when_goal_exists(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("作業B")], env=ON)
    assert len(goals(out)) == 1
    assert last(out)["title"] == "作業A"
    assert any("既に目標があります" in m for m in msgs(out))


def test_set_allowed_again_after_clear(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("clear"), goal("作業B")], env=ON)
    assert last(out)["title"] == "作業B"
    assert last(out)["state"] == "active"


def test_status_without_goal(tmp_path):
    out = run(tmp_path, [START, goal("")], env=ON)
    assert any("目標はありません" in m for m in msgs(out))


def test_status_with_goal_shows_text(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("status")], env=ON)
    assert "作業A" in msgs(out)[-1]
    assert len(goals(out)) == 1


def test_draft_does_not_touch_ledger(tmp_path):
    out = run(tmp_path, [START, goal("draft メモ")], env=ON)
    assert goals(out) == []
    assert "メモ" in msgs(out)[-1]


def test_no_ui_does_not_notify_or_throw(tmp_path):
    out = run(tmp_path, [START, goal("作業A", ui=False)], env=ON)
    assert out["notices"] == []
    assert last(out)["state"] == "active"


# ── pause / resume / budget / clear ──
def test_pause_then_resume(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("pause"), goal("resume")], env=ON)
    assert goals(out, 2)[-1]["state"] == "paused"
    assert goals(out, 2)[-1]["pauseReason"] == "user"
    assert last(out)["state"] == "active"


def test_resume_when_active_is_noop(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("resume")], env=ON)
    assert last(out)["state"] == "active"
    assert "既に実行中" in msgs(out)[-1]


def test_pause_without_goal_rejected(tmp_path):
    out = run(tmp_path, [START, goal("pause")], env=ON)
    assert any("拒否" in m for m in msgs(out))


def test_budget_changes_ledger_budget(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("budget --rounds 50 --minutes 10")], env=ON)
    b = last(out)["budget"]
    assert (b["rounds"], b["ms"]) == (50, 600_000)


def test_budget_without_goal_rejected(tmp_path):
    out = run(tmp_path, [START, goal("budget --rounds 5")], env=ON)
    assert any("拒否" in m for m in msgs(out))


def test_clear_cancels_goal(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("clear")], env=ON)
    assert last(out)["state"] == "cancelled"


def test_clear_without_goal_is_noop(tmp_path):
    out = run(tmp_path, [START, goal("clear")], env=ON)
    assert goals(out) == []
    assert "破棄する目標はありません" in msgs(out)[-1]


# ── 予算は必須の有限値 ──
@pytest.mark.parametrize(
    "arg",
    [
        "--rounds 0 作業",
        "--rounds 201 作業",
        "--rounds Infinity 作業",
        "--rounds abc 作業",
        "--rounds -1 作業",
        "--minutes 0 作業",
        "--minutes 1441 作業",
        "--minutes NaN 作業",
        "--tokens 0 作業",
        "--tokens 2g 作業",
        "--tokens 1000000001 作業",
        "--rounds 作業",
    ],
)
def test_invalid_budget_on_set_rejected(tmp_path, arg):
    out = run(tmp_path, [START, goal(arg)], env=ON)
    assert goals(out) == []
    assert any(n["level"] == "warning" and "拒否" in n["message"] for n in out["notices"])


@pytest.mark.parametrize(
    "arg",
    [
        "budget --rounds 0",
        "budget --rounds 201",
        "budget --minutes Infinity",
        "budget --tokens 0",
        "budget",
    ],
)
def test_invalid_budget_change_rejected(tmp_path, arg):
    out = run(tmp_path, [START, goal("作業A"), goal(arg)], env=ON)
    assert last(out)["budget"]["rounds"] == 20
    assert last(out)["budget"]["ms"] == 90 * 60_000
    assert any("拒否" in m for m in msgs(out))


# ── 現行 goal-core との差分試験 ──
DIFFS = [
    ["作業A", "pause", "resume", "budget --rounds 7", "clear"],
    [
        "--rounds 3 --minutes 5 --tokens 10k 作業",
        "budget --minutes 20",
        "pause",
        "budget --rounds 9",
        "resume",
    ],
    ["--audit 作業", "pause", "pause", "resume", "resume", "clear", "clear"],
    [
        "pause",
        "resume",
        "budget --rounds 5",
        "作業A",
        "作業B",
        "--rounds 0 作業C",
        "clear",
        "作業D",
    ],
    [
        "作業A",
        "budget --rounds 0",
        "budget --tokens 5k",
        "budget --minutes 1441",
        "pause",
        "clear",
        "作業B",
    ],
]


@pytest.mark.parametrize("cmds", DIFFS)
def test_matches_goal_core(tmp_path, cmds):
    out = run(tmp_path, [START, {"diff": cmds}], env=ON)
    assert out["results"][-1]["mismatches"] == []


# ── 利用者の入力で一時停止 ──
def test_user_input_pauses_active_goal(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), {"input": "別の話"}], env=ON)
    assert last(out)["state"] == "paused"
    assert last(out)["pauseReason"] == "input"
    assert any("一時停止" in m for m in msgs(out))


def test_extension_input_does_not_pause(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), {"input": "続けて", "source": "extension"}], env=ON)
    assert last(out)["state"] == "active"


def test_goal_command_text_does_not_pause(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), {"input": "/goal status"}], env=ON)
    assert last(out)["state"] == "active"


def test_input_without_goal_is_noop(tmp_path):
    out = run(tmp_path, [START, {"input": "こんにちは"}], env=ON)
    assert goals(out) == []
    assert out["results"][-1]["ret"] == [None]


def test_input_on_paused_goal_keeps_reason(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), goal("pause"), {"input": "別の話"}], env=ON)
    assert last(out)["pauseReason"] == "user"


def test_resume_after_input_pause(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), {"input": "x"}, goal("resume")], env=ON)
    assert last(out)["state"] == "active"


def test_input_handler_returns_continue(tmp_path):
    out = run(tmp_path, [START, goal("作業A"), {"input": "x"}], env=ON)
    assert out["results"][-1]["ret"] == [None]


# ── モデル出所は拒否される ──
def test_model_cannot_resume(tmp_path):
    out = run(
        tmp_path,
        [START, goal("作業A"), goal("pause"), {"model": [{"type": "goal.resumed"}]}],
        env=ON,
    )
    assert out["results"][-1]["model"][0]["ok"] is False
    assert last(out)["state"] == "paused"


def test_model_cannot_change_budget(tmp_path):
    ev = {
        "type": "budget.adjusted",
        "data": {"budget": {"usd": 1, "tokens": 1, "ms": 1, "rounds": 1}},
    }
    out = run(tmp_path, [START, goal("作業A"), {"model": [ev]}], env=ON)
    assert out["results"][-1]["model"][0]["ok"] is False
    assert last(out)["budget"]["rounds"] == 20


def test_model_cannot_approve_plan(tmp_path):
    steps = [
        START,
        {
            "tool": {
                "op": "plan",
                "goal": "G",
                "tasks": [{"title": "t", "kind": "task", "deps": []}],
            }
        },
        {"model": [{"type": "plan.approved", "data": {"hash": "x"}}]},
    ]
    out = run(tmp_path, steps, env=BOTH)
    assert out["results"][-1]["model"][0]["ok"] is False
    assert last(out)["state"] != "active"


def test_model_cannot_cancel_goal(tmp_path):
    ev = {"type": "verdict", "data": {"verdict": "cancel", "reason": "x"}}
    out = run(tmp_path, [START, goal("作業A"), {"model": [ev]}], env=ON)
    assert out["results"][-1]["model"][0]["ok"] is False
    assert last(out)["state"] == "active"


# ── 計画の承認 ──
PLAN = {"tool": {"op": "plan", "goal": "G", "tasks": [{"title": "t1", "kind": "task", "deps": []}]}}


def test_model_plan_does_not_run_tasks(tmp_path):
    out = run(tmp_path, [START, PLAN], env=BOTH)
    assert last(out)["state"] in ("draft", "planned")
    assert all(t["state"] not in ("ready", "running") for t in out["results"][-1]["snap"]["tasks"])


def test_approve_by_user_activates_goal(tmp_path):
    out = run(tmp_path, [START, PLAN, goal("approve")], env=BOTH)
    assert last(out)["state"] == "active"
    assert any("承認しました" in m for m in msgs(out))


def test_approve_declined_keeps_plan(tmp_path):
    out = run(tmp_path, [START, PLAN, goal("approve", confirm=False)], env=BOTH)
    assert last(out)["state"] != "active"
    assert any("取りやめ" in m for m in msgs(out))


def test_approve_without_plan(tmp_path):
    out = run(tmp_path, [START, goal("approve")], env=ON)
    assert goals(out) == []
    assert any("承認待ちの計画はありません" in m for m in msgs(out))


def test_approve_twice_second_is_noop(tmp_path):
    out = run(tmp_path, [START, PLAN, goal("approve"), goal("approve")], env=BOTH)
    assert "承認待ちの計画はありません" in msgs(out)[-1]


def test_set_rejected_while_plan_pending(tmp_path):
    out = run(tmp_path, [START, PLAN, goal("別の目標")], env=BOTH)
    assert len(goals(out)) == 1
    assert any("既に目標があります" in m for m in msgs(out))


def test_approve_without_ui_proceeds(tmp_path):
    out = run(tmp_path, [START, PLAN, goal("approve", ui=False)], env=BOTH)
    assert last(out)["state"] == "active"


# ── runtime の共有・読み取り専用 ──
def test_shared_runtime_with_work_tool(tmp_path):
    out = run(
        tmp_path,
        [
            START,
            goal("作業A"),
            {"tool": {"op": "add", "title": "子作業"}},
            {"tool": {"op": "list"}},
        ],
        env=BOTH,
    )
    assert out["hasTool"] is True
    assert "子作業" in out["results"][-1]["tool"]
    # 同じ台帳なので、task は /goal の goal の下に入る
    assert [t["title"] for t in out["results"][-1]["snap"]["tasks"]] == ["子作業"]
    assert len(goals(out)) == 1


def test_shared_mode_does_not_open_own_runtime(tmp_path):
    out = run(tmp_path, [START, goal("作業A")], env=BOTH)
    assert last(out)["state"] == "active"
    assert (tmp_path / ".tmp" / "work" / "log").exists() or (tmp_path / ".tmp" / "work").exists()


def test_off_runtime_rejects_set(tmp_path):
    out = run(tmp_path, [START, goal("作業A")], env=ON, off=True)
    assert goals(out) == []
    assert any("拒否" in m for m in msgs(out))


def test_off_runtime_rejects_approve(tmp_path):
    out = run(tmp_path, [START, goal("approve")], env=ON, off=True)
    assert any("拒否" in m or "承認待ち" in m for m in msgs(out))


def test_command_before_session_start_is_safe(tmp_path):
    out = run(tmp_path, [goal("作業A")], env=ON)
    assert any("台帳が開いていない" in m for m in msgs(out))


# ── settle への goal の事実 ──
def facts(out):
    return out["results"][-1]["facts"]


def test_facts_none_without_goal(tmp_path):
    assert facts(run(tmp_path, [START, {"facts": True}], env=ON)) is None


def test_facts_active_goal(tmp_path):
    f = facts(run(tmp_path, [START, goal("作業A"), {"facts": True}], env=ON))
    assert f["goal"] == {"active": True, "claim": False, "stall": False, "unapproved": 0}
    assert f["budgetExhausted"] is False


def test_facts_paused_goal_inactive(tmp_path):
    f = facts(run(tmp_path, [START, goal("作業A"), goal("pause"), {"facts": True}], env=ON))
    assert f["goal"]["active"] is False


def test_facts_none_for_unapproved_plan(tmp_path):
    assert facts(run(tmp_path, [START, PLAN, {"facts": True}], env=BOTH)) is None


def test_facts_none_when_runtime_off(tmp_path):
    assert facts(run(tmp_path, [START, {"facts": True}], env=ON, off=True)) is None


def test_facts_shape_is_complete(tmp_path):
    f = facts(run(tmp_path, [START, goal("作業A"), {"facts": True}], env=ON))
    assert set(f) == {"goal", "budgetExhausted"}
    assert set(f["goal"]) == {"active", "claim", "stall", "unapproved"}


def test_facts_none_when_not_registered(tmp_path):
    assert facts(run(tmp_path, [START, {"facts": True}], env={})) == "none"


# ── 配線 (静的) ──
def test_index_wires_goal_run_once():
    src = INDEX.read_text(encoding="utf-8")
    assert src.count('from "./work/goal-run.ts"') == 1
    assert src.count("registerGoal(pi,") == 1


def test_goal_run_default_off_and_child_excluded():
    src = GOAL_RUN.read_text(encoding="utf-8")
    assert 'env.PI_WORK_GOAL === "1"' in src
    assert "PI_HARNESS_CHILD" in src
    assert 'env.PI_WORK !== "0"' in src


def test_goal_run_has_no_user_only_event_from_model():
    src = GOAL_RUN.read_text(encoding="utf-8")
    assert '"model"' not in src
