"""OpenCode の guide: pip の前段 (``tool.execute.before``) での説明付きの停止。

V2 は config の静的 deny に当たると plugin の ``permission.evaluate`` を呼ばず、説明を付けられない。
そこで ``early = true`` の規則は ``execute.before`` で例外を投げて止める。
生成した rules.json を実際の guide plugin (node) に通して判定する。

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

SCRIPT = """
import plugin from './index.js'
const hooks = {}
const ctx = { tool: { hook: (n, fn) => { hooks[n] = fn } }, permission: { hook() {} },
  shell: { hook() {} } }
await plugin.setup(ctx)
const cases = JSON.parse(process.argv[2])
const out = []
for (const [cmd, agent, tool] of cases) {
  const e = { tool, agent, id: "x", input: { command: cmd } }
  try {
    await hooks["execute.before"](e)
    out.push({ thrown: null })
  } catch (err) {
    out.push({ thrown: err.message })
  }
}
console.log(JSON.stringify(out))
"""


def _run(tmp_path: Path, cases: list[tuple[str, str, str]], rules_text: str | None = None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    shutil.copy(PLUGIN / "index.js", tmp_path / "index.js")
    if rules_text is None:
        rules_text = json.dumps(gen.build_opencode_guide({}, COMMON))
    (tmp_path / "rules.json").write_text(rules_text, "utf-8")
    (tmp_path / "run.mjs").write_text(SCRIPT, "utf-8")
    done = subprocess.run(
        [node, str(tmp_path / "run.mjs"), json.dumps(cases)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=node_env(),
    )
    return json.loads(done.stdout)


BLOCKED = [
    "pip install x",
    "pip3 install x",
    "python -m pip install x",
    "uv run python -m pip install x",
    "ls && pip install x",
    "pip --version",
]

# 前段では止めない (誤検知チェック)。ここに載せたものは pip 規則に当たらない。
PASSED = [
    "uv pip install x",
    "uv add x",
    "pipx --version",
    "poetry add x",
    'echo "pip install"',
    "grep -r 'pip install' docs",
    "git commit -m 'use pip'",
    "git commit -m 'docs: pip install を止める'",
]


def test_pip_is_stopped_early_with_the_uv_message(tmp_path):
    out = _run(tmp_path, [(c, "build", "shell") for c in BLOCKED])
    for cmd, got in zip(BLOCKED, out, strict=True):
        assert got["thrown"] and "uv add" in got["thrown"], cmd


def test_non_pip_commands_pass_the_early_stage(tmp_path):
    out = _run(tmp_path, [(c, "build", "shell") for c in PASSED])
    for cmd, got in zip(PASSED, out, strict=True):
        assert got["thrown"] is None, f"{cmd!r} を前段で止めてしまう: {got['thrown']}"


def test_only_early_rules_are_checked_early(tmp_path):
    """early の無い規則 (rm の誘導など) は前段では止めず、従来どおり evaluate に任せる。"""
    out = _run(tmp_path, [("rm -rf .git", "build", "shell"), ("cat > f <<EOF", "build", "shell")])
    assert out == [{"thrown": None}] * 2


def test_bypass_agents_are_stopped_like_the_others(tmp_path):
    """bypass でも前段で止める。止まるのは shell だけで、ほかのツールは通す。"""
    names = gen.opencode_bypass_agents(COMMON)
    assert names, "前提: bypass agent が定義されている"
    for name in names:
        out = _run(tmp_path, [("pip install x", name, "shell"), ("pip install x", name, "grep")])
        assert out[0]["thrown"] and "uv add" in out[0]["thrown"], name
        assert out[1] == {"thrown": None}, name


def test_unreadable_rules_do_nothing_so_static_deny_decides(tmp_path):
    """rules.json が壊れていても例外を投げない (後段の静的 deny が止める)。"""
    out = _run(tmp_path, [("pip install x", "build", "shell")], rules_text="{ broken")
    assert out == [{"thrown": None}]


def test_early_flag_is_generated_only_for_the_pip_rule():
    rules = gen.build_opencode_guide({}, COMMON)["guide"]
    early = [r for r in rules if r.get("early")]
    assert len(early) == 1
    assert "pip は使わないでください" in early[0]["message"]
