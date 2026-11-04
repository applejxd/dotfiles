"""pi の implementer だけ、``git restore --staged <パス>...`` の厳密な 1 形式を許可する (``deny_except``)。

- worker は対象外 (``git add`` / ``git commit`` などを持たず、unstage の需要も無い)。許可形も全モードで deny。
- 許可するのは、index だけを戻す形 (作業ツリーを変えない)。元のコマンド全体が 1 形式に一致するときだけ。
- 作業ツリーを変えうる形・オプション付き・前置き・複合・引用・展開・グロブ・リダイレクトは、従来の deny のまま。
- 既定が deny の役割・``local_git`` を切った場合は deny。``git reset`` / ``git checkout --`` / ``git stash`` は変えない。

see docs/spec/guard/pi-decide.md#git-restore---staged-の例外
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

ALLOWED_ROLES = ["implementer"]
DENIED_ROLES = ["worker", "explorer", "reader", "committer", "orchestrator"]

PLAIN = [
    "git restore --staged a.txt",
    "git restore -S a.txt",
    "git restore -S -- a b",
    "git restore --staged -- a",
    "git restore --staged a b c",
    "git restore --staged .",
    "git restore --staged ./a",
    "git restore --staged /abs/a",
    "git restore --staged a/b.c_d-e@f%g+h=i:j,k",
    "git restore --staged :/",
    "git restore --staged @",
    "git restore --staged " + " ".join(f"f{i}" for i in range(50)),
]

# 従来どおり deny のままの形 (両役割・全モード)
DENIED = [
    "git restore a.txt",
    "git restore .",
    "git restore -- a",
    "git restore --staged",
    "git restore -S",
    "git restore --staged --worktree a",
    "git restore --staged --worktree",
    "git restore -S -W a",
    "git restore -SW a",
    "git restore -WS a",
    "git restore --stag a",
    "git restore --staged=x a",
    "git restore --no-staged a",
    "git restore --work a",
    "git restore --staged --work a",
    "git restore --worktree",
    "git restore --staged a\x00",
    "git restore --staged a\x00b",
    "git restore --staged a\r",
    "git restore --staged a\rb",
    "git restore --staged a\u00a0b",
    "git restore --staged a\u2003b",
    "git restore --staged\u3000a",
    "git restore \uff0d\uff0dstaged a",
    "git restore --staged a\u3000b",
    "git restore -W a",
    "git restore --worktree a",
    "git restore -s HEAD~1 --staged a",
    "git restore --source=HEAD --staged a",
    "git restore --staged a -s HEAD",
    "git restore --staged a -W",
    "git restore --staged a --worktree",
    "git restore --staged -p a",
    "git restore -p --staged a",
    "git restore --staged --patch a",
    "git restore --staged --overlay a",
    "git restore --staged --no-overlay a",
    "git restore --staged --ours a",
    "git restore --staged --theirs a",
    "git restore --staged --merge a",
    "git restore --staged --ignore-unmerged a",
    "git restore --staged --pathspec-from-file=f",
    "git restore --staged --pathspec-from-file f",
    "git restore --staged --pathspec-file-nul a",
    "git restore --staged --stage a",
    "git restore --stage a",
    "git restore --st a",
    "git restore --staged -S a",
    "git restore --staged --staged a",
    "git restore --staged -- -a",
    "git restore --staged -- --worktree",
    "git restore --staged -- -W",
    "git restore --staged -- -- a",
    "git restore --staged -- a -- b",
    "git restore --staged a b -- c",
    "git restore --staged ../x",
    "git restore --staged a/../b",
    "git restore --staged ..",
    "git restore --staged -- ..",
    "git restore --staged ./..",
    "git restore --staged a/..",
    "git restore --staged a..b",
    "git restore --staged ../",
    'git restore --staged "a b"',
    "git restore --staged 'a'",
    "git restore --staged a\\ b",
    "git restore --staged $(cat f)",
    "git restore --staged $X",
    "git restore --staged `cat f`",
    "git restore --staged a*",
    "git restore --staged a?",
    "git restore --staged a[1]",
    "git restore --staged {a,b}",
    "git restore --staged ~/x",
    "git restore --staged :(top)a",
    "git restore --staged a#b",
    "git restore --staged a > o",
    "git restore --staged a 2>&1",
    "git restore --staged a | cat",
    "git restore --staged a &",
    "git restore --staged a; rm b",
    "git restore --staged -- a; rm b",
    "git restore --staged a && rm b",
    "git restore --staged a\ngit push",
    "git restore --staged a \\\nb",
    "git restore --staged " + " ".join(f"f{i}" for i in range(51)),
    "cd x && git restore --staged a",
    "sudo git restore --staged a",
    "env git restore --staged a",
    "FOO=1 git restore --staged a",
    "command git restore --staged a",
    "bash -c 'git restore --staged a'",
    "xargs git restore --staged",
    "git -C . restore --staged a",
    " git restore --staged a",
    "git restore --staged a ",
    "git restore --staged a\n",
    "\tgit restore --staged a",
    "git restore --staged  a",
    "git  restore --staged a",
    "git restore\t--staged a",
    "git restore --STAGED a",
    "git restore --STAGED a",
    "git restore -s a",
]

# 大文字小文字違いの先頭語は、従来から deny に当たらない (どの規則にも当たらず役割の既定)。例外でも変わらないこと
CASE_VARIANTS = ["GIT RESTORE --staged a", "Git restore --staged a", "git RESTORE --staged a"]


def _results(commands, **kw):
    requests = [r for c in commands for r in _modes(c, **kw)]
    results = _judge(requests)
    return list(zip((r["input"]["command"] for r in requests), results, strict=True))


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize("command", PLAIN)
def test_staged_form_is_neither_denied_nor_forced_to_confirm(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] != "deny", (role, command, res)
        assert not res.get("mustConfirm"), (role, command, res)


@pytest.mark.parametrize("role", ALLOWED_ROLES)
def test_staged_form_decisions_are_the_default_ones(role):
    res = _judge(_modes("git restore --staged a.txt", role=role))
    # 通常は ask、bypass は allow、boundary は allow
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
        "ssh sbx@sandbox-gpu 'git restore --staged a'",
        "ssh sbx@sandbox-gpu git restore --staged a",
        "ssh -p 22 sbx@sandbox-gpu 'git restore --staged a'",
    ],
)
def test_ssh_remote_does_not_get_the_exception(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


@pytest.mark.parametrize("role", DENIED_ROLES)
@pytest.mark.parametrize("command", PLAIN[:4])
def test_roles_without_the_exception_deny_staged_too(role, command):
    for _, res in _results([command], role=role):
        assert res["decision"] == "deny", (role, command, res)


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize(
    "command",
    [
        "git reset HEAD a",
        "git reset --hard",
        "git checkout -- a",
        "git stash",
        "git stash drop",
        "git push origin main",
    ],
)
def test_other_destructive_commands_are_unchanged(role, command):
    # 例外を足す前 (deny_except から git restore --staged を除いた設定) と、同じ判定であること
    base = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    exc = base["pi"]["profiles"][role]["deny_except"]
    exc.remove("git restore --staged")
    for flags in ({}, {"bypass": True}, {"boundary": True}):
        want = _judge([_bash(command, role=role, **flags)], common=base)[0]
        got = _judge([_bash(command, role=role, **flags)])[0]
        assert (got["decision"], got["source"]) == (want["decision"], want["source"]), (
            command,
            got,
            want,
        )


@pytest.mark.parametrize("role", ALLOWED_ROLES)
@pytest.mark.parametrize("command", DENIED + CASE_VARIANTS)
def test_denied_forms_equal_the_decision_without_the_exception(role, command):
    # 例外を外した設定でも同じ deny になる (許可しない形の判定が、変更前と変わっていない)
    base = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    base["pi"]["profiles"][role]["deny_except"].remove("git restore --staged")
    for flags in ({}, {"bypass": True}):
        want = _judge([_bash(command, role=role, **flags)], common=base)[0]
        got = _judge([_bash(command, role=role, **flags)])[0]
        assert (got["decision"], got["source"], got["reason"]) == (
            want["decision"],
            want["source"],
            want["reason"],
        )


def test_switching_local_git_off_disables_the_exception():
    common = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    common["pi"]["confirm"]["local_git"] = False
    for role in ALLOWED_ROLES:
        for req in _modes("git restore --staged a", role=role):
            assert _judge([req], common=common)[0]["decision"] == "deny", (role, req)


def test_a_role_without_the_word_is_denied_even_if_others_have_it():
    common = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    common["pi"]["profiles"]["implementer"]["deny_except"] = ["git worktree remove"]
    res = _judge([_bash("git restore --staged a", role="implementer")], common=common)[0]
    assert res["decision"] == "deny", res
    # worktree remove の例外は、もう一方の語を持たなくても働く
    assert (
        _judge([_bash("git worktree remove ../wt", role="implementer")], common=common)[0][
            "decision"
        ]
        != "deny"
    )


def test_only_the_implementer_has_the_word():
    profiles = load_common()["pi"]["profiles"]
    assert [
        n for n, p in profiles.items() if "git restore --staged" in p.get("deny_except", [])
    ] == ["implementer"]


def test_the_common_deny_still_has_it_and_other_clis_are_unchanged():
    common = load_common()
    assert "git restore" in common["bash"]["deny"]
    assert "git restore" in common["bash"]["deny_guide"]["user_only"]
    assert "git restore" in common["pi"]["profiles"]["worker"]["shell_deny"]
    without = copy.deepcopy(common)
    for p in without["pi"]["profiles"].values():
        p.pop("deny_except", None)
    assert gen.build_claude_permissions(common) == gen.build_claude_permissions(without)
    assert gen.build_opencode_permissions(common) == gen.build_opencode_permissions(without)


@pytest.mark.parametrize("command", ["git checkout feature/x", "git switch feature/x"])
def test_the_implementer_already_may_run_hook_triggering_git_operations(command):
    """この例外が implementer に新しい能力を与えない前提（review）。checkout / switch が全モードで deny でないこと。

    git は `restore --staged` でも `post-checkout` hook を呼ぶが、implementer は元から checkout / switch で hook を動かせる。
    この前提が崩れたら（implementer に checkout / switch の deny が付いたら）、例外の理由を見直す。
    """
    for _, res in _results([command], role="implementer"):
        assert res["decision"] != "deny", (command, res)
