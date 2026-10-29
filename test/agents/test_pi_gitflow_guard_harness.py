"""gitflow-lite 規約の強制 (CHG-0049) の統合試験。

実 pi + 偽のモデル (faux) で、使い捨ての git リポジトリに対する edit / write と git_commit の拒否を確かめる。
fixture と補助は test_pi_harness.py / test_pi_actions_harness.py のものを再利用する。
see docs/spec/guard/pi-gitflow-guard.md
"""

from __future__ import annotations

import os
import subprocess

import pytest
import test_pi_actions_harness as A
import test_pi_harness as H

pytestmark = pytest.mark.skipif(H.PI is None, reason="pi is not installed")

env = H.env  # 使い捨ての作業ツリーと rules.json (fixture を再利用)

LITE = """[gitflow]
\tversion = 1.0
\tinitialized = true
\tworktreePath = .tmp/worktrees/{{ branchName }}
[gitflow "branch.develop"]
\ttype = base
\tparent = main
\tupstreamStrategy = merge
\tdownstreamStrategy = merge
\tautoUpdate = true
\ttag = false
[gitflow "branch.feature"]
\ttype = topic
\tparent = develop
\tstartPoint = develop
\tupstreamStrategy = squash
\tdownstreamStrategy = rebase
\tprefix = feature/
\tautoUpdate = false
\ttag = false
\tworktree = false
[gitflow "branch.main"]
\ttype = base
\tupstreamStrategy = none
\tdownstreamStrategy = none
\tautoUpdate = false
\ttag = false
"""


def git(cwd, *args):
    """グローバル設定に依存せずに git を実行する。"""
    cmd = [
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.test",
        "-c",
        "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
    ).stdout


def make_repo(proj, *, lite=True):
    """proj を develop 上のリポジトリにする (lite のときは .gitflow を develop にコミットする。main も作る)。"""
    if not (proj / ".git").exists():
        git(proj, "init", "-q", "-b", "main")
        (proj / "base.txt").write_text("base\n", encoding="utf-8")
        git(proj, "add", "base.txt")
        git(proj, "commit", "-q", "-m", "base")
    git(proj, "switch", "-q", "-C", "develop")
    git(proj, "branch", "-f", "main", "HEAD")
    if lite:
        (proj / ".gitflow").write_text(LITE, encoding="utf-8")
        git(proj, "add", ".gitflow")
        git(proj, "commit", "-q", "-m", "gitflow")


def write_call(path, content="x\n"):
    return [{"name": "guarded_write", "args": {"path": str(path), "content": content}}]


def refused(proc):
    return "guarded_write: isError=true" in proc.stdout


@pytest.fixture
def lite_env(env):
    make_repo(env["proj"])
    return env


def test_write_to_develop_body_is_refused_with_guidance(lite_env):
    """lite + develop の本体への write は拒否され、feature の起票を案内する。"""
    proj = lite_env["proj"]
    proc = H.run_pi(lite_env, write_call(proj / "a.txt"))
    assert refused(proc), proc.stdout + proc.stderr
    assert "gitflow_feature_start" in proc.stdout, proc.stdout
    assert not (proj / "a.txt").exists()


def test_write_to_tmp_in_the_body_is_allowed(lite_env):
    """本体の .tmp/ の下は、develop でも書ける。"""
    proj = lite_env["proj"]
    proc = H.run_pi(lite_env, write_call(proj / ".tmp" / "x.txt"))
    assert not refused(proc), proc.stdout + proc.stderr
    assert (proj / ".tmp" / "x.txt").read_text(encoding="utf-8") == "x\n"


def test_write_to_feature_worktree_from_the_body_is_allowed(lite_env):
    """本体 (develop) を cwd にしていても、feature worktree の中のファイルへは書ける。"""
    proj = lite_env["proj"]
    wt = proj / ".tmp" / "worktrees" / "x"
    git(proj, "worktree", "add", "-q", "-b", "feature/x", str(wt), "develop")
    proc = H.run_pi(lite_env, write_call(wt / "a.txt"))
    assert not refused(proc), proc.stdout + proc.stderr
    assert (wt / "a.txt").read_text(encoding="utf-8") == "x\n"


def test_bypass_does_not_lift_the_write_refusal(lite_env):
    """bypass を有効にしても、規約の拒否は外れない。"""
    proj = lite_env["proj"]
    proc = H.run_pi(lite_env, write_call(proj / "a.txt"), PI_HARNESS_BYPASS="1")
    assert refused(proc), proc.stdout + proc.stderr
    assert not (proj / "a.txt").exists()


def test_non_lite_repo_behaves_as_before(env):
    """.gitflow の無いリポジトリでは、develop への write は従来どおり通る。"""
    proj = env["proj"]
    make_repo(proj, lite=False)
    proc = H.run_pi(env, write_call(proj / "a.txt"))
    assert not refused(proc), proc.stdout + proc.stderr
    assert (proj / "a.txt").exists()


def test_branch_flip_between_tool_call_and_execute_is_caught(env):
    """tool_call の後・execute の前に本体が feature から develop に変わったら、キャッシュが命中しても拒否する。"""
    proj = env["proj"]
    make_repo(proj)
    git(proj, "switch", "-q", "-c", "feature/x")
    proc = H.run_pi(
        env,
        write_call(proj / "a.txt"),
        extra=("-e", str(H.FIXTURES / "branch_flip.ts")),
        FLIP_REPO=str(proj),
        FLIP_TO="develop",
    )
    assert (
        git(proj, "symbolic-ref", "HEAD").strip() == "refs/heads/develop"
    )  # 切り替えは実際に起きた
    assert refused(proc), proc.stdout + proc.stderr
    # tool_call の時点 (feature/x) では通っているので、止めたのは execute() の取り直し
    assert "実行前の判定で止めた" in proc.stdout + proc.stderr, proc.stdout + proc.stderr
    assert not (proj / "a.txt").exists()


def test_unknown_state_asks_and_without_ui_is_blocked(env):
    """壊れた .git (空ファイル) の下の write は確認になり、UI の無い実行ではブロックされる。"""
    proj = env["proj"]
    (proj / ".git").write_text("", encoding="utf-8")
    proc = H.run_pi(env, write_call(proj / "a.txt"))
    assert refused(proc), proc.stdout + proc.stderr
    assert "not approved" in proc.stdout, proc.stdout
    assert not (proj / "a.txt").exists()


@A.needs_action
def test_git_commit_on_develop_is_refused_before_snapshot_and_preview(env):
    """develop の本体の git_commit は、退避・プレビュー・確認の UI より前に拒否する。"""
    A._prepare(env)
    proj = env["proj"]
    make_repo(proj)
    A._stage(proj)
    head = A._head(proj)
    staged = A._git(proj, "diff", "--cached", "--name-only")
    requests, results = A._rpc(env, A._call("git_commit", message="feat: x"), A._choose(A.APPROVE))
    assert requests == [], requests
    assert results and results[0][0] is True, results
    assert "gitflow_feature_start" in results[0][1], results
    assert A._refs(proj) == []
    assert A._git(proj, "for-each-ref", "refs/pi/pending") == ""
    assert A._head(proj) == head
    assert A._git(proj, "diff", "--cached", "--name-only") == staged


@A.needs_action
def test_git_commit_in_a_feature_worktree_is_unaffected(env):
    """feature worktree 内の git_commit は拒否されず、確認の後に実行される。"""
    A._prepare(env)
    proj = env["proj"]
    make_repo(proj)
    wt = proj / ".tmp" / "worktrees" / "x"
    git(proj, "worktree", "add", "-q", "-b", "feature/x", str(wt), "develop")
    A._stage(wt)
    before = A._head(wt)
    requests, results = A._rpc(
        {**env, "proj": wt}, A._call("git_commit", message="feat: x"), A._choose(A.APPROVE)
    )
    assert A._methods(requests) == ["select"], requests
    assert results and results[0][0] is False, results
    assert A._head(wt) != before
    assert A._head(proj) == before  # 本体 (develop) は動かない
    assert git(proj, "symbolic-ref", "HEAD").strip() == "refs/heads/develop"
