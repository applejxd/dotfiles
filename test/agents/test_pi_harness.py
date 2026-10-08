"""pi のハーネス (``~/.config/pi/harness``) を、偽のモデル (faux) で通信なしに回す試験。

pi が無い環境では skip する。pi の内部の挙動に頼る点 (``/reload`` で組み込みが同じ名前で
戻ること・``details`` に生の出力が入ることなど) も、ここで検出する。
see docs/spec/pi-harness.md
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT, agents_config_dir, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

HARNESS_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"
DECIDE = ROOT / "home" / "dot_claude" / "hooks" / "executable_decide.py"
FIXTURES = Path(__file__).resolve().parent / "pi"
SECRET = "abc123rawsecret"


@pytest.fixture
def env(tmp_path):
    """ハーネスの置き場 (rules.json 付き)・作業ツリー・使い捨ての agent 置き場を用意する。"""
    harness = tmp_path / "harness"
    harness.mkdir()
    shutil.copy2(HARNESS_SRC, harness / "index.ts")
    rules = gen.build_pi_harness({}, load_common())
    rules["decide"] = str(DECIDE)
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
    for key in ("PI_HARNESS_ROLE", "PI_HARNESS_BYPASS", "PI_HARNESS_BOUNDARY"):
        base.pop(key, None)
    return {"harness": harness, "proj": proj, "env": base, "tmp": tmp_path}


def run_pi(env, calls, *messages, extra=(), mode="print", **env_extra):
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", str(env["harness"])]
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
    names = ("bash", "edit", "find", "grep", "ls", "read", "write")
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


def test_reader_role_cannot_use_bash(env):
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="reader")
    assert "isError=true" in proc.stdout and "使えない" in proc.stdout


def test_broken_decide_is_denied(env):
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    rules["decide"] = str(env["tmp"] / "missing.py")
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
