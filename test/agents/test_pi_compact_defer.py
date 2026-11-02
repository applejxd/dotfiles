"""圧縮の最中は、完了通知 (triggerTurn の sendMessage) で新しい発言を始めない (#173)。

* harness: ``index.ts`` の ``// region compact-defer`` の中身 (依存なし) を取り出し、node (型除去) で実行する。
* activity: typebox / pi-tui だけ差し替え、偽の ``pi`` に通知を記録させて実行する。
* 配線 (送信 4 か所とイベント) は、ソースの文字列で確かめる。

see docs/spec/guard/pi-extensions.md#圧縮中の完了通知の保留
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"
ACTIVITY = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "activity" / "index.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

REGION = re.compile(r"// region compact-defer\n(.*?)// endregion compact-defer", re.S)


def _defer(tmp_path, body):
    """compact-defer の区画だけを .ts にして、body (JS) を実行し、最後の console.log の JSON を返す。"""
    match = REGION.search(HARNESS.read_text(encoding="utf-8"))
    assert match, "index.ts に // region compact-defer が無い"
    (tmp_path / "defer.ts").write_text(match.group(1), encoding="utf-8")
    runner = tmp_path / "run.mjs"
    runner.write_text(
        'import { createCompactDefer } from "./defer.ts";\n'
        "const sleep = (ms) => new Promise((r) => setTimeout(r, ms));\n"
        "const log = [];\n"
        f"{body}\n"
        "console.log(JSON.stringify(log));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_node(), str(runner)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_is_delivered_while_compacting(tmp_path):
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer();
d.begin();
d.run(() => log.push("a"));
d.run(() => log.push("b"));
await sleep(30);
log.push("still-held");
d.shutdown();
""",
    )
    assert log == ["still-held"]


@pytest.mark.parametrize("finish", ["end", "fail"])
def test_held_notices_are_delivered_in_order_when_compaction_ends(tmp_path, finish):
    # session_compact と session_compact_failed は、どちらも end() に配線する (配線は別の試験で確かめる)
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer();
d.begin();
d.run(() => log.push("a"));
d.run(() => log.push("b"));
d.run(() => log.push("c"));
log.push("before-end");
d.end();
log.push("after-end");
d.run(() => log.push("later"));
""",
    )
    assert log == ["before-end", "a", "b", "c", "after-end", "later"], finish


def test_not_compacting_delivers_immediately_in_order(tmp_path):
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer();
d.run(() => log.push("a"));
log.push("between");
d.run(() => log.push("b"));
d.begin();
d.end();
d.run(() => log.push("c"));
""",
    )
    assert log == ["a", "between", "b", "c"]


def test_a_throwing_notice_does_not_stop_the_rest(tmp_path):
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer();
d.begin();
d.run(() => log.push("a"));
d.run(() => { throw new Error("boom"); });
d.run(() => log.push("c"));
d.end();
""",
    )
    assert log == ["a", "c"]


def test_a_stuck_compaction_is_released_by_the_safety_valve(tmp_path):
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer({ maxMs: 40 });
d.begin();
d.run(() => log.push("held"));
await sleep(10);
log.push("early");
await sleep(120);
log.push("late");
d.run(() => log.push("now-immediate"));
d.shutdown();
""",
    )
    assert log == ["early", "held", "late", "now-immediate"]


def test_a_second_begin_rearms_the_valve_and_keeps_the_held_notices(tmp_path):
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer({ maxMs: 80 });
d.begin();
d.run(() => log.push("held"));
await sleep(50);
d.begin();
await sleep(50);
log.push("t100");
await sleep(100);
log.push("t200");
d.shutdown();
""",
    )
    assert log == ["t100", "held", "t200"]


def test_shutdown_stops_the_timer_and_drops_held_notices(tmp_path):
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer({ maxMs: 30 });
d.begin();
d.run(() => log.push("held"));
d.shutdown();
await sleep(100);
log.push("quiet");
""",
    )
    assert log == ["quiet"]


# ─── 配線 (ソースの文字列) ────────────────────────────────────────────


def _harness_text():
    return HARNESS.read_text(encoding="utf-8")


def test_shutdown_drops_held_notices_even_if_a_late_end_arrives(tmp_path):
    # 圧縮の終わりのイベントが shutdown の後に届いても (reload・別セッション)、古い通知を流さない
    log = _defer(
        tmp_path,
        """
const d = createCompactDefer();
d.begin();
d.run(() => log.push("held"));
d.shutdown();
d.end();
log.push("after");
""",
    )
    assert log == ["after"]


def test_all_three_harness_senders_go_through_the_deferral():
    src = _harness_text()
    for custom_type in ("pending-result", "child-finished"):
        for m in re.finditer(rf'customType: "{custom_type}"', src):
            head = src[max(0, m.start() - 400) : m.start()]
            assert "deferWhileCompacting(" in head, (
                f"{custom_type} (offset {m.start()}) が保留を通らない"
            )
    assert len(re.findall(r'customType: "(?:pending-result|child-finished)"', src)) == 3
    # 保留を通さない送信が残っていない
    assert src.count("pi.sendMessage(") == 3


def test_harness_compaction_events_drive_the_deferral():
    src = _harness_text()
    before = src.index('pi.on("session_before_compact"')
    assert "compactDefer.begin()" in src[before : before + 300]
    for event in ("session_compact", "session_compact_failed"):
        start = src.index(f'pi.on("{event}"')
        assert "compactDefer.end()" in src[start : start + 400], event
    # 成功は、pi が圧縮の状態を解く前に届くので 1 tick 遅らせる。失敗は解いた後なので即時
    ok = src.index('pi.on("session_compact"')
    assert "setTimeout(() => compactDefer.end(), 0)" in src[ok : ok + 400]
    failed = src.index('pi.on("session_compact_failed"')
    assert "setTimeout" not in src[failed : failed + 200]
    start = src.index('pi.on("session_shutdown", async (event: any)')
    assert "compactDefer.shutdown()" in src[start : start + 300]


# ─── activity ────────────────────────────────────────────────────────

ACTIVITY_RUNNER = """
import { pathToFileURL } from "node:url";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const mod = await import(pathToFileURL(process.argv[2]).href);
const handlers = {};
const tools = {};
const sent = [];
const pi = {
  on: (n, f) => { handlers[n] = f; },
  registerTool: (t) => { tools[t.name] = t; },
  sendMessage: (m, o) => sent.push({ type: m.customType, ids: m.details?.ids, opts: o }),
};
mod.default(pi);
globalThis.__PI_FULL_GUARD__ = true;
const run = (cmd) => tools.bg_run.execute("x", { command: cmd }, undefined, undefined, { cwd: process.cwd() });
const fire = (n) => handlers[n]?.({}, {});
%s
console.log(JSON.stringify(out));
"""


def _activity(tmp_path, body):
    ext = tmp_path / "ext"
    for name, code in (
        ("typebox", "const f=()=>({});export const Type={Object:f,String:f,Optional:f,Number:f};"),
        ("@earendil-works/pi-tui", "export const truncateToWidth=(s)=>s;"),
    ):
        stub = ext / "node_modules" / name
        stub.mkdir(parents=True, exist_ok=True)
        (stub / "package.json").write_text(
            json.dumps({"name": name, "type": "module", "main": "index.js"})
        )
        (stub / "index.js").write_text(code)
    (ext / "index.ts").write_text(ACTIVITY.read_text(encoding="utf-8"), encoding="utf-8")
    runner = ext / "runner.mjs"
    runner.write_text(ACTIVITY_RUNNER % body, encoding="utf-8")
    proc = subprocess.run(
        [_node(), str(runner), str(ext / "index.ts")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_activity_holds_jobs_while_busy_or_compacting_and_sends_once_after(tmp_path):
    out = _activity(
        tmp_path,
        """
await fire("agent_start");
await run("true");
await sleep(3300);                  // 窓 (2.5 秒) を過ぎても、作業中は送らない
const duringBusy = sent.length;
await fire("agent_settled");        // 作業が終わる → 届く
await sleep(50);
const afterSettled = sent.length;
await fire("session_before_compact");
await run("true");
await run("true");
await sleep(3300);                  // 圧縮の最中は、窓を過ぎても送らない
const duringCompact = sent.length;
await fire("session_compact");
const insideHandler = sent.length;   // 成功の通知は圧縮の状態が解かれる前に届くので、その場では流さない
await sleep(50);
const out = { duringBusy, afterSettled, duringCompact, insideHandler, sent };
""",
    )
    assert out["duringBusy"] == 0
    assert out["afterSettled"] == 1
    assert out["duringCompact"] == 1, out  # 圧縮の最中に増えていない
    assert out["insideHandler"] == 1, out  # session_compact のハンドラの中では流さない (1 tick 後)
    assert len(out["sent"]) == 2, out  # 圧縮の後に、2 件を 1 通にまとめて 1 回だけ
    assert len(out["sent"][1]["ids"]) == 2, out


def test_activity_also_delivers_after_a_failed_compaction(tmp_path):
    out = _activity(
        tmp_path,
        """
await fire("session_before_compact");
await run("true");
await sleep(3300);
const during = sent.length;
await fire("session_compact_failed");
await sleep(50);
const out = { during, sent };
""",
    )
    assert out["during"] == 0
    assert len(out["sent"]) == 1, out
