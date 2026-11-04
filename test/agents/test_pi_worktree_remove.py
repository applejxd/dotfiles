"""pi の implementer / worker だけ、``git worktree remove`` の単純な 1 行を許可する (``deny_except``)。

- 例外が効くのは、元のコマンド全体が ``git worktree remove`` + 単純なパスだけの 1 行に一致するときだけ。
- force 付き・前置き・複合・引用・変数・リダイレクト・行継続・前後の空白は deny のまま (確認つきで通す案は採らない)。
- 既定が deny の役割・``local_git`` を切った場合・未知の語は deny。pi 以外 (Claude・OpenCode) の生成物は変わらない。

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

# 許可される形 (deny でも mustConfirm でもない)
PLAIN = [
    "git worktree remove .tmp/worktrees/a",
    "git worktree remove ../a",
    "git worktree remove /abs/path/wt",
    "git worktree remove .",
    "git worktree remove a b c",
    "git worktree remove ../wt-1_2.3",
    "git worktree remove 123",
    "git worktree remove a@b%c+d=e:f,g",
]

# deny のままになる形 (両役割・全モード)
DENIED = [
    "git worktree remove -f x",
    "git worktree remove --force x",
    "git worktree remove x -f",
    "git worktree remove -ff x",
    "git worktree remove --for x",
    "git worktree remove --forc x",
    "git worktree remove -- x",
    "git worktree remove -- -f",
    "git -C . worktree remove x",
    "git -C . worktree remove './a -- b' -f",
    "env git worktree remove './a -- b' -f",
    "xargs -a .tmp/flags git worktree remove ../wt",
    "xargs git worktree remove",
    "echo ../wt | xargs git worktree remove -f",
    "git worktree remove --force>/dev/null ../wt",
    "git worktree remove > -- -f ../wt",
    "git worktree remove './a -- b' -f",
    "git worktree remove \\\n--force x",
    "git worktree remove a \\\nb",
    " git worktree remove a",
    "git worktree remove a ",
    "git worktree remove a\n",
    "\tgit worktree remove a",
    "git worktree remove\ta",
    "git worktree remove  a",
    "git  worktree remove a",
    "cd x && git worktree remove a",
    "git worktree remove a; git push",
    "git worktree remove a && git push",
    "git worktree remove a && git push origin main",
    "git push origin main; git worktree remove a",
    "git worktree remove a && git stash drop",
    "git worktree remove a | cat",
    "git worktree remove a &",
    "git worktree remove a\ngit push",
    "git worktree remove $X",
    "git worktree remove $(echo -f) a",
    "git worktree remove `echo -f` a",
    'git worktree remove "a"',
    "git worktree remove 'a'",
    "git worktree remove .tmp/worktrees/a\\ b",
    "bash -c 'git worktree remove a'",
    "sudo git worktree remove a",
    "command git worktree remove a",
    "FOO=1 git worktree remove a",
    "git worktree remove a b -f",
    "git worktree remove ~/x",
    "git worktree remove a*",
    "git worktree remove a?",
    "git worktree remove a[1]",
    "git worktree remove {a,b}",
    "git worktree remove !x",
    "git worktree remove a 2>&1",
    "git worktree remove a#b",
    "git worktree remove",
]


def _results(commands, **kw):
    requests = [r for c in commands for r in _modes(c, **kw)]
    results = _judge(requests)
    return list(zip((r["input"]["command"] for r in requests), results, strict=True))


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize("command", PLAIN)
def test_plain_form_is_neither_denied_nor_forced_to_confirm(role, command):
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
@pytest.mark.parametrize("command", DENIED)
def test_everything_else_stays_denied(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize(
    "command",
    [
        "ssh sbx@sandbox-gpu 'git worktree remove ../wt'",
        "ssh sbx@sandbox-gpu git worktree remove ../wt",
        "ssh -p 22 sbx@sandbox-gpu 'git worktree remove ../wt'",
    ],
)
def test_ssh_remote_does_not_get_the_exception(role, command):
    # ssh のリモート側は再帰で判定されるが、変換後の文字列には例外を効かせない (元の入力だけ)
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


@pytest.mark.parametrize("role", DENIED_ROLES)
@pytest.mark.parametrize("command", PLAIN[:4])
def test_roles_without_the_exception_deny_plain_too(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize(
    "command",
    [
        "git worktree prune",
        "git worktree move a b",
        "git worktree repair",
        "git worktree remove-foo a",
        "git push origin main",
    ],
)
def test_other_worktree_subcommands_are_unchanged(role, command):
    # prune / move / repair は従来どおり (deny パターンの対象外なら deny ではない。対象なら deny のまま)。例外を足す前と同じ結果であること
    base = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    base["pi"]["profiles"][role].pop("deny_except")
    want = _judge([_bash(command, role=role)], common=base)[0]
    got = _judge([_bash(command, role=role)])[0]
    assert got["decision"] == want["decision"], (command, got, want)


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


def test_the_exception_is_only_for_implementer_and_worker():
    profiles = load_common()["pi"]["profiles"]
    with_exception = sorted(n for n, p in profiles.items() if "deny_except" in p)
    assert with_exception == ["implementer", "worker"]
    assert all(
        p["deny_except"]
        == (
            ["git worktree remove", "git restore --staged"]
            if n == "implementer"
            else ["git worktree remove"]
        )
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
