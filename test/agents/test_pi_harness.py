"""pi のフルガード (``~/.config/pi/harness``) を、偽のモデル (faux) で通信なしに回す試験。

pi が無い環境では skip する。pi の内部の挙動に頼る点 (``/reload`` で組み込みが同じ名前で
戻ること・``details`` に生の出力が入ることなど) も、ここで検出する。
see docs/spec/pi-guard.md
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from agents_common import ROOT, agents_config_dir, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

HARNESS_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"
TODO_EXT = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "todo" / "index.ts"
COMMIT_MESSAGE_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "commit-message.js"
FIXTURES = Path(__file__).resolve().parent / "pi"
SECRET = "abc123rawsecret"


@pytest.fixture
def env(tmp_path):
    """フルガードの置き場 (rules.json 付き)・作業ツリー・使い捨ての agent 置き場を用意する。"""
    harness = tmp_path / ".config" / "pi" / "harness"
    harness.mkdir(parents=True)
    shutil.copy2(HARNESS_SRC, harness / "index.ts")
    shutil.copytree(HARNESS_SRC.parent / "judge", harness / "judge")
    shutil.copy2(HARNESS_SRC.parent / "redact.ts", harness / "redact.ts")
    shutil.copy2(HARNESS_SRC.parent / "canary.ts", harness / "canary.ts")
    shutil.copy2(COMMIT_MESSAGE_SRC, harness / "commit-message.js")
    rules = gen.build_pi_harness({}, load_common())
    # 子エージェントも偽のモデルで動かす (階層のモデルは認証が要る)
    for agent in rules["agents"].values():
        agent["model"] = None
    (harness / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    agent = tmp_path / "agent"
    agent.mkdir()
    base = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(agent),
        "AGENTS_CONFIG_DIR": str(agents_config_dir()),
        "TMPDIR": str(tmp_path),
    }
    # 作業している環境の変数を持ち込まない (Orca の中で回すと ORCA_* が入っている)
    for key in [k for k in base if k.startswith(("PI_HARNESS_", "ORCA_"))]:
        base.pop(key, None)
    return {"harness": harness, "proj": proj, "env": base, "tmp": tmp_path}


def run_pi(env, calls, *messages, extra=(), mode="print", session=False, **env_extra):
    args = [PI, *(() if session else ("--no-session",)), "--model", "faux/spike"]
    args += ["-nbt", "-ne", "-e", "builtin:mcp", "-e", str(env["harness"])]
    args += [*extra, "-e", str(FIXTURES / "faux.ts")]
    if mode == "json":
        args += ["--mode", "json"]
    else:
        args += ["-p"]
    proc = subprocess.run(
        [*args, *(messages or ("go",))],
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls), **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    return proc


def bash_call(command):
    return [{"name": "guarded_bash", "args": {"command": command}}]


def lines(proc):
    return proc.stdout.strip().splitlines()


def test_only_guarded_tools_are_declared(env):
    proc = run_pi(env, [])
    assert proc.returncode == 0, proc.stderr
    tools = json.loads(lines(proc)[0].removeprefix("TOOLS="))
    names = ("bash", "edit", "find", "grep", "ls", "read", "task", "write")
    assert tools == sorted(f"guarded_{t}" for t in names)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("wc -c /dev/null", "isError=false"),
        ("git push", "isError=true :: `git push` は deny"),
        # UI の無い起動では確認できないので拒否
        ("touch made-by-pi", "isError=true :: not approved:"),
    ],
)
def test_decisions_reach_the_tools(env, command, expected):
    proc = run_pi(env, bash_call(command))
    assert expected in proc.stdout, proc.stdout + proc.stderr
    assert not (env["proj"] / "made-by-pi").exists()


def test_bypass_runs_ask_but_not_deny(env):
    run_pi(env, bash_call("touch made-by-pi"), PI_HARNESS_BYPASS="1")
    assert (env["proj"] / "made-by-pi").exists()
    proc = run_pi(env, bash_call("git push"), PI_HARNESS_BYPASS="1")
    assert "isError=true" in proc.stdout


# ─── サンドボックスのゲート (カナリアで実測できたときだけ緩和する) ───────────────


def _boundary_env(env, *, read=None, write=None, allowed=True):
    """サンドボックスの内側のつもりの環境変数。カナリアの既定は「読めない・書けない」(存在しない場所)。"""
    tmp = env["tmp"]
    out = {
        "PI_HARNESS_BOUNDARY": "1",
        "PI_HARNESS_CANARY_READ": str(read or tmp / "hidden" / "canary-read"),
        "PI_HARNESS_CANARY_WRITE": str(write or tmp / "hidden" / "canary-write"),
    }
    if allowed:
        root = str(env["proj"])
        out["PI_HARNESS_ALLOWED"] = json.dumps({"read": [root], "write": [root]})
    return out


def test_boundary_expected_but_canary_readable_refuses_to_start(env):
    readable = env["tmp"] / "readable"
    readable.write_text("secret", encoding="utf-8")
    proc = run_pi(env, bash_call("touch made-by-pi"), **_boundary_env(env, read=readable))
    assert proc.returncode != 0 and "サンドボックスを確認できない" in proc.stdout + proc.stderr
    assert not (env["proj"] / "made-by-pi").exists()


def test_boundary_expected_but_canary_writable_refuses_to_start(env):
    writable = env["tmp"] / "writable"
    proc = run_pi(env, [], **_boundary_env(env, write=writable))
    assert proc.returncode != 0 and "サンドボックスを確認できない" in proc.stdout + proc.stderr
    assert not writable.exists(), "カナリアの書き込みの跡を残している"
    existing = env["tmp"] / "existing"
    existing.write_text("x", encoding="utf-8")
    proc = run_pi(env, [], **_boundary_env(env, write=existing))
    assert proc.returncode != 0, "既にあるパスへの書き込みの失敗は、拒否の証明にならない"


def test_boundary_env_alone_never_relaxes(env):
    # 一覧・カナリアの場所が無い自己申告だけでは、起動しない (緩和もしない)
    proc = run_pi(env, bash_call("touch made-by-pi"), PI_HARNESS_BOUNDARY="1")
    assert proc.returncode != 0 and not (env["proj"] / "made-by-pi").exists()
    proc = run_pi(env, bash_call("touch made-by-pi"), **_boundary_env(env, allowed=False))
    assert proc.returncode != 0 and not (env["proj"] / "made-by-pi").exists()


def test_proven_boundary_drops_the_plain_shell_ask_and_explains_outside_access(env):
    proven = _boundary_env(env)
    proc = run_pi(env, bash_call("touch made-by-pi"), **proven)
    assert proc.returncode == 0, proc.stderr
    assert (env["proj"] / "made-by-pi").exists(), "証明できたのに日常の shell を確認した"
    # 規則に当たる deny は変わらない
    proc = run_pi(env, bash_call("git push"), **proven)
    assert "isError=true :: `git push` は deny" in proc.stdout
    # 許可の外は、確認ではなく理由つきの deny
    proc = run_pi(env, [{"name": "guarded_read", "args": {"path": "/etc/hostname"}}], **proven)
    assert "サンドボックスの外" in proc.stdout, proc.stdout + proc.stderr


def test_reader_role_does_not_see_bash(env):
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="reader")
    assert lines(proc)[0] == 'TOOLS=["guarded_find","guarded_grep","guarded_ls","guarded_read"]'
    assert "Tool guarded_bash not found" in proc.stdout


def test_the_default_role_comes_from_the_rules_and_the_environment_overrides_it(env):
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    rules["default_role"] = "reader"
    path.write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, bash_call("wc -c /dev/null"))
    assert lines(proc)[0] == 'TOOLS=["guarded_find","guarded_grep","guarded_ls","guarded_read"]'
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="implementer")
    assert "guarded_bash" in lines(proc)[0]


def test_unknown_role_registers_no_tools(env):
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="nobody")
    assert lines(proc)[0] == "TOOLS=[]", proc.stdout


def test_broken_judge_settings_are_denied(env):
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    rules["judge"]["common"] = {}  # [pi] が無い設定は、判定が失敗して deny になる
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, bash_call("wc -c /dev/null"))
    assert "isError=true" in proc.stdout, proc.stdout


def test_missing_rules_stop_startup(env):
    (env["harness"] / "rules.json").unlink()
    proc = run_pi(env, bash_call("wc -c /dev/null"))
    assert proc.returncode != 0


@pytest.mark.parametrize("mode", ["syntax", "delete"])
def test_reload_without_harness_leaves_no_tools(env, mode):
    builtin = {"name": "bash", "args": {"command": "wc -c /dev/null"}}
    calls = [*bash_call("wc -c /dev/null"), builtin]
    proc = run_pi(
        env,
        calls,
        "/spike-reload",
        "go",
        SPIKE_BREAK_MODE=mode,
        SPIKE_BREAK_FILE=str(env["harness"] / "index.ts"),
    )
    assert "TOOLS=[]" in proc.stdout, proc.stdout
    assert "Tool guarded_bash not found" in proc.stdout
    assert "Tool bash not found" in proc.stdout


def test_input_rewritten_after_the_decision_is_rejected(env):
    proc = run_pi(
        env,
        bash_call("wc -c /dev/null"),
        extra=("-e", str(FIXTURES / "mutator.ts")),
        MUTATE_TO=f"touch {env['proj']}/pwned",
    )
    assert "実行前の判定で止めた" in proc.stdout, proc.stdout
    assert not (env["proj"] / "pwned").exists()


def _secret_script(env):
    (env["proj"] / "big.py").write_text(
        "import time\n"
        f'print("password = \\"{SECRET}\\"", flush=True)\n'
        "time.sleep(1.5)\n"
        'for i in range(3000):\n    print(f"line {i} " + "x" * 40)\n'
        f'print("password = \\"{SECRET}\\" tail", flush=True)\n',
        encoding="utf-8",
    )


def test_bash_output_is_redacted_everywhere(env):
    _secret_script(env)
    # python3 は既定で確認になるので bypass で通す (判定ではなく伏字化を見る試験)
    proc = run_pi(env, bash_call("python3 big.py"), mode="json", PI_HARNESS_BYPASS="1")
    assert proc.returncode == 0, proc.stderr
    assert "伏字" in proc.stdout
    assert SECRET not in proc.stdout
    spills = {p for p in env["tmp"].glob("pi-bash-*.log")}
    assert spills, "退避ファイルができていない (出力の量か pi の版を確かめる)"
    for spill in spills:
        assert SECRET not in spill.read_text(encoding="utf-8")
    # details に生の出力が入る pi の挙動 (spike の E3) が前提なので、入っていることも確かめる
    events = [json.loads(line) for line in lines(proc) if line.startswith("{")]
    ends = [e for e in events if e.get("type") == "tool_execution_end"]
    assert any("truncation" in json.dumps(e["result"].get("details") or {}) for e in ends)


def test_output_of_commands_touching_protected_paths_is_withheld(env):
    proc = run_pi(env, bash_call("wc -c ~/.ssh/known_hosts"), PI_HARNESS_BYPASS="1")
    # wc は deny (秘密のパスの読み取り) で止まるか、通っても出力を伏せる
    assert "isError=true" in proc.stdout or "[伏字] 保護対象のパス" in proc.stdout, proc.stdout


# ─── 子エージェント ─────────────────────────────────────────────────


def run_child(env, agent, child_calls, **env_extra):
    calls = [{"name": "guarded_task", "args": {"agent": agent, "task": "do it"}}]
    return run_pi(
        env,
        calls,
        FAUX_CHILD_TOOL_CALLS=json.dumps(child_calls),
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
        **env_extra,
    )


def test_child_cannot_start_another_child(env):
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "x"}}]
    proc = run_child(env, "worker", calls)
    assert "completed" in proc.stdout, proc.stdout
    assert "Tool guarded_task not found" in proc.stdout


def test_reader_child_does_not_get_bash(env):
    proc = run_child(env, "explore", bash_call("wc -c /dev/null"))
    assert "Tool guarded_bash not found" in proc.stdout, proc.stdout


def test_child_ask_is_returned_as_blocked(env):
    proc = run_child(env, "worker", bash_call("touch by-child"))
    assert "child worker: blocked" in proc.stdout, proc.stdout
    assert "needs the user's approval" in proc.stdout
    assert "isError=true" in proc.stdout
    assert not (env["proj"] / "by-child").exists()


def test_parent_bypass_reaches_only_children_that_inherit_it(env):
    proc = run_child(env, "worker", bash_call("touch by-child"), PI_HARNESS_BYPASS="1")
    assert "child worker: completed" in proc.stdout, proc.stdout
    assert (env["proj"] / "by-child").exists()


@pytest.mark.parametrize("agent", ["worker", "commit"])
def test_child_role_denies_git_state_changes_even_with_bypass(env, agent):
    proc = run_child(env, agent, bash_call("git add -- x"), PI_HARNESS_BYPASS="1")
    assert "shell_deny" in proc.stdout, proc.stdout


def test_commit_child_reads_git_without_confirmation(env):
    subprocess.run(["git", "init", "-q"], cwd=env["proj"], check=True)
    proc = run_child(env, "commit", bash_call("git status --short"))
    assert "child commit: completed" in proc.stdout, proc.stdout
    assert "tool error" not in proc.stdout


# ─── MCP ────────────────────────────────────────────────────────────


def test_mcp_servers_are_registered_by_the_harness_and_judged(env):
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    config = {"command": sys.executable, "args": [str(FIXTURES / "mcp_server.py")]}
    rules["mcp"] = [{"name": "spike", "config": {**config, "exposure": "direct"}}]
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, [{"name": "mcp__spike__echo_secret", "args": {}}])
    assert "mcp__spike__echo_secret" in lines(proc)[0], proc.stdout
    # 実装役では MCP のツールは既定の扱い (確認)。UI の無い起動では拒否になる
    assert "isError=true :: not approved:" in proc.stdout, proc.stdout
    assert "mcp-raw-secret" not in proc.stdout


def test_guides_point_to_the_tool_to_use(env):
    (env["proj"] / "f.txt").write_text("x\n", encoding="utf-8")
    proc = run_pi(env, bash_call("cat f.txt"), PI_HARNESS_BYPASS="1")
    assert "isError=true" in proc.stdout, proc.stdout
    assert "read ツールを使ってください" in proc.stdout


# ─── 起動の入口 (pis) ───────────────────────────────────────────────

PIS = ROOT / "home" / "dot_local" / "bin" / "executable_pis"
OCS_LIB = ROOT / "home" / "dot_local" / "share" / "ocs"


@pytest.fixture
def pis_env(env, tmp_path):
    """pis が読む ~/.config/pi/harness を、一時的な HOME の下に置く。"""
    home = tmp_path / "home"
    shutil.copytree(env["harness"], home / ".config" / "pi" / "harness")
    # pis は ~/.local/share/ocs の本体を読み込む (配備先と同じ置き場)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(OCS_LIB, home / ".local" / "share" / "ocs", ignore=ignore)
    return {**env, "home": home, "env": {**env["env"], "HOME": str(home)}}


def run_pis(pis_env, *pis_args, calls=(), **env_extra):
    faux = str(FIXTURES / "faux.ts")
    # 標準はサンドボックスの中。この試験は素の起動 (フルガードだけ) を見るので --no-sandbox を付ける
    sandbox = () if "--boundary" in pis_args else ("--no-sandbox",)
    args = [str(PIS), *sandbox, *pis_args, "--model", "faux/spike", "-e", faux, "-p", "go"]
    return subprocess.run(
        [sys.executable, *args],
        cwd=pis_env["proj"],
        env={**pis_env["env"], "FAUX_TOOL_CALLS": json.dumps(list(calls)), **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )


def test_pis_starts_pi_with_the_harness(pis_env):
    proc = run_pis(pis_env, calls=bash_call("touch made-by-pi"), PI_HARNESS_CHILD="1")
    assert proc.returncode == 0, proc.stderr
    assert "guarded_task" in lines(proc)[0], "子の印を外して起動していない"
    assert "isError=true :: not approved:" in proc.stdout


def test_pis_bypass_and_role(pis_env):
    run_pis(pis_env, "--bypass", calls=bash_call("touch made-by-pi"))
    assert (pis_env["proj"] / "made-by-pi").exists()
    proc = run_pis(pis_env, "--role", "reader")
    assert lines(proc)[0] == 'TOOLS=["guarded_find","guarded_grep","guarded_ls","guarded_read"]'


def test_pis_refuses_without_the_harness(pis_env):
    shutil.rmtree(pis_env["home"] / ".config" / "pi" / "harness")
    proc = run_pis(pis_env)
    assert proc.returncode == 1 and "フルガードが無い" in proc.stderr


def _set_rules(pis_env, **changes):
    path = pis_env["home"] / ".config" / "pi" / "harness" / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            rules.pop(key, None)
        else:
            rules[key] = value
    path.write_text(json.dumps(rules), encoding="utf-8")


def test_pis_loads_exactly_the_own_extensions_listed_in_rules_json(pis_env):
    agent = Path(pis_env["env"]["PI_CODING_AGENT_DIR"])
    for name in ("own-demo", "unlisted"):
        (agent / "extensions" / name).mkdir(parents=True)
        shutil.copy2(FIXTURES / "ext_tool.ts", agent / "extensions" / name / "index.ts")
    # 一覧にあって配られていないもの (missing) は足さず、一覧に無いもの (unlisted) は読まない
    _set_rules(pis_env, extensions=["own-demo", "missing"])
    marker = pis_env["tmp"] / "loaded"
    proc = run_pis(pis_env, EXT_LOADED_FILE=str(marker))
    assert proc.returncode == 0, proc.stderr
    assert "ext_search" in lines(proc)[0] and marker.exists()
    _set_rules(pis_env, extensions=[])
    marker.unlink()
    proc = run_pis(pis_env, EXT_LOADED_FILE=str(marker))
    assert proc.returncode == 0, proc.stderr
    assert "ext_search" not in lines(proc)[0] and not marker.exists()


def test_pis_refuses_a_rules_json_without_the_extension_list(pis_env):
    _set_rules(pis_env, extensions=None)
    proc = run_pis(pis_env)
    assert proc.returncode == 1 and "拡張の一覧" in proc.stderr


def test_pis_refuses_servers_in_the_agent_mcp_json(pis_env):
    agent = Path(pis_env["env"]["PI_CODING_AGENT_DIR"])
    (agent / "mcp.json").write_text('{"mcpServers": {"x": {"command": "true"}}}', encoding="utf-8")
    proc = run_pis(pis_env)
    assert proc.returncode == 1 and "mcp.json" in proc.stderr
    (agent / "mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    assert run_pis(pis_env).returncode == 0


# ─── 圧縮・commit の表示・整形・RPC ─────────────────────────────────


def _session_entries(session_dir):
    entries = []
    for path in session_dir.rglob("*.jsonl"):
        entries += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return entries


def test_compaction_carries_the_handover_instructions_and_file_lists(env):
    settings = env["proj"] / ".pi"
    settings.mkdir()
    small = '{"compaction": {"keepRecentTokens": 1}}'
    (settings / "settings.json").write_text(small, encoding="utf-8")
    (env["proj"] / "f.txt").write_text("x\n", encoding="utf-8")
    sessions = env["tmp"] / "sessions"
    calls = [{"name": "guarded_read", "args": {"path": "f.txt"}}]
    proc = run_pi(
        env,
        calls,
        "go",
        "again",  # 履歴の要約 (指示が入る側) が空にならないよう、ターンを複数にする
        "/spike-compact",
        session=True,
        extra=("--approve", "--session-dir", str(sessions), "-e", str(FIXTURES / "compact.ts")),
    )
    assert proc.returncode == 0, proc.stderr
    compactions = [e for e in _session_entries(sessions) if e.get("type") == "compaction"]
    assert compactions, proc.stdout + proc.stderr
    entry = compactions[-1]
    assert "INSTR=yes" in entry["summary"], f"圧縮の指示が要約の依頼に入っていない: {proc.stderr}"
    details = entry.get("details") or {}
    assert "f.txt" in json.dumps(details), "別名のツールで読んだファイルが一覧に無い"


def _rpc(env, calls, answers, timeout=120):
    """pi を RPC モードで動かし、確認の要求 (extension_ui_request) に answers の順に応える。"""
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), "-e", str(FIXTURES / "faux.ts"), "--mode", "rpc"]
    proc = subprocess.Popen(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    requests = []
    proc.stdin.write(json.dumps({"type": "prompt", "message": "go"}) + "\n")
    proc.stdin.flush()
    deadline = time.time() + timeout
    try:
        for line in proc.stdout:
            if time.time() > deadline:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "extension_ui_request" and event.get("method") == "confirm":
                requests.append(event)
                answer = answers[len(requests) - 1] if len(requests) <= len(answers) else False
                reply = {"type": "extension_ui_response", "id": event["id"], "confirmed": answer}
                proc.stdin.write(json.dumps(reply) + "\n")
                proc.stdin.flush()
            if event.get("type") == "agent_end":
                break
    finally:
        proc.kill()
    return requests


def _rpc_script(env, calls, messages, answers, timeout=120, status_key="bypass", extra=()):
    """RPC で messages を順に送る。確認 (confirm) には answers の順に応え、尽きたら拒否する。

    各メッセージは、応答 (response) を待ち、実行が始まったもの (started) は agent_end まで待つ。
    返すのは、確認の要求と、status_key の表示 (setStatus) の履歴。
    """
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), *extra, "-e", str(FIXTURES / "faux.ts"), "--mode", "rpc"]
    proc = subprocess.Popen(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    requests, statuses = [], []
    deadline = time.time() + timeout
    try:
        for index, message in enumerate(messages):
            command = {"id": f"m{index}", "type": "prompt", "message": message}
            proc.stdin.write(json.dumps(command) + "\n")
            proc.stdin.flush()
            responded, started, ended = False, False, False
            for line in proc.stdout:
                if time.time() > deadline:
                    raise TimeoutError(f"{message!r}: {requests} {statuses}")
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "extension_ui_request":
                    if event.get("method") == "confirm":
                        requests.append(event)
                        n = len(requests)
                        answer = answers[n - 1] if n <= len(answers) else False
                        reply = {"type": "extension_ui_response", "id": event["id"]}
                        proc.stdin.write(json.dumps({**reply, "confirmed": answer}) + "\n")
                        proc.stdin.flush()
                    elif (
                        event.get("method") == "setStatus" and event.get("statusKey") == status_key
                    ):
                        statuses.append(event.get("statusText"))
                if event.get("type") == "response" and event.get("id") == f"m{index}":
                    responded = True
                    started = (event.get("data") or {}).get("disposition") == "started"
                if event.get("type") == "agent_end":
                    ended = True
                if responded and (ended or not started):
                    break
    finally:
        proc.kill()
    return requests, statuses


def test_bypass_command_turns_on_after_confirmation_and_shows_the_status(env):
    # /bypass on の確認に応じると、次の ask が確認なしで通る
    calls = bash_call("touch made-by-pi")
    requests, statuses = _rpc_script(env, calls, ["/bypass on", "go"], [True])
    assert len(requests) == 1 and "bypass" in requests[0]["title"], requests
    # 先頭の None は起動時の消去。ON で表示が出る
    assert statuses[0] is None and "bypass" in statuses[-1], statuses
    assert (env["proj"] / "made-by-pi").exists()


def test_bypass_command_declined_keeps_asking(env):
    calls = bash_call("touch made-by-pi")
    requests, statuses = _rpc_script(env, calls, ["/bypass on", "go"], [False, False])
    assert len(requests) == 2, requests  # bypass の確認と、touch の確認
    assert statuses == [] or all(s is None for s in statuses)
    assert not (env["proj"] / "made-by-pi").exists()


def test_bypass_command_off_restores_asking_and_clears_the_status(env):
    messages = ["/bypass on", "/bypass off", "go"]
    requests, statuses = _rpc_script(env, bash_call("touch made-by-pi"), messages, [True, False])
    assert len(requests) == 2, requests  # bypass の確認 (OFF は確認なし) と、touch の確認
    assert statuses[0] is None and "bypass" in statuses[1] and statuses[-1] is None, statuses
    assert not (env["proj"] / "made-by-pi").exists()


def test_bypass_command_does_not_lift_deny(env):
    requests, _ = _rpc_script(env, bash_call("git push"), ["/bypass on", "go"], [True])
    assert len(requests) == 1, requests  # git push は確認も出ずに拒否される
    assert not (env["proj"] / "pushed").exists()


def test_bypass_starting_value_is_shown_and_can_be_turned_off(env):
    env["env"]["PI_HARNESS_BYPASS"] = "1"
    calls = bash_call("touch made-by-pi")
    requests, statuses = _rpc_script(env, calls, ["/bypass off", "go"], [False])
    assert statuses and statuses[-1] is None, statuses
    assert len(requests) == 1, requests  # touch の確認だけ
    assert not (env["proj"] / "made-by-pi").exists()


def _todo(**args):
    return {"name": "todo", "args": args}


def _last_todo_result(stdout):
    """偽のモデルが書き出した、最後の todo の結果 (`todo: isError=… :: 本文`) の本文。"""
    return stdout.split("todo: isError=")[-1]


def _run_todo(env, calls, *messages, **kwargs):
    extra = ("-e", str(TODO_EXT), *kwargs.pop("extra", ()))
    return run_pi(env, calls, *messages, extra=extra, **kwargs)


def test_todo_adds_many_sets_states_and_folds_finished_items(env):
    calls = [
        _todo(action="add", texts=["a", "b", "c"]),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=2, status="in_progress"),
        _todo(action="list"),
    ]
    proc = _run_todo(env, calls)
    assert proc.returncode == 0, proc.stderr
    assert "追加: #1 a / #2 b / #3 c" in proc.stdout, proc.stdout
    # 畳んだ一覧: 未完了だけ出し、完了は件数にする
    tail = _last_todo_result(proc.stdout)
    assert "[>] #2: b" in tail and "[ ] #3: c" in tail and "完了 1 件" in tail, proc.stdout
    assert "[x] #1: a" not in tail, proc.stdout


def test_todo_list_all_shows_finished_and_cancelled(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=2, status="cancelled"),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    assert "[x] #1: a" in proc.stdout and "[-] #2: b" in proc.stdout, proc.stdout


def test_todo_set_is_idempotent_unlike_toggle(env):
    calls = [
        _todo(action="add", text="a"),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=1, status="done"),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    assert "[x] #1: a" in _last_todo_result(proc.stdout), proc.stdout


def test_todo_warns_on_several_in_progress_and_rejects_bad_input(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(action="set", id=1, status="in_progress"),
        _todo(action="set", id=2, status="in_progress"),
        _todo(action="set", id=99, status="done"),
        _todo(action="update", id=1),
        _todo(action="add"),
    ]
    proc = _run_todo(env, calls)
    assert "in_progress が 2 件" in proc.stdout, proc.stdout
    assert "#99 が無い" in proc.stdout, proc.stdout
    assert "update には text が要る" in proc.stdout, proc.stdout
    assert "add には text か texts が要る" in proc.stdout, proc.stdout


def test_todo_update_and_remove(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(action="update", id=1, text="a2"),
        _todo(action="remove", id=2),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    last = _last_todo_result(proc.stdout)
    assert "[ ] #1: a2" in last and "#2" not in last, proc.stdout


def _todo_states(sessions):
    """セッションに残った todo の状態を、古い順に返す。

    ツール結果の details と、利用者の操作の custom エントリ (todo-state) の両方。
    """
    states = []
    for e in _session_entries(sessions):
        if e.get("type") == "message" and e["message"].get("toolName") == "todo":
            states.append(e["message"]["details"])
        elif e.get("type") == "custom" and e.get("customType") == "todo-state":
            states.append(e["data"])
    return states


def _resume_todo(env, sessions, calls, *messages, **kwargs):
    extra = ("--approve", "--session-dir", str(sessions), "-c", *kwargs.pop("extra", ()))
    return _run_todo(env, calls, *messages, session=True, extra=extra, **kwargs)


def test_todo_state_survives_resume_and_reads_the_old_format(env):
    sessions = env["tmp"] / "sessions"
    first = [_todo(action="add", texts=["a", "b"]), _todo(action="set", id=1, status="done")]
    proc = _run_todo(env, first, session=True, extra=("--approve", "--session-dir", str(sessions)))
    assert proc.returncode == 0, proc.stderr
    # 旧形式 ({ id, text, done }) に戻す
    for path in sessions.rglob("*.jsonl"):
        text = path.read_text(encoding="utf-8")
        text = text.replace('"status":"done"', '"done":true').replace(
            '"status":"pending"', '"done":false'
        )
        path.write_text(text, encoding="utf-8")
    proc = _resume_todo(
        env, sessions, [_todo(action="add", text="c"), _todo(action="list", all=True)]
    )
    assert proc.returncode == 0, proc.stderr
    last = _last_todo_result(proc.stdout)
    # 旧形式の done が完了として読まれ、ID は続き (#3) から振られる
    assert "[x] #1: a" in last and "[ ] #2: b" in last and "[ ] #3: c" in last, proc.stdout


def test_todos_tidy_and_clear_are_user_commands_that_persist(env):
    sessions = env["tmp"] / "sessions"
    calls = [_todo(action="add", texts=["a", "b"]), _todo(action="set", id=1, status="done")]
    extra = ("--approve", "--session-dir", str(sessions))
    proc = _run_todo(env, calls, "go", "/todos tidy", session=True, extra=extra)
    assert proc.returncode == 0, proc.stderr
    # 利用者の操作は custom エントリで残り、完了だけが片付いている
    last = _todo_states(sessions)[-1]
    assert [t["id"] for t in last["todos"]] == [2], last
    # 再開しても片付いたまま。モデルが呼べるのはツールだけで、/todos は呼べない
    proc = _resume_todo(env, sessions, [_todo(action="list", all=True)])
    tail = _last_todo_result(proc.stdout)
    assert "#1" not in tail and "[ ] #2: b" in tail, proc.stdout


def test_todo_state_survives_compaction(env):
    settings = env["proj"] / ".pi"
    settings.mkdir()
    (settings / "settings.json").write_text(
        '{"compaction": {"keepRecentTokens": 1}}', encoding="utf-8"
    )
    sessions = env["tmp"] / "sessions"
    extra = ("--approve", "--session-dir", str(sessions), "-e", str(FIXTURES / "compact.ts"))
    calls = [_todo(action="add", text="x")]
    proc = _run_todo(env, calls, "go", "again", "/spike-compact", session=True, extra=extra)
    assert proc.returncode == 0, proc.stderr
    assert any(e.get("type") == "compaction" for e in _session_entries(sessions)), (
        proc.stdout + proc.stderr
    )
    proc = _resume_todo(
        env, sessions, [_todo(action="list", all=True)], extra=("-e", str(FIXTURES / "compact.ts"))
    )
    # 圧縮の前に足した項目 (2 ターン分) が、圧縮のあとも復元される
    assert "#1: x" in proc.stdout and "#2: x" in proc.stdout, proc.stdout


def test_todo_footer_shows_progress_the_active_item_and_clears_on_tidy(env):
    calls = [
        _todo(action="add", texts=["first step", "second"]),
        _todo(action="set", id=1, status="in_progress"),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=2, status="done"),
    ]
    extra = (str(TODO_EXT),)
    _, statuses = _rpc_script(
        env, calls, ["go", "/todos tidy"], [], status_key="todo", extra=("-e", *extra)
    )
    assert any(s and "📋 0/2 ▶ first step" in s for s in statuses), statuses
    assert any(s and "✅ 2/2" in s for s in statuses), statuses
    assert statuses[-1] is None, statuses  # 片付けて空になったら表示を消す


def test_git_commit_confirmation_shows_subject_and_body(env):
    subprocess.run(["git", "init", "-q"], cwd=env["proj"], check=True)
    command = "git commit -m 'feat: 件名です' -m '本文の 1 行目'"
    requests = _rpc(env, bash_call(command), [False])
    assert len(requests) == 1, requests
    message = requests[0]["message"]
    assert "件名: feat: 件名です" in message and "本文の 1 行目" in message
    assert "理由:" in message
    # RPC ではクライアントが応えないと永久に待つので、期限が付く
    assert requests[0].get("timeout"), "確認に期限が付いていない"


def test_approved_rpc_confirmation_runs_the_tool(env):
    requests = _rpc(env, bash_call("touch made-via-rpc"), [True])
    assert len(requests) == 1
    assert (env["proj"] / "made-via-rpc").exists()


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")
def test_python_files_are_formatted_after_a_write(env):
    messy = "x   =   1\nprint( x )\n"
    calls = [{"name": "guarded_write", "args": {"path": "m.py", "content": messy}}]
    run_pi(env, calls)
    assert (env["proj"] / "m.py").read_text(encoding="utf-8") == "x = 1\nprint(x)\n"


@pytest.mark.skipif(shutil.which("markdownlint-cli2") is None, reason="markdownlint-cli2 無し")
def test_markdownlint_warnings_reach_the_model(env):
    body = "# Title\n\n```\ncode without a language\n```\n"
    calls = [{"name": "guarded_write", "args": {"path": "d.md", "content": body}}]
    proc = run_pi(env, calls)
    assert "[markdownlint] issues remain" in proc.stdout, proc.stdout


# ─── プロンプトテンプレート (/fleet)・キーバインド・共通の指示 ──────


def _render(template: Path) -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    done = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=template.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout


def test_fleet_prompt_template_expands_under_no_extensions(env):
    prompts = Path(env["env"]["PI_CODING_AGENT_DIR"]) / "prompts"
    prompts.mkdir()
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "prompts" / "fleet.md.tmpl")
    (prompts / "fleet.md").write_text(rendered, encoding="utf-8")
    proc = run_pi(env, [], "/fleet README を直す", FAUX_ECHO_USER="1")
    assert proc.returncode == 0, proc.stderr
    # 引数が $ARGUMENTS に入り、テンプレート本文が利用者の発言として届く
    assert "依頼:\nREADME を直す" in proc.stdout, proc.stdout
    assert "guarded_task" in proc.stdout


def test_stepback_prompt_template_expands_the_question_and_asks_for_a_step_back(env):
    prompts = Path(env["env"]["PI_CODING_AGENT_DIR"]) / "prompts"
    prompts.mkdir()
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "prompts" / "stepback.md.tmpl")
    (prompts / "stepback.md").write_text(rendered, encoding="utf-8")
    proc = run_pi(env, [], "/stepback なぜ cron が動かない", FAUX_ECHO_USER="1")
    assert proc.returncode == 0, proc.stderr
    assert "質問:\nなぜ cron が動かない" in proc.stdout, proc.stdout
    assert "ステップバック質問" in proc.stdout
    # 読み取りだけで確かめる指示 (状態を変えない) と、ツール名に依らない文面であること
    assert "状態を変えない" in proc.stdout
    assert "guarded_" not in proc.stdout


def test_stepback_without_an_argument_targets_the_previous_exchange(env):
    prompts = Path(env["env"]["PI_CODING_AGENT_DIR"]) / "prompts"
    prompts.mkdir()
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "prompts" / "stepback.md.tmpl")
    (prompts / "stepback.md").write_text(rendered, encoding="utf-8")
    proc = run_pi(env, [], "/stepback", FAUX_ECHO_USER="1")
    assert proc.returncode == 0, proc.stderr
    # 引数が空でも展開され、「質問:」が空のときは直前のやり取りを対象にする指示が届く
    assert "質問:\n\n" in proc.stdout, proc.stdout
    assert "直前の利用者の質問" in proc.stdout
    assert "$ARGUMENTS" not in proc.stdout


def test_shared_instructions_are_rendered_for_pi():
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "AGENTS.md.tmpl")
    assert rendered.strip(), "共通の指示が空"
    claude = _render(ROOT / "home" / "dot_claude" / "CLAUDE.md.tmpl")
    assert rendered.strip() == claude.strip()


def test_keybindings_are_generated_from_the_declaration():
    out = gen.pi_keybindings({}, load_common())
    assert out["app.interrupt"] == ["escape", "ctrl+c"] and out["app.clear"] == []
    assert out == load_common()["pi"]["keybinds"]


@pytest.mark.parametrize("bad", [{"app.exit": ""}, {"app.exit": [1]}, {"app.exit": None}])
def test_bad_keybindings_stop_generation(bad):
    common = load_common()
    common["pi"]["keybinds"] = bad
    with pytest.raises(SystemExit, match=r"pi\.keybinds"):
        gen.pi_keybindings({}, common)


# ─── Orca のステータス拡張 ──────────────────────────────────────────


def _orca_extension(pis_env, probe, marker=True):
    """Orca が置く拡張の代役。呼ばれたら印のファイルを書く。"""
    agent = Path(pis_env["env"]["PI_CODING_AGENT_DIR"])
    (agent / "extensions").mkdir(exist_ok=True)
    head = "// @orca-managed-pi-extension\n" if marker else "// someone else\n"
    body = (
        head
        + 'import { writeFileSync } from "node:fs";\n'
        + "export default function (pi) {\n"
        + '  pi.registerCommand("orca-probe", { description: "p", handler: async () => {\n'
        + f'    writeFileSync("{probe}", "loaded");\n'
        + "  } });\n}\n"
    )
    (agent / "extensions" / "orca-agent-status.ts").write_text(body, encoding="utf-8")


def _run_pis_probe(pis_env, **env_extra):
    faux = str(FIXTURES / "faux.ts")
    probe = ["-p", "/orca-probe"]
    return subprocess.run(
        [sys.executable, str(PIS), "--no-sandbox", "--model", "faux/spike", "-e", faux, *probe],
        cwd=pis_env["proj"],
        env={**pis_env["env"], "FAUX_TOOL_CALLS": "[]", **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_pis_loads_orcas_status_extension_only_from_orca_with_its_marker(pis_env, tmp_path):
    probe = tmp_path / "probe"
    _orca_extension(pis_env, probe)
    _run_pis_probe(pis_env)
    assert not probe.exists(), "Orca の外で Orca の拡張を読んだ"
    _run_pis_probe(pis_env, ORCA_AGENT_HOOK_PORT="1")
    assert probe.exists(), "Orca の中で Orca の拡張を読んでいない"
    probe.unlink()
    _orca_extension(pis_env, probe, marker=False)
    _run_pis_probe(pis_env, ORCA_AGENT_HOOK_PORT="1")
    assert not probe.exists(), "印の無い拡張を読んだ"
