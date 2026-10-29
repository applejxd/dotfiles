"""親を「計画・判断・委譲」に絞る役割 (orchestrator)。/orchestrate の切り替えと、設定の検証。

- 生成器: [pi.orchestrate] と [pi.profiles.orchestrator] を検証し、rules.json へ出す。
- 判定器: orchestrator は作業のツール (bash・edit・write) を使えない。読み取り・委譲・質問・ToDo は通る。
- ハーネス: ON の間は、作業のツールがモデルに見えず、呼べない (bypass でも)。OFF で戻る。子には効かない。

see docs/spec/guard/pi-subagents.md#親の絞り込みorchestrate
"""

from __future__ import annotations

import copy
import json
import sys

import pytest
import test_pi_harness as H
from agents_common import ROOT, load_common
from test_pi_confirm import _judge, needs_node

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

env = H.env


def _common():
    return copy.deepcopy(load_common())


# ─── 生成器 ───────────────────────────────────────────────────────────


def test_the_current_settings_are_valid_and_off_by_default():
    out = gen.pi_orchestrate(load_common())
    assert out == {"enabled": True, "default": "off", "role": "orchestrator"}


def test_without_the_section_the_feature_is_off():
    common = _common()
    del common["pi"]["orchestrate"]
    assert gen.pi_orchestrate(common) == {"enabled": False, "default": "off", "role": ""}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["pi"]["profiles"].pop("orchestrator"),
        lambda c: c["pi"]["profiles"]["orchestrator"].update(default="allow"),
        lambda c: c["pi"]["profiles"]["orchestrator"]["tools"].remove("task"),
        lambda c: c["pi"]["profiles"]["orchestrator"]["tools"].append("bash"),
        lambda c: c["pi"]["profiles"]["orchestrator"]["tools"].append("edit"),
        lambda c: c["pi"]["profiles"]["orchestrator"]["tools"].append("write"),
        lambda c: c["pi"]["profiles"]["orchestrator"]["tools"].append("bg_run"),
        lambda c: c["pi"]["profiles"]["orchestrator"]["tools"].append("mcp__*"),
        lambda c: c["pi"]["profiles"]["orchestrator"]["tools"].append(
            "not_a_tool_of_the_base_role"
        ),
        lambda c: c["pi"]["orchestrate"].update(default="maybe"),
        lambda c: c["pi"]["orchestrate"].update(extra=1),
        lambda c: c["pi"].update(orchestrate="on"),
    ],
)
def test_an_unsafe_or_malformed_setting_stops_the_generation(mutate):
    common = _common()
    mutate(common)
    with pytest.raises((SystemExit, ValueError)):
        gen.pi_orchestrate(common)


def test_rules_json_carries_the_orchestrate_setting():
    rules = gen.build_pi_harness({}, load_common())
    assert rules["orchestrate"]["enabled"] is True
    assert rules["profile_tools"]["orchestrator"][:4] == ["read", "grep", "find", "ls"]


# ─── 判定器 ───────────────────────────────────────────────────────────


def _req(tool, input_, role="orchestrator", **extra):
    return {"tool": tool, "input": input_, "cwd": "/work/proj", "role": role, **extra}


@needs_node
def test_the_orchestrator_cannot_use_work_tools_even_with_bypass():
    requests = [
        _req("bash", {"command": "ls"}, **flags)
        for flags in ({}, {"bypass": True}, {"boundary": True})
    ] + [
        _req(tool, {"path": "a.txt", "content": "x", "oldText": "a", "newText": "b"}, **flags)
        for tool in ("edit", "write")
        for flags in ({}, {"bypass": True})
    ]
    for res in _judge(requests):
        assert res["decision"] == "deny", res
        assert "orchestrator" in res["reason"], res


@needs_node
def test_the_orchestrator_may_read_delegate_ask_and_keep_todos():
    results = _judge(
        [
            _req("read", {"path": "README.md"}),
            _req("grep", {"pattern": "x", "path": "."}),
            _req("task", {"agent": "worker", "task": "t"}),
            _req("todo", {"action": "list"}),
            _req("ask", {"questions": []}),
        ]
    )
    assert [r["decision"] for r in results] == ["allow"] * 5, results


# ─── ハーネス ─────────────────────────────────────────────────────────


def _tools(proc):
    return json.loads(H.lines(proc)[0].removeprefix("TOOLS="))


def test_when_it_starts_on_the_work_tools_are_not_declared_to_the_model(env):
    proc = H.run_pi(env, [], PI_HARNESS_ORCHESTRATE="1")
    assert proc.returncode == 0, proc.stderr
    tools = _tools(proc)
    for name in ("bash", "edit", "write"):
        assert f"guarded_{name}" not in tools, tools
    for name in ("read", "grep", "find", "ls", "task"):
        assert f"guarded_{name}" in tools, tools


def test_without_it_the_tools_are_unchanged(env):
    proc = H.run_pi(env, [])
    tools = _tools(proc)
    assert "guarded_bash" in tools and "guarded_edit" in tools and "guarded_write" in tools, tools


def test_a_work_tool_call_is_refused_while_on_even_with_bypass(env):
    env["env"]["PI_HARNESS_BYPASS"] = "1"
    H.run_pi(env, H.bash_call("touch made-by-pi"), PI_HARNESS_ORCHESTRATE="1")
    assert not (env["proj"] / "made-by-pi").exists()


def test_a_child_is_not_affected(env):
    proc = H.run_pi(env, [], PI_HARNESS_ORCHESTRATE="1", PI_HARNESS_CHILD="1")
    tools = _tools(proc)
    assert "guarded_bash" in tools and "guarded_task" not in tools, tools


def test_the_command_turns_it_on_and_off(env):
    env["env"]["PI_HARNESS_BYPASS"] = "1"
    calls = H.bash_call("touch made-by-pi")
    # ON: bypass でも作業のツールは使えない。ステータスが出る
    _requests, statuses = H._rpc_script(
        env, calls, ["/orchestrate on", "go"], [], status_key="orchestrate"
    )
    assert any(s and "orchestrate" in s for s in statuses), statuses
    assert not (env["proj"] / "made-by-pi").exists()


def test_off_brings_the_work_tools_back(env):
    env["env"]["PI_HARNESS_BYPASS"] = "1"
    calls = H.bash_call("touch made-by-pi")
    _requests, statuses = H._rpc_script(
        env, calls, ["/orchestrate on", "/orchestrate off", "go"], [], status_key="orchestrate"
    )
    assert statuses[-1] is None, statuses
    assert (env["proj"] / "made-by-pi").exists()


def test_the_default_can_start_it_on_and_the_environment_can_turn_it_off(env):
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    rules["orchestrate"]["default"] = "on"
    path.write_text(json.dumps(rules), encoding="utf-8")
    assert "guarded_bash" not in _tools(H.run_pi(env, []))
    assert "guarded_bash" in _tools(H.run_pi(env, [], PI_HARNESS_ORCHESTRATE="0"))


def _rules_edit(env, fn):
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    fn(rules)
    path.write_text(json.dumps(rules), encoding="utf-8")


@pytest.mark.parametrize(
    "broken",
    [
        lambda r: r.pop("orchestrate"),
        lambda r: r["orchestrate"].update(enabled=False),
        lambda r: r["orchestrate"].update(role="implementer"),
        lambda r: r["orchestrate"].update(default="maybe"),
        lambda r: r["profile_tools"].update(orchestrator=["read", "bash", "task"]),
        lambda r: r["profile_tools"].update(orchestrator=["read"]),
    ],
)
def test_an_explicit_on_request_never_falls_back_to_the_normal_role(env, broken):
    # 設定が欠ける・壊れているときに、ON を要求したのに黙って通常の権限で動くことがない (fail-closed)
    env["env"]["PI_HARNESS_BYPASS"] = "1"
    _rules_edit(env, broken)
    proc = H.run_pi(env, H.bash_call("touch made-by-pi"), PI_HARNESS_ORCHESTRATE="1")
    assert not (env["proj"] / "made-by-pi").exists(), proc.stdout
    assert proc.returncode != 0 or "orchestrate" in (proc.stderr + proc.stdout), (proc.returncode, proc.stderr)


def test_a_child_ignores_a_broken_request(env):
    _rules_edit(env, lambda r: r.pop("orchestrate"))
    proc = H.run_pi(env, [], PI_HARNESS_ORCHESTRATE="1", PI_HARNESS_CHILD="1")
    assert proc.returncode == 0, proc.stderr
    assert "guarded_bash" in _tools(proc)


def test_the_users_choice_survives_a_reload(env):
    env["env"]["PI_HARNESS_BYPASS"] = "1"
    calls = H.bash_call("touch made-by-pi")
    H._rpc_script(env, calls, ["/orchestrate on", "/reload", "go"], [], status_key="orchestrate")
    assert not (env["proj"] / "made-by-pi").exists()
