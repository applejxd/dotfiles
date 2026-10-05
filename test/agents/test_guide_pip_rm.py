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
from agents_common import load_common, node_env  # noqa: E402

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


def _run(
    tmp_path: Path, cases: list[tuple[str, str, str]], rules_text: str | bool | None = True
) -> list[dict]:
    """``rules_text``: True なら生成した rules.json、None なら置かない、文字列ならそのまま書く。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")
    shutil.copy(PLUGIN / "index.js", tmp_path / "index.js")
    if rules_text is True:
        rules_text = json.dumps(gen.build_opencode_guide({}, COMMON))
    if rules_text is not None:
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
    # git / gh のメッセージ指定を前に付けても、連結・置換の側は止める
    ("git commit -m x && rm -rf ~", "$HOME"),
    ("git commit -m x; rm -rf .", "作業ディレクトリ"),
    ("git commit -m x\nrm -rf ~", "$HOME"),
    ("git commit -m 'a' && find / -delete", "find"),
    ("git commit -m x && pip install x", "uv add"),
    ("git commit -m \"$(cat <<'EOF'\nx\nEOF\n)\" && rm -rf ~", "$HOME"),
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
    "git commit -m \"$(cat <<'EOF'\nfix: x\n\nrm -rf ~ を止める\nEOF\n)\"",
    'gh pr create --title x --body "a; find / -delete を止める"',
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


def test_bypass_agents_are_guided_like_the_others(tmp_path):
    """bypass でも誘導は効き、deny のまま (誘導で止めたものは ask→allow に上げない)。"""
    names = gen.opencode_bypass_agents(COMMON)
    assert names, "前提: bypass agent が定義されている"
    for name in names:
        out = _run(tmp_path, [("rm -rf .git", "ask", name), ("rm -rf .git", "allow", name)])
        assert [o["effect"] for o in out] == ["deny", "deny"], name
        assert all(".git" in o["message"] for o in out), name


def test_bypass_agents_get_ask_upgraded_to_allow(tmp_path):
    """誘導に当たらない ask は allow になる。bypass 以外は ask のまま。説明も付けない。"""
    out = _run(
        tmp_path,
        [
            ("touch x", "ask", "bypass"),
            ("touch x", "ask", "bypass-worker"),
            ("touch x", "ask", "bypass-fleet-worker"),
            ("touch x", "ask", "build"),
            ("touch x", "ask", "commit"),
            ("touch x", "deny", "bypass"),
            ("ls", "allow", "bypass"),
        ],
    )
    assert [o["effect"] for o in out] == [
        "allow",
        "allow",
        "allow",
        "ask",
        "ask",
        "deny",
        "allow",
    ]
    assert all(o["message"] is None for o in out)


@pytest.mark.parametrize("broken", ["{ broken", "[]", None, '{"bypass_agents": "bypass"}'])
def test_ask_stays_ask_when_bypass_agents_are_unusable(tmp_path, broken):
    """rules.json が読めない・bypass_agents が壊れているときは ask のまま (安全側)。"""
    out = _run(tmp_path, [("touch x", "ask", "bypass")], rules_text=broken)
    assert out == [{"effect": "ask", "message": None}]


def test_bypass_agents_missing_from_rules_keep_ask(tmp_path):
    rules = gen.build_opencode_guide({}, COMMON)
    del rules["bypass_agents"]
    out = _run(tmp_path, [("touch x", "ask", "bypass")], rules_text=json.dumps(rules))
    assert out == [{"effect": "ask", "message": None}]


def test_broken_guarded_subagents_do_not_stop_the_ask_upgrade(tmp_path):
    """子の一覧 (起動元の検査) が壊れても、bypass_agents が正常なら ask→allow は続ける。"""
    rules = gen.build_opencode_guide({}, COMMON)
    rules["guarded_subagents"] = "bypass-worker"
    out = _run(tmp_path, [("touch x", "ask", "bypass")], rules_text=json.dumps(rules))
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
