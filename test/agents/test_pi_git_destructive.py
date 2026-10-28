"""元に戻せないローカルの git 操作 (``[pi.confirm] local_git``) は、bypass でも確認する。

- ``git branch -D``・``git clean``・``git tag -d`` など (別の書き方も) は、全役割・全モードで mustConfirm の ask。
- 安全な形 (``--list``・``-d``・``clean -n``・``tag -l``・``checkout -b``) は巻き込まない。
- 既定が deny の役割は、既存の deny のまま。設定を切れば、従来の判定に戻る。

see docs/spec/guard/pi-decide.md#confirm
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

LOCAL_PREFIX = "確認が必要な元に戻せない git 操作 (bypass でも確認する): "

DESTRUCTIVE = [
    "git branch -D x",
    "git branch -fd x",
    "git branch -df x",
    "git branch --delete --force x",
    "git branch -f x HEAD~1",
    "git branch -M new",
    "git clean -f",
    "git clean -fd",
    "git clean -fdx",
    "git clean -e '-n' -f",
    "git tag -d v1",
    "git tag --delete v1",
    "git tag -f v1",
    "git checkout -B x",
    "git switch -C x",
    "git switch --force-create x",
    # 前置と複合
    "git -C repo branch -D x",
    "git -c k=v branch -D x",
    "git --git-dir=.git branch -D x",
    "git --git-dir .git --work-tree . clean -fd",
    "env -u HOME git branch -D x",
    "FOO=1 git clean -fd",
    "cd sub && git tag -d v1",
    "git status && git branch -D x",
]

SAFE = [
    "git branch",
    "git branch --list",
    "git branch -a",
    "git branch --show-current",
    "git branch --list -f",
    "git branch -d merged",
    "git branch -m old new",
    "git branch -u origin/x",
    "git clean -n",
    "git clean -nfd",
    "git clean --dry-run -fd",
    "git tag",
    "git tag -l",
    "git tag --list 'v*'",
    "git tag v1",
    "git tag -a v1 -m message",
    "git checkout -b x",
    "git switch -c x",
    "git status",
]


def _results(commands, **kw):
    requests = [r for c in commands for r in _modes(c, **kw)]
    results = _judge(requests)
    return list(zip((r["input"]["command"] for r in requests), results, strict=True))


@pytest.mark.parametrize("command", DESTRUCTIVE)
def test_destructive_git_is_confirmed_even_with_bypass_and_boundary(command):
    for _, res in _results([command]):
        assert res["decision"] == "ask", (command, res)
        assert res.get("mustConfirm") is True, (command, res)
        assert res["reason"].startswith(LOCAL_PREFIX), (command, res)


@pytest.mark.parametrize("command", SAFE)
def test_safe_git_is_not_pulled_into_the_confirmation(command):
    for _, res in _results([command]):
        assert not res.get("mustConfirm"), (command, res)


@pytest.mark.parametrize("role", ["explorer", "committer", "reader"])
def test_a_role_that_denies_by_default_denies_them_even_with_bypass(role):
    # これらの役割は shell で元に戻せない操作をしない。以前は [bash] ask が役割の既定の deny より先に当たり、bypass で allow だった
    for command in ("git tag -d v1", "git branch -fd x", "git clean -fd", "git branch -D x"):
        for _, res in _results([command], role=role):
            assert res["decision"] == "deny", (role, command, res)
    off = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    off["pi"]["confirm"]["local_git"] = False
    res = _judge([_bash("git branch -D x", role="explorer", bypass=True)], common=off)[0]
    assert res["decision"] == "allow", res  # 設定を切ると従来の (穴のある) 判定


def test_switching_it_off_restores_the_old_decisions():
    common = copy.deepcopy(gen.pi_judge_data(load_common())["common"])
    common["pi"]["confirm"]["local_git"] = False
    res = _judge([_bash("git tag -d v1", bypass=True)], common=common)[0]
    assert res["decision"] == "allow" and not res.get("mustConfirm"), res
    res = _judge([_bash("git tag -d v1", bypass=True)])[0]
    assert res["decision"] == "ask" and res["mustConfirm"] is True, res


def test_the_normal_decision_of_an_already_asked_form_is_unchanged():
    # `git branch -D` は [bash] ask で、通常も ask。bypass なしの結果は ask のまま (mustConfirm の印が付くだけ)
    res = _judge([_bash("git branch -D x")])[0]
    assert res["decision"] == "ask", res


def test_the_generator_validates_local_git():
    common = load_common()
    common = copy.deepcopy(common)
    common["pi"]["confirm"]["local_git"] = "yes"
    with pytest.raises(SystemExit):
        gen.pi_confirm(common)
