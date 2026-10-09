"""素の pi 向けの補助 (home/dot_config/pi/commit-confirm) の試験。

settings.json の ``extensions`` から読ませ、本物の pi + 偽のモデルで確認の流れを見る。
see docs/spec/pi-harness.md#commit-の確認-素の-pi
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from agents_common import ROOT

PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

EXT_SRC = ROOT / "home" / "dot_config" / "pi" / "commit-confirm"
GUIDE_SRC = ROOT / "home" / "dot_config" / "opencode" / "guide-plugin"
FIXTURES = Path(__file__).resolve().parent / "pi"
HARNESS_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"


@pytest.fixture
def env(tmp_path):
    # 配備先と同じ並び (拡張は ../../opencode/guide-plugin/commit-message.js を取り込む)
    ext = tmp_path / ".config" / "pi" / "commit-confirm"
    ext.mkdir(parents=True)
    shutil.copy2(EXT_SRC / "index.ts", ext / "index.ts")
    guide = tmp_path / ".config" / "opencode" / "guide-plugin"
    guide.mkdir(parents=True)
    shutil.copy2(GUIDE_SRC / "commit-message.js", guide / "commit-message.js")
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(json.dumps({"extensions": [str(ext)]}), encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    git_env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    base = {**os.environ, **git_env, "PI_CODING_AGENT_DIR": str(agent), "TMPDIR": str(tmp_path)}
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    (proj / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=proj, check=True)
    return {"proj": proj, "env": base, "tmp": tmp_path}


def bash_call(command):
    return [{"name": "bash", "args": {"command": command}}]


def commits(env):
    done = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=env["proj"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return done.stdout.split()


def _args(*extra, mode):
    faux = str(FIXTURES / "faux.ts")
    return [PI, "--no-session", "--model", "faux/spike", *extra, "-e", faux, "--mode", mode]


def _rpc(env, calls, answers, extra=()):
    """RPC で動かし、確認の要求 (extension_ui_request) に answers の順に応える。"""
    proc = subprocess.Popen(
        _args(*extra, mode="rpc"),
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
    deadline = time.time() + 120
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
                ok = answers[len(requests) - 1] if len(requests) <= len(answers) else False
                reply = {"type": "extension_ui_response", "id": event["id"], "confirmed": ok}
                proc.stdin.write(json.dumps(reply) + "\n")
                proc.stdin.flush()
            if event.get("type") == "agent_end":
                break
    finally:
        proc.kill()
    return requests


COMMIT = "git commit -m 'feat: 件名です' -m '本文の 1 行目'"


def test_commit_confirmation_shows_subject_and_body(env):
    requests = _rpc(env, bash_call(COMMIT), [False])
    assert len(requests) == 1, requests
    message = requests[0]["message"]
    assert "件名: feat: 件名です" in message and "本文の 1 行目" in message
    assert requests[0].get("timeout"), "確認に期限が付いていない"


def test_refusal_blocks_the_commit(env):
    _rpc(env, bash_call(COMMIT), [False])
    assert commits(env) == []


def test_approval_runs_the_commit(env):
    requests = _rpc(env, bash_call(COMMIT), [True])
    assert len(requests) == 1
    assert commits(env) == ["feat:", "件名です"]


@pytest.mark.parametrize(
    "command", ["git status --short", "echo git commit is only text", "git log --oneline -1"]
)
def test_other_commands_pass_without_confirmation(env, command):
    assert _rpc(env, bash_call(command), [False]) == []


@pytest.mark.parametrize(
    "command",
    ["git -C . commit -m x", "cd . && git commit -m x", "git -c core.x=1 commit -m x"],
)
def test_commit_variants_are_confirmed(env, command):
    assert len(_rpc(env, bash_call(command), [False])) == 1


def test_without_a_screen_the_commit_is_blocked(env):
    done = subprocess.run(
        [*_args(mode="text"), "-p", "go"],
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(bash_call(COMMIT))},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert commits(env) == [], done.stdout + done.stderr


def test_the_harness_replaces_it_instead_of_doubling(env):
    """pis (-ne -e harness) では settings.json の extensions が外れ、確認は 1 回だけ。"""
    tmp = env["tmp"]
    harness = tmp / ".config" / "pi" / "harness"
    harness.mkdir(parents=True)
    shutil.copy2(HARNESS_SRC, harness / "index.ts")
    # ハーネス側の確認が 1 回だけ出ること。ハーネスの規則は本物の生成物を使う
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "agents"))
    import generate as gen
    from agents_common import agents_config_dir, load_common

    rules = gen.build_pi_harness({}, load_common())
    rules["decide"] = str(ROOT / "home" / "dot_claude" / "hooks" / "executable_decide.py")
    for agent in rules["agents"].values():
        agent["model"] = None
    (harness / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    env["env"]["AGENTS_CONFIG_DIR"] = str(agents_config_dir())
    calls = [{"name": "guarded_bash", "args": {"command": COMMIT}}]
    requests = _rpc(env, calls, [False], extra=("-nbt", "-ne", "-e", str(harness)))
    assert len(requests) == 1, requests
