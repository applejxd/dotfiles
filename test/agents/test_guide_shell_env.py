"""guide plugin の ``shell.create.before``: git を入力待ちにさせない環境変数。

値は生成した rules.json の ``agent_env`` (正本は common.toml の ``[agent_env]``)。
未設定のときだけ入れ、設定済みの値は (空文字も) 上書きしない。

see docs/spec/agent-config-generation.md#shell-ツールの環境変数

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common, node_env  # noqa: E402

COMMON = load_common()
PLUGIN = ROOT / "home/dot_config/opencode/guide-plugin"

EXPECTED = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_EDITOR": "false",
    "GCM_INTERACTIVE": "never",
}

SCRIPT = """
import plugin from './index.js'
const hooks = {}
const ctx = { tool: { hook() {} }, permission: { hook() {} },
  shell: { hook: (name, fn) => { hooks[name] = fn } } }
await plugin.setup(ctx)
const env = JSON.parse(process.argv[2])
hooks['create.before']({ env })
console.log(JSON.stringify(env))
"""


def _call(tmp_path: Path, env: dict, rules_text: str | None = None) -> dict:
    """``rules_text``: None なら生成した rules.json、文字列ならそのまま書く。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    shutil.copy(PLUGIN / "index.js", tmp_path / "index.js")
    if rules_text is None:
        rules_text = json.dumps(gen.build_opencode_guide({}, COMMON))
    (tmp_path / "rules.json").write_text(rules_text, "utf-8")
    (tmp_path / "run.mjs").write_text(SCRIPT, "utf-8")
    done = subprocess.run(
        [node, str(tmp_path / "run.mjs"), json.dumps(env)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=node_env(),
    )
    return json.loads(done.stdout)


def _rules_with(**overrides) -> str:
    rules = gen.build_opencode_guide({}, COMMON)
    rules.update(overrides)
    return json.dumps(rules)


def test_generated_values_match_source():
    assert gen.build_opencode_guide({}, COMMON)["agent_env"] == EXPECTED


def test_unset_variables_are_added(tmp_path):
    assert _call(tmp_path, {"HOME": "/h"}) == {"HOME": "/h", **EXPECTED}


def test_existing_values_are_kept(tmp_path):
    env = {"GIT_EDITOR": "vim", "GIT_TERMINAL_PROMPT": "1", "GCM_INTERACTIVE": "always"}
    assert _call(tmp_path, env) == env


def test_empty_string_is_kept(tmp_path):
    env = {"GIT_EDITOR": "", "GIT_TERMINAL_PROMPT": "", "GCM_INTERACTIVE": ""}
    assert _call(tmp_path, env) == env


def test_only_missing_ones_are_added(tmp_path):
    out = _call(tmp_path, {"GIT_EDITOR": "vim"})
    assert out["GIT_EDITOR"] == "vim"
    assert out["GIT_TERMINAL_PROMPT"] == "0"
    assert out["GCM_INTERACTIVE"] == "never"


@pytest.mark.parametrize(
    "rules_text",
    [
        "{ broken",
        "[]",
        json.dumps({}),
        json.dumps({"agent_env": None}),
        json.dumps({"agent_env": ["GIT_EDITOR"]}),
        json.dumps({"agent_env": {"GIT_EDITOR": 1}}),
        json.dumps({"agent_env": {"GIT_EDITOR": "false", "X": None}}),
    ],
    ids=["JSON でない", "配列", "agent_env 無し", "null", "配列の値", "数値", "一部だけ不正"],
)
def test_nothing_is_added_when_unusable(tmp_path, rules_text):
    assert _call(tmp_path, {"HOME": "/h"}, rules_text) == {"HOME": "/h"}


def test_broken_agent_env_does_not_break_other_sections(tmp_path):
    out = _call(tmp_path, {"HOME": "/h"}, _rules_with(agent_env="bad"))
    assert out == {"HOME": "/h"}


# --- 生成器 ---------------------------------------------------------------


def test_missing_section_gives_empty_dict():
    assert gen.build_opencode_guide({}, {})["agent_env"] == {}


def test_empty_value_is_emitted():
    guide = gen.build_opencode_guide({}, {"agent_env": {"GIT_EDITOR": ""}})
    assert guide["agent_env"] == {"GIT_EDITOR": ""}


@pytest.mark.parametrize(
    "table",
    [
        {"git_editor": "x"},
        {"1A": "x"},
        {"A-B": "x"},
        {"A": 1},
        {"A": None},
        {"A": ["x"]},
        "text",
    ],
)
def test_invalid_agent_env_stops_generation(table):
    with pytest.raises(SystemExit):
        gen.build_opencode_guide({}, {"agent_env": table})


def test_other_cli_outputs_do_not_carry_agent_env():
    outs = [
        gen.merge_claude_settings({}, COMMON),
        gen.merge_copilot_perms({}, COMMON),
        gen.merge_copilot_settings({}, COMMON),
    ]
    for out in outs:
        text = json.dumps(out)
        assert "agent_env" not in text
        assert "GIT_TERMINAL_PROMPT" not in text
