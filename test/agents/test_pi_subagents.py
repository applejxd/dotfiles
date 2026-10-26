"""素の pi (Windows) 用の子エージェント宣言。see docs/spec/guard/pi-subagents.md#windows-の子エージェント"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest
from agents_common import ROOT, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen


def test_only_read_only_agents_are_declared():
    agents = gen.build_pi_subagents({}, load_common())["agents"]

    # shell・編集を持つ役割 (commit / worker) は判定器が無いので出さない
    assert set(agents) == {"explore", "review"}
    for agent in agents.values():
        assert set(agent) == {"description", "system", "model"}


def test_declarations_stay_in_step_with_the_full_guard_agents():
    # Windows の subagents とフルガードの task は別物 (see docs/spec/guard/pi-subagents.md#二つの-task-を別物にしている理由) だが、
    # 同じ [pi.agents] から出る宣言なので、名前・モデル・読み取り専用の役割の説明と指示は食い違わせない
    common = load_common()
    plain = gen.build_pi_subagents({}, common)["agents"]
    full = gen.build_pi_harness({}, common)["agents"]
    raw = common["pi"]["agents"]
    assert set(plain) <= set(full), set(plain) - set(full)
    for name, agent in plain.items():
        assert agent["model"] == full[name]["model"], name
        if raw[name].get("plain_description"):
            # 読み取り専用の版を宣言している役割 (explore): 説明と指示は意図して違う
            assert agent["description"] == raw[name]["plain_description"].strip(), name
            assert agent["system"] == raw[name]["plain_system"].strip(), name
        else:
            assert agent["description"] == full[name]["description"], name
            assert agent["system"] == full[name]["system"], name


def test_pi_tier_override_beats_the_opencode_tier():
    common = load_common()
    provider = common["opencode"]["model"]["provider"]
    override = (common["pi"].get("model", {}).get("tier", {}).get(provider) or {}).get(
        "second_opinion"
    )
    if override:
        assert gen.pi_model_ref(common, "second_opinion").endswith(override)


_RUNNER = """
const { childArgs } = await import(process.argv[2]);
const cases = JSON.parse(process.argv[3]);
console.log(JSON.stringify(cases.map((c) => childArgs(c))));
"""


def _child_args(tmp_path, cases):
    """subagents/index.ts の childArgs を node で実行する (typebox だけ差し替える)。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無い")
    ext = tmp_path / "ext"
    stub = ext / "node_modules" / "typebox"
    stub.mkdir(parents=True, exist_ok=True)
    (stub / "package.json").write_text('{"name":"typebox","type":"module","main":"index.js"}')
    (stub / "index.js").write_text(
        "const f=()=>({});export const Type={Object:f,String:f,Union:f,Literal:f};"
    )
    shutil.copy(
        ROOT / "home" / "dot_pi" / "agent" / "extensions" / "subagents" / "index.ts",
        ext / "index.ts",
    )
    runner = ext / "runner.mjs"
    runner.write_text(_RUNNER)
    out = subprocess.run(
        [node, str(runner), (ext / "index.ts").as_uri(), json.dumps(cases)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    return json.loads(out.stdout)


def _case(**kw):
    return {"bun": False, "model": "p/m", "system": "S", "task": "T", "guard": "G/index.ts", **kw}


def test_child_args_pass_the_cli_script_for_the_node_build(tmp_path):
    [args] = _child_args(tmp_path, [_case(argv1="C:/x/cli.js")])
    assert args[0] == "C:/x/cli.js"
    assert args[-1] == "T" and args[-3:-1] == ["--append-system-prompt", "S"]


def test_child_args_drop_the_virtual_path_of_the_bun_binary(tmp_path):
    cases = [_case(argv1="B:/~BUN/root/pi.exe", bun=True), _case(argv1="/$bunfs/root/pi", bun=True)]
    for args in _child_args(tmp_path, cases):
        assert args[0] == "--mode"
        assert not any("BUN" in a or "bunfs" in a for a in args)
        assert args[-1] == "T"


def test_child_args_load_the_full_guard_without_a_tools_list(tmp_path):
    [args] = _child_args(tmp_path, [_case(argv1="C:/x/cli.js")])
    assert "--tools" not in args
    for flag in ("--no-approve", "-nbt", "-ne"):
        assert flag in args
    assert args[args.index("builtin:mcp") - 1] == "-e"
    assert args[args.index("G/index.ts") - 1] == "-e"


_EXT_RUNNER = """
const m = await import(process.argv[2]);
const home = process.argv[3];
const out = { guard: m.findGuard(home), env: m.childEnv({ PI_HARNESS_BYPASS: "1", KEEP: "x" }, process.argv[4] || undefined) };
const tools = [];
m.default({ registerTool: (t) => tools.push(t) });
const run = (t) => t.execute("id", { agent: "review", task: "T" }, undefined, undefined, { cwd: ".", model: { provider: "p", id: "m" } });
globalThis.__PI_FULL_GUARD__ = undefined;
out.noMark = await run(tools[0]);
globalThis.__PI_FULL_GUARD__ = true;
try { await run(tools[0]); out.noGuard = "started"; } catch (e) { out.noGuard = String(e.message); }
console.log(JSON.stringify(out));
"""


def _run_ext(tmp_path, home, profile=""):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無い")
    _child_args(tmp_path, [])  # 拡張と typebox の差し替えを用意する
    ext = tmp_path / "ext"
    (ext / "agents.json").write_text(
        json.dumps({"agents": {"review": {"description": "d", "system": "s", "model": "p/m"}}})
    )
    runner = ext / "ext_runner.mjs"
    runner.write_text(_EXT_RUNNER)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    out = subprocess.run(
        [node, str(runner), (ext / "index.ts").as_uri(), str(home), profile],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
        env=env,
    )
    return json.loads(out.stdout)


def test_guard_is_found_only_when_index_and_rules_are_both_readable(tmp_path):
    home = tmp_path / "home"
    harness = home / ".config" / "pi" / "harness"
    harness.mkdir(parents=True)
    (harness / "index.ts").write_text("")
    assert _run_ext(tmp_path, home)["guard"] is None
    (harness / "rules.json").write_text("{}")
    assert _run_ext(tmp_path, home)["guard"].endswith("index.ts")


def test_child_env_sets_role_and_drops_the_bypass(tmp_path):
    env = _run_ext(tmp_path, tmp_path / "h")["env"]
    assert env["PI_HARNESS_CHILD"] == "1" and env["PI_HARNESS_ROLE"] == "reader"
    assert "PI_HARNESS_BYPASS" not in env and env["KEEP"] == "x"
    assert _run_ext(tmp_path, tmp_path / "h", "commit")["env"]["PI_HARNESS_ROLE"] == "commit"


def test_task_refuses_without_the_parent_mark_or_the_guard_dir(tmp_path):
    out = _run_ext(tmp_path, tmp_path / "empty")
    assert out["noMark"]["isError"] is True
    assert "task" in out["noMark"]["content"][0]["text"]
    assert "起動しない" in out["noGuard"]


def test_child_args_guard_a_task_that_starts_with_a_dash(tmp_path):
    [args] = _child_args(tmp_path, [_case(argv1="C:/x/cli.js", task="--help me")])
    assert args[-1] == "Task: --help me"
