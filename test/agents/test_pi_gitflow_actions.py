"""git flow の操作 (``gitflow_feature_start`` / ``gitflow_feature_finish``。CHG-0047) の統合試験。

RPC + faux プロバイダーで、``guarded_action`` を通しで確かめる。本物の ``git-flow`` は使わず、
引数を記録するだけの偽の ``git-flow`` を PATH に置く (固定の引数・確認の有無・実効設定の検査を見る)。
``pi.actions`` の表は試験が rules.json へ自分で書く。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

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
        "id": "gitflow_feature_commit",
        "label": "git flow: feature の worktree で WIP コミット",
        "argv": ["git", "commit", "--message={message}"],
        "fields": {
            "name": {"type": "featurename"},
            "message": {"type": "text", "content": True, "max_chars": 1200},
        },
        "replaces": ["git flow feature commit"],
        "preview": "gitflow_commit",
        "confirm": "gitflow_wip",
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
    {
        "id": "gitflow_feature_discard",
        "label": "git flow: feature を捨てる",
        "argv": [
            "git",
            "flow",
            "feature",
            "delete",
            "{name}",
            "--force",
            "--no-fetch",
            "--no-remote",
        ],
        "fields": {"name": {"type": "featurename"}},
        "replaces": ["git flow feature delete"],
        "preview": "gitflow_discard",
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
def test_a_discard_asks_and_runs_with_fixed_arguments_that_never_touch_the_remote(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    requests, results = A._rpc(
        env, A._call("gitflow_feature_discard", name="x"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == ["select"], requests
    title = requests[0]["title"]
    assert "feature/x" in title and "捨てる" in title and "1 件" in title, title
    assert results and results[0][0] is False, results
    args = _fake_args(env)
    assert args == ["feature", "delete", "x", "--force", "--no-fetch", "--no-remote"], args


@A.needs_action
def test_a_discard_that_is_not_approved_runs_nothing(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    _requests, results = A._rpc(
        env, A._call("gitflow_feature_discard", name="x"), lambda req: {"value": A.REJECT}
    )
    assert results[0][0] is True and "not approved:" in results[0][1], results
    assert _fake_args(env) is None


@A.needs_action
def test_a_discard_is_refused_for_a_missing_feature_or_outside_develop(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    requests, results = A._rpc(
        env, A._call("gitflow_feature_discard", name="nope"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == [] and "無い" in results[0][1], (requests, results)
    _feature_ahead(proj, "x")
    A._git(proj, "checkout", "-q", "feature/x")
    requests, results = A._rpc(
        env, A._call("gitflow_feature_discard", name="x"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == [] and "develop が checked out" in results[0][1], (
        requests,
        results,
    )
    assert _fake_args(env) is None


@A.needs_action
def test_a_discard_with_a_dirty_feature_worktree_is_refused(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    wt = env["tmp"] / "wt-x"
    A._git(proj, "worktree", "add", "-q", str(wt), "feature/x")
    (wt / "dirty.txt").write_text("d\n", encoding="utf-8")
    requests, results = A._rpc(
        env, A._call("gitflow_feature_discard", name="x"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == [] and "コミットしていない変更" in results[0][1], (
        requests,
        results,
    )
    assert _fake_args(env) is None


@A.needs_action
def test_a_discard_is_refused_when_the_config_would_push(env, monkeypatch):
    config = {**SAFE_CONFIG, "gitflow.branch.feature.finish.push": "true"}
    proj = _setup(env, monkeypatch, config=config)
    _feature_ahead(proj, "x")
    requests, results = A._rpc(
        env, A._call("gitflow_feature_discard", name="x"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == [] and "安全な構成" in results[0][1], (requests, results)
    assert _fake_args(env) is None


@A.needs_action
def test_a_finish_that_would_conflict_is_refused_before_asking(env, monkeypatch):
    """squash が途中で止まると、develop が衝突状態で残り、git flow の --abort も squash では動かない。始める前に断る。"""
    proj = _setup(env, monkeypatch)
    A._git(proj, "checkout", "-q", "-b", "feature/x", "develop")
    (proj / "shared.txt").write_text("feature\n", encoding="utf-8")
    A._git(proj, "add", "shared.txt")
    A._git(proj, "commit", "-q", "-m", "feature side")
    A._git(proj, "checkout", "-q", "develop")
    (proj / "shared.txt").write_text("develop\n", encoding="utf-8")
    A._git(proj, "add", "shared.txt")
    A._git(proj, "commit", "-q", "-m", "develop side")
    requests, results = A._rpc(
        env, A._call("gitflow_feature_finish", name="x", message="m"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == [], requests
    assert results[0][0] is True and "衝突" in results[0][1], results
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
def test_a_finish_is_refused_when_develop_has_uncommitted_tracked_changes(env, monkeypatch):
    """develop の本体にステージ済みの変更があると、squash のコミットに混ざってしまう (実機で発生)。"""
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    tracked = next(iter(sorted(p for p in proj.iterdir() if p.is_file() and p.name != ".git")))
    tracked.write_text("changed\n", encoding="utf-8")
    for stage in (True, False):
        if stage:
            A._git(proj, "add", tracked.name)
        requests, results = A._rpc(
            env, A._call("gitflow_feature_finish", name="x", message="m"), A._choose(A.APPROVE)
        )
        assert A._methods(requests) == [], requests
        assert results[0][0] is True and "コミットしていない変更" in results[0][1], results
        assert _fake_args(env) is None
        if stage:
            A._git(proj, "reset", "-q")


@A.needs_action
def test_untracked_files_do_not_block_a_finish(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_ahead(proj, "x")
    (proj / "scratch.txt").write_text("s\n", encoding="utf-8")
    requests, _results = A._rpc(
        env, A._call("gitflow_feature_finish", name="x", message="m"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == ["select"], requests


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


def _real_git_flow():
    """本物の git-flow-next の置き場。環境変数 GIT_FLOW_NEXT_DIR か、PATH の git-flow。無ければ None"""
    d = os.environ.get("GIT_FLOW_NEXT_DIR")
    if d and (Path(d) / "git-flow").exists():
        return d
    found = shutil.which("git-flow")
    return str(Path(found).parent) if found else None


# 読み込み時に決める (fixture が環境変数を触ることがある)
REAL_GIT_FLOW = _real_git_flow()


@A.needs_action
@pytest.mark.skipif(
    REAL_GIT_FLOW is None, reason="本物の git-flow-next が無い (GIT_FLOW_NEXT_DIR か PATH)"
)
def test_the_whole_feature_cycle_with_the_real_git_flow(env, monkeypatch):
    """起票 → worktree で WIP コミット 2 回 (確認なし) → クローズ (確認あり、squash) を、本物の git-flow で通す。"""
    monkeypatch.setattr(A, "ACTIONS", A.ACTIONS + GITFLOW_ACTIONS)
    A._prepare(env)
    env["env"]["PATH"] = f"{REAL_GIT_FLOW}{os.pathsep}{env['env']['PATH']}"
    proj = env["proj"]
    A._git(proj, "branch", "-M", "main")
    sub = {**os.environ, "PATH": env["env"]["PATH"], "GIT_CONFIG_GLOBAL": "/dev/null"}

    def flow(*args):
        r = subprocess.run(
            ["git", "flow", *args],
            cwd=proj,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=sub,
        )
        assert r.returncode == 0, (
            args,
            r.stdout,
            r.stderr,
            sub["PATH"][:300],
            shutil.which("git-flow", path=sub["PATH"]),
        )

    # 利用者が (サンドボックスの外で) 一度だけ行う設定
    flow("init", "--preset=classic", "--defaults")
    flow("config", "edit", "topic", "feature", "--upstream-strategy=squash")
    for topic in ("release", "hotfix", "support", "bugfix"):
        flow("config", "delete", "topic", topic)
    A._git(proj, "config", "gitflow.worktreePath", ".tmp/worktrees/{{ branchName }}")
    develop_before = A._git(proj, "rev-parse", "develop").strip()

    # 1. 起票 (確認なし)
    requests, results = A._rpc(
        env, A._call("gitflow_feature_start", name="cycle"), lambda req: None
    )
    assert A._methods(requests) == [] and results[0][0] is False, (requests, results)
    wt = proj / ".tmp" / "worktrees" / "cycle"
    assert wt.is_dir() and A._git(wt, "branch", "--show-current").strip() == "feature/cycle"

    # 2. worktree の中の WIP コミット 2 回 (確認なし)
    for i in (1, 2):
        A._stage(wt, name=f"f{i}.txt", text=f"{i}\n")
        env["proj"] = wt
        requests, results = A._rpc(
            env, A._call("git_commit", message=f"wip: {i}"), lambda req: None
        )
        assert A._methods(requests) == [] and results[0][0] is False, (requests, results)
    assert A._git(proj, "rev-list", "--count", "develop..feature/cycle").strip() == "2"

    # 3. クローズ (確認あり。本体の develop から)
    env["proj"] = proj
    message = "feat: cycle\n\n- one change"
    requests, results = A._rpc(
        env, A._call("gitflow_feature_finish", name="cycle", message=message), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == ["select"], requests
    assert "feature/cycle" in requests[0]["title"] and "f1.txt" in requests[0]["title"]
    assert results[0][0] is False, results
    # develop に 1 コミット (squash)。feature のブランチと worktree は消え、リモートは無い
    assert A._git(proj, "rev-list", "--count", f"{develop_before}..develop").strip() == "1"
    assert A._git(proj, "log", "-1", "--format=%s", "develop").strip() == "feat: cycle"
    assert not wt.exists()
    assert "feature/cycle" not in A._git(proj, "branch", "--list", "feature/*")
    assert A._git(proj, "ls-tree", "-r", "--name-only", "develop").split() == [
        "base.txt",
        "f1.txt",
        "f2.txt",
    ]


def _feature_worktree(env, proj, name="w"):
    """feature/<name> の worktree を、本体の .tmp/worktrees/ の下に作る (git flow の start と同じ置き場)。"""
    path = proj / ".tmp" / "worktrees" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    A._git(proj, "worktree", "add", "-q", "-b", f"feature/{name}", str(path), "develop")
    return path


def _wip(env, name="w", message="wip: a"):
    return A._rpc(
        env,
        A._call("gitflow_feature_commit", name=name, message=message),
        lambda req: {"value": A.REJECT},
    )


@A.needs_action
def test_a_wip_commit_action_stages_everything_and_commits_in_the_feature_worktree(
    env, monkeypatch
):
    proj = _setup(env, monkeypatch)
    wt = _feature_worktree(env, proj)
    (wt / "new.txt").write_text("n\n", encoding="utf-8")
    (wt / "base.txt").write_text("changed\n", encoding="utf-8")
    main_head = A._head(proj)
    before = A._head(wt)
    requests, results = _wip(env)
    # 本体の pi から、確認なしで動く
    assert A._methods(requests) == [], requests
    assert results[0][0] is False and "確認なしで実行した" in results[0][1], results
    assert A._head(wt) != before
    assert A._head(proj) == main_head
    assert sorted(A._git(wt, "show", "--name-only", "--format=", "HEAD").split()) == [
        "base.txt",
        "new.txt",
    ]
    assert A._git(wt, "log", "-1", "--format=%s").strip() == "wip: a"


@A.needs_action
def test_a_wip_commit_never_stages_a_protected_file(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    wt = _feature_worktree(env, proj)
    (wt / "ok.txt").write_text("ok\n", encoding="utf-8")
    (wt / ".env").write_text("SECRET=1\n", encoding="utf-8")
    before = A._head(wt)
    _requests, results = _wip(env)
    assert results[0][0] is True and "保護対象" in results[0][1], results
    assert A._head(wt) == before
    assert A._git(wt, "diff", "--cached", "--name-only").strip() == ""  # ステージもしない


@A.needs_action
def test_a_wip_commit_without_changes_or_with_an_unsafe_config_is_refused(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    _feature_worktree(env, proj)
    _requests, results = _wip(env)
    assert results[0][0] is True and "変更が無い" in results[0][1], results


@A.needs_action
def test_a_wip_commit_is_refused_when_the_config_is_unsafe(env, monkeypatch):
    proj = _setup(env, monkeypatch, config={**SAFE_CONFIG, "gitflow.feature.finish.push": "true"})
    wt = _feature_worktree(env, proj)
    (wt / "x.txt").write_text("x\n", encoding="utf-8")
    _requests, results = _wip(env)
    assert results[0][0] is True, results
    assert A._git(wt, "diff", "--cached", "--name-only").strip() == ""


@A.needs_action
def test_a_wip_commit_needs_a_real_feature_worktree_under_the_main_one(env, monkeypatch):
    proj = _setup(env, monkeypatch)
    # 名前の feature が無い
    _requests, results = _wip(env, name="nope")
    assert results[0][0] is True and "worktree が無い" in results[0][1], results
    # 手で作った、.tmp/worktrees/ の外の worktree
    outside = env["tmp"] / "outside-wt"
    A._git(proj, "worktree", "add", "-q", "-b", "feature/o", str(outside), "develop")
    (outside / "x.txt").write_text("x\n", encoding="utf-8")
    _requests, results = _wip(env, name="o")
    assert results[0][0] is True and ".tmp/worktrees" in results[0][1], results
    assert A._git(outside, "diff", "--cached", "--name-only").strip() == ""
    # 不正な名前
    _requests, results = _wip(env, name="--help")
    assert results[0][0] is True and "name" in results[0][1], results


@A.needs_action
@pytest.mark.skipif(
    REAL_GIT_FLOW is None, reason="本物の git-flow-next が無い (GIT_FLOW_NEXT_DIR か PATH)"
)
def test_a_discard_removes_the_branch_and_the_worktree_with_the_real_git_flow(env, monkeypatch):
    """起票 → WIP コミット → 破棄 (確認あり) で、ブランチと worktree が消え、develop は動かない。リモートは無い。"""
    monkeypatch.setattr(A, "ACTIONS", A.ACTIONS + GITFLOW_ACTIONS)
    A._prepare(env)
    env["env"]["PATH"] = f"{REAL_GIT_FLOW}{os.pathsep}{env['env']['PATH']}"
    proj = env["proj"]
    A._git(proj, "branch", "-M", "main")
    sub = {**os.environ, "PATH": env["env"]["PATH"], "GIT_CONFIG_GLOBAL": "/dev/null"}

    def flow(*args):
        r = subprocess.run(
            ["git", "flow", *args],
            cwd=proj,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=sub,
        )
        assert r.returncode == 0, (args, r.stdout, r.stderr)

    flow("init", "--preset=classic", "--defaults")
    flow("config", "edit", "topic", "feature", "--upstream-strategy=squash")
    for topic in ("release", "hotfix", "support", "bugfix"):
        flow("config", "delete", "topic", topic)
    A._git(proj, "config", "gitflow.worktreePath", ".tmp/worktrees/{{ branchName }}")
    develop_before = A._git(proj, "rev-parse", "develop").strip()

    requests, results = A._rpc(env, A._call("gitflow_feature_start", name="gone"), lambda req: None)
    assert results[0][0] is False, (requests, results)
    wt = proj / ".tmp" / "worktrees" / "gone"
    A._stage(wt, name="g.txt", text="g\n")
    env["proj"] = wt
    _requests, results = A._rpc(env, A._call("git_commit", message="wip: g"), lambda req: None)
    assert results[0][0] is False, results

    env["proj"] = proj
    requests, results = A._rpc(
        env, A._call("gitflow_feature_discard", name="gone"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == ["select"], requests
    assert "feature/gone" in requests[0]["title"] and "g.txt" in requests[0]["title"]
    assert results[0][0] is False, results
    assert not wt.exists()
    assert "feature/gone" not in A._git(proj, "branch", "--list", "feature/*")
    assert A._git(proj, "rev-parse", "develop").strip() == develop_before
    assert A._git(proj, "worktree", "list", "--porcelain").count("worktree ") == 1
