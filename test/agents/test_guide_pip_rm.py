"""OpenCode の guide: pip の uv 誘導と、危険な rm / find の「うっかり防止」。

生成した rules.json を実際の guide plugin (node) に通して判定する。
止めるべき例と、止めてはいけない例 (誤検知) を両方並べる。
これは事故防止であって完全な保護ではない (see docs/spec/agent-command-policy.md)。

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
from agents_common import load_common  # noqa: E402

COMMON = load_common()
PLUGIN = ROOT / "home/dot_config/opencode/guide-plugin"

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
    rules = gen.build_opencode_guide({}, COMMON)
    (tmp_path / "rules.json").write_text(json.dumps(rules), "utf-8")
    (tmp_path / "run.mjs").write_text(SCRIPT, "utf-8")
    done = subprocess.run(
        [node, str(tmp_path / "run.mjs"), json.dumps(cases)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={"PATH": ""},
    )
    return json.loads(done.stdout)


# 止めるべき例 (message に含まれるべき語)
BLOCKED = [
    ("pip install x", "uv add"),
    ("pip3 install x", "uv add"),
    ("python -m pip install x", "uv pip install"),
    ("python3 -mpip install x", "uvx"),
    ("python3.12 -m pip install x", "uv sync"),
    ("uv run python -m pip install x", "uv add"),
    ("ls && pip install x", "uv add"),
    ("rm -rf .git", ".git"),
    ("rm -rf .git/objects", ".git"),
    ("rm -rf ./.git", ".git"),
    ("rm -f sub/.git/HEAD", ".git"),
    ("rm -rf ~", "$HOME"),
    ("rm -rf ~/", "$HOME"),
    ("rm -rf $HOME", "$HOME"),
    ('rm -rf "$HOME"', "$HOME"),
    ("rm -rf /", "$HOME"),
    ("rm -rf /*", "$HOME"),
    ("rm -rf .", "作業ディレクトリ"),
    ("rm -rf ..", "作業ディレクトリ"),
    ("rm -rf *", "作業ディレクトリ"),
    ("rm -r -f ./", "作業ディレクトリ"),
    ("rm --recursive .", "作業ディレクトリ"),
    ("echo x; rm -rf .", "作業ディレクトリ"),
    ("find / -delete", "find"),
    ("find ~ -exec rm {} +", "find"),
    ("find $HOME -delete", "find"),
    ("find .git -delete", "find"),
    ("find / -name '*.log' -exec rm -f {} ;", "find"),
]

# 止めてはいけない例 (誤検知チェック)
ALLOWED = [
    "uv pip install x",
    "uv pip list",
    "uv add x",
    "uvx ruff check",
    "poetry add x",
    "pipenv install",
    "pipx --version",
    "python -m pytest",
    "python3 -m venv .venv",
    'echo "pip install"',
    "echo 'run python -m pip install x'",
    "grep -r 'pip install' docs",
    "rm -rf .tmp/foo",
    "rm -rf ./build",
    "rm -f a.txt",
    "rm -rf node_modules",
    "rm -rf dist build",
    "rm -rf .tmp/x/y",
    "rm -rf ~/.cache/foo",
    "rm -f ~/a.txt",
    "rm -rf /tmp/foo",
    "rm .gitignore",
    "rm -rf .github",
    "rm -rf foo.git",
    "rm -rf build/*",
    "rm -f *.pyc",
    "rm -rf ./*.o",
    "git rm file",
    "git rm -r --cached .",
    "git rm -rf .",
    "ls .git",
    "git log --oneline",
    "find . -name '*.pyc' -delete",
    "find .tmp -type f -delete",
    "find build -exec rm {} +",
    "find /tmp/foo -delete",
    "find ~/proj -name x -delete",
    "find / -name foo",
    "find ~ -name '*.md'",
    "grep -r 'rm -rf' .",
    'echo "rm -rf /"',
    "git commit -m 'docs: rm -rf . と pip install を止める'",
    'git commit -m "x; rm -rf ."',
]


@pytest.mark.parametrize("effect", ["allow", "ask"])
def test_dangerous_examples_are_denied(tmp_path, effect):
    out = _run(tmp_path, [(c, effect, "build") for c, _ in BLOCKED])
    for (cmd, word), got in zip(BLOCKED, out, strict=True):
        assert got["effect"] == "deny", cmd
        assert word in got["message"], f"{cmd!r}: {got['message']}"


def test_allowed_examples_are_left_alone(tmp_path):
    out = _run(tmp_path, [(c, "allow", "build") for c in ALLOWED])
    for cmd, got in zip(ALLOWED, out, strict=True):
        assert got["effect"] == "allow", f"{cmd!r} を止めてしまう: {got['message']}"
        assert got["message"] is None, cmd


def test_static_deny_is_never_overridden_by_the_plugin(tmp_path):
    """plugin は静的 deny を緩めない (effect は deny のまま、message も足さない)。

    evaluate には静的 deny の呼び出しが届かないので、通常版の pip の誘導文は
    execute.before で付ける (see test_guide_early_pip.py)。
    """
    out = _run(tmp_path, [("pip install x", "deny", "build"), ("ssh host", "deny", "build")])
    assert out == [{"effect": "deny", "message": None}] * 2


def test_bypass_agents_are_not_guided(tmp_path):
    names = gen.opencode_bypass_agents(COMMON)
    if not names:
        pytest.skip("bypass agent が定義されていない")
    out = _run(tmp_path, [("rm -rf .git", "allow", names[0])])
    assert out == [{"effect": "allow", "message": None}]


def test_static_pip_deny_is_still_generated():
    """説明を出すために静的 deny を外していないこと (プラグイン不調時の挙動を保つ)。"""
    config = gen.merge_opencode_config({}, COMMON)
    denied = [
        r["resource"]
        for r in config["permissions"]
        if r["action"] == "shell" and r["effect"] == "deny"
    ]
    assert any(r.startswith("pip ") or r == "pip" for r in denied), denied[:5]


def test_ocs_keeps_the_guide_rules():
    """ocs は permission を捨てるだけで、guide 規則は通常版と同じ rules.json を使う。"""
    rules = gen.build_opencode_guide({}, COMMON)["guide"]
    messages = "\n".join(r["message"] for r in rules)
    for word in ("pip は使わないでください", ".git", "$HOME", "find"):
        assert word in messages
    drop = COMMON["opencode"]["sandbox"]["permissions"]["drop_shell"]
    assert any("pip3?" in d for d in drop)  # permission 側の pip deny は ocs で消える
