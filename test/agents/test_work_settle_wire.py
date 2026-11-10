"""調停の配線 (autocheckpoint.ts・todo 拡張・work/settle.ts を同じ偽の pi に登録) の試験。

``test/agents/pi/work_settle_wire_driver.mjs`` が実物の 3 者を 1 つの偽の pi に登録する。
旗 ``PI_WORK_ARBITER`` が無効なら現行どおり (2 者が登録し調停は登録しない)、有効なら
``agent_before_settle`` のハンドラは調停の 1 つだけで、entries は高々 1 件・wake は高々 1 回になることを確かめる。
あわせて snapshot の組み立て (``work/settle-snapshot.ts``) の表を確かめる。

see docs/spec/work/settle.md
"""

from __future__ import annotations

import itertools
import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_settle_wire_driver.mjs"
TODO = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "todo"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def todo_path(tmp_path_factory):
    """todo 拡張を、pi の依存を偽物に差し替えた一時ディレクトリへ写す (test_pi_autocheckpoint.py と同じ流儀)"""
    ext = tmp_path_factory.mktemp("wire") / "ext"
    for name, code in (
        ("@earendil-works/pi-ai", "export const StringEnum=()=>({});"),
        (
            "@earendil-works/pi-tui",
            "export const matchesKey=()=>false;export class Text{};"
            "export const truncateToWidth=(s)=>s;export const visibleWidth=(s)=>s.length;",
        ),
        ("typebox", "const f=()=>({});export const Type=new Proxy({},{get:()=>f});"),
    ):
        stub = ext / "node_modules" / name
        stub.mkdir(parents=True, exist_ok=True)
        (stub / "package.json").write_text(
            json.dumps({"name": name, "type": "module", "main": "index.js"}), encoding="utf-8"
        )
        (stub / "index.js").write_text(code, encoding="utf-8")
    for name in ("index.ts", "view.ts"):
        (ext / name).write_text((TODO / name).read_text(encoding="utf-8"), encoding="utf-8")
    return ext / "index.ts"


def drive(payload, *args):
    proc = subprocess.run(
        [_node(), str(DRIVER), *args],
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


def wire(todo_path, flag, steps, todos=()):
    return drive(
        {"mode": "wire", "flag": flag, "steps": steps, "todos": list(todos)}, str(todo_path)
    )


DOING = [{"id": 1, "text": "作業", "status": "in_progress"}]
MIXED = [
    {"id": 1, "text": "a", "status": "pending"},
    {"id": 2, "text": "b", "status": "in_progress"},
    {"id": 3, "text": "c", "status": "blocked"},
    {"id": 4, "text": "d", "status": "done"},
]


# ─── ① 旗が無効: 現行と同じ登録 ──────────────────────────────────────


def test_flag_off_registers_the_legacy_two_handlers_and_no_arbiter(todo_path):
    out = wire(todo_path, False, [])
    assert out["handlers"]["agent_before_settle"] == 2
    assert out["registered"] is None
    # 旧コミット (3abfbf6a^) の autocheckpoint (agent_before_settle 1) と todo (session_start・session_tree・
    # before_agent_start・agent_before_settle) の合成と完全一致。調停のための ctx 捕捉・turn_end は無い
    assert out["handlers"] == {
        "agent_before_settle": 2,
        "session_start": 1,
        "session_tree": 1,
        "before_agent_start": 1,
    }
    # agent_before_settle の登録順 (autocheckpoint → todo) は結果の順で確かめる
    on = wire(todo_path, False, [{"percent": 90}], DOING)
    assert on["steps"][0]["types"] == ["autocheckpoint", "todo-reminder"]


def test_flag_off_behaviour_is_the_legacy_chain(todo_path):
    out = wire(todo_path, False, [{"percent": 90}], DOING)
    assert out["steps"][0]["types"] == ["autocheckpoint", "todo-reminder"]
    assert out["steps"][0]["wakes"] == 0


# ─── ② 旗が有効: ハンドラは 1 つ ─────────────────────────────────────


def test_flag_on_has_exactly_one_settle_handler(todo_path):
    out = wire(todo_path, True, [])
    assert out["handlers"]["agent_before_settle"] == 1
    assert out["registered"] is True


# ─── ③ 3 者が重なっても entries ≤ 1・wake ≤ 1 ───────────────────────


@pytest.mark.parametrize("percent", [None, 10, 79, 80, 95])
@pytest.mark.parametrize("todos", [[], DOING, MIXED])
def test_flag_on_entries_at_most_one_and_wake_at_most_one(todo_path, percent, todos):
    out = wire(todo_path, True, [{"percent": percent}], todos)
    s = out["steps"][0]
    assert len(s["types"]) <= 1, s
    assert s["wakes"] <= 1, s


def test_flag_on_checkpoint_wins_over_todo_when_both_ready(todo_path):
    out = wire(todo_path, True, [{"percent": 90}], DOING)
    assert out["steps"][0]["types"] == ["autocheckpoint"]
    assert out["steps"][0]["cont"] is True


def test_flag_on_todo_reminder_once_per_user_turn(todo_path):
    out = wire(
        todo_path,
        True,
        [{"percent": 10}, {"percent": 10, "userTurn": False}, {"percent": 10}],
        DOING,
    )
    types = [s["types"] for s in out["steps"]]
    assert types == [
        ["todo-reminder"],
        [],
        ["todo-reminder"],
    ]  # 利用者の発言ごとに 1 回 (従来と同じ)


def test_flag_on_matches_flag_off_on_which_provider_acts(todo_path):
    steps = [{"percent": 10}, {"percent": 10, "userTurn": False}]
    off = wire(todo_path, False, steps, DOING)
    on = wire(todo_path, True, steps, DOING)
    assert [s["types"] for s in on["steps"]] == [s["types"] for s in off["steps"]]


def test_flag_on_user_input_stops_continuation(todo_path):
    out = wire(todo_path, True, [{"percent": 90, "pending": True}], DOING)
    assert out["steps"][0]["types"] == []


# ─── ④ 保存 → 圧縮 → 再開 ───────────────────────────────────────────


def test_flag_on_save_then_compact_leaves_no_phase(todo_path):
    steps = [{"percent": 90}, {"percent": 90, "finish": "complete"}]
    out = wire(todo_path, True, steps, DOING)
    a, b = out["steps"]
    assert a["types"] == ["autocheckpoint"] and a["phase"] == "saving"
    assert (
        b["types"] == [] and b["compacts"] == 1
    )  # 保存中の settle で調停が checkpoint の効果を出す
    assert b["phase"] == "idle"
    # 圧縮完了後の自動再開は従来の経路のまま (1 回だけ)
    assert len(out["resumes"]) == 1 and "自動の再開" in out["resumes"][0]


def test_flag_on_abort_while_saving_cancels_the_cycle(todo_path):
    out = wire(todo_path, True, [{"percent": 90}, {"percent": 90, "outcome": "aborted"}], DOING)
    a, b = out["steps"]
    assert a["phase"] == "saving"
    assert b["compacts"] == 0 and b["phase"] == "idle"


def test_flag_on_error_while_saving_still_compacts(todo_path):
    out = wire(todo_path, True, [{"percent": 90}, {"percent": 90, "outcome": "error"}], DOING)
    assert out["steps"][1]["compacts"] == 1


def test_flag_off_save_then_compact_is_the_legacy_flow(todo_path):
    steps = [{"percent": 90}, {"percent": 90, "finish": "complete"}]
    out = wire(todo_path, False, steps, DOING)
    assert out["steps"][0]["types"] == ["autocheckpoint", "todo-reminder"]
    assert out["steps"][1]["compacts"] == 1


# ─── ⑤ __piTodoSnapshot ─────────────────────────────────────────────


@pytest.mark.parametrize("flag", [False, True])
def test_todo_snapshot_reports_open_count(todo_path, flag):
    out = wire(todo_path, flag, [], MIXED)
    snap = out["todoSnapshot"]
    assert snap["open"] == 3
    assert snap["doing"] == ["#2 b"] and snap["blocked"] == ["#3 c"] and snap["queued"] == ["#1 a"]
    assert snap["nudged"] is False and snap["nudgedWaiting"] is False


def test_todo_snapshot_excludes_future_items_from_queue(todo_path):
    todos = [
        {"id": 1, "text": "【将来】x", "status": "pending"},
        {"id": 2, "text": "y", "status": "pending"},
    ]
    snap = wire(todo_path, True, [], todos)["todoSnapshot"]
    assert snap["queued"] == ["#2 y"] and snap["open"] == 2


# ─── ⑥ snapshot の組み立て (表) ──────────────────────────────────────

FULL = {
    "checkpoint": {
        "phase": "idle",
        "percent": 50,
        "threshold": 80,
        "cooldown": False,
        "disabled": False,
        "llmStep": True,
        "prompt": "P",
    },
    "todo": {
        "disabled": False,
        "doing": ["#1 a"],
        "blocked": [],
        "queued": [],
        "nudged": False,
        "nudgedWaiting": False,
    },
    "ledger": {"failed": 0, "parentStep": False, "newUserWait": False},
}


def snaps(cases):
    return drive({"mode": "snap", "cases": cases})["results"]


@pytest.mark.parametrize(
    ("phase", "want", "compacting"),
    [
        ("idle", "idle", False),
        ("saving", "saving", False),
        ("compacting", "compacting", True),
        ("bogus", "compacting", True),  # 未知は継続しない側
        (None, "compacting", True),
        (3, "compacting", True),
    ],
)
def test_phase_mapping(phase, want, compacting):
    case = {**FULL, "checkpoint": {**FULL["checkpoint"], "phase": phase}}
    (s,) = snaps([case])
    assert s["phase"] == want and s["compacting"] is compacting


@pytest.mark.parametrize(
    ("percent", "want"),
    [
        (0, 0),
        (79.5, 79.5),
        (100, 100),
        (None, None),
        ("90", None),
        (None, None),
        (True, None),
    ],
)
def test_percent_normalization(percent, want):
    case = {**FULL, "checkpoint": {**FULL["checkpoint"], "percent": percent}}
    (s,) = snaps([case])
    assert s["checkpoint"]["percent"] == want


@pytest.mark.parametrize(
    ("threshold", "want"),
    [(80, 80), (50, 50), (100, 100), (0, 80), (-1, 80), (101, 80), ("x", 80), (None, 80)],
)
def test_threshold_normalization(threshold, want):
    case = {**FULL, "checkpoint": {**FULL["checkpoint"], "threshold": threshold}}
    (s,) = snaps([case])
    assert s["checkpoint"]["threshold"] == want


def test_missing_parts_fail_closed():
    for case in (
        None,
        "__undefined__",
        {},
        {"checkpoint": FULL["checkpoint"]},
        {"todo": FULL["todo"]},
    ):
        (s,) = snaps([case])
        assert s["children"] == {"failed": 0, "parentStep": False, "newUserWait": False}
        assert s["goal"]["active"] is False and s["budgetExhausted"] is False
    (s,) = snaps([{}])
    assert s["checkpoint"]["disabled"] is True and s["todo"]["disabled"] is True
    assert s["phase"] == "idle" and s["checkpoint"]["percent"] is None
    (s,) = snaps([{"checkpoint": FULL["checkpoint"]}])
    assert s["checkpoint"]["disabled"] is False and s["todo"]["disabled"] is True
    (s,) = snaps([{"todo": FULL["todo"]}])
    assert s["todo"]["disabled"] is False and s["checkpoint"]["disabled"] is True


@pytest.mark.parametrize(
    ("raw", "want"),
    [(0, 0), (1, 1), (2.9, 2), (-3, 0), ("2", 0), (None, 0)],
)
def test_children_failed_count(raw, want):
    (s,) = snaps([{**FULL, "ledger": {"failed": raw}}])
    assert s["children"]["failed"] == want


@pytest.mark.parametrize("raw", [True, False, 1, "true", None])
def test_children_flags_are_strict_booleans(raw):
    (s,) = snaps([{**FULL, "ledger": {"parentStep": raw, "newUserWait": raw}}])
    assert s["children"]["parentStep"] is (raw is True)
    assert s["children"]["newUserWait"] is (raw is True)


@pytest.mark.parametrize(
    ("streak", "max_streak", "want"),
    [
        (0, 3, (0, 3)),
        (2, 3, (2, 3)),
        (-1, 3, (0, 3)),
        ("1", 3, (0, 3)),
        (0, 0, (0, 5)),
        (0, None, (0, 5)),
        (None, None, (0, 5)),
    ],
)
def test_streak_defaults(streak, max_streak, want):
    (s,) = snaps([{**FULL, "streak": streak, "maxStreak": max_streak}])
    assert (s["streak"], s["maxStreak"]) == want


def test_todo_labels_keep_only_strings():
    todo = {**FULL["todo"], "doing": ["#1 a", 2, None], "blocked": "x", "queued": ["#3 c"]}
    (s,) = snaps([{**FULL, "todo": todo}])
    assert (
        s["todo"]["doing"] == ["#1 a"]
        and s["todo"]["blocked"] == []
        and s["todo"]["queued"] == ["#3 c"]
    )


def test_boolean_fields_are_strict_over_the_product():
    flags = [True, False, "yes", None]
    cases = [
        {
            **FULL,
            "checkpoint": {**FULL["checkpoint"], "cooldown": a, "disabled": b},
            "todo": {**FULL["todo"], "nudged": c, "nudgedWaiting": c, "disabled": b},
        }
        for a, b, c in itertools.product(flags, repeat=3)
    ]
    assert len(cases) == 64
    for case, s in zip(cases, snaps(cases), strict=True):
        cp, td = case["checkpoint"], case["todo"]
        assert s["checkpoint"]["cooldown"] is (cp["cooldown"] is True)
        # disabled === false が明示され、抑止用の旗が有効な boolean のときだけ有効 (不正は無効へ)
        cp_ok = cp["disabled"] is False and isinstance(cp["cooldown"], bool)
        assert s["checkpoint"]["disabled"] is (not cp_ok)
        assert s["todo"]["nudged"] is (td["nudged"] is True)
        td_ok = td["disabled"] is False and isinstance(td["nudged"], bool)
        assert s["todo"]["disabled"] is (not td_ok)


def test_llm_step_must_be_boolean_and_prompt_is_kept():
    (s,) = snaps([FULL])
    assert s["checkpoint"]["llmStep"] is True and s["checkpoint"]["prompt"] == "P"
    assert s["checkpoint"]["disabled"] is False
    # LLM に保存させないなら prompt は要らない
    (s,) = snaps([{**FULL, "checkpoint": {**FULL["checkpoint"], "llmStep": False, "prompt": 5}}])
    assert s["checkpoint"]["llmStep"] is False and s["checkpoint"]["prompt"] == ""
    assert s["checkpoint"]["disabled"] is False
    # llmStep の欠落は「保存させる」としては扱わず、部品を無効にする
    cp = {k: v for k, v in FULL["checkpoint"].items() if k != "llmStep"}
    (s,) = snaps([{**FULL, "checkpoint": cp}])
    assert s["checkpoint"]["disabled"] is True


# ─── 不完全な snapshot は buildSnapshot → handleSettle まで通しても継続しない ──────────────

CP_OK = {
    "phase": "idle",
    "percent": 90,
    "threshold": 80,
    "cooldown": False,
    "disabled": False,
    "llmStep": True,
    "prompt": "P",
}
TD_OK = {
    "disabled": False,
    "doing": ["#1 a"],
    "blocked": [],
    "queued": [],
    "nudged": False,
    "nudgedWaiting": False,
}


def through(cases):
    return drive({"mode": "through", "cases": cases})["results"]


def _without(d, key):
    return {k: v for k, v in d.items() if k != key}


BAD_CHECKPOINTS = [
    _without(CP_OK, "disabled"),
    {**CP_OK, "disabled": None},
    {**CP_OK, "disabled": "false"},
    {**CP_OK, "disabled": 0},
    _without(CP_OK, "cooldown"),
    {**CP_OK, "cooldown": None},
    {**CP_OK, "cooldown": "no"},
    _without(CP_OK, "llmStep"),
    {**CP_OK, "llmStep": "true"},
    _without(CP_OK, "prompt"),
    {**CP_OK, "prompt": ""},
    {**CP_OK, "prompt": "  "},
    {**CP_OK, "prompt": None},
    {**CP_OK, "prompt": 5},
    _without(CP_OK, "threshold"),
    {**CP_OK, "threshold": 0},
    {**CP_OK, "threshold": "80"},
    _without(CP_OK, "percent"),
    {**CP_OK, "percent": "90"},
    {**CP_OK, "percent": 101},
    {**CP_OK, "percent": -1},
    {**CP_OK, "percent": True},
    _without(CP_OK, "phase"),
    {**CP_OK, "phase": "bogus"},
    {"percent": 90},  # 事例: レビューの再現入力 (他は全部欠落)
]
BAD_TODOS = [
    _without(TD_OK, "disabled"),
    {**TD_OK, "disabled": None},
    {**TD_OK, "disabled": "false"},
    _without(TD_OK, "nudged"),
    {**TD_OK, "nudged": None},
    {**TD_OK, "nudged": "no"},
    _without(TD_OK, "nudgedWaiting"),
    {**TD_OK, "nudgedWaiting": 0},
    _without(TD_OK, "doing"),
    {**TD_OK, "doing": "x"},
    {**TD_OK, "doing": ["#1 a", 2]},
    {**TD_OK, "doing": None},
    {"doing": ["#1 a"]},
]


def test_the_good_baseline_does_continue():
    # 対照: 完全な入力は継続する (下の不完全の試験が空打ちでないこと)
    a, b = through([{"checkpoint": CP_OK}, {"todo": TD_OK}])
    assert a["cont"] is True and b["cont"] is True


def test_incomplete_checkpoint_never_continues_or_compacts():
    assert len(BAD_CHECKPOINTS) >= 15
    cases = [{"checkpoint": c} for c in BAD_CHECKPOINTS]
    for c, r in zip(BAD_CHECKPOINTS, through(cases), strict=True):
        assert r["cont"] is False and r["entries"] == 0 and r["checkpoint"] == [], c
        assert r["wake"] == 0, c


def test_incomplete_todo_never_continues():
    assert len(BAD_TODOS) >= 10
    cases = [{"todo": t} for t in BAD_TODOS]
    for t, r in zip(BAD_TODOS, through(cases), strict=True):
        assert r["cont"] is False and r["entries"] == 0, t


def test_incomplete_part_does_not_hide_a_complete_one():
    # 壊れた todo があっても、完全な checkpoint は動く (部品ごとの無効化)
    (r,) = through([{"checkpoint": CP_OK, "todo": BAD_TODOS[0]}])
    assert r["cont"] is True


def test_real_producers_return_complete_snapshots_that_pass(todo_path):
    """実物の producer (checkpointSnapshot・__piTodoSnapshot) の返り値は全項目を持ち、無効にされない"""
    out = wire(todo_path, True, [{"percent": 10}], DOING)
    todo = out["todoSnapshot"]
    assert {"disabled", "doing", "blocked", "queued", "nudged", "nudgedWaiting"} <= set(todo)
    (s,) = snaps([{"todo": todo, "checkpoint": out["checkpointSnapshot"]}])
    assert s["todo"]["disabled"] is False and s["checkpoint"]["disabled"] is False
    assert s["todo"]["doing"] == ["#1 作業"]
    assert s["checkpoint"]["prompt"] != ""
    # 実際に調停を通しても正常に動く (最初のターン: todo のリマインド、高使用率: 保存)
    assert out["steps"][0]["types"] == ["todo-reminder"]
    assert wire(todo_path, True, [{"percent": 90}], DOING)["steps"][0]["types"] == [
        "autocheckpoint"
    ]


# ─── 保存中に見送ったときは周期を取りやめる (saving を残さない) ──────────────


def test_user_input_while_saving_cancels_the_cycle(todo_path):
    steps = [
        {"percent": 90},
        {"percent": 90, "pending": True, "userTurn": False},
        {"percent": 10},
    ]
    out = wire(todo_path, True, steps, [])
    a, b, c = out["steps"]
    assert a["types"] == ["autocheckpoint"] and a["phase"] == "saving"
    assert b["types"] == [] and b["compacts"] == 0 and b["phase"] == "idle"  # saving を残さない
    # 最後の別ターンは閾値未満なので圧縮しない
    assert c["types"] == [] and c["compacts"] == 0 and c["phase"] == "idle"
    assert out["resumes"] == []


def test_is_compacting_while_saving_cancels_the_cycle(todo_path):
    steps = [
        {"percent": 90},
        {"percent": 90, "isCompacting": True, "userTurn": False},
        {"percent": 10},
    ]
    out = wire(todo_path, True, steps, [])
    a, b, c = out["steps"]
    assert a["phase"] == "saving"
    assert b["compacts"] == 0 and b["phase"] == "idle"
    assert c["compacts"] == 0 and c["types"] == []


def test_user_input_when_idle_has_no_cancel_side_effect(todo_path):
    out = wire(todo_path, True, [{"percent": 10, "pending": True}], [])
    assert out["steps"][0]["phase"] == "idle" and out["steps"][0]["compacts"] == 0


# ─── 配線の静的な確認 ────────────────────────────────────────────────


def test_index_registers_settle_only_under_the_flag():
    src = (ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts").read_text(encoding="utf-8")
    assert "if (arbiterEnabled()) {" in src and "registerSettle(" in src
    assert (
        src.index("registerAutoCheckpoint(pi,")
        < src.index("registerSettle(")
        < src.index("registerJournal(pi,")
    )
    assert src.count("sendUserMessage(") >= 1
