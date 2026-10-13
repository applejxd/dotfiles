"""素の pi 向けのガード (home/dot_config/pi/guard) を、本物の pi と偽のモデルで動かす試験。

settings.json の ``extensions`` から読ませる (ハーネスは使わない)。deny だけを止め、ask は通す。
see docs/spec/pi-harness.md#素の-pi-のガード
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from agents_common import ROOT, load_common
from test_pi_harness import SECRET, _secret_script

PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

PI_DIR = ROOT / "home" / "dot_config" / "pi"
FIXTURES = Path(__file__).resolve().parent / "pi"


@pytest.fixture
def env(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "agents"))
    import generate as gen

    config = tmp_path / ".config" / "pi"
    guard = config / "guard"
    harness = config / "harness"
    guard.mkdir(parents=True)
    harness.mkdir()
    shutil.copy2(PI_DIR / "guard" / "index.ts", guard / "index.ts")
    shutil.copytree(PI_DIR / "harness" / "judge", harness / "judge")
    shutil.copy2(PI_DIR / "harness" / "redact.ts", harness / "redact.ts")
    (harness / "rules.json").write_text(
        json.dumps(gen.build_pi_harness({}, load_common())), encoding="utf-8"
    )
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(json.dumps({"extensions": [str(guard)]}), encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    # HOME を使い捨てにする: ガードが働かなかったとき、`rm -rf ~` が本物のホームを消さないように
    base = {
        **os.environ,
        "HOME": str(tmp_path),
        "PI_CODING_AGENT_DIR": str(agent),
        "TMPDIR": str(tmp_path),
    }
    for key in [k for k in base if k.startswith(("PI_HARNESS_", "ORCA_"))]:
        base.pop(key, None)
    return {"guard": guard, "harness": harness, "proj": proj, "env": base, "tmp": tmp_path}


def run_pi(env, calls, *, extra=(), **env_extra):
    args = [PI, "--no-session", "--model", "faux/spike", *extra, "-e", str(FIXTURES / "faux.ts")]
    proc = subprocess.run(
        [*args, "-p", "go"],
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls), **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    return proc


def bash(command):
    return [{"name": "bash", "args": {"command": command}}]


def test_a_denied_command_is_blocked_with_the_reason(env):
    marker = env["tmp"] / "started"
    proc = run_pi(env, bash(f"touch {marker.as_posix()}; rm -rf ~"))
    assert "isError=true" in proc.stdout, proc.stdout
    assert "壊滅的" in proc.stdout, proc.stdout
    assert not marker.exists()


def test_git_push_is_denied(env):
    proc = run_pi(env, bash("git push"))
    assert "isError=true" in proc.stdout and "deny" in proc.stdout, proc.stdout


def test_a_guide_denial_tells_the_model_what_to_do_instead(env):
    (env["proj"] / "a.txt").write_text("x\n", encoding="utf-8")
    proc = run_pi(env, bash("cat a.txt"))
    assert "isError=true" in proc.stdout, proc.stdout
    assert "read ツール" in proc.stdout, proc.stdout


def test_an_allowed_command_runs(env):
    proc = run_pi(env, bash("wc -c /dev/null"))
    assert "isError=false" in proc.stdout, proc.stdout


def test_ask_is_not_blocked_unlike_the_harness(env):
    """ハーネスなら確認になる (UI が無ければ拒否) 操作が、ガードでは通る。確認は出さない。"""
    marker = env["tmp"] / "made"
    proc = run_pi(env, bash(f"touch {marker.as_posix()}"))
    assert "isError=false" in proc.stdout, proc.stdout
    assert marker.exists()


def test_reading_a_protected_path_is_denied(env):
    secret = env["tmp"] / ".ssh" / "id_rsa"  # HOME は使い捨て
    secret.parent.mkdir()
    secret.write_text("not a key" + chr(10), encoding="utf-8")
    calls = [{"name": "read", "args": {"path": str(secret)}}]
    proc = run_pi(env, calls)
    assert "isError=true" in proc.stdout, proc.stdout
    assert "read_deny_globs" in proc.stdout, proc.stdout


def test_other_extensions_tools_are_not_judged(env):
    """判定器は役割に無いツールを deny するので、対象を判定器の規則があるツールに絞っている。"""
    ran = env["tmp"] / "ran"
    calls = [{"name": "ext_search", "args": {"query": "hello"}}]
    run_pi(
        env,
        calls,
        extra=("-e", str(FIXTURES / "ext_tool.ts")),
        EXT_RAN_FILE=str(ran),
    )
    assert ran.exists()


def test_a_broken_judge_setting_blocks_the_judged_tools_instead_of_passing_them(env):
    (env["harness"] / "rules.json").write_text("{}", encoding="utf-8")
    marker = env["tmp"] / "started"
    proc = run_pi(env, bash(f"touch {marker.as_posix()}"))
    assert "isError=true" in proc.stdout, proc.stdout
    assert "ガードの設定を読めない" in proc.stdout, proc.stdout
    assert not marker.exists()


def test_background_jobs_are_judged_like_bash(env):
    activity = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "activity" / "index.ts"
    marker = env["tmp"] / "started"
    calls = [{"name": "bg_run", "args": {"command": f"touch {marker.as_posix()}; rm -rf ~"}}]
    proc = run_pi(env, calls, extra=("-e", str(activity)))
    assert "isError=true" in proc.stdout and "壊滅的" in proc.stdout, proc.stdout
    assert not marker.exists()


def test_the_guard_is_listed_on_unix_but_not_on_windows():
    """ガードはハーネスの判定器に依るので、Windows の settings.json には載せない。"""
    from test_herdr_integration import render_template

    path = ROOT / "home" / "dot_config" / "agents" / "common.toml.tmpl"

    linux = tomllib.loads(render_template(path, os_name="linux"))
    windows = tomllib.loads(render_template(path, os_name="windows"))
    assert "~/.config/pi/guard" in linux["pi"]["settings"]["extensions"]
    assert "~/.config/pi/commit-confirm" in linux["pi"]["settings"]["extensions"]
    assert windows["pi"]["settings"]["extensions"] == ["~/.config/pi/commit-confirm"]


# ─── 伏字化 ──────────────────────────────────────────────────────────


def test_bash_output_is_redacted_including_the_spill_file(env):
    _secret_script(env)
    args = [PI, "--no-session", "--model", "faux/spike", "-e", str(FIXTURES / "faux.ts")]
    proc = subprocess.run(
        [*args, "--mode", "json", "go"],
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(bash("python3 big.py"))},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "伏字" in proc.stdout
    # 実行中の途中経過 (tool_execution_update) は、ガードでは伏せられない (画面とイベントに出るだけ
    # で、モデルへ渡る結果ではない)。最終の結果・メッセージ・退避ファイルは伏せる
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    final = [e for e in events if e.get("type") != "tool_execution_update"]
    assert SECRET not in json.dumps(final, ensure_ascii=False)
    spills = list(env["tmp"].glob("pi-bash-*.log"))
    assert spills, "退避ファイルができていない (出力の量か pi の版を確かめる)"
    for spill in spills:
        assert SECRET not in spill.read_text(encoding="utf-8")


def test_a_command_touching_a_protected_path_is_not_run(env):
    marker = env["tmp"] / "started"
    proc = run_pi(env, bash(f"touch {marker.as_posix()} ~/.ssh/known_hosts"))
    assert "isError=true" in proc.stdout, proc.stdout
    assert not marker.exists()


def test_file_tools_are_not_redacted(env):
    """read の結果を伏せると、伏せた本文を元に edit されてファイルへ伏字が書き込まれる。"""
    (env["proj"] / "note.txt").write_text("password = " + SECRET + "\n", encoding="utf-8")
    proc = run_pi(env, [{"name": "read", "args": {"path": "note.txt"}}])
    assert SECRET in proc.stdout, proc.stdout


def _ext_result(env):
    calls = [{"name": "ext_search", "args": {"query": "hello"}}]
    return run_pi(
        env,
        calls,
        extra=("-e", str(FIXTURES / "ext_tool.ts")),
        EXT_RAN_FILE=str(env["tmp"] / "ran"),
        EXT_SECRET=SECRET,
    )


def test_other_extensions_results_are_redacted(env):
    proc = _ext_result(env)
    assert "伏字" in proc.stdout, proc.stdout
    assert SECRET not in proc.stdout


def test_results_are_withheld_when_the_redaction_setting_is_missing(env):
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    del rules["redact"]
    path.write_text(json.dumps(rules), encoding="utf-8")
    proc = _ext_result(env)
    assert "伏字化に失敗" in proc.stdout, proc.stdout
    assert SECRET not in proc.stdout
