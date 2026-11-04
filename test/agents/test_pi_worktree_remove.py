"""pi の implementer / worker だけ、``git worktree remove`` の force なしを許可する (``deny_except``)。

- force なしは deny でも mustConfirm でもない (通常・bypass・boundary の全モード)。
- force 付き (``-f``・``-ff``・``--force``・省略形・束ね・前置・複合) は mustConfirm の ask (bypass でも)。
- force の有無を確定できない形は deny のまま。既定が deny の役割・``local_git`` を切った場合・未知の語は deny。
- pi 以外 (Claude・OpenCode) の生成物は変わらない。

see docs/spec/guard/pi-decide.md#git-worktree-remove-の例外
"""

from __future__ import annotations

import copy
import sys

import pytest
from agents_common import ROOT, load_common
from test_pi_confirm import _bash, _judge, _modes, needs_node

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

pytestmark = needs_node

ALLOWED_ROLES = ["implementer", "worker"]
DENIED_ROLES = ["explorer", "reader", "committer", "orchestrator"]

PLAIN = [
    "git worktree remove ../wt",
    "git worktree remove /abs/path/wt",
    "git worktree remove .",
    "git -C /repo worktree remove ../wt",
    "git --git-dir /repo/.git worktree remove ../wt",
    "git worktree remove -- -f",
    "git worktree remove ../wt -- -f",
    "cd /repo && git worktree remove ../wt",
    "git worktree list",
    "git worktree prune",
]

FORCE = [
    "git worktree remove -f ../wt",
    "git worktree remove -ff ../wt",
    "git worktree remove --force ../wt",
    "git worktree remove --for ../wt",
    "git worktree remove --forc ../wt",
    "git worktree remove ../wt -f",
    "git worktree remove ../wt --force",
    "git worktree remove -f -f ../wt",
    "git -C /repo worktree remove -f ../wt",
    "git --git-dir /repo/.git worktree remove -f ../wt",
    "git --git-dir=/repo/.git worktree remove -ff ../wt",
    "env git worktree remove -f ../wt",
    "FOO=1 git worktree remove -f ../wt",
    "command git worktree remove -f ../wt",
    "bash -c 'git worktree remove -f ../wt'",
    "echo a; git worktree remove -f ../wt",
    "true && git worktree remove -f ../wt",
    "echo $(git worktree remove -f ../wt)",
    "echo ../wt | xargs git worktree remove -f",
    "git worktree remove ../wt && git worktree remove -f ../w2",
]

# force の有無を確定できない形は deny のまま
UNDECIDABLE = [
    "git worktree remove $F ../wt",
    "git worktree remove ../wt $F",
    "git worktree remove $(echo -f) ../wt",
    "git worktree remove `echo -f` ../wt",
    "git worktree remove ../w* ",
    "git worktree remove -?",
    "git worktree remove -[f] ../wt",
    "git worktree remove {-f,x}",
    "git worktree remove ~/wt",
    "git worktree remove !x",
    "git worktree remove 'unterminated",
    "git worktree remove ../wt; git worktree remove $X",
]


def _results(commands, **kw):
    requests = [r for c in commands for r in _modes(c, **kw)]
    results = _judge(requests)
    return list(zip((r["input"]["command"] for r in requests), results, strict=True))


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize("command", PLAIN)
def test_plain_form_is_not_denied_nor_forced_to_confirm(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] != "deny", (role, command, res)
        assert not res.get("mustConfirm"), (role, command, res)


@pytest.mark.parametrize("role", ALLOWED_ROLES)
def test_plain_form_decisions_are_the_default_ones(role):
    res = _judge(_modes("git worktree remove ../wt", role=role))
    # 通常は ask、bypass は allow、boundary は allow (source は default)
    assert res[0]["decision"] == "ask" and res[0]["source"] == "default", res[0]
    assert res[1]["decision"] == "allow", res[1]
    assert res[2]["decision"] == "allow", res[2]


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize("command", FORCE)
def test_force_form_must_be_confirmed_even_with_bypass_and_boundary(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "ask", (role, command, res)
        assert res.get("mustConfirm") is True, (role, command, res)


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize("command", UNDECIDABLE)
def test_undecidable_form_stays_denied(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


@pytest.mark.parametrize("role", DENIED_ROLES)
@pytest.mark.parametrize("command", PLAIN[:6] + FORCE[:8])
def test_roles_without_the_exception_deny_every_form(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


def test_switching_local_git_off_disables_the_exception():
    common = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    common["pi"]["confirm"]["local_git"] = False
    for role in ALLOWED_ROLES:
        for req in _modes("git worktree remove ../wt", role=role):
            assert _judge([req], common=common)[0]["decision"] == "deny", (role, req)


def test_unknown_word_in_deny_except_is_an_error_deny():
    common = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    common["pi"]["profiles"]["worker"]["deny_except"] = ["git worktree remove", "git push"]
    res = _judge([_bash("git status", role="worker")], common=common)[0]
    assert res["decision"] == "deny" and res["source"] == "error", res
    assert "deny_except" in res["reason"], res


def test_deny_except_must_be_a_list_of_strings():
    common = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    common["pi"]["profiles"]["worker"]["deny_except"] = "git worktree remove"
    res = _judge([_bash("git status", role="worker")], common=common)[0]
    assert res["decision"] == "deny" and res["source"] == "error", res


def test_a_role_without_deny_except_is_denied_even_if_others_have_it():
    common = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    assert "deny_except" not in common["pi"]["profiles"]["explorer"]
    common["pi"]["profiles"]["worker"].pop("deny_except")
    res = _judge([_bash("git worktree remove ../wt", role="worker")], common=common)[0]
    assert res["decision"] == "deny", res


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize(
    "command",
    [
        "git worktree remove ../wt && git push origin main",
        "git push origin main; git worktree remove ../wt",
        "git worktree remove ../wt && git stash drop",
        "git worktree remove ../wt && git filter-branch",
    ],
)
def test_other_denies_are_unaffected(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


def test_the_exception_is_only_for_implementer_and_worker():
    profiles = load_common()["pi"]["profiles"]
    with_exception = sorted(n for n, p in profiles.items() if "deny_except" in p)
    assert with_exception == ["implementer", "worker"]
    assert all(
        p["deny_except"] == ["git worktree remove"]
        for n, p in profiles.items()
        if n in with_exception
    )


def test_the_common_deny_still_has_it_and_other_clis_are_unchanged():
    common = load_common()
    assert "git worktree remove" in common["bash"]["deny"]
    assert "git worktree remove" in common["bash"]["deny_guide"]["user_only"]
    assert "Bash(git worktree remove:*)" in gen.build_claude_permissions(common)["deny"]
    # deny_except を外した設定と、pi 以外の生成物が同じ (pi だけの変更)
    without = copy.deepcopy(common)
    for p in without["pi"]["profiles"].values():
        p.pop("deny_except", None)
    assert gen.build_claude_permissions(common) == gen.build_claude_permissions(without)
    assert gen.build_opencode_permissions(common) == gen.build_opencode_permissions(without)
    assert gen.opencode_deny_guide_rules(common) == gen.opencode_deny_guide_rules(without)
    opencode = gen.build_opencode_permissions(common)
    assert any(
        r.get("resource", "").startswith("git worktree remove") and r.get("effect") == "deny"
        for r in opencode
    ), "OpenCode の deny に git worktree remove が残っていない"
