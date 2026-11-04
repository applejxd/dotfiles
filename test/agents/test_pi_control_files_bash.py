"""素の pi (Fence が無い) の制御ファイルを、bash から書き換えさせない (``judge/rules_guard.ts`` の GUARD_TARGETS)。

``guarded_write`` / ``guarded_edit`` の拒否 (``[file] write_deny_globs``) とは別に、bash の経由 (リダイレクト・
mv / cp / rm / tee / インラインコード) でも、settings.json・mcp.json・extensions・フルガードを書かせない。
see docs/spec/guard/pi-guard.md#判定の外で動くもの
"""

from __future__ import annotations

import pytest
from test_pi_confirm import _bash, _judge, needs_node

pytestmark = needs_node

TARGETS = [
    "~/.pi/agent/settings.json",
    "~/.pi/agent/mcp.json",
    "~/.pi/agent/extensions/x/index.ts",
    "~/.config/pi/harness/rules.json",
    "$HOME/.pi/agent/settings.json",
]


def _decisions(commands):
    results = _judge([_bash(c) for c in commands])
    return [r["decision"] for r in results]


@pytest.mark.parametrize("target", TARGETS)
def test_redirect_and_mutating_commands_to_the_control_files_are_denied(target):
    commands = [
        f"echo x > {target}",
        f"echo x >> {target}",
        f"tee {target} < /dev/null",
        f"rm {target}",
        f"mv /tmp/a {target}",
        f"cp /tmp/a {target}",
    ]
    assert _decisions(commands) == ["deny"] * len(commands)


@pytest.mark.parametrize("target", TARGETS[:3])
def test_inline_code_touching_the_control_files_is_denied(target):
    command = f"python3 -c \"open('{target}', 'w').write('x')\""
    assert _decisions([command]) == ["deny"]


# 作業台帳の置き場 (ハーネスだけが fs で書く)。書き込みは拒否し、読み取りと通常のファイルは従来どおり
LEDGER = [".git/pi-work/log/x.jsonl", ".tmp/work/journal/x.jsonl", ".git/pi-work/DEGRADED.json"]
ROLES = ["implementer", "worker", "explore"]


def _file(tool, path, role):
    return {
        "tool": tool,
        "input": {"path": path, "content": "x"},
        "cwd": "/work/proj",
        "role": role,
    }


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("path", LEDGER)
def test_ledger_is_denied_for_file_write_tools(role, path):
    for p in (path, f"/work/proj/{path}"):
        reqs = [_file(t, p, role) for t in ("write", "edit")]
        assert [r["decision"] for r in _judge(reqs)] == ["deny", "deny"]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("path", LEDGER)
def test_ledger_is_denied_for_bash_writes(role, path):
    commands = [
        f"echo x > {path}",
        f"echo x >> {path}",
        f"tee {path} < /dev/null",
        f"cp /tmp/a {path}",
        f"rm {path}",
    ]
    results = _judge([{**_bash(c), "role": role} for c in commands])
    assert [r["decision"] for r in results] == ["deny"] * len(commands)


@pytest.mark.parametrize("path", LEDGER)
def test_ledger_inline_code_is_denied(path):
    assert _decisions([f"python3 -c \"open('{path}', 'w').write('x')\""]) == ["deny"]


def test_ledger_reads_and_ordinary_writes_are_unchanged():
    reads = [_file(t, p, "implementer") for t in ("read", "grep") for p in LEDGER]
    assert all(r["decision"] != "deny" for r in _judge(reads))
    ordinary = [
        _file("write", p, "implementer")
        for p in ("docs/x.md", ".tmp/worktrees/x/f.txt", ".tmp/keep/work/a.md")
    ]
    assert all(r["decision"] != "deny" for r in _judge(ordinary))
    cmds = [
        "grep x .git/pi-work/log/x.jsonl",
        "echo x > .tmp/worktrees/a/f.txt",
        "echo x > docs/x.md",
    ]
    assert "deny" not in _decisions(cmds)
