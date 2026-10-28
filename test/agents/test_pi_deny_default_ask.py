"""既定が deny の役割 (explorer・reader・committer) は、[bash] ask を bypass でも通さない。

``[bash] ask`` は役割の既定の deny より先に当たる。bypass は ask を allow にするので、以前は
``docker rm``・``git clean``・``git branch -D`` などが、読み取り専用の子でも bypass で通った (2026-10-29 に実測)。
いまは deny にする。ask が既定の役割 (implementer・worker) と、mustConfirm の ask は変えない。

see docs/spec/guard/pi-decide.md#既定が-deny-の役割の-ask
"""

from __future__ import annotations

import pytest
from test_pi_confirm import _bash, _judge, _modes, needs_node

pytestmark = needs_node

DENY_DEFAULT_ROLES = ["explorer", "committer", "reader"]

# [bash] ask の操作 (通常は ask、bypass なら allow だったもの)
ASKED = [
    "docker rm c",
    "docker rmi i",
    "git clean -fd",
    "git branch -D x",
    "git tag -d v1",
    "pipx install x",
    "gh pr checkout 1",
]

SUFFIX = "この役割は既定が deny なので、承認で通さない (bypass でも通さない)"


@pytest.mark.parametrize("role", DENY_DEFAULT_ROLES)
@pytest.mark.parametrize("command", ASKED)
def test_asked_commands_are_denied_for_deny_default_roles(role, command):
    for req, res in zip(
        _modes(command, role=role), _judge(_modes(command, role=role)), strict=True
    ):
        assert res["decision"] == "deny", (role, command, req, res)


@pytest.mark.parametrize("role", ["explorer", "committer"])
def test_the_ask_reason_is_kept_and_the_deny_is_explained(role):
    res = _judge([_bash("docker rm c", role=role, bypass=True)])[0]
    assert res["decision"] == "deny"
    assert "docker rm" in res["reason"] and res["reason"].endswith(SUFFIX), res


@pytest.mark.parametrize("role", ["implementer", "worker"])
def test_roles_that_ask_by_default_are_unchanged(role):
    normal = _judge([_bash("docker rm c", role=role)])[0]
    assert normal["decision"] == "ask", normal
    bypassed = _judge([_bash("docker rm c", role=role, bypass=True)])[0]
    assert bypassed["decision"] == "allow" and bypassed.get("bypassed") is True, bypassed


@pytest.mark.parametrize("role", ["explorer", "committer"])
def test_must_confirm_asks_are_not_turned_into_denies(role):
    # 確認が要る操作は ask のまま (子では UI が無いので、ハーネスが拒否する)
    for res in _judge(
        [
            _bash("gh pr create --title t --body b", role=role, **flags)
            for flags in ({}, {"bypass": True})
        ]
    ):
        assert res["decision"] == "ask" and res.get("mustConfirm") is True, res
