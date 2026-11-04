"""作業台帳の核 (``home/dot_config/pi/harness/work/*.ts``) の純関数の試験。

``test/agents/pi/work_core_driver.mjs`` に JSON を渡して reducer・不変条件・投影を呼ぶ (node の型除去を使うので、
22.18 未満の node では飛ばす)。
遷移表は Python 側に独立した仕様 (``SPEC``) を持ち、driver が出す全セルと照合する。

see docs/spec/work/ledger.md
"""

from __future__ import annotations

import copy
import itertools
import json
import subprocess
from functools import cache, lru_cache

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_core_driver.mjs"

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


def call(fn, *args, events=None, state=None):
    c = {"fn": fn, "args": list(args)}
    if events is not None:
        c["events"] = events
    if state is not None:
        c["state"] = state
    return drive({"calls": [c]})["results"][0]


Z = {"usd": 0, "tokens": 0, "ms": 0}


def M(usd=0, tokens=0, ms=0):
    return {"usd": usd, "tokens": tokens, "ms": ms}


# ── イベントの組み立て ──
def E(type_, nid=None, source=None, **data):
    e = {"type": type_, "data": data}
    if nid is not None:
        e["node"] = nid
    if source is not None:
        e["source"] = source
    return e


def goal(g="G", budget=None, approve=True):
    d = {"title": g}
    if budget:
        d["budget"] = budget
    evs = [E("goal.created", g, **d), E("plan.proposed", g, hash="h")]
    if approve:
        evs.append(E("plan.approved", g, source="user", hash="h"))
    return evs


def task(t, parent="G", after=None, writes=None, kind="task", budget=None, attrs=None):
    n = {"kind": kind, "parent": parent, "title": t, "after": after or [], "writes": writes or []}
    if budget:
        n["budget"] = budget
    if attrs:
        n["attrs"] = attrs
    return E("node.added", t, node=n)


def reserve(r, t, est=None):
    return E("run.reserved", r, task=t, est=est or Z)


def start(r):
    return E("run.started", r)


def end(r, status="done", **kw):
    return E("run.ended", r, status=status, **kw)


def passed(t, ok=True):
    return E("check.result", t, name="c", ok=ok)


def complete(t, r):
    """task t を run r で最後まで進める (予約 → 開始 → 終了 → 検査 pass)"""
    return [reserve(r, t), start(r), end(r), passed(t)]


def play(events, tolerant=False):
    return drive({"scenario": {"events": events, "tolerant": tolerant}})


def ok(events):
    """全イベントが通り、不変条件違反が無い。状態を返す"""
    out = play(events)
    assert not [s for s in out["steps"] if "error" in s], out["steps"]
    assert out["violations"] == []
    assert all(s["violations"] == [] for s in out["steps"])
    return out["state"]


def rejected(events):
    """最後のイベントだけが拒否される。理由を返す"""
    out = play(events)
    assert "error" in out["steps"][-1], "拒否されるはずが通った"
    assert len(out["steps"]) == len(events)
    return out["steps"][-1]["error"]


def N(state, i):
    return state["nodes"][i]


def ser(state):
    """scenario の state (nodes が辞書) を serialize 形式 (nodes が組の配列) へ戻す"""
    s = copy.deepcopy(state)
    s["nodes"] = [[k, v] for k, v in s["nodes"].items()]
    return s


def violations(state):
    return call("check", state=ser(state))["ok"]


def invs(state):
    return {v["inv"] for v in violations(state)}


# ── a) 遷移表の全セル: 独立した仕様 ──
RUN_STATUSES = ["done", "blocked", "failed", "limit", "aborted", "lost"]
FAILS = ["failed", "limit", "aborted", "lost"]
# 仕様: kind → 状態 → {(イベント, 変種): 次の状態 ("=" は同じ)}
SPEC: dict = {"goal": {}, "task": {}, "run": {}}


def rule(kind, froms, evs, variants, to):
    for f in [froms] if isinstance(froms, str) else froms:
        for e in [evs] if isinstance(evs, str) else evs:
            for v in [variants] if isinstance(variants, str) else variants:
                SPEC[kind].setdefault(f, {})[(e, v)] = f if to == "=" else to


GOAL_ALL = ["draft", "planned", "active", "paused", "done", "cancelled"]
GOAL_LIVE = ["draft", "planned", "active", "paused"]
rule("goal", ["draft", "planned"], "plan.proposed", "*", "planned")
rule("goal", "planned", "plan.approved", "*", "active")
rule("goal", "active", "goal.paused", "*", "paused")
rule("goal", "paused", "goal.resumed", "*", "active")
rule("goal", "active", "goal.done", "*", "done")
rule("goal", GOAL_LIVE, "verdict", "cancel", "cancelled")
rule("goal", "active", "verdict", ["done", "continue"], "=")
rule("goal", GOAL_ALL, "note.appended", "*", "=")
rule("goal", GOAL_LIVE, ["budget.adjusted", "lease.acquired", "wait.opened"], "*", "=")
rule("goal", GOAL_ALL, ["lease.released", "lease.expired"], "*", "=")
rule("goal", GOAL_LIVE, "wait.resolved", ["remain", "live", "idle"], "=")

TASK_ALL = [
    "proposed",
    "ready",
    "running",
    "waiting",
    "checking",
    "done",
    "failed",
    "blocked",
    "cancelled",
    "skipped",
]
rule("task", "proposed", "plan.approved", "*", "ready")
rule("task", "ready", "run.reserved", "*", "running")
rule("task", "running", "run.ended", "done", "checking")
rule("task", "running", "run.ended", "blocked", "blocked")
rule("task", "running", "run.ended", FAILS, "failed")
rule("task", ["waiting", "cancelled", "skipped"], "run.ended", RUN_STATUSES, "=")
rule("task", "checking", "check.result", "pass", "done")
rule("task", "checking", "check.result", "fail", "failed")
rule("task", "running", "wait.opened", "*", "waiting")
rule("task", ["waiting", "failed", "blocked"], "wait.opened", "*", "=")
rule("task", "waiting", "wait.resolved", "remain", "waiting")
rule("task", "waiting", "wait.resolved", "live", "running")
rule("task", "waiting", "wait.resolved", "idle", "ready")
rule("task", ["failed", "blocked"], "wait.resolved", ["remain", "live", "idle"], "=")
rule("task", ["failed", "blocked"], "verdict", "retry", "ready")
rule("task", "failed", "verdict", "block", "blocked")
rule(
    "task",
    ["proposed", "ready", "running", "waiting", "checking", "failed", "blocked"],
    "verdict",
    "cancel",
    "cancelled",
)
rule("task", ["proposed", "ready"], "verdict", "skip", "skipped")
rule("task", ["proposed", "ready"], "edge.added", "*", "=")
rule("task", TASK_ALL, ["edge.rejected", "note.appended"], "*", "=")
rule(
    "task",
    ["proposed", "ready", "running", "waiting", "checking", "failed", "blocked"],
    "budget.adjusted",
    "*",
    "=",
)

RUN_ALL = ["reserved", "started", "done", "blocked", "failed", "limit", "aborted", "lost"]
rule("run", "reserved", "run.started", "*", "started")
rule("run", "started", "run.usage", "*", "started")
for st in RUN_STATUSES:
    rule("run", "started", "run.ended", st, st)
for st in FAILS:
    rule("run", "reserved", "run.ended", st, st)
rule("run", RUN_ALL, "note.appended", "*", "=")

STATES = {"goal": GOAL_ALL, "task": TASK_ALL, "run": RUN_ALL}
# イベントが別の種類のノード専用で、対象の種類を取り違えて ReduceError になるもの (TransitionError ではない)
KIND_ONLY = {
    "goal": {"check.result", "edge.added", "edge.rejected"},
    "task": {
        "goal.paused",
        "goal.resumed",
        "goal.done",
        "lease.acquired",
        "lease.released",
        "lease.expired",
    },
    "run": {
        "check.result",
        "edge.added",
        "edge.rejected",
        "wait.resolved",
        "goal.paused",
        "goal.resumed",
        "goal.done",
    }
    | {"lease.acquired", "lease.released", "lease.expired"},
}


@lru_cache(maxsize=1)
def cells():
    out = {}
    for c in drive({"cells": True})["cells"]:
        if c["applicable"]:
            out[(c["kind"], c["from"], c["on"], c["variant"])] = c
    return out


def test_cells_count_and_spec_cover_table():
    """driver の全セル (792 のうち、状態に引ける 778) と、仕様の定義の総数が合う"""
    defined = sum(len(v) for kind in SPEC.values() for v in kind.values())
    assert len(cells()) == 778
    assert defined == sum(1 for c in cells().values() if c["table"] is not None)
    assert (
        sum(1 for c in cells().values() if c["actual"] is not None) == defined + 9
    )  # 9 = task の plan.approved の連鎖 (goal 宛てのイベントで、task は動かない。下で別に検証)


@pytest.mark.parametrize("kind,state", [(k, s) for k, ss in STATES.items() for s in ss])
def test_transition_cells(kind, state):
    spec = SPEC[kind].get(state, {})
    n = 0
    for (k, f, on, variant), c in cells().items():
        if (k, f) != (kind, state):
            continue
        n += 1
        want = spec.get((on, variant))
        if kind == "task" and on == "plan.approved" and state != "proposed":
            # 利用者専用の plan.approved は goal へ向く。task へは goal の承認が連鎖するだけで、直接の遷移は無い
            assert want is None and c["table"] is None and c["actual"] == state
            continue
        if want is not None:
            assert c["table"] == want, c
            assert c["actual"] == want, c  # 表と、実際の reduce の結果が一致する
        else:
            assert c["table"] is None and c["actual"] is None, c
            etype = c["error"].split(":")[0]
            assert etype == (
                "ReduceError"
                if on in KIND_ONLY[kind] or (kind == "run" and on == "wait.resolved")
                else "TransitionError"
            ), c
    assert n > 20


def test_undefined_cells_are_many_and_all_rejected():
    und = [c for c in cells().values() if c["table"] is None and c["actual"] is None]
    assert len(und) > 500
    assert all("error" in c for c in und)


# ── b) 性質試験 (seed 固定の乱数列) ──
@cache
def fuzz(seed):
    return drive({"fuzz": {"seed": seed, "runs": 40, "steps": 300}})


SEEDS = [1, 2, 3]


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_volume(seed):
    f = fuzz(seed)
    assert f["attempts"] >= 10000
    assert f["applied"] > 3000 and f["rejected"] > 500
    # 主要なイベントが一通り通っている (性質が空振りしていない)
    for t in [
        "goal.created",
        "node.added",
        "run.reserved",
        "run.ended",
        "wait.opened",
        "wait.resolved",
        "verdict",
        "note.appended",
        "check.result",
    ]:
        assert f["byType"].get(t, 0) > 0, t


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_invariants_hold(seed):
    assert fuzz(seed)["violations"] == []


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_deterministic(seed):
    assert fuzz(seed)["nondeterministic"] == []


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_does_not_mutate_input(seed):
    assert fuzz(seed)["mutated"] == []


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_fold_prefix_and_snapshot(seed):
    assert fuzz(seed)["prefixMismatch"] == []


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_model_cannot_emit_user_only(seed):
    assert fuzz(seed)["rejectedUserOnlyFromModel"] > 0


def test_fold_prefix_plus_tail_by_hand():
    evs = [
        *goal(budget=M(10, 1000, 10**5)),
        task("t1"),
        task("t2", after=["t1"]),
        *complete("t1", "r1"),
        E("note.appended", "t2", by="llm", text="x"),
    ]
    whole = play(evs)["state"]
    for cut in range(1, len(evs) + 1):
        assert play(evs[:cut])["state"]["seq"] == cut
    assert whole["seq"] == len(evs)
    # 各接頭辞の状態は、全体の途中の状態と一致する (逐次の畳み込みと同じ)
    assert N(play(evs[:-1])["state"], "t2")["notes"] == []
    assert len(N(whole, "t2")["notes"]) == 1


# ── c) 循環の拒否 ──
def chain_events(n):
    return (
        goal()
        + [task(f"t{i}") for i in range(n)]
        + [
            E("edge.added", f"t{i + 1}", **{"from": f"t{i + 1}", "to": f"t{i}"})
            for i in range(n - 1)
        ]
    )


@pytest.mark.parametrize("n", [2, 3, 5, 100])
def test_cycle_rejected_in_chain(n):
    evs = [*chain_events(n), E("edge.added", "t0", **{"from": "t0", "to": f"t{n - 1}"})]
    s = ok(evs)
    assert N(s, "t0")["after"] == []  # 閉じる辺は足されない
    assert [(r["from"], r["to"], r["reason"]) for r in s["rejections"]] == [
        ("t0", f"t{n - 1}", "cycle")
    ]
    assert N(s, f"t{n - 1}")["after"] == [f"t{n - 2}"]
    assert "I1" not in invs(s)


def test_self_dependency_rejected():
    s = ok([*goal(), task("a"), E("edge.added", "a", **{"from": "a", "to": "a"})])
    assert N(s, "a")["after"] == []
    assert s["rejections"][0]["reason"] == "cycle"


def test_acyclic_edge_is_accepted_and_idempotent():
    s = ok(
        [
            *goal(),
            task("a"),
            task("b"),
            E("edge.added", "b", **{"from": "b", "to": "a"}),
            E("edge.added", "b", **{"from": "b", "to": "a"}),
        ]
    )
    assert N(s, "b")["after"] == ["a"]
    assert s["rejections"] == []


def test_diamond_is_not_a_cycle():
    s = ok(
        [
            *goal(),
            task("a"),
            task("b", after=["a"]),
            task("c", after=["a"]),
            task("d", after=["b", "c"]),
            E("edge.added", "d", **{"from": "d", "to": "a"}),
        ]
    )
    assert N(s, "d")["after"] == ["b", "c", "a"]


def test_resolve_edge_turns_cycle_into_rejected():
    base = ok([*goal(), task("a"), task("b", after=["a"])])
    r = call(
        "resolveEdge",
        {"type": "edge.added", "node": "a", "data": {"from": "a", "to": "b"}},
        state=ser(base),
    )
    assert r["ok"]["type"] == "edge.rejected" and r["ok"]["data"]["reason"] == "cycle"
    r2 = call(
        "resolveEdge",
        {"type": "edge.added", "node": "b", "data": {"from": "b", "to": "a"}},
        state=ser(base),
    )
    assert r2["ok"]["type"] == "edge.added"


def test_edge_to_other_goal_is_rejected():
    msg = rejected(
        goal()
        + goal("H")
        + [task("a"), task("b", parent="H"), E("edge.added", "a", **{"from": "a", "to": "b"})]
    )
    assert "同じ goal" in msg


# ── d) 合流性 ──
@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_confluence_independent_runs(order):
    base = goal() + goal("H") + [task("a"), task("b"), task("c", parent="H")]
    runs = [("a", "ra"), ("b", "rb"), ("c", "rc")]
    ref = ok(base + [e for t, r in runs for e in complete(t, r)])
    interleaved = []
    for i in order:
        t, r = runs[i]
        interleaved += [reserve(r, t)]
    for i in order:
        interleaved += [start(runs[i][1])]
    for i in order:
        interleaved += [end(runs[i][1])]
    for i in order:
        interleaved += [passed(runs[i][0])]
    got = ok(base + interleaved)
    # 証拠の id には seq が入るので、完了順を入れ替えるとそこだけ変わる (合流性は seq を除いて成り立つ)
    norm = lambda n: {**n, "evidence": [e.split(":")[0] for e in n["evidence"]]}  # noqa: E731
    for t in ["G", "H", "a", "b", "c", "ra", "rb", "rc"]:
        assert norm(N(got, t)) == norm(N(ref, t)), t


# ── e) globsMayOverlap ──
@cache
def overlap(seed):
    return drive({"overlap": {"seed": seed, "samples": 100000}})


@pytest.mark.parametrize("seed", [1, 2])
def test_globs_no_false_negative_bruteforce(seed):
    o = overlap(seed)
    assert o["misses"] == []
    assert o["pairs"] >= 100000 and o["trueOverlap"] > 10000
    assert o["exactDisjoint"] > 10000  # 保守的すぎて常に「重なる」と答える実装を弾く


OVERLAP_CASES = [
    ("a/**", "a/b.ts", True),
    ("a/*.ts", "b/*.ts", False),
    ("docs/", "docs/x.md", True),
    ("a/*.ts", "b/*.md", False),
    ("src/a.ts", "src/a.ts", True),
    ("src/a.ts", "src/b.ts", False),
    ("**/*.md", "docs/x.md", True),
    ("a/", "b/", False),
    ("a/?.ts", "a/b.ts", True),
    ("x/**", "**", True),
    ("./a/b", "a/b", True),
    ("a/b/c.ts", "a/b", True),
]


@pytest.mark.parametrize("a,b,want", OVERLAP_CASES)
def test_globs_known_cases(a, b, want):
    assert call("globsMayOverlap", a, b)["ok"] is want
    assert call("globsMayOverlap", b, a)["ok"] is want  # 対称


def test_write_sets_overlap_and_empty():
    assert call("writeSetsMayOverlap", ["a/*"], ["b/*", "a/x"])["ok"] is True
    assert call("writeSetsMayOverlap", [], ["a/**"])["ok"] is False
    assert call("writeSetsMayOverlap", ["a/*.ts"], ["b/*.ts", "c/"])["ok"] is False


# ── f) 利用者専用イベント ──
def user_only_setup(kind):
    """kind の利用者専用イベントを出せる直前の状態と、そのイベント (出所は後で差し替える)"""
    if kind == "plan.approved":
        return goal(approve=False), E("plan.approved", "G", hash="h")
    if kind == "budget.adjusted":
        return goal(budget=M(5, 500, 5000)), E("budget.adjusted", "G", budget=M(9, 900, 9000))
    return [*goal(), E("goal.paused", "G", reason="r")], E("goal.resumed", "G")


@pytest.mark.parametrize("kind", ["plan.approved", "budget.adjusted", "goal.resumed"])
@pytest.mark.parametrize("src", ["model", "system", "x"])
def test_user_only_events_rejected_from_non_user(kind, src):
    pre, ev = user_only_setup(kind)
    ev["source"] = src
    assert "利用者専用" in rejected([*pre, ev])


@pytest.mark.parametrize("kind", ["plan.approved", "budget.adjusted", "goal.resumed"])
def test_user_only_events_accepted_from_user(kind):
    pre, ev = user_only_setup(kind)
    ev["source"] = "user"
    s = ok([*pre, ev])
    assert N(s, "G")["state"] == "active"


def test_user_wait_only_resolved_by_user():
    pre = [
        *goal(),
        task("a"),
        reserve("r", "a"),
        start("r"),
        E(
            "wait.opened",
            "a",
            wait={"on": "user", "ref": "w", "since": 1, "auto": False, "prompt": "p"},
        ),
    ]
    assert "I5" in rejected([*pre, E("wait.resolved", "a", ref="w", by="run", source="system")])
    assert "利用者専用" in rejected(
        [*pre, E("wait.resolved", "a", ref="w", by="user", source="model")]
    )
    s = ok([*pre, E("wait.resolved", "a", ref="w", by="user", source="user")])
    assert N(s, "a")["waits"] == [] and N(s, "a")["state"] == "running"


def test_user_wait_cannot_be_auto():
    pre = [*goal(), task("a"), reserve("r", "a"), start("r")]
    msg = rejected(
        [
            *pre,
            E(
                "wait.opened",
                "a",
                wait={"on": "user", "ref": "w", "since": 1, "auto": True, "prompt": "p"},
            ),
        ]
    )
    assert "auto" in msg


def test_auto_wait_resolved_by_matching_fact_only():
    pre = [
        *goal(),
        task("a"),
        reserve("r", "a"),
        start("r"),
        E("wait.opened", "a", wait={"on": "job", "ref": "j", "since": 1, "auto": True}),
    ]
    assert "I5" in rejected([*pre, E("wait.resolved", "a", ref="j", by="merge", source="system")])
    s = ok([*pre, E("wait.resolved", "a", ref="j", by="job", source="system")])
    assert N(s, "a")["state"] == "running"


def test_plan_approval_requires_matching_hash():
    msg = rejected([*goal(approve=False), E("plan.approved", "G", source="user", hash="zz")])
    assert "hash" in msg


def test_plan_approval_promotes_proposed_tasks():
    s = ok([*goal(approve=False), task("a"), task("b", after=["a"])])
    assert N(s, "a")["state"] == "proposed"
    s2 = ok([*goal(approve=False), task("a"), E("plan.approved", "G", source="user", hash="h")])
    assert N(s2, "a")["state"] == "ready" and N(s2, "G")["attrs"]["approvedBy"] == "user"


# ── g) 予算 ──
B = M(10, 1000, 100000)


def test_budget_reserve_moves_up_hierarchy():
    s = ok([*goal(budget=B), task("t"), reserve("r", "t", M(4, 400, 1000))])
    for n in ["G", "t", "r"]:
        assert N(s, n)["reserved"] == M(4, 400, 1000)
        assert N(s, n)["spent"] == Z


def test_budget_usage_moves_from_reserved_to_spent():
    s = ok(
        [
            *goal(budget=B),
            task("t"),
            reserve("r", "t", M(4, 400, 1000)),
            start("r"),
            E("run.usage", "r", usage=M(1, 100, 300)),
        ]
    )
    for n in ["G", "t", "r"]:
        assert N(s, n)["spent"] == M(1, 100, 300)
        assert N(s, n)["reserved"] == M(4, 400, 1000)  # 見積りの範囲では予約は変わらない


def test_budget_unused_reservation_released_at_run_end():
    s = ok(
        [
            *goal(budget=B),
            task("t"),
            reserve("r", "t", M(4, 400, 1000)),
            start("r"),
            E("run.usage", "r", usage=M(1, 100, 300)),
            end("r"),
        ]
    )
    for n in ["G", "t", "r"]:
        assert N(s, n)["reserved"] == M(1, 100, 300)
        assert N(s, n)["spent"] == M(1, 100, 300)


def test_budget_release_via_run_end_usage():
    s = ok(
        [
            *goal(budget=B),
            task("t"),
            reserve("r", "t", M(4, 400, 1000)),
            start("r"),
            end("r", usage=M(2, 0, 0)),
        ]
    )
    assert N(s, "G")["reserved"]["usd"] == 2 and N(s, "G")["reserved"]["tokens"] == 0


def test_budget_over_reservation_rejected():
    pre = [*goal(budget=B), task("t1"), task("t2"), reserve("r1", "t1", M(4, 400, 1000))]
    assert "予算超過" in rejected([*pre, reserve("r2", "t2", M(7, 0, 0))])
    ok([*pre, reserve("r2", "t2", M(6, 600, 99000))])  # ちょうど上限は通る


def test_budget_released_reservation_can_be_reused():
    pre = [
        *goal(budget=B),
        task("t1"),
        task("t2"),
        reserve("r1", "t1", M(9, 0, 0)),
        start("r1"),
        end("r1"),
    ]
    ok([*pre, reserve("r2", "t2", M(9, 0, 0))])


def test_task_budget_limits_its_own_runs():
    pre = [*goal(budget=B), task("t", budget=M(2, 200, 2000))]
    assert "予算超過: t" in rejected([*pre, reserve("r", "t", M(3, 0, 0))])


def test_usage_over_estimate_raises_reservation():
    s = ok(
        [
            *goal(budget=B),
            task("t"),
            reserve("r", "t", M(1, 0, 0)),
            start("r"),
            E("run.usage", "r", usage=M(3, 0, 0)),
        ]
    )
    assert N(s, "G")["reserved"]["usd"] == 3 and N(s, "G")["spent"]["usd"] == 3


def test_budget_adjust_below_reserved_rejected_and_above_ok():
    pre = [*goal(budget=B), task("t"), reserve("r", "t", M(4, 0, 0))]
    assert "予約" in rejected(
        [*pre, E("budget.adjusted", "G", source="user", budget=M(3, 1000, 100000))]
    )
    s = ok([*pre, E("budget.adjusted", "G", source="user", budget=M(30, 1000, 100000))])
    assert N(s, "G")["budget"]["usd"] == 30


def test_budget_status_levels():
    s = ok([*goal(budget=B), task("t"), reserve("r", "t", M(8, 100, 1000))])
    st = call("budgetStatus", N(s, "G"))["ok"]
    assert st["usd"] == {"budget": 10, "spent": 0, "reserved": 8, "remaining": 2, "level": "warn"}
    assert st["tokens"]["level"] == "ok" and st["tokens"]["remaining"] == 900
    nb = call("budgetStatus", N(s, "r"))["ok"]
    assert (
        nb["usd"]["budget"] is None
        and nb["usd"]["level"] == "ok"
        and nb["usd"]["remaining"] is None
    )


def test_budget_status_over():
    n = {"budget": M(1, 1, 1), "spent": M(2, 0, 0), "reserved": M(2, 0, 0)}
    assert call("budgetStatus", n)["ok"]["usd"]["level"] == "over"


def test_run_usage_on_reserved_run_rejected():
    assert "未定義" in rejected(
        [
            *goal(budget=B),
            task("t"),
            reserve("r", "t", M(1, 0, 0)),
            E("run.usage", "r", usage=M(1, 0, 0)),
        ]
    )


def test_budget_hierarchy_sums_children():
    s = ok(
        [
            *goal(budget=B),
            task("t1"),
            task("t2"),
            reserve("r1", "t1", M(2, 0, 0)),
            reserve("r2", "t2", M(3, 0, 0)),
        ]
    )
    assert N(s, "G")["reserved"]["usd"] == 5


# ── h) ready ──
def ids(r):
    return [n["id"] for n in r["ok"]]


def test_ready_basic_after_and_state():
    evs = [*goal(), task("a"), task("b", after=["a"])]
    assert ids(call("ready", events=evs)) == ["a"]
    assert ids(call("ready", events=evs + complete("a", "r"))) == ["b"]


def test_ready_priority_critical_path_first():
    evs = [
        *goal(),
        task("a", attrs={"estimateMs": 10}),
        task("b", attrs={"estimateMs": 50}),
        task("c", after=["b"], attrs={"estimateMs": 30}),
    ]
    assert ids(call("ready", events=evs)) == ["b", "a"]  # b → c の路 (80) が a (10) より長い


def test_ready_priority_bundle_then_cost_then_id():
    evs = [
        *goal(),
        task("z", attrs={"bundle": "x", "estUsd": 5}),
        task("y", attrs={"estUsd": 1}),
        task("x", attrs={"estUsd": 1}),
        task("w", attrs={"estUsd": 3}),
    ]
    assert ids(call("ready", {"bundle": "x"}, events=evs)) == [
        "z",
        "x",
        "y",
        "w",
    ]  # bundle → 費用 → id
    assert ids(call("ready", events=evs)) == ["x", "y", "w", "z"]


def test_ready_excludes_overlap_with_running_writes():
    evs = [
        *goal(),
        task("run", writes=["a/**"]),
        task("y", writes=["a/f.ts"]),
        task("z", writes=["b/**"]),
        reserve("r", "run"),
        start("r"),
    ]
    assert ids(call("ready", events=evs)) == ["z"]


def test_ready_excludes_overlap_while_waiting_or_checking():
    base = [
        *goal(),
        task("run", writes=["a/**"]),
        task("y", writes=["a/f.ts"]),
        reserve("r", "run"),
        start("r"),
    ]
    assert ids(call("ready", events=[*base, end("r")])) == []  # checking
    w = [
        *base,
        E(
            "wait.opened",
            "run",
            wait={"on": "user", "ref": "w", "since": 1, "auto": False, "prompt": "p"},
        ),
    ]
    assert ids(call("ready", events=w)) == []  # waiting


def test_ready_picks_only_one_of_mutually_overlapping_candidates():
    evs = [
        *goal(),
        task("a", writes=["x/**"]),
        task("b", writes=["x/f"]),
        task("c", writes=["y/**"]),
    ]
    got = ids(call("ready", events=evs))
    assert got == ["a", "c"]


def test_ready_frees_writes_after_task_done():
    evs = [
        *goal(),
        task("run", writes=["a/**"]),
        task("y", writes=["a/f.ts"]),
        *complete("run", "r"),
    ]
    assert ids(call("ready", events=evs)) == ["y"]


def test_ready_skipped_dependency_counts_as_satisfied_but_cancelled_not():
    evs = [
        *goal(),
        task("a"),
        task("b", after=["a"]),
        E("verdict", "a", verdict="skip", reason="r"),
    ]
    assert ids(call("ready", events=evs)) == ["b"]
    evs2 = [
        *goal(),
        task("a"),
        task("b", after=["a"]),
        E("verdict", "a", verdict="cancel", reason="r"),
    ]
    assert ids(call("ready", events=evs2)) == []


def test_ready_requires_active_goal_and_respects_limit():
    evs = [*goal(), task("a"), task("b"), task("c")]
    assert ids(call("ready", {"limit": 2}, events=evs)) == ["a", "b"]
    assert ids(call("ready", {"limit": 0}, events=evs)) == []
    assert ids(call("ready", events=[*evs, E("goal.paused", "G", reason="r")])) == []
    assert ids(call("ready", events=[*goal(approve=False), task("a")])) == []


def test_critical_paths_lengths():
    evs = [
        *goal(),
        task("a", attrs={"estimateMs": 10}),
        task("b", after=["a"], attrs={"estimateMs": 5}),
        task("c", after=["a"]),
    ]
    cp = call("criticalPaths", events=evs)["ok"]
    assert cp["a"] == 15 and cp["b"] == 5 and cp["c"] == 1


def test_ready_does_not_mutate_and_deterministic():
    evs = [*goal(), task("a"), task("b", writes=["q/*"]), task("c", writes=["q/x"])]
    assert call("ready", events=evs) == call("ready", events=evs)


# ── i) 不変条件の否定試験 ──
def healthy():
    return ok(
        [
            *goal(budget=B),
            task("a", writes=["a/*"]),
            task("b", writes=["b/*"], after=["a"]),
            *complete("a", "r1"),
        ]
    )


def test_healthy_state_has_no_violations():
    assert violations(healthy()) == []


def mutate(fn):
    s = healthy()
    fn(s["nodes"], s)
    return s


def test_i1_cycle_and_dangling():
    assert "I1" in invs(mutate(lambda n, s: n["a"]["after"].append("b")))
    assert "I1" in invs(mutate(lambda n, s: n["a"]["after"].append("zzz")))


def test_i2_running_without_run_or_wait():
    def f(n, s):
        n["b"]["state"] = "running"

    assert "I2" in invs(mutate(f))

    def g(n, s):
        n["b"]["state"] = "waiting"

    assert "I2" in invs(mutate(g))


def test_i3_spent_over_reserved_budget_and_children():
    assert "I3" in invs(mutate(lambda n, s: n["a"]["spent"].update(usd=99)))
    assert "I3" in invs(mutate(lambda n, s: n["G"]["reserved"].update(usd=99)))  # budget 超過
    assert "I3" in invs(
        mutate(lambda n, s: n["r1"]["reserved"].update(usd=5))
    )  # 親が子の合計を下回る
    assert "I3" in invs(mutate(lambda n, s: n["a"]["reserved"].update(tokens=-1)))


def test_i3_spent_decrease_detected_with_prev():
    prev = ok(
        [
            *goal(budget=B),
            task("a"),
            reserve("r", "a", M(2, 0, 0)),
            start("r"),
            E("run.usage", "r", usage=M(1, 0, 0)),
        ]
    )
    cur = copy.deepcopy(prev)
    for n in ["G", "a", "r"]:
        cur["nodes"][n]["spent"]["usd"] = 0
    v = call("check", {"$state": ser(prev)}, state=ser(cur))["ok"]
    assert any(x["inv"] == "I3" and "減った" in x["message"] for x in v)


def test_i4_overlapping_writes_of_active_tasks():
    def f(n, s):
        n["a"]["state"] = n["b"]["state"] = "checking"
        n["a"]["writes"] = ["x/*"]
        n["b"]["writes"] = ["x/f.ts"]

    assert "I4" in invs(mutate(f))


def test_i4_disjoint_active_tasks_are_fine():
    def f(n, s):
        n["a"]["state"] = n["b"]["state"] = "checking"

    assert "I4" not in invs(mutate(f))


def test_i5_wait_shape_and_resolution_source():
    assert "I5" in invs(
        mutate(
            lambda n, s: n["b"]["waits"].append(
                {"on": "user", "ref": "w", "since": 1, "auto": True}
            )
        )
    )
    dup = {"on": "job", "ref": "j", "since": 1, "auto": True}
    assert "I5" in invs(mutate(lambda n, s: n["b"]["waits"].extend([dup, dup])))
    assert "I5" in invs(
        mutate(
            lambda n, s: s["resolutions"].append(
                {"seq": 1, "node": "b", "ref": "w", "on": "user", "by": "user", "source": "model"}
            )
        )
    )
    assert "I5" in invs(
        mutate(
            lambda n, s: s["resolutions"].append(
                {"seq": 1, "node": "b", "ref": "w", "on": "user", "by": "run", "source": "system"}
            )
        )
    )


def test_i6_done_without_check_evidence_and_goal_done_rules():
    assert "I6" in invs(mutate(lambda n, s: n["a"].update(evidence=[])))

    def f(n, s):
        n["G"]["state"] = "done"
        n["G"]["evidence"] = ["verdict:9:done"]

    assert "I6" in invs(mutate(f))  # b が未決着

    def g(n, s):
        n["G"]["state"] = "done"

    assert "I6" in invs(mutate(g))  # verdict done が無い


def test_i7_notes_append_only_and_shape():
    prev = ok([*goal(), task("a"), E("note.appended", "a", by="llm", text="x")])
    cur = copy.deepcopy(prev)
    cur["nodes"]["a"]["notes"][0]["text"] = "書き換え"
    assert any(x["inv"] == "I7" for x in call("check", {"$state": ser(prev)}, state=ser(cur))["ok"])
    cur2 = copy.deepcopy(prev)
    cur2["nodes"]["a"]["notes"] = []
    assert any(
        x["inv"] == "I7" for x in call("check", {"$state": ser(prev)}, state=ser(cur2))["ok"]
    )
    cur3 = copy.deepcopy(prev)
    del cur3["nodes"]["a"]
    assert any(
        x["inv"] == "I7" and "消えた" in x["message"]
        for x in call("check", {"$state": ser(prev)}, state=ser(cur3))["ok"]
    )
    assert "I7" in invs(
        mutate(lambda n, s: n["a"]["notes"].append({"by": "llm", "at": 1, "text": "x" * 301}))
    )
    assert "I7" in invs(
        mutate(lambda n, s: n["a"]["notes"].append({"by": "bot", "at": 1, "text": "x"}))
    )


def test_i8_lease_shape():
    assert "I8" in invs(
        mutate(
            lambda n, s: n["a"].update(
                owner={"holder": "A", "pid": 1, "startedAt": 0, "heartbeat": 0}
            )
        )
    )
    assert "I8" in invs(
        mutate(
            lambda n, s: n["G"].update(
                owner={"holder": "", "pid": 1, "startedAt": 0, "heartbeat": 0}
            )
        )
    )


def test_i8_holder_mismatch_rejected_by_reducer():
    pre = [*goal(), E("lease.acquired", "G", holder="A", pid=1), task("a")]
    assert "I8" in rejected([*pre, {**E("note.appended", "a", by="llm", text="x"), "holder": "B"}])
    ok([*pre, {**E("note.appended", "a", by="llm", text="x"), "holder": "A"}])
    # data の中の holder は I8 の対象でない (専用欄だけを見る)
    ok([*pre, E("note.appended", "a", by="llm", text="x", holder="B")])
    assert "I8" in rejected([*pre, E("lease.acquired", "G", holder="B", pid=2)])
    assert "I8" in rejected([*pre, E("lease.released", "G", holder="B")])


def test_i9_seq_gap_and_duplicate():
    base = goal()
    gap = [*base, {**task("a"), "seq": 9}]
    out = play(gap, tolerant=True)
    assert any(v["inv"] == "I9" for v in out["violations"])
    dup = [*base, {**task("a"), "seq": 2}]
    assert any(v["inv"] == "I9" for v in play(dup, tolerant=True)["violations"])
    assert not any(v["inv"] == "I9" for v in play(base)["violations"])


def test_i10_goal_active_without_user_approval():
    assert "I10" in invs(mutate(lambda n, s: n["G"]["attrs"].pop("approvedBy")))


def test_aux_events_only_advance_seq():
    s = ok(
        [
            *goal(),
            {"type": "notice", "data": {"text": "x"}, "aux": True},
            {"type": "tool.call", "data": {}},
            task("a"),
        ]
    )
    assert s["seq"] == 6 and set(s["nodes"]) == {"G", "a"}


# ── j) 二重配送・不正入力の拒否 ──
def test_run_ended_twice_rejected():
    pre = [*goal(), task("a"), reserve("r", "a"), start("r"), end("r")]
    assert "未定義" in rejected([*pre, end("r")])
    assert "未定義" in rejected([*pre, end("r", "failed")])


def test_goal_created_twice_rejected():
    assert "既にある" in rejected([*goal(), E("goal.created", "G", title="G")])


def test_node_added_duplicate_id_rejected():
    assert "既にある" in rejected([*goal(), task("a"), task("a")])


def test_plan_approved_twice_rejected():
    assert "未定義" in rejected([*goal(), E("plan.approved", "G", source="user", hash="h")])


def test_run_reserved_twice_for_one_task_rejected():
    assert "未定義" in rejected([*goal(), task("a"), reserve("r1", "a"), reserve("r2", "a")])


def test_run_reserved_blocked_by_unfinished_dependency():
    assert "未完了" in rejected([*goal(), task("a"), task("b", after=["a"]), reserve("r", "b")])


def test_run_reserved_blocked_by_overlapping_writes():
    pre = [*goal(), task("a", writes=["x/**"]), task("b", writes=["x/y"]), reserve("r", "a")]
    assert "重なる" in rejected([*pre, reserve("r2", "b")])


def test_run_reserved_requires_active_goal():
    assert "active" in rejected(
        [*goal(), task("a"), E("goal.paused", "G", reason="r"), reserve("r", "a")]
    )


def test_invalid_payloads_rejected():
    assert "title" in rejected([E("goal.created", "G")])
    assert "note.appended" in rejected([*goal(), E("note.appended", "G", by="llm", text="x" * 301)])
    assert "by" in rejected([*goal(), E("note.appended", "G", by="bot", text="x")])
    assert "node" in rejected(
        [*goal(), {"type": "verdict", "data": {"verdict": "cancel", "reason": "r"}}]
    )


def test_node_added_to_finished_goal_rejected():
    pre = [*goal(), E("verdict", "G", verdict="cancel", reason="r")]
    assert "終わった" in rejected([*pre, task("a")])


def test_goal_done_needs_verdict_and_settled_tasks():
    pre = [*goal(), task("a")]
    assert "I6" in rejected([*pre, E("goal.done", "G")])
    pre2 = [*pre, E("verdict", "G", verdict="done", reason="r")]
    assert "I6" in rejected([*pre2, E("goal.done", "G")])
    s = ok([*pre2, E("verdict", "a", verdict="cancel", reason="r"), E("goal.done", "G")])
    assert N(s, "G")["state"] == "done"


# ── k) 注釈は追記のみ ──
def test_notes_append_in_order_on_any_node():
    s = ok(
        [
            *goal(),
            task("a"),
            E("note.appended", "a", by="user", text="1"),
            E("note.appended", "a", by="llm", text="2"),
            E("note.appended", "a", by="run:r1", text="3"),
        ]
    )
    assert [x["text"] for x in N(s, "a")["notes"]] == ["1", "2", "3"]
    assert [x["by"] for x in N(s, "a")["notes"]] == ["user", "llm", "run:r1"]


def test_notes_allowed_on_finished_nodes_and_do_not_change_state():
    s = ok(
        [
            *goal(),
            task("a"),
            *complete("a", "r"),
            E("note.appended", "a", by="llm", text="x"),
            E("note.appended", "r", by="llm", text="y"),
        ]
    )
    assert N(s, "a")["state"] == "done" and N(s, "r")["state"] == "done"
    assert len(N(s, "a")["notes"]) == 1 and len(N(s, "r")["notes"]) == 1


def test_notes_prefix_never_changes():
    evs = goal() + [task("a")] + [E("note.appended", "a", by="llm", text=str(i)) for i in range(5)]
    prev = ok(evs[:6])
    cur = ok(evs)
    k = len(N(prev, "a")["notes"])
    assert N(cur, "a")["notes"][:k] == N(prev, "a")["notes"]
    assert call("check", {"$state": ser(prev)}, state=ser(cur))["ok"] == []


def test_note_max_exactly_300_ok():
    ok([*goal(), E("note.appended", "G", by="llm", text="あ" * 300)])


# ── 状態遷移の経路 ──
def test_full_lifecycle_to_goal_done():
    s = ok(
        [
            *goal(),
            task("a"),
            *complete("a", "r"),
            E("verdict", "G", verdict="done", reason="r"),
            E("goal.done", "G"),
        ]
    )
    assert [N(s, x)["state"] for x in ["G", "a", "r"]] == ["done", "done", "done"]
    assert N(s, "a")["evidence"] == ["check:8"] or N(s, "a")["evidence"][0].startswith("check:")


def test_check_fail_then_retry_goes_ready_and_counts_attempts():
    s = ok(
        [
            *goal(),
            task("a"),
            reserve("r", "a"),
            start("r"),
            end("r"),
            passed("a", False),
            E("verdict", "a", verdict="retry", reason="r"),
        ]
    )
    assert N(s, "a")["state"] == "ready" and N(s, "a")["attrs"]["attempts"] == 1
    s2 = ok(
        [
            *goal(),
            task("a"),
            reserve("r", "a"),
            start("r"),
            end("r", "failed"),
            E("verdict", "a", verdict="block", reason="r"),
        ]
    )
    assert N(s2, "a")["state"] == "blocked"


@pytest.mark.parametrize(
    "status,task_state",
    [
        ("done", "checking"),
        ("blocked", "blocked"),
        ("failed", "failed"),
        ("limit", "failed"),
        ("aborted", "failed"),
        ("lost", "failed"),
    ],
)
def test_run_end_status_maps_to_task_state(status, task_state):
    s = ok([*goal(), task("a"), reserve("r", "a"), start("r"), end("r", status)])
    assert N(s, "r")["state"] == status and N(s, "a")["state"] == task_state


def test_wait_open_and_resolve_back_to_running_or_ready():
    w = E(
        "wait.opened",
        "a",
        wait={"on": "user", "ref": "w", "since": 1, "auto": False, "prompt": "p"},
    )
    res = E("wait.resolved", "a", source="user", ref="w", by="user")
    s = ok([*goal(), task("a"), reserve("r", "a"), start("r"), w])
    assert N(s, "a")["state"] == "waiting"
    assert (
        N(ok([*goal(), task("a"), reserve("r", "a"), start("r"), w, res]), "a")["state"]
        == "running"
    )
    # 走る run が終わっていれば、解除で ready へ戻る
    assert (
        N(ok([*goal(), task("a"), reserve("r", "a"), start("r"), w, end("r"), res]), "a")["state"]
        == "ready"
    )


def test_wait_remain_stays_waiting():
    w1 = E("wait.opened", "a", wait={"on": "job", "ref": "j1", "since": 1, "auto": True})
    w2 = E("wait.opened", "a", wait={"on": "job", "ref": "j2", "since": 2, "auto": True})
    s = ok(
        [
            *goal(),
            task("a"),
            reserve("r", "a"),
            start("r"),
            w1,
            w2,
            E("wait.resolved", "a", ref="j1", by="job"),
        ]
    )
    assert N(s, "a")["state"] == "waiting" and len(N(s, "a")["waits"]) == 1


def test_task_cancel_then_late_run_end_is_tolerated():
    s = ok(
        [
            *goal(),
            task("a"),
            reserve("r", "a"),
            start("r"),
            E("verdict", "a", verdict="cancel", reason="r"),
            end("r", "aborted"),
        ]
    )
    assert N(s, "a")["state"] == "cancelled" and N(s, "r")["state"] == "aborted"


def test_goal_pause_resume_and_cancel():
    s = ok([*goal(), E("goal.paused", "G", reason="r"), E("goal.resumed", "G", source="user")])
    assert N(s, "G")["state"] == "active" and N(s, "G")["attrs"]["resumes"] == 1
    assert (
        N(ok([*goal(), E("verdict", "G", verdict="cancel", reason="r")]), "G")["state"]
        == "cancelled"
    )


def test_lease_acquire_keep_startedAt_and_release():
    s = ok(
        [
            *goal(),
            E("lease.acquired", "G", holder="A", pid=7),
            E("lease.acquired", "G", holder="A", pid=7),
        ]
    )
    assert N(s, "G")["owner"]["holder"] == "A"
    s2 = ok(
        [*goal(), E("lease.acquired", "G", holder="A", pid=7), E("lease.released", "G", holder="A")]
    )
    assert "owner" not in N(s2, "G")


def test_check_and_integrate_follow_task_table():
    s = ok(
        [
            *goal(),
            task("a"),
            task("c", kind="check", after=["a"]),
            task("i", kind="integrate", writes=["m/*"]),
            *complete("a", "r1"),
            *complete("c", "r2"),
        ]
    )
    assert N(s, "c")["state"] == "done"
    assert N(s, "i")["state"] == "ready"


# ── 投影・イベントの検証 ──
def test_waiting_user_order_and_next_decision():
    evs = (
        goal(approve=False)
        + goal("H")
        + [task("a", parent="H"), reserve("r", "a"), start("r")]
        + [
            E(
                "wait.opened",
                "a",
                wait={"on": "user", "ref": "w", "since": 5, "auto": False, "prompt": "確認して"},
            )
        ]
        + [task("b", parent="H"), reserve("r2", "b"), start("r2"), end("r2", "blocked")]
    )
    w = call("waitingUser", events=evs)["ok"]
    assert [x["kind"] for x in w] == ["plan", "blocked", "wait"]
    assert w[0]["node"] == "G" and w[1]["node"] == "b" and w[2]["prompt"] == "確認して"
    assert call("nextDecision", events=evs)["ok"]["kind"] == "plan"
    assert call("nextDecision", events=goal())["ok"] is None


def test_make_event_enforces_source():
    r = call("makeEvent", "plan.approved", "G", {"hash": "h"}, "model")
    assert "利用者専用" in r["error"]
    r = call("makeEvent", "plan.approved", "G", {"hash": "h"}, "user")
    assert r["ok"]["data"] == {"hash": "h"} and r["ok"]["source"] == "user"
    r = call(
        "makeEvent", "note.appended", "G", {"by": "llm", "text": "x"}, "model", {"holder": "A"}
    )
    assert r["ok"]["holder"] == "A" and r["ok"]["source"] == "model"
    assert "holder" not in r["ok"]["data"] and "source" not in r["ok"]["data"]


def test_make_event_drops_source_and_holder_in_data():
    # data の中の偽装は捨てられ、model 出所の plan.approved は拒否される
    r = call("makeEvent", "plan.approved", "G", {"hash": "h", "source": "user"}, "model")
    assert "利用者専用" in r["error"]
    r = call(
        "makeEvent",
        "note.appended",
        "G",
        {"by": "llm", "text": "x", "holder": "EVIL"},
        "model",
        {"holder": "A"},
    )
    assert r["ok"]["holder"] == "A" and "holder" not in r["ok"]["data"]
    r = call(
        "makeEvent", "note.appended", "G", {"by": "llm", "text": "x", "holder": "EVIL"}, "model"
    )
    assert "holder" not in r["ok"] and "holder" not in r["ok"]["data"]
    # lease.* の data.holder はペイロードなので残る
    r = call("makeEvent", "lease.acquired", "G", {"holder": "A", "pid": 1}, "system")
    assert r["ok"]["data"]["holder"] == "A"


def test_data_source_cannot_forge_user_only_event():
    pre = [*goal(approve=False), task("a")]
    forged = {
        "type": "plan.approved",
        "node": "G",
        "data": {"hash": "h", "source": "user"},
        "source": "model",
    }
    assert "利用者専用" in rejected([*pre, forged])


def test_event_without_source_is_treated_as_system():
    # source 欄が無いイベントは system 扱い: 利用者専用は拒否、それ以外は通る
    pre = [*goal(approve=False), task("a")]
    ev = {
        "type": "plan.approved",
        "node": "G",
        "data": {"hash": "h", "source": "user"},
        "noSource": True,
    }
    assert "利用者専用" in rejected([*pre, ev])
    ok([*pre, {**E("note.appended", "a", by="llm", text="x"), "noSource": True}])


def test_edge_rejected_keeps_source():
    base = ok([*goal(), task("a"), task("b", after=["a"])])
    ev = {"type": "edge.added", "node": "a", "data": {"from": "a", "to": "b"}, "source": "model"}
    r = call("resolveEdge", ev, state=ser(base))
    assert r["ok"]["type"] == "edge.rejected" and r["ok"]["source"] == "model"
    assert "source" not in r["ok"]["data"]
    # data の中の source は引き継がれない
    ev = {"type": "edge.added", "node": "a", "data": {"from": "a", "to": "b", "source": "user"}}
    r = call("resolveEdge", ev, state=ser(base))
    assert r["ok"]["type"] == "edge.rejected" and "source" not in r["ok"]["data"]


@pytest.mark.parametrize(
    "ptype,data,frag",
    [
        ("goal.created", {}, "title"),
        ("plan.proposed", {}, "hash"),
        ("run.reserved", {"task": "t"}, "est"),
        ("run.ended", {"status": "weird"}, "status"),
        ("verdict", {"verdict": "nope", "reason": "r"}, "verdict"),
        ("wait.opened", {"wait": {"on": "user", "ref": "w", "since": 1, "auto": False}}, "prompt"),
        (
            "wait.opened",
            {"wait": {"on": "job", "ref": "w", "since": 1, "auto": True, "prompt": "あ" * 24}},
            "46",
        ),
        ("budget.adjusted", {"budget": {"usd": -1, "tokens": 0, "ms": 0}}, "Money"),
        ("lease.acquired", {"holder": "A"}, "pid"),
    ],
)
def test_validate_payload_rejects(ptype, data, frag):
    assert frag in call("validatePayload", ptype, data)["ok"]


def test_validate_payload_accepts_valid_and_aux():
    assert call("validatePayload", "run.reserved", {"task": "t", "est": Z})["ok"] is None
    assert call("validatePayload", "notice", {"anything": 1})["ok"] is None


def test_serialize_roundtrip_is_lossless():
    s = healthy()
    again = call("serialize", state=ser(s))
    assert again["ok"]["nodes"] == ser(s)["nodes"]
    assert json.loads(json.dumps(again["ok"])) == again["ok"]


def test_rejected_event_leaves_state_unchanged():
    base = [*goal(), task("a")]
    out = play([*base, reserve("r", "zzz")], tolerant=True)
    assert "error" in out["steps"][-1]
    assert out["state"]["seq"] == len(base)  # 拒否された seq は進まない
    assert out["violations"] == []
