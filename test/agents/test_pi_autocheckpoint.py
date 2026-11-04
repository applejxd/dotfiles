"""自動の保存と圧縮 (``home/dot_config/pi/harness/autocheckpoint.ts``) の状態機械の試験。

``test/agents/pi/autocheckpoint_driver.mjs`` に偽のイベントとコンテキストを渡し、handler の戻り値と compact の呼び出しを見る
(node の型除去を使うので、22.18 未満の node では飛ばす)。

see docs/spec/guard/pi-extensions.md#文脈の使用率による自動の保存と圧縮
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "autocheckpoint_driver.mjs"
INDEX = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

MIN = 60_000


def run(steps, **scenario):
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps({"steps": steps, **scenario}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def prompt_of(step):
    return step["result"]["entries"][0]["content"]


def test_below_threshold_does_nothing():
    out = run([{"percent": 79}, {"percent": 10}])
    assert [s["result"] for s in out["steps"]] == [None, None]
    assert out["notes"] == []


def test_at_threshold_continues_with_a_checkpoint_prompt():
    out = run([{"percent": 80}])
    r = out["steps"][0]["result"]
    assert r["continue"] is True
    entry = r["entries"][0]
    assert entry["type"] == "custom_message" and entry["display"] is True
    for word in (
        "コミットしない",
        "私物のホスト名",
        "本体の作業ツリー",
        "NEXT.md",
        "sdd-docs",
        "保存完了",
    ):
        assert word in entry["content"]
    assert out["steps"][0]["compacts"] == 0


def test_next_settle_compacts_exactly_once_with_the_instructions():
    out = run([{"percent": 85}, {"percent": 85}, {"percent": 90}, {"percent": 95}])
    s = out["steps"]
    assert s[0]["result"]["continue"] is True
    assert [x["compacts"] for x in s] == [0, 1, 0, 0]
    assert s[1]["result"] is None
    assert out["compactOptions"] == ["INSTR"]


def test_one_save_continuation_per_cycle_no_loop():
    # 圧縮の完了を待つ間 (compacting) は、使用率が高くても継続を積まない
    out = run([{"percent": 90}] * 6)
    conts = [x for x in out["steps"] if x["result"]]
    assert len(conts) == 1 and sum(x["compacts"] for x in out["steps"]) == 1


@pytest.mark.parametrize("finish", ["complete", "error"])
def test_cooldown_after_complete_or_error_then_resumes(finish):
    steps = [
        {"at": 0, "percent": 90},
        {"at": 1, "percent": 90, "finish": finish},
        {"at": 2 * MIN, "percent": 90},  # 冷却中 (既定 10 分)
        {"at": 9 * MIN, "percent": 90},  # 冷却中
        {"at": 11 * MIN + 1, "percent": 90},  # 冷却が明けて再び保存
    ]
    r = [x["result"] for x in run(steps)["steps"]]
    assert r[0] and r[1] is None and r[2] is None and r[3] is None and r[4]["continue"] is True


def test_error_path_notifies():
    out = run([{"percent": 90}, {"percent": 90, "finish": "error"}])
    assert any("失敗" in n for n in out["notes"])


def test_cooldown_is_configurable():
    steps = [
        {"at": 0, "percent": 90},
        {"at": 1, "percent": 90, "finish": "complete"},
        {"at": 5000, "percent": 90},
    ]
    assert run(steps, cooldownMs=1000)["steps"][2]["result"]["continue"] is True


def test_compact_throwing_does_not_wedge_the_state():
    steps = [
        {"at": 0, "percent": 90},
        {"at": 1, "percent": 90, "compactThrows": True},
        {"at": 11 * MIN, "percent": 90},
    ]
    s = run(steps)["steps"]
    assert s[1]["compacts"] == 1 and s[2]["result"]["continue"] is True


def test_compaction_still_runs_when_the_save_run_errored():
    out = run([{"percent": 90}, {"percent": 90, "outcome": "error"}])
    assert out["steps"][1]["compacts"] == 1


def test_abort_during_save_cancels_the_cycle():
    out = run(
        [
            {"at": 0, "percent": 90},
            {"at": 1, "percent": 90, "outcome": "aborted"},
            {"at": 2, "percent": 90},
        ]
    )
    assert [x["compacts"] for x in out["steps"]] == [0, 0, 0]
    assert out["steps"][2]["result"] is None  # 冷却中


def test_an_aborted_or_errored_run_does_not_start_a_cycle():
    out = run([{"percent": 95, "outcome": "aborted"}, {"percent": 95, "outcome": "error"}])
    assert [x["result"] for x in out["steps"]] == [None, None]


@pytest.mark.parametrize(
    ("scenario", "step"),
    [
        ({"child": True}, {"percent": 99}),
        ({}, {"percent": 99, "mode": "print"}),
        ({}, {"percent": 99, "mode": "json"}),
        ({"env": {"PI_AUTOCHECKPOINT": "0"}}, {"percent": 99}),
        ({}, {"percent": None}),
    ],
    ids=["child", "print", "json", "disabled", "percent-null"],
)
def test_inactive_cases_do_nothing(scenario, step):
    out = run([step, step], **scenario)
    assert [x["result"] for x in out["steps"]] == [None, None]
    assert sum(x["compacts"] for x in out["steps"]) == 0


def test_threshold_env_and_invalid_values():
    assert (
        run([{"percent": 55}], env={"PI_AUTOCHECKPOINT_PERCENT": "50"})["steps"][0]["result"][
            "continue"
        ]
        is True
    )
    assert (
        run([{"percent": 79}], env={"PI_AUTOCHECKPOINT_PERCENT": "abc"})["steps"][0]["result"]
        is None
    )
    assert (
        run([{"percent": 80}], env={"PI_AUTOCHECKPOINT_PERCENT": "abc"})["steps"][0]["result"][
            "continue"
        ]
        is True
    )


# ─── 同じ settle で todo と合成する ───────────────────────────────────
#
# pi 1.5.0 の emitBoundary (dist/core/extensions/runner.js 759-802) は、後のハンドラの entries で前の entries を
# **置き換える** (775-776 行)。前のハンドラの結果は event.entries に入って渡る (767-771 行)。continue も後勝ち (777-778 行)。
# ロード順は harness (autocheckpoint) → extensions (todo)。ここではその規則を模して 2 つの実物を順に呼ぶ。

COMPOSE_RUNNER = """
import { pathToFileURL } from "node:url";
const [, , acPath, todoPath, mode] = process.argv;
const { createAutoCheckpoint } = await import(pathToFileURL(acPath).href);
const todoMod = await import(pathToFileURL(todoPath).href);
const handlers = {};
todoMod.default({
  on: (n, f) => { (handlers[n] ??= []).push(f); },
  registerTool: () => {}, registerCommand: () => {}, appendEntry: () => {},
});
const ac = createAutoCheckpoint({ child: false, compactInstructions: "I", env: {}, now: () => 0 });
const todos = [{ id: 1, text: "x", status: "in_progress" }];
const branch = mode === "todo" || mode === "both"
  ? [{ type: "custom", customType: "todo-state", data: { nextId: 2, todos } }]
  : [];
const ctx = {
  mode: "tui", hasUI: false,
  ui: { notify: () => {}, setStatus: () => {} },
  sessionManager: { getBranch: () => branch },
  getContextUsage: () => ({ percent: mode === "todo" ? 10 : 90 }),
  compact: () => {},
};
for (const f of handlers.session_start ?? []) await f({}, ctx);
for (const f of handlers.before_agent_start ?? []) await f({ messageType: "user" }, ctx);
// pi 本体の合成規則: entries は後勝ち、continue も後勝ち。event.entries に前の結果が入る
let entries = [];
let cont = false;
const chain = [(e, c) => ac(e, c), ...(handlers.agent_before_settle ?? [])];
for (const h of chain) {
  const r = await h({ type: "agent_before_settle", outcome: "completed", entries, continue: cont }, ctx);
  if (r?.entries !== undefined) entries = r.entries;
  if (r?.continue !== undefined) cont = r.continue;
}
console.log(JSON.stringify({ types: entries.map((x) => x.customType), cont }));
"""

TODO = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "todo"


def _compose(tmp_path, mode):
    ext = tmp_path / "ext"
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
    runner = ext / "runner.mjs"
    runner.write_text(COMPOSE_RUNNER, encoding="utf-8")
    harness = ROOT / "home" / "dot_config" / "pi" / "harness" / "autocheckpoint.ts"
    proc = subprocess.run(
        [_node(), str(runner), str(harness), str(ext / "index.ts"), mode],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_checkpoint_and_todo_reminder_both_survive_the_same_settle(tmp_path):
    out = _compose(tmp_path, "both")
    assert out["types"] == ["autocheckpoint", "todo-reminder"], out
    assert out["cont"] is True


@pytest.mark.parametrize(
    ("mode", "types"), [("checkpoint", ["autocheckpoint"]), ("todo", ["todo-reminder"])]
)
def test_each_handler_alone_is_unchanged(tmp_path, mode, types):
    out = _compose(tmp_path, mode)
    assert out["types"] == types, out
    assert out["cont"] is True


def test_index_wires_it_with_the_compact_instructions():
    src = INDEX.read_text(encoding="utf-8")
    assert 'from "./autocheckpoint.ts"' in src
    assert (
        "registerAutoCheckpoint(pi, { child: CHILD, compactInstructions: COMPACT_INSTRUCTIONS })"
        in src
    )


# --- 圧縮の完了後の再開 ---

COMPLETE = [
    {"at": 0, "percent": 90},
    {"at": 1, "percent": 90, "finish": "complete", "wait": 40},
]


def test_resume_is_sent_once_after_a_successful_compaction():
    out = run(COMPLETE)
    assert len(out["resumes"]) == 1
    assert any("再開を指示" in n for n in out["notes"])


def test_resume_text_is_japanese_and_mentions_next_md():
    text = run(COMPLETE)["resumes"][0]
    for word in ("自動の再開", "NEXT.md", "待機", "todo"):
        assert word in text


def test_resume_is_not_sent_on_error():
    out = run([{"at": 0, "percent": 90}, {"at": 1, "percent": 90, "finish": "error", "wait": 40}])
    assert out["resumes"] == []


def test_resume_is_not_sent_when_compact_throws():
    out = run(
        [{"at": 0, "percent": 90}, {"at": 1, "percent": 90, "compactThrows": True, "wait": 40}]
    )
    assert out["resumes"] == []


def test_resume_is_not_sent_when_aborted_during_save():
    out = run(
        [{"at": 0, "percent": 90}, {"at": 1, "percent": 90, "outcome": "aborted", "wait": 40}]
    )
    assert out["resumes"] == []


def test_resume_env_zero_disables_only_the_resume():
    out = run(COMPLETE, env={"PI_AUTOCHECKPOINT_RESUME": "0"})
    assert out["resumes"] == [] and out["steps"][1]["compacts"] == 1


def test_resume_is_skipped_when_disabled_during_the_wait():
    steps = [
        {"at": 0, "percent": 90},
        {"at": 1, "percent": 90, "finish": "complete"},
        {"at": 2, "percent": None, "setEnv": {"PI_AUTOCHECKPOINT": "0"}, "wait": 40},
    ]
    assert run(steps, resumeDelayMs=20)["resumes"] == []


def test_resume_is_skipped_when_a_new_cycle_starts_during_the_wait():
    # 冷却 0 で、完了の直後に次の周期が始まる (phase が idle でなくなる)
    steps = [
        {"at": 0, "percent": 90},
        {"at": 1, "percent": 90, "finish": "complete"},
        {"at": 2, "percent": 90, "wait": 40},
    ]
    out = run(steps, cooldownMs=0, resumeDelayMs=20)
    assert out["resumes"] == []


def test_cooldown_prevents_a_second_resume_even_if_usage_stays_high():
    steps = [
        {"at": 0, "percent": 90},
        {"at": 1, "percent": 95, "finish": "complete", "wait": 40},
        {"at": 2 * MIN, "percent": 95, "wait": 40},  # 冷却中: 保存も再開も起きない
        {"at": 5 * MIN, "percent": 95, "wait": 40},
    ]
    out = run(steps)
    assert len(out["resumes"]) == 1
    assert [x["result"] for x in out["steps"][2:]] == [None, None]


def test_resume_runs_again_in_the_next_cycle_after_the_cooldown():
    steps = [
        {"at": 0, "percent": 90},
        {"at": 1, "percent": 90, "finish": "complete", "wait": 40},
        {"at": 11 * MIN, "percent": 90},
        {"at": 11 * MIN + 1, "percent": 90, "finish": "complete", "wait": 40},
    ]
    assert len(run(steps)["resumes"]) == 2


@pytest.mark.parametrize(
    ("scenario", "mode"),
    [({"child": True}, "tui"), ({}, "print"), ({}, "json")],
    ids=["child", "print", "json"],
)
def test_resume_is_not_sent_in_child_or_print_modes(scenario, mode):
    steps = [
        {"at": 0, "percent": 90, "mode": mode},
        {"at": 1, "percent": 90, "mode": mode, "finish": "complete", "wait": 40},
    ]
    assert run(steps, **scenario)["resumes"] == []


def test_register_sends_a_follow_up_user_message():
    src = (ROOT / "home" / "dot_config" / "pi" / "harness" / "autocheckpoint.ts").read_text(
        encoding="utf-8"
    )
    assert 'pi.sendUserMessage(text, { deliverAs: "followUp" })' in src
