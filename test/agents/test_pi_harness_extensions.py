"""フルガードへ明示の ``-e`` で足した拡張が、判定・伏字化の中でどう扱われるかを、偽のモデルで試す。

pi が無い環境では skip する (``test_pi_harness.py`` と同じ)。
see docs/research/agents/pi-extension-under-harness.md
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest
from agents_common import ROOT
from test_pi_harness import FIXTURES, PI, SECRET, bash_call, env, run_pi  # noqa: F401

pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

sys.path.insert(0, str(ROOT / "scripts" / "agents"))

EXT = ("-e", str(FIXTURES / "ext_tool.ts"))
CALL = [{"name": "ext_search", "args": {"query": "hello"}}]


def _list_tool_in_role(env, tool):
    """役割 implementer の tools に ``tool`` を足す (判定器の設定は rules.json の judge にある)."""
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    tools = rules["judge"]["common"]["pi"]["profiles"]["implementer"]["tools"]
    assert "mcp__*" in tools, "implementer の tools が変わった (この試験の前提を直す)"
    tools.append(tool)
    path.write_text(json.dumps(rules), encoding="utf-8")


def test_extension_tool_is_denied_unless_the_role_lists_it(env):
    loaded, ran = env["tmp"] / "loaded", env["tmp"] / "ran"
    proc = run_pi(env, CALL, extra=EXT, EXT_LOADED_FILE=str(loaded), EXT_RAN_FILE=str(ran))

    # -ne でも明示の -e は読まれ、ツールはモデルに宣言される。だが役割に無ければ判定で拒否する
    assert loaded.exists()
    assert '"ext_search"' in proc.stdout
    assert "は ext_search を使えない" in proc.stdout, proc.stdout
    assert not ran.exists()
    # bypass でも deny は通らない
    proc = run_pi(env, CALL, extra=EXT, PI_HARNESS_BYPASS="1", EXT_RAN_FILE=str(ran))
    assert "は ext_search を使えない" in proc.stdout, proc.stdout
    assert not ran.exists()


def test_listed_extension_tool_is_asked_and_its_result_is_redacted(env):
    ran = env["tmp"] / "ran"
    _list_tool_in_role(env, "ext_search")
    common = dict(EXT_RAN_FILE=str(ran), EXT_SECRET=SECRET)

    # 役割に載せても、規則が無ければ既定の確認になる (UI の無い起動では拒否)
    proc = run_pi(env, CALL, extra=EXT, **common)
    assert "not approved:" in proc.stdout, proc.stdout
    assert not ran.exists()

    # bypass で実行させると、フルガードの tool_result が結果の秘密を伏せる
    proc = run_pi(env, CALL, extra=EXT, mode="json", PI_HARNESS_BYPASS="1", **common)
    assert ran.exists()
    assert "伏字" in proc.stdout
    assert SECRET not in proc.stdout
    results = [
        json.loads(line)
        for line in proc.stdout.splitlines()
        if line.startswith("{") and '"toolName":"ext_search"' in line
    ]
    assert results


def test_extension_cannot_replace_a_guarded_tool(env):
    pwned = env["proj"] / "pwned"
    proc = run_pi(
        env,
        bash_call("wc -c /dev/null"),
        extra=(*EXT, "-e", str(FIXTURES / "mutator.ts")),
        MUTATE_TO=f"touch {pwned.as_posix()}",
        EXT_OVERRIDE="guarded_bash",
        EXT_SHELL=shutil.which("bash") or "bash",
    )

    # 同じ名前のツールを後から登録すると、読み込みの失敗で起動が止まる (許可側へは倒れない)
    assert proc.returncode != 0
    assert 'Tool "guarded_bash" conflicts' in proc.stderr, proc.stderr
    assert not pwned.exists()


# ─── MCP の exposure (生成器 → フルガード) ─────────────────────────────

MCP_SERVER = FIXTURES / "mcp_server.py"


def _common_with_mcp(**extra):
    from agents_common import load_common

    common = json.loads(json.dumps(load_common()))
    common["mcp"] = [
        {
            "id": "spike",
            "purpose": "試験",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(MCP_SERVER)],
            "clis": ["pi"],
            **extra,
        }
    ]
    return common


def test_generated_mcp_config_defaults_to_direct_and_honours_exposure():
    import generate as gen

    servers = gen.pi_mcp_servers(_common_with_mcp())
    assert servers[0]["config"]["exposure"] == "direct"
    servers = gen.pi_mcp_servers(_common_with_mcp(exposure="deferred"))
    assert servers[0]["config"]["exposure"] == "deferred"
    # Claude / Copilot / OpenCode / Codex へ出す定義には exposure を混ぜない
    shared = gen.mcp_servers(_common_with_mcp(exposure="deferred"))
    assert all("exposure" not in entry for _, entry in shared)
    with pytest.raises(ValueError, match="exposure"):
        gen.pi_mcp_servers(_common_with_mcp(exposure="codemod"))


def test_mcp_tool_from_the_generated_config_is_declared_and_asked_under_the_harness(env):
    """pis は -ne で codemode / tool_search を外す。
    生成器が direct を出さないと、MCP のツールは呼べない (E6)。"""
    import generate as gen

    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    rules["mcp"] = gen.pi_mcp_servers(_common_with_mcp())
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, [{"name": "mcp__spike__echo_secret", "args": {}}])

    assert '"mcp__spike__echo_secret"' in proc.stdout.splitlines()[0], proc.stdout
    # 実装役では MCP のツールは既定の確認。UI の無い起動では拒否になる (pis で ask)
    assert "isError=true :: not approved:" in proc.stdout, proc.stdout
    assert "mcp-raw-secret" not in proc.stdout


def test_mcp_tool_without_exposure_is_unreachable_under_the_harness(env):
    """欠陥の再現 (exposure を出さない旧い生成)。
    pi が codemode を宣言する版になれば、この試験を見直す。"""
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    config = {"command": sys.executable, "args": [str(MCP_SERVER)]}
    rules["mcp"] = [{"name": "spike", "config": config}]
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, [{"name": "mcp__spike__echo_secret", "args": {}}])

    assert "Tool mcp__spike__echo_secret not found" in proc.stdout, proc.stdout


ACTIVITY = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "activity" / "index.ts"


def _bg(command):
    return [{"name": "bg_run", "args": {"command": command}}]


def test_bg_run_is_judged_like_bash_and_denied_commands_do_not_start(env):
    """バックグラウンド実行も、bash と同じ deny を通らない (bypass でも)。"""
    marker = env["tmp"] / "started"
    command = f"touch {marker.as_posix()}; rm -rf ~"
    for extra in ({}, {"PI_HARNESS_BYPASS": "1"}):
        # HOME を使い捨てにする: 判定が働かなかったとき、`rm -rf ~` が本物のホームを消さないように
        home = {"HOME": str(env["tmp"])}
        proc = run_pi(env, _bg(command), extra=("-e", str(ACTIVITY)), **home, **extra)
        assert "isError=true" in proc.stdout, proc.stdout
        assert "壊滅的" in proc.stdout, proc.stdout
        assert not marker.exists()


def test_bg_run_starts_an_allowed_command_and_bg_log_and_bg_kill_are_allowed(env):
    proc = run_pi(env, _bg("wc -c /dev/null"), extra=("-e", str(ACTIVITY)))
    assert "isError=false" in proc.stdout, proc.stdout
    proc = run_pi(
        env,
        [{"name": "bg_log", "args": {}}, {"name": "bg_kill", "args": {"id": "j999"}}],
        extra=("-e", str(ACTIVITY)),
    )
    assert "not approved" not in proc.stdout, proc.stdout
    assert "使えない" not in proc.stdout, proc.stdout


def test_bg_run_does_not_show_the_log_path_and_bg_log_reports_the_line_count(env):
    """ログのパスは read_deny で読めないので、教えるとモデルが行き止まる (B1 の F4)。読むのは bg_log。"""
    calls = [*_bg("wc -c /dev/null"), {"name": "bg_log", "args": {"id": "j1"}}]
    proc = run_pi(env, calls, extra=("-e", str(ACTIVITY)))
    assert "started j1" in proc.stdout, proc.stdout
    assert "pi-jobs" not in proc.stdout, proc.stdout
    assert "bg_log" in proc.stdout.split("started j1", 1)[1], proc.stdout
    assert re.search(r"tail \d+ of \d+ lines", proc.stdout), proc.stdout


def _agent_runs_after_jobs(env, rounds, quiet=6.0, limit=60.0):
    """RPC で 1 回依頼し、ジョブの終了通知でターンが何回始まったか (agent_start の数) と、届いた通知の本文を返す。

    確認 (confirm) はすべて承認する。最後の出来事から quiet 秒、何も起きなければ終わり。
    """
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += [
        "-e",
        str(env["harness"]),
        "-e",
        str(ACTIVITY),
        "-e",
        str(FIXTURES / "faux.ts"),
        "--mode",
        "rpc",
    ]
    proc = subprocess.Popen(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_ROUNDS": json.dumps(rounds)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    starts, notices, state = [], [], {"last": time.time(), "running": False}

    def read():
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "agent_start":
                starts.append(time.time())
                state["running"] = True
            elif kind == "agent_end":
                state["running"] = False
            if kind in ("agent_start", "agent_end", "tool_execution_end"):
                state["last"] = time.time()
            if kind == "message_end" and (event.get("message") or {}).get("role") == "custom":
                notices.append(json.dumps(event["message"], ensure_ascii=False))
            if kind == "extension_ui_request" and event.get("method") == "confirm":
                reply = {"type": "extension_ui_response", "id": event["id"], "confirmed": True}
                proc.stdin.write(json.dumps(reply) + "\n")
                proc.stdin.flush()

    threading.Thread(target=read, daemon=True).start()
    try:
        proc.stdin.write(json.dumps({"id": "m0", "type": "prompt", "message": "go"}) + "\n")
        proc.stdin.flush()
        deadline = time.time() + limit
        settled = False
        while time.time() < deadline:
            time.sleep(0.2)
            if not state["running"] and starts and time.time() - state["last"] > quiet:
                settled = True
                break
    finally:
        proc.kill()
    assert settled, (
        f"{limit} 秒で落ち着かなかった (ターンが続いている): {len(starts)} 回, {notices}"
    )
    return starts, notices


def test_jobs_that_finish_together_wake_the_agent_once(env):
    """同じごろに終わったジョブは 1 通にまとめ、ターンは 1 回だけ起きる (B1 の F3)。"""
    rounds = [[*_bg("wc -c /dev/null"), *_bg("wc -l /dev/null"), *_bg("wc -w /dev/null")]]
    starts, notices = _agent_runs_after_jobs(env, rounds)
    assert len(starts) == 2, (starts, notices)  # 最初の依頼 + まとめた通知の 1 回
    assert len(notices) == 1 and "3 件が終わりました" in notices[0], notices


def test_a_job_read_with_bg_log_after_it_finished_does_not_wake_the_agent(env):
    """終了後に bg_log で読んだジョブの通知は、ターンを起こさない (B1 の F2)。"""
    rounds = [
        _bg("sleep 0.2"),
        [{"name": "guarded_bash", "args": {"command": "sleep 1.5"}}],  # ジョブが終わるまでの間
        [{"name": "bg_log", "args": {"id": "j1"}}],
    ]
    starts, notices = _agent_runs_after_jobs(env, rounds)
    assert len(starts) == 1 and notices == [], (starts, notices)


def test_a_job_not_read_still_wakes_the_agent_after_the_turn(env):
    """読み済みでないジョブは、作業中に終わってもターンの後に届く (対照)。"""
    rounds = [_bg("sleep 0.2"), [{"name": "guarded_bash", "args": {"command": "sleep 1.5"}}]]
    starts, notices = _agent_runs_after_jobs(env, rounds)
    assert len(starts) == 2 and len(notices) == 1, (starts, notices)


def test_the_notice_waits_for_the_coalescing_window_even_after_the_turn_settled(env):
    """ターンが settled しても、まとめる窓 (2.5 秒) が開いている間は送らない。送るのは窓と settled の両方を満たしてから。"""
    rounds = [_bg("sleep 0.2"), [{"name": "guarded_bash", "args": {"command": "sleep 0.4"}}]]
    starts, notices = _agent_runs_after_jobs(env, rounds)
    assert len(starts) == 2 and len(notices) == 1, (starts, notices)
    # ジョブは起動の 0.2 秒後に終わる。窓はその 2.5 秒後に閉じる (ターンは 1 秒未満で settled)
    assert starts[1] - starts[0] >= 2.2, starts


def test_a_killed_job_does_not_wake_the_agent(env):
    rounds = [_bg("sleep 30"), [{"name": "bg_kill", "args": {"id": "j1"}}]]
    starts, notices = _agent_runs_after_jobs(env, rounds)
    assert len(starts) == 1 and notices == [], (starts, notices)


def test_long_sleep_is_refused_in_guarded_bash_but_not_inside_a_background_job(env):
    """長い sleep で会話を止めない (#77)。待つジョブ (bg_run) の中身には当てない。bypass でも外れない。"""
    proc = run_pi(env, bash_call("sleep 30"), PI_HARNESS_BYPASS="1")
    assert "isError=true" in proc.stdout and "10 秒以上の sleep" in proc.stdout, proc.stdout
    proc = run_pi(env, bash_call("sleep 1.5"), PI_HARNESS_BYPASS="1")
    assert "10 秒以上の sleep" not in proc.stdout, proc.stdout
    proc = run_pi(env, _bg("sleep 30"), extra=("-e", str(ACTIVITY)), PI_HARNESS_BYPASS="1")
    assert "started j1" in proc.stdout, proc.stdout
    assert "10 秒以上の sleep" not in proc.stdout, proc.stdout


def test_bg_run_asks_when_bash_would_ask(env):
    """bash なら確認になるコマンドは、バックグラウンドでも確認になる (UI が無ければ拒否)。"""
    marker = env["tmp"] / "started"
    proc = run_pi(env, _bg(f"touch {marker.as_posix()}"), extra=("-e", str(ACTIVITY)))
    assert "not approved:" in proc.stdout, proc.stdout
    assert not marker.exists()


def test_a_role_without_bash_cannot_use_the_background_tools(env):
    calls = [*_bg("wc -c /dev/null"), {"name": "bg_log", "args": {}}]
    proc = run_pi(env, calls, extra=("-e", str(ACTIVITY)), PI_HARNESS_ROLE="reader")
    assert "は bash を使えない" in proc.stdout, proc.stdout
    assert "は bg_log を使えない" in proc.stdout, proc.stdout


NOTIFY = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "notify" / "index.ts"


def test_the_bell_is_written_only_in_the_tui_not_in_print_mode(env):
    """BEL (\\x07) は TUI のときだけ。print / RPC では stdout が出力・通信なので汚さない。

    TUI で鳴ること自体は自動試験にできない (実機で確かめる)。
    """
    proc = run_pi(env, [], extra=("-e", str(NOTIFY)))
    assert proc.returncode == 0, proc.stderr
    assert "\x07" not in proc.stdout, repr(proc.stdout)
    proc = run_pi(env, bash_call("touch made-by-pi"), extra=("-e", str(NOTIFY)))
    assert "\x07" not in proc.stdout, repr(proc.stdout)


# --- todo の blocked (外部の完了待ち)。helper は test_pi_harness.py のものを使う ---
from test_pi_harness import TODO_EXT, _last_todo_result, _run_todo, _todo  # noqa: E402


def test_todo_blocked_can_be_set_and_stays_open(env):
    calls = [
        _todo(action="add", text="a"),
        _todo(action="set", id=1, status="blocked", note="bg job 7"),
        _todo(action="list"),
    ]
    proc = _run_todo(env, calls)
    assert proc.returncode == 0, proc.stderr
    tail = _last_todo_result(proc.stdout)
    assert "[~] #1: a — bg job 7" in tail, proc.stdout
    assert "注意" not in proc.stdout, proc.stdout


def test_todo_does_not_remind_when_only_blocked_items_remain(env):
    rounds = [
        [
            _todo(action="add", texts=["a"]),
            _todo(action="set", id=1, status="blocked", note="bg job 7"),
        ]
    ]
    proc = run_pi(
        env,
        [],
        extra=("-e", str(TODO_EXT)),
        FAUX_TOOL_ROUNDS=json.dumps(rounds),
        FAUX_ECHO_REMINDER="1",
    )
    assert proc.returncode == 0, proc.stderr
    assert "REMINDER=" not in proc.stdout, proc.stdout


def test_todo_blocked_is_not_counted_in_the_one_in_progress_warning(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(action="set", id=1, status="blocked", note="bg job 7"),
        _todo(action="set", id=2, status="in_progress"),
    ]
    proc = _run_todo(env, calls)
    assert proc.returncode == 0, proc.stderr
    assert "同時に 1 件" not in proc.stdout, proc.stdout


def test_todo_blocked_without_a_note_warns_but_is_accepted(env):
    calls = [_todo(action="add", text="a"), _todo(action="set", id=1, status="blocked")]
    proc = _run_todo(env, calls)
    assert proc.returncode == 0, proc.stderr
    tail = _last_todo_result(proc.stdout)
    assert "待ち先" in tail and "note" in tail and "#1 を blocked にした" in tail, proc.stdout


# --- delegate-nudge (N1a: 通知なしで集計を記録するだけ。CHG-0031) ---
from test_pi_harness import _session_entries, _task  # noqa: E402

DELEGATE_EXT = ROOT / "home/dot_pi/agent/extensions/delegate-nudge/index.ts"
READ_TOOLS = {"guarded_read", "guarded_grep", "guarded_find", "guarded_ls"}


def _delegate_run(env, calls, *messages, rounds=None, **env_extra):
    """セッションを残して実行する。記録は ``_delegate_stats`` でセッションのファイルから読む。"""
    sessions = env["tmp"] / "sessions"
    extra = ("--approve", "--session-dir", str(sessions), "-e", str(DELEGATE_EXT))
    if rounds is not None:
        env_extra.update(
            FAUX_TOOL_ROUNDS=json.dumps(rounds),
            FAUX_CHILD_TOOL_CALLS="[]",
            FAUX_COUNT_USER="1",
            PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
        )
    return run_pi(env, calls, *messages, session=True, extra=extra, **env_extra), sessions


def _delegate_stats(sessions):
    entries = [
        e["data"]
        for e in _session_entries(sessions)
        if e.get("type") == "custom" and e.get("customType") == "delegate-stats"
    ]
    return sorted(entries, key=lambda d: d["seq"])


def _read_results(sessions):
    """セッションに残った読み取り系ツールの結果 (message エントリ)。"""
    return [
        e["message"]
        for e in _session_entries(sessions)
        if e.get("type") == "message" and e["message"].get("toolName") in READ_TOOLS
    ]


def _text_lines(message):
    texts = [c["text"] for c in message["content"] if c.get("type") == "text"]
    return sum(0 if t == "" else t.count("\n") + 1 for t in texts)


READS = [
    {"name": "guarded_read", "args": {"path": "f.txt"}},
    {"name": "guarded_ls", "args": {"path": "."}},
]


def _with_file(env):
    (env["proj"] / "f.txt").write_text("a\nb\nc\n", encoding="utf-8")


def test_delegate_nudge_records_reads_without_notice_or_changing_results(env):
    _with_file(env)
    proc, sessions = _delegate_run(env, READS)
    assert proc.returncode == 0, proc.stderr
    # (a) 通知も結果の変更も無い: 結果は 1 要素のまま、出力に拡張の語が無い
    results = _read_results(sessions)
    assert len(results) == 2, proc.stdout
    assert all(len(m["content"]) == 1 for m in results), results
    assert "delegate" not in proc.stdout.lower(), proc.stdout
    # (b) 記録が 1 件。行数は、セッションに残った結果から数え直した値と一致する
    (stat,) = _delegate_stats(sessions)
    assert stat["v"] == 1 and stat["seq"] == 1 and stat["nudge"] == "off", stat
    assert re.fullmatch(r"[0-9a-f]{8}", stat["turnId"]), stat
    assert stat["readCalls"] == 2 and stat["readErrors"] == 0, stat
    assert stat["byTool"] == {"guarded_read": 1, "guarded_ls": 1}, stat
    assert stat["readLines"] == sum(_text_lines(m) for m in results) > 0, stat
    assert stat["delegations"] == {"explore": 0, "review": 0, "commit": 0, "worker": 0}, stat
    assert stat["otherCalls"] == 0, stat
    # 読んだ内容・パスは入れない
    assert "f.txt" not in json.dumps(stat) and set(stat) == {
        "v", "turnId", "seq", "ts", "nudge", "readCalls", "readLines", "readChars",
        "readErrors", "byTool", "delegations", "otherCalls", "endReason",
    }, stat  # fmt: skip


def test_delegate_nudge_splits_records_per_user_message(env):
    _with_file(env)
    proc, sessions = _delegate_run(env, READS, "go", "again")
    assert proc.returncode == 0, proc.stderr
    stats = _delegate_stats(sessions)
    # (c) 発言ごとにリセットされ、2 件に分かれる (累積ではない)
    assert [s["seq"] for s in stats] == [1, 2], stats
    assert [s["readCalls"] for s in stats] == [2, 2], stats
    assert stats[0]["turnId"] != stats[1]["turnId"], stats


def test_delegate_nudge_counts_new_delegations_but_not_status_or_followups(env):
    rounds = [
        [_task(agent="worker", task="first", keep=True)],
        [_task(jobId="{{JOB}}", status=True)],
        [_task(jobId="{{JOB}}", task="second")],
        [_task(jobId="{{JOB}}", close=True)],
        [_task(list=True)],
        [_task(tasks=[{"agent": "explore", "task": "x"}, {"agent": "review", "task": "y"}])],
    ]
    proc, sessions = _delegate_run(env, [], rounds=rounds)
    assert proc.returncode == 0, proc.stderr
    (stat,) = _delegate_stats(sessions)
    # (d) 新規は worker 1 + 一括の explore / review。status・追加依頼・close・list は数えない
    assert stat["delegations"] == {"explore": 1, "review": 1, "commit": 0, "worker": 1}, stat
    assert stat["otherCalls"] == 6 and stat["readCalls"] == 0, stat


def test_delegate_nudge_records_nothing_in_a_child(env):
    _with_file(env)
    proc, sessions = _delegate_run(
        env, [], PI_HARNESS_CHILD="1", FAUX_CHILD_TOOL_CALLS=json.dumps(READS)
    )
    # (e) 対照: 読み取りは実際に動いている (記録が無いのは拡張が動かなかったから)
    assert proc.returncode == 0, proc.stderr
    assert _read_results(sessions), proc.stdout
    assert _delegate_stats(sessions) == []


def test_delegate_nudge_can_be_turned_off_with_the_environment_variable(env):
    _with_file(env)
    proc, sessions = _delegate_run(env, READS, PI_DELEGATE_NUDGE="0")
    # (f) 対照 (上の試験) と同じ呼び出しで、記録だけが無い
    assert proc.returncode == 0, proc.stderr
    assert len(_read_results(sessions)) == 2, proc.stdout
    assert _delegate_stats(sessions) == []
