"""git flow の操作 (``gitflow_feature_start`` / ``gitflow_feature_finish``。CHG-0047) の統合試験。

RPC + faux プロバイダーで、``guarded_action`` を通しで確かめる。本物の ``git-flow`` は使わず、
引数を記録するだけの偽の ``git-flow`` を PATH に置く (固定の引数・確認の有無・実効設定の検査を見る)。
``pi.actions`` の表は試験が rules.json へ自分で書く。
"""

from __future__ import annotations

import pytest
import test_pi_actions_harness as A
import test_pi_harness as H

pytestmark = pytest.mark.skipif(H.PI is None, reason="pi is not installed")

env = H.env

GITFLOW_ACTIONS = [
    {
        "id": "gitflow_feature_start",
        "label": "git flow: feature を起票",
        "argv": ["git", "flow", "feature", "start", "{name}", "--worktree", "--no-fetch"],
        "fields": {"name": {"type": "featurename"}},
        "replaces": ["git flow feature start"],
        "preview": "gitflow_start",
        "confirm": "gitflow_start",
    },
    {
        "id": "gitflow_feature_finish",
        "label": "git flow: feature をクローズ",
        "argv": [
            "git",
            "flow",
            "feature",
            "finish",
            "{name}",
            "--squash",
            "--squash-message={message}",
            "--keepremote",
            "--no-fetch",
            "--no-push",
            "--no-pushtag",
            "--notag",
        ],
        "fields": {
            "name": {"type": "featurename"},
            "message": {"type": "text", "content": True, "max_chars": 1200},
        },
        "replaces": ["git flow feature finish"],
        "preview": "gitflow_finish",
    },
]

SAFE_CONFIG = {
    "gitflow.version": "1.0",
    "gitflow.initialized": "true",
    "gitflow.worktreePath": ".tmp/worktrees/{{ branchName }}",
    "gitflow.branch.main.type": "base",
    "gitflow.branch.develop.type": "base",
    "gitflow.branch.develop.parent": "main",
    "gitflow.branch.feature.type": "topic",
    "gitflow.branch.feature.parent": "develop",
    "gitflow.branch.feature.startpoint": "develop",
    "gitflow.branch.feature.prefix": "feature/",
    "gitflow.branch.feature.upstreamstrategy": "squash",
}


def _setup(env, monkeypatch, config=SAFE_CONFIG, branches=("develop",), checkout="develop"):
    monkeypatch.setattr(A, "ACTIONS", A.ACTIONS + GITFLOW_ACTIONS)
    A._prepare(env)
    proj = env["proj"]
    A._git(proj, "branch", "-M", "main")
    for b in branches:
        A._git(proj, "branch", b)
    A._git(proj, "checkout", "-q", checkout)
    for key, value in (config or {}).items():
        A._git(proj, "config", key, value)
    # 引数を記録するだけの偽の git-flow
    log = env["tmp"] / "gflog"
    log.mkdir()
    fake = env["tmp"] / "fakebin" / "git-flow"
    fake.write_text(
        '#!/bin/sh\nfor a in "$@"; do printf "%s\\0" "$a"; done > "$FAKE_GF_DIR/args"\necho ok\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env["env"]["FAKE_GF_DIR"] = str(log)
    env["gflog"] = log
    return proj


def _feature_ahead(proj, name="x"):
    A._git(proj, "checkout", "-q", "-b", f"feature/{name}", "develop")
    (proj / f"{name}.txt").write_text("f\n", encoding="utf-8")
    A._git(proj, "add", f"{name}.txt")
    A._git(proj, "commit", "-q", "-m", "wip")
    A._git(proj, "checkout", "-q", "develop")


def _fake_args(env):
    p = env["gflog"] / "args"
    return p.read_text(encoding="utf-8").split("\0")[:-1] if p.exists() else None


@A.needs_action
def test_a_feature_start_runs_without_a_confirmation_and_with_fixed_arguments(env, monkeypatch):
    _setup(env, monkeypatch)
    requests, results = A._rpc(
        env, A._call("gitflow_feature_start", name="alpha"), lambda req: None
    )
    assert A._methods(requests) == [], requests  # 確認を出さない
    assert results and results[0][0] is False, results
    assert "確認なしで実行した" in results[0][1]
    assert _fake_args(env) == ["feature", "start", "alpha", "--worktree", "--no-fetch"]


@A.needs_action
def test_a_feature_start_is_refused_when_the_config_would_push(env, monkeypatch):
    _setup(env, monkeypatch, config={**SAFE_CONFIG, "gitflow.feature.finish.push": "true"})
    _requests, results = A._rpc(
        env, A._call("gitflow_feature_start", name="alpha"), lambda req: None
    )
    assert results and results[0][0] is True and "安全な構成" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
def test_a_repository_without_git_flow_config_is_refused(env, monkeypatch):
    _setup(env, monkeypatch, config={})
    _requests, results = A._rpc(
        env, A._call("gitflow_feature_start", name="alpha"), lambda req: None
    )
    assert results[0][0] is True and "git flow を使っていない" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
@pytest.mark.parametrize("bad", ["--help", "-x", "A", "a..b", "a.lock", "a/b", ""])
def test_a_bad_feature_name_never_reaches_git_flow(env, monkeypatch, bad):
    _setup(env, monkeypatch)
    _requests, results = A._rpc(env, A._call("gitflow_feature_start", name=bad), lambda req: None)
    assert results[0][0] is True and "name" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
def test_an_existing_feature_is_refused(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "alpha")
    _requests, results = A._rpc(
        env, A._call("gitflow_feature_start", name="alpha"), lambda req: None
    )
    assert results[0][0] is True and "すでにある" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
def test_a_finish_asks_and_runs_with_fixed_arguments_that_never_push(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    message = "-weird: msg\n\n- bullet"
    requests, results = A._rpc(
        env,
        A._call("gitflow_feature_finish", name="x", message=message),
        A._choose(A.APPROVE),
    )
    assert A._methods(requests) == ["select"], requests
    assert "feature/x" in requests[0]["title"] and "squash" in requests[0]["title"]
    assert results and results[0][0] is False, results
    args = _fake_args(env)
    assert args[:3] == ["feature", "finish", "x"]
    assert f"--squash-message={message}" in args
    for flag in ("--squash", "--keepremote", "--no-fetch", "--no-push", "--no-pushtag", "--notag"):
        assert flag in args


@A.needs_action
def test_a_finish_that_is_not_approved_runs_nothing(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    _requests, results = A._rpc(
        env,
        A._call("gitflow_feature_finish", name="x", message="m"),
        lambda req: {"value": A.REJECT},
    )
    assert results[0][0] is True and "not approved:" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
def test_a_finish_outside_develop_or_without_commits_is_refused_before_asking(env, monkeypatch):
    proj = _setup(env, monkeypatch, checkout="main")
    _feature_ahead(proj, "x")
    A._git(proj, "checkout", "-q", "main")
    requests, results = A._rpc(
        env, A._call("gitflow_feature_finish", name="x", message="m"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == [], requests
    assert results[0][0] is True and "develop が checked out" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
def test_a_finish_with_a_dirty_feature_worktree_is_refused(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    wt = env["tmp"] / "wt-x"
    A._git(proj, "worktree", "add", "-q", str(wt), "feature/x")
    (wt / "dirty.txt").write_text("d\n", encoding="utf-8")
    A._git(wt, "add", "dirty.txt")
    _requests, results = A._rpc(
        env, A._call("gitflow_feature_finish", name="x", message="m"), A._choose(A.APPROVE)
    )
    assert results[0][0] is True and "コミットしていない変更" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
def test_state_changes_after_the_confirmation_stop_the_finish(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")

    def handler(req):
        # 確認を待つ間に、feature が進む
        A._git(proj, "checkout", "-q", "feature/x")
        (proj / "late.txt").write_text("l\n", encoding="utf-8")
        A._git(proj, "add", "late.txt")
        A._git(proj, "commit", "-q", "-m", "late")
        A._git(proj, "checkout", "-q", "develop")
        return {"value": A.APPROVE}

    _requests, results = A._rpc(
        env, A._call("gitflow_feature_finish", name="x", message="m"), handler
    )
    assert results[0][0] is True and "状態が変わった" in results[0][1], results
    assert _fake_args(env) is None


def _worktree(env, proj, branch, name="w"):
    path = env["tmp"] / f"wt-{name}"
    A._git(proj, "worktree", "add", "-q", "-b", branch, str(path), "develop")
    return path


def _commit_requests(env, cwd):
    """cwd で git_commit を 1 回呼び、確認の要求の一覧と結果を返す (確認が出たら拒否で答える)。"""
    A._stage(cwd)
    env["proj"] = cwd
    return A._rpc(env, A._call("git_commit", message="wip: a"), lambda req: {"value": A.REJECT})


@A.needs_action
def test_a_wip_commit_in_a_feature_worktree_needs_no_confirmation(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    wt = _worktree(env, proj, "feature/w")
    before = A._head(wt)
    requests, results = _commit_requests(env, wt)
    assert A._methods(requests) == [], requests
    assert results and results[0][0] is False, results
    assert "確認なしで実行した" in results[0][1]
    assert A._head(wt) != before


@A.needs_action
@pytest.mark.parametrize("where", ["main_on_develop", "main_on_feature", "linked_other_branch"])
def test_other_commits_are_still_confirmed(env, monkeypatch, where):
    proj = _setup(env, monkeypatch)
    if where == "main_on_develop":
        cwd = proj
    elif where == "main_on_feature":
        A._git(proj, "checkout", "-q", "-b", "feature/m", "develop")
        cwd = proj
    else:
        cwd = _worktree(env, proj, "hotfix/h")
    before = A._head(cwd)
    requests, results = _commit_requests(env, cwd)
    assert A._methods(requests)[:1] == ["select"], requests
    assert results[0][0] is True and "not approved:" in results[0][1], results
    assert A._head(cwd) == before


@A.needs_action
def test_an_unsafe_gitflow_config_keeps_the_confirmation_in_a_feature_worktree(env, monkeypatch):
    proj = _setup(env, monkeypatch, config={**SAFE_CONFIG, "gitflow.feature.finish.push": "true"})
    wt = _worktree(env, proj, "feature/w")
    requests, _results = _commit_requests(env, wt)
    assert A._methods(requests)[:1] == ["select"], requests
