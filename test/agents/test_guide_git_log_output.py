"""OpenCode の guide: allow の ``git log *`` に当たる ``git log --output`` の書き込みを止める。

生成した rules.json を実際の guide plugin (node) に通して判定する。
止めるべき例と、止めてはいけない例 (誤検知) を両方並べる。
see docs/spec/agent-command-policy.md#opencode-の-allow-したコマンドの書き込み形

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
MESSAGE = "git log の --output"

SCRIPT = """
import plugin from './index.js'
const hooks = {}
const ctx = { tool: { hook() {} }, permission: { hook: (n, fn) => { hooks[n] = fn } },
  shell: { hook() {} } }
await plugin.setup(ctx)
const cases = JSON.parse(process.argv[2])
const out = []
for (const [cmd, effect, agent] of cases) {
  const e = { action: "shell", agent, effect, resources: [cmd], source: { id: "x" } }
  await hooks.evaluate(e)
  out.push({ effect: e.effect, message: e.message ?? null })
}
console.log(JSON.stringify(out))
"""


def _run(tmp_path: Path, cases: list[tuple[str, str, str]]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    shutil.copy(PLUGIN / "index.js", tmp_path / "index.js")
    (tmp_path / "rules.json").write_text(json.dumps(gen.build_opencode_guide({}, COMMON)), "utf-8")
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


# 止めるべき例
BLOCKED = [
    "git log -1 --output=f",
    "git log --output f",
    "git log -p --output=f",
    "git log -1 --output=/tmp/x.txt",
    "ls && git log -1 --output=f",
    "ls; git log --output=f",
    "false || git log -1 --output=f",
    "git log --format='a|b' --output=f",
    "git log '--output=f'",
    "git log \\\n  --output=f",
    "echo $(git log --output=f)",
]

# 止めてはいけない例 (誤検知チェック)
ALLOWED = [
    "git log -1 --oneline",
    "git log --stat",
    "git log --output-indicator-new=+ -p",
    "git log --grep='--output=x'",
    "git commit -m 'git log --output=x'",
    "echo --output",
    "git log -1; echo --output=f",
]


@pytest.mark.parametrize("effect", ["allow", "ask"])
def test_git_log_output_is_denied(tmp_path, effect):
    out = _run(tmp_path, [(c, effect, "build") for c in BLOCKED])
    for cmd, got in zip(BLOCKED, out, strict=True):
        assert got["effect"] == "deny", cmd
        assert MESSAGE in got["message"], f"{cmd!r}: {got['message']}"


def test_other_forms_are_left_alone(tmp_path):
    out = _run(tmp_path, [(c, "allow", "build") for c in ALLOWED])
    for cmd, got in zip(ALLOWED, out, strict=True):
        assert got["effect"] == "allow", f"{cmd!r} を止めてしまう: {got['message']}"
        assert got["message"] is None, cmd


def test_bypass_and_plan_are_guided_too(tmp_path):
    """bypass の ask→allow より先に止まり、plan の確認 (ask) でも同じ説明で止まる。"""
    agents = [*gen.opencode_bypass_agents(COMMON), "plan", "explore", "general"]
    out = _run(tmp_path, [("git log -1 --output=f", "ask", a) for a in agents])
    for agent, got in zip(agents, out, strict=True):
        assert got["effect"] == "deny", agent
        assert MESSAGE in got["message"], agent


def test_rule_has_no_unless():
    """unless はコマンド全体に当たるので、連結した後ろの書き込みまで見送ってしまう。"""
    guards = [g for g in gen.opencode_guide_rules(COMMON) if MESSAGE in g["message"]]
    assert len(guards) == 1
    assert "unless" not in guards[0]
    assert "early" not in guards[0], "静的 allow の穴なので evaluate で足りる"
