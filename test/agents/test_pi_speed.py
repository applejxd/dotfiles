"""自作の拡張 ``speed`` (直近 1 回の TTFT と decode 速度をステータス行へ出す) の試験。

* 純関数と、時計を差し替えたイベント列は ``test/agents/pi/speed_driver.mjs`` (node の型除去。22.18 未満は skip)。
* 偽のモデルでの統合は RPC で、``setStatus`` が ``speed`` のキーで出ることまで。faux は
  ``before_provider_request`` を呼ばないので、TTFT の値は確かめられない (純関数の試験で補う)。
  実際のストリームの時刻の精度・TUI・Orca の見え方は未確認。

see docs/spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw
"""

from __future__ import annotations

import json
import subprocess
import threading
import time

import pytest
from agents_common import ROOT
from test_pi_harness import FIXTURES, PI, env  # noqa: F401
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "speed_driver.mjs"
SPEED = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "speed" / "index.ts"

needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
needs_pi = pytest.mark.skipif(PI is None, reason="pi is not installed")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


@needs_node
def test_ttft_and_decode_are_computed_from_the_three_timestamps(table):
    c = table["compute"]["normal"]
    assert c == {"ttftMs": 1200, "tps": 60, "approx": False}


@needs_node
def test_decode_is_withheld_below_30_tokens_or_0_3_seconds(table):
    c = table["compute"]
    assert "tps" not in c["short_output"] and c["short_output"]["ttftMs"] == 1200
    assert c["min_output"]["tps"] == 30 / 2
    assert "tps" not in c["short_span"]
    assert c["min_span"]["tps"] == 100 / 0.3


@needs_node
def test_missing_timestamps_leave_the_value_out(table):
    c = table["compute"]
    assert "ttftMs" not in c["no_first"] and "tps" not in c["no_first"]
    assert "ttftMs" not in c["no_t0"] and c["no_t0"]["tps"] == 60


@needs_node
def test_approx_only_when_reasoning_was_counted_but_no_thinking_delta_was_seen(table):
    c = table["compute"]
    assert c["reasoning_unseen"]["approx"] is True
    assert c["reasoning_seen"]["approx"] is False
    assert c["reasoning_zero_unseen"]["approx"] is False
    assert c["approx_without_rate"]["approx"] is False  # decode が無ければ印も付けない


@needs_node
def test_format_is_short_and_uses_a_dash_for_missing_values(table):
    f = table["format"]
    assert f["normal"] == "⚡60t/s 1.2s"
    assert f["approx"] == "⚡~60t/s 1.2s"
    assert f["no_rate"] == "⚡— 1.2s"
    assert f["no_ttft"] == "⚡60t/s —"
    assert f["none"] == "—"
    assert all(len(v) <= 18 for v in f.values()), f


def _statuses(table, name):
    assert all(key == "speed" for key, _ in table["events"][name])
    return [text for _, text in table["events"][name]]


@needs_node
def test_status_comes_from_the_first_typed_delta_and_message_end(table):
    # start は最初のトークンではない。thinking・text・toolcall のどのデルタでもよい
    for name in ("text", "thinking", "toolcall"):
        assert _statuses(table, name) == [None, "⚡55t/s 1.2s"], name
    # 思考が出ない経路の疑い (reasoning を数えたのに thinking のデルタが無い)
    assert _statuses(table, "reasoning_hidden") == [None, "⚡~55t/s 1.2s"]


@needs_node
def test_status_without_the_request_hook_or_a_delta(table):
    assert _statuses(table, "no_request_hook") == ["⚡55t/s —"]
    assert _statuses(table, "no_delta") == ["—"]


@needs_node
def test_status_is_not_updated_for_errors_aborts_or_non_assistant_messages(table):
    assert _statuses(table, "error") == [None]
    assert _statuses(table, "aborted") == [None]
    assert _statuses(table, "user_message") == []


@needs_node
def test_each_call_is_measured_alone_and_a_new_session_clears_the_status(table):
    assert _statuses(table, "second_call_resets") == [None, "⚡55t/s 1.2s", "⚡~50t/s 0.5s"]
    assert _statuses(table, "cleared_on_switch") == [None, "⚡55t/s 1.2s", None]


@needs_node
def test_nothing_is_shown_without_a_ui_and_a_child_registers_nothing(table):
    assert table["events"]["no_ui"] == []
    assert table["child"] == {"child": 0, "parent": 4}


# --- 偽のモデルで、実際の pi に載せる (RPC。UI があるので setStatus が出る) ---


def _rpc_status_events(env, *extra, **env_extra):
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), *extra, "-e", str(FIXTURES / "faux.ts"), "--mode", "rpc"]
    proc = subprocess.Popen(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": "[]", **env_extra},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    events, state = [], {"running": False, "started": False, "last": time.time()}

    def read():
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "agent_start":
                state["started"] = state["running"] = True
            elif kind == "agent_end":
                state["running"] = False
            if kind == "extension_ui_request" and event.get("method") == "setStatus":
                events.append((event.get("statusKey"), event.get("statusText")))
            state["last"] = time.time()

    threading.Thread(target=read, daemon=True).start()
    try:
        proc.stdin.write(json.dumps({"id": "m0", "type": "prompt", "message": "go"}) + "\n")
        proc.stdin.flush()
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(0.2)
            if state["started"] and not state["running"] and time.time() - state["last"] > 1.5:
                break
    finally:
        proc.kill()
        proc.wait(timeout=10)
    return events


@needs_pi
def test_speed_status_reaches_the_ui_with_a_faux_model(env):
    events = _rpc_status_events(env, "-e", str(SPEED))
    speed = [text for key, text in events if key == "speed"]
    # 偽のモデルは出力が 30 トークン未満で、before_provider_request も呼ばない (値は —)
    assert speed and speed[-1] == "—", events


@needs_pi
def test_speed_status_is_absent_in_a_child(env):
    events = _rpc_status_events(env, "-e", str(SPEED), PI_HARNESS_CHILD="1")
    assert not [e for e in events if e[0] == "speed"], events
