"""統合の実行器 (harness/integrate-exec.ts) の試験。使い捨ての実 git リポジトリで確かめる。

品質ゲート (hook・署名) を迂回しないこと、失敗時に元へ戻すこと、precheck が何も変えないことを見る。
see docs/change/0055
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_integrate_plan import MSG, PROTECTED, RISK, _commit, _git, _snapshot
from test_pi_judge_ts import _node

PLAN_DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_plan_driver.mjs"
EXEC_DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_exec_driver.mjs"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="hook をシェルスクリプトで作る")


def _node_run(driver: Path, payload: dict, timeout: int = 90) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(driver)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=timeout,
    )
    return json.loads(out.stdout)


def _plan(cwd: Path) -> dict:
    plan = _node_run(
        PLAN_DRIVER,
        {
            "cwd": str(cwd),
            "source": "feature/x",
            "target": "develop",
            "message": MSG,
            "protectedRefs": PROTECTED,
            "riskPaths": RISK,
        },
    )
    assert plan["ok"] is True, plan
    return plan


def _exec(plan: dict, approver: Path, cleanup: str = "none", **kw) -> dict:
    return _node_run(
        EXEC_DRIVER, {"plan": plan, "cleanup": cleanup, "approverCwd": str(approver), **kw}
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "main"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
        _git(r, "config", k, v)
    _commit(r, "a.txt", "1\n2\n3\n", "init")
    _git(r, "checkout", "-q", "-b", "feature/x")
    _commit(r, "b.txt", "new\nfile\n")
    _git(r, "checkout", "-q", "develop")
    _commit(r, "c.txt", "dev\n")
    return r


@pytest.fixture
def feat(repo: Path, tmp_path: Path) -> Path:
    """feature/x をチェックアウトした別 worktree"""
    p = tmp_path / "feat"
    _git(repo, "worktree", "add", "-q", str(p), "feature/x")
    return p


def _hook(repo: Path, tmp_path: Path, body: str) -> None:
    d = tmp_path / "hooks"
    d.mkdir(exist_ok=True)
    h = d / "pre-commit"
    h.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    h.chmod(h.stat().st_mode | stat.S_IEXEC)
    _git(repo, "config", "core.hooksPath", str(d))


def _unchanged(
    repo: Path, before: tuple[str, ...], res: dict, outcome: str = "not_executed"
) -> None:
    assert res["outcome"] == outcome, res
    assert _snapshot(repo) == before
    assert _git(repo, "status", "--porcelain") == _git(repo, "status", "--porcelain")


def test_success_without_cleanup(repo: Path, feat: Path) -> None:
    plan = _plan(repo)
    old = _git(repo, "rev-parse", "develop").strip()
    res = _exec(plan, repo)
    assert res["outcome"] == "success" and res["phase"] == "done", res["evidence"]
    assert _git(repo, "rev-parse", "develop~1").strip() == old
    assert _git(repo, "rev-parse", "develop^{tree}").strip() == plan["resultTree"]
    assert _git(repo, "log", "-1", "--format=%B").strip() == MSG
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "rev-parse", "--verify", "feature/x").strip()
    assert any("squash" in e for e in res["confirmedEffects"])


def test_precheck_develop_advanced(repo: Path) -> None:
    plan = _plan(repo)
    _commit(repo, "d.txt", "more\n")
    before = _snapshot(repo)
    _unchanged(repo, before, _exec(plan, repo))


def test_precheck_feature_advanced(repo: Path) -> None:
    plan = _plan(repo)
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, "e.txt", "more\n")
    _git(repo, "checkout", "-q", "develop")
    before = _snapshot(repo)
    _unchanged(repo, before, _exec(plan, repo))


@pytest.mark.parametrize("kind", ["tracked", "untracked"])
def test_precheck_dirty(repo: Path, kind: str) -> None:
    plan = _plan(repo)
    (repo / ("a.txt" if kind == "tracked" else "new.txt")).write_text("x\n", encoding="utf-8")
    before = _snapshot(repo)
    _unchanged(repo, before, _exec(plan, repo))
    assert (repo / ("a.txt" if kind == "tracked" else "new.txt")).read_text(
        encoding="utf-8"
    ) == "x\n"


def test_precheck_merge_in_progress(repo: Path) -> None:
    plan = _plan(repo)
    p = _git(repo, "rev-parse", "--git-path", "MERGE_HEAD").strip()
    (repo / p).write_text(_git(repo, "rev-parse", "HEAD"), encoding="utf-8")
    before = _snapshot(repo)
    _unchanged(repo, before, _exec(plan, repo))


def test_precheck_no_target_worktree(repo: Path) -> None:
    plan = _plan(repo)
    plan["targetWorktree"] = None
    before = _snapshot(repo)
    _unchanged(repo, before, _exec(plan, repo))


def test_precheck_merge_driver(repo: Path) -> None:
    plan = _plan(repo)
    _git(repo, "config", "merge.foo.driver", "true")
    before = _snapshot(repo)
    _unchanged(repo, before, _exec(plan, repo))


def test_tree_mismatch_rolls_back(repo: Path) -> None:
    plan = _plan(repo)
    plan["resultTree"] = "0" * 40
    before = _snapshot(repo)
    res = _exec(plan, repo)
    _unchanged(repo, before, res)
    assert res["phase"] == "merge"
    assert not (repo / "b.txt").exists()


def test_hook_failure_rolls_back(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "echo hookmsg-denied >&2\nexit 1")
    before = _snapshot(repo)
    res = _exec(plan, repo)
    _unchanged(repo, before, res, "failed_confirmed")
    assert res["phase"] == "commit"
    assert any("hookmsg-denied" in e for e in res["evidence"]), res
    assert not (repo / "b.txt").exists()


def test_secret_hook_blocks_integration(repo: Path, tmp_path: Path) -> None:
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, "key.txt", "token=DUMMY_SECRET_123\n")
    _git(repo, "checkout", "-q", "develop")
    plan = _plan(repo)
    _hook(
        repo,
        tmp_path,
        "if git diff --cached | grep -q DUMMY_SECRET_123; then echo secret-found >&2; exit 1; fi",
    )
    before = _snapshot(repo)
    res = _exec(plan, repo)
    _unchanged(repo, before, res, "failed_confirmed")
    assert not (repo / "key.txt").exists()


def test_hook_changes_content(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "echo x > extra.txt\ngit add extra.txt")
    res = _exec(plan, repo)
    assert res["outcome"] == "success", res
    assert any("hook が内容を変えた" in e for e in res["evidence"]), res
    assert _git(repo, "rev-parse", "develop^{tree}").strip() != plan["resultTree"]
    assert _git(repo, "status", "--porcelain") == ""


def test_signing_failure_rolls_back(repo: Path) -> None:
    plan = _plan(repo)
    _git(repo, "config", "commit.gpgsign", "true")
    _git(repo, "config", "gpg.program", "/bin/false")
    before = _snapshot(repo)
    _unchanged(repo, before, _exec(plan, repo), "failed_confirmed")


def test_cleanup_branch_and_worktree(repo: Path, feat: Path) -> None:
    plan = _plan(repo)
    res = _exec(plan, repo, "branch_and_worktree")
    assert res["outcome"] == "success", res
    assert res["remainingCleanup"] == [], res
    assert not feat.exists()
    assert _git(repo, "branch", "--list", "feature/x").strip() == ""


def test_cleanup_approver_inside_worktree(repo: Path, feat: Path) -> None:
    plan = _plan(repo)
    res = _exec(plan, feat, "branch_and_worktree")
    assert res["outcome"] == "success", res
    assert feat.exists()
    assert any("承認した pi" in r for r in res["remainingCleanup"]), res
    assert _git(repo, "branch", "--list", "feature/x").strip() != ""


def test_cleanup_branch_keeps_used_branch(repo: Path, feat: Path) -> None:
    plan = _plan(repo)
    res = _exec(plan, repo, "branch")
    assert res["outcome"] == "success", res
    assert feat.exists()
    assert res["remainingCleanup"], res
    assert _git(repo, "branch", "--list", "feature/x").strip() != ""


def test_cleanup_branch_without_worktree(repo: Path) -> None:
    plan = _plan(repo)
    res = _exec(plan, repo, "branch")
    assert res["outcome"] == "success" and res["remainingCleanup"] == [], res
    assert _git(repo, "branch", "--list", "feature/x").strip() == ""


def test_cleanup_dirty_worktree_kept(repo: Path, feat: Path) -> None:
    plan = _plan(repo)
    (feat / "wip.txt").write_text("wip\n", encoding="utf-8")
    res = _exec(plan, repo, "branch_and_worktree")
    assert res["outcome"] == "success", res
    assert feat.exists() and (feat / "wip.txt").exists()
    assert res["remainingCleanup"], res


def test_abort_during_hook(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "sleep 30")
    before = _snapshot(repo)
    res = _exec(plan, repo, abortAfterMs=1500)
    _unchanged(repo, before, res)
    assert any("中断" in e for e in res["evidence"]), res
