"""guide plugin の ``shell.create.before``: git を入力待ちにさせない環境変数。

未設定のときだけ入れ、設定済みの値は上書きしない。

see docs/spec/agent-config-generation.md#plugin-層-guide-plugin

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "home/dot_config/opencode/guide-plugin"

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


def _call(tmp_path: Path, env: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    shutil.copy(PLUGIN / "index.js", tmp_path / "index.js")
    (tmp_path / "run.mjs").write_text(SCRIPT, "utf-8")
    done = subprocess.run(
        [node, str(tmp_path / "run.mjs"), json.dumps(env)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={"PATH": ""},
    )
    return json.loads(done.stdout)


def test_unset_variables_are_added(tmp_path):
    out = _call(tmp_path, {"HOME": "/h"})
    assert out == {
        "HOME": "/h",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_EDITOR": "false",
        "GCM_INTERACTIVE": "never",
    }


def test_existing_values_are_kept(tmp_path):
    env = {"GIT_EDITOR": "vim", "GIT_TERMINAL_PROMPT": "1", "GCM_INTERACTIVE": "always"}
    assert _call(tmp_path, env) == env


def test_only_missing_ones_are_added(tmp_path):
    out = _call(tmp_path, {"GIT_EDITOR": "vim"})
    assert out["GIT_EDITOR"] == "vim"
    assert out["GIT_TERMINAL_PROMPT"] == "0"
    assert out["GCM_INTERACTIVE"] == "never"
