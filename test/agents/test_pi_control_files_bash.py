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
