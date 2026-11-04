"""作業台帳の観測ログ (``home/dot_config/pi/harness/work/journal.ts``) と集計 (``scripts/work_stats.py``) の試験。

``test/agents/pi/work_journal_driver.mjs`` に偽の pi と偽のイベントを渡し、journal の記録を見る
(node の型除去を使うので、22.18 未満の node では飛ばす)。集計は python の関数を直接呼ぶ。

see docs/spec/work/journal.md
"""

from __future__ import annotations

import importlib.util
import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_journal_driver.mjs"
BASE = 1_700_000_000_000


def _load_stats():
    spec = importlib.util.spec_from_file_location("work_stats", ROOT / "scripts" / "work_stats.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(scenario):
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(scenario),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def evs(result):
    return [json.loads(line) for line in result["lines"]]


needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@needs_node
def test_形式は1行1json_aux付き_連番(tmp_path):
    r = run(
        {
            "mode": "create",
            "dir": str(tmp_path / "j"),
            "events": [
                {"type": "tool.call", "data": {"tool": "x", "ms": 5}},
                {"type": "settle", "data": {"outcome": "completed"}, "node": "t1"},
            ],
        }
    )
    got = evs(r)
    assert [e["seq"] for e in got] == [1, 2]
    assert all(e["aux"] is True for e in got)
    assert got[0]["type"] == "tool.call" and got[0]["data"] == {"tool": "x", "ms": 5}
    assert got[1]["node"] == "t1"
    assert r["files"] == ["s1.jsonl"]


@needs_node
def test_書けなくても例外を出さず_lastErrorに残す(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    r = run(
        {"mode": "create", "dir": str(blocker / "sub"), "events": [{"type": "settle", "data": {}}]}
    )
    assert r["lastError"]
    assert r["lines"] == []


@needs_node
def test_巨大な本文と秘密は入れず_文字数だけ残す(tmp_path):
    secret = "ghp_" + "A" * 400
    r = run(
        {
            "mode": "create",
            "dir": str(tmp_path / "j"),
            "events": [
                {"type": "tool.call", "data": {"tool": "bash", "out": secret, "short": "ok"}}
            ],
        }
    )
    assert "ghp_" not in r["lines"][0]
    d = evs(r)[0]["data"]
    assert d["out"] == "<404 chars>"
    assert d["short"] == "ok"


@needs_node
def test_無効と子では購読しない(tmp_path):
    assert (
        run(
            {
                "mode": "register",
                "dir": str(tmp_path / "a"),
                "env": {"PI_JOURNAL": "0"},
                "steps": [],
            }
        )["registered"]
        is False
    )
    assert (
        run({"mode": "register", "dir": str(tmp_path / "b"), "child": True, "steps": []})[
            "registered"
        ]
        is False
    )
    assert run({"mode": "register", "dir": str(tmp_path / "c"), "steps": []})["registered"] is True


def _steps():
    child_msg = {
        "role": "custom",
        "customType": "child-finished",
        "display": True,
        "content": "x" * 800,
        "details": {
            "agent": "worker",
            "status": "done",
            "id": "j1",
            "stats": {"durationMs": 90000, "cost": 0.5},
        },
    }
    return [
        {"at": 1, "event": "session_start", "payload": {"reason": "startup"}},
        {
            "at": 2,
            "event": "tool_execution_start",
            "payload": {
                "toolName": "guarded_task",
                "args": {"agent": "worker", "task": "T" * 500, "background": True},
            },
        },
        {
            "at": 3,
            "event": "tool_execution_start",
            "payload": {"toolName": "guarded_task", "args": {"status": True, "jobId": "j1"}},
        },
        {
            "at": 4,
            "event": "tool_execution_end",
            "payload": {
                "toolName": "guarded_bash",
                "durationMs": 12,
                "isError": True,
                "result": {"content": [{"text": "abc"}]},
            },
        },
        {"at": 5, "event": "ui_prompt_start", "payload": {"kind": "confirm"}},
        {"at": 9, "event": "ui_prompt_end", "payload": {"kind": "confirm"}},
        {"at": 10, "event": "message_end", "payload": {"message": child_msg}},
        {
            "at": 11,
            "event": "message_end",
            "payload": {"message": {"role": "assistant", "content": []}},
        },
        {
            "at": 12,
            "event": "agent_before_settle",
            "payload": {
                "outcome": "completed",
                "continue": True,
                "entries": [{"type": "custom_message", "customType": "todo-reminder"}],
            },
        },
        {"at": 13, "event": "after_provider_response", "payload": {"status": 429}},
        {"at": 14, "event": "after_provider_response", "payload": {"status": 200}},
    ]


@needs_node
def test_イベントを記録し_戻り値は常にundefined(tmp_path):
    r = run({"mode": "register", "dir": str(tmp_path / "j"), "steps": _steps()})
    assert all(x is None for x in r["returns"])
    got = evs(r)
    types = [e["type"] for e in got]
    assert types == [
        "session.start",
        "run.started",
        "tool.call",
        "wait.opened",
        "wait.resolved",
        "notice",
        "run.ended",
        "settle",
        "resource.429",
    ]
    by = {e["type"]: e for e in got}
    assert by["run.started"]["data"] == {"role": "worker", "background": True}
    assert by["tool.call"]["data"] == {
        "tool": "guarded_bash",
        "ms": 12,
        "isError": True,
        "chars": 3,
    }
    assert by["wait.resolved"]["data"]["ms"] == 4
    notice = by["notice"]["data"]
    assert (
        notice["kind"] == "child-finished" and notice["shown"] is True and notice["folded"] is True
    )
    assert (
        notice["chars_to_model"] == 800
        and notice["lines_shown"] == 1
        and 0 < notice["chars_shown"] < 100
    )
    assert by["run.ended"]["data"] == {
        "id": "j1",
        "role": "worker",
        "state": "done",
        "ms": 90000,
        "usd": 0.5,
    }
    assert by["settle"]["data"] == {"outcome": "completed", "continue": True, "by": "todo-reminder"}
    # 依頼文 (500 字) は記録しない
    assert "TTTT" not in json.dumps(got)


@needs_node
def test_畳まないとき_見える行数は全文の行数(tmp_path):
    msg = {
        "role": "custom",
        "customType": "todo-reminder",
        "display": True,
        "content": "a\nb\nc",
        "details": {"open": 2},
    }
    r = run({"mode": "register", "dir": str(tmp_path / "j"), "env": {"PI_QUIET_NOTICES": "0"}, "steps": [
        {"at": 1, "event": "session_start", "payload": {}},
        {"at": 2, "event": "message_end", "payload": {"message": msg}},
        {"at": 3, "event": "message_end", "payload": {"message": {**msg, "display": False}}},
        {"at": 4, "event": "message_end", "payload": {"message": {"role": "user", "content": "【自動の再開】続けて"}}},
    ]})  # fmt: skip
    notices = [e["data"] for e in evs(r) if e["type"] == "notice"]
    assert [
        (n["kind"], n["shown"], n["folded"], n["lines_shown"], n["chars_to_model"]) for n in notices
    ] == [
        ("todo-reminder", True, False, 3, 5),
        ("todo-reminder", False, False, 0, 5),
        ("autocheckpoint-resume", True, False, 1, 10),
    ]


@needs_node
def test_壊れた入力でも本体を止めない(tmp_path):
    r = run(
        {
            "mode": "register",
            "dir": str(tmp_path / "j"),
            "steps": [
                {"at": 1, "event": "session_start", "payload": {}},
                {"at": 2, "event": "message_end", "payload": None},
                {"at": 3, "event": "tool_execution_end", "payload": None},
                {"at": 4, "event": "agent_before_settle", "payload": {"entries": "x"}},
                {"at": 5, "event": "session_start", "payload": {}, "ctx": None},
            ],
        }
    )
    assert all(x is None for x in r["returns"])


def test_集計の値(tmp_path):
    ws = _load_stats()

    def ev(seq, off, typ, **data):
        return {"ts": BASE + off, "seq": seq, "type": typ, "data": data, "aux": True}

    rows = [
        ev(1, 0, "run.started", role="worker"),
        ev(2, 0, "run.started", role="worker"),
        ev(3, 1_000, "tool.call", tool="a"),
        ev(4, 2_000, "tool.call", tool="b"),
        ev(5, 2_500, "tool.call", tool="c", nested=True),
        ev(6, 3_000, "wait.resolved", on="user", ms=4000),
        ev(7, 3_500, "wait.resolved", on="user", ms=6000),
        ev(8, 10_000, "run.ended", id="j1"),
        ev(9, 10_000, "notice", kind="child-finished", lines_shown=1, chars_to_model=300),
        ev(10, 11_000, "notice", kind="bg-job-finished", lines_shown=1, chars_to_model=500),
        ev(11, 11_500, "notice", kind="todo-reminder", lines_shown=1, chars_to_model=100),
        ev(12, 11_600, "notice", kind="autocheckpoint", lines_shown=0, chars_to_model=900),
        ev(13, 12_000, "run.started", role="review"),
        ev(14, 20_000, "run.ended", id="j2"),
        ev(15, 30_000, "run.ended", id="j3"),
    ]
    d = tmp_path / "j"
    d.mkdir()
    (d / "a.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\nbroken{\n", encoding="utf-8"
    )
    s = ws.compute(ws.load([d]))
    assert s["events"] == 15
    assert (s["m1_tool_calls"], s["m1_wakes"], s["m1_contacts"], s["m1_runs_started"]) == (
        2,
        2,
        4,
        3,
    )
    assert s["m1_contacts_per_run"] == pytest.approx(4 / 3)
    assert s["m2_concurrency_max"] == 2
    assert s["m2_concurrency_avg"] == pytest.approx(48_000 / 30_000)
    assert (s["m4_restart_samples"], s["m4_restart_delay_p50_s"], s["m4_restart_delay_p90_s"]) == (
        1,
        2.0,
        2.0,
    )
    assert (s["user_waits"], s["user_wait_total_s"]) == (2, 10.0)
    assert (s["m5_visible_lines_total"], s["m5_visible_lines_per_day"]) == (3, 3.0)
    assert (s["m6_notices"], s["m6_chars_to_model_p90"]) == (4, 900.0)


def test_集計は空でも落ちない(tmp_path):
    ws = _load_stats()
    s = ws.compute(ws.load([tmp_path / "none"]))
    assert (
        s["events"] == 0 and s["m1_contacts_per_run"] is None and s["m6_chars_to_model_p90"] is None
    )
