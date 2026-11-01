"""統合の算出 (harness/integrate-plan.ts) の試験。使い捨ての実 git リポジトリで確かめる。

see docs/change/0055 (P7/P8)
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_plan_driver.mjs"
PROTECTED = ["develop", "main", "release/*"]
RISK = ["scripts/**", ".github/**"]
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
MSG = "feat: x"


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *IDENT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


def _write(repo: Path, name: str, text: str) -> None:
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(repo: Path, name: str, text: str, msg: str = "c") -> None:
    _write(repo, name, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _plan(cwd: Path, **kw) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    payload = {
        "cwd": str(cwd),
        "source": "feature/x",
        "target": "develop",
        "message": MSG,
        "protectedRefs": PROTECTED,
        "riskPaths": RISK,
        **kw,
    }
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "main"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    _commit(r, "a.txt", "1\n2\n3\n", "init")
    _git(r, "branch", "main")
    _git(r, "checkout", "-q", "-b", "feature/x")
    _commit(r, "b.txt", "new\nfile\n")
    _commit(r, "scripts/run.sh", "echo\n")
    _git(r, "checkout", "-q", "develop")
    _commit(r, "c.txt", "dev\n")
    return r


def _snapshot(r: Path) -> tuple[str, ...]:
    return (
        _git(r, "for-each-ref"),
        _git(r, "rev-parse", "HEAD"),
        _git(r, "ls-files", "-s"),
        _git(r, "status", "--porcelain"),
    )


def test_normal_matches_real_squash(repo: Path, tmp_path: Path) -> None:
    before = _snapshot(repo)
    plan = _plan(repo)
    assert _snapshot(repo) == before
    assert plan["ok"] is True, plan
    assert plan["source"]["ref"] == "refs/heads/feature/x"
    assert plan["target"]["ref"] == "refs/heads/develop"
    assert plan["targetAhead"] == 1
    assert plan["stats"] == {"commits": 2, "files": 2, "additions": 3, "deletions": 0}
    assert {f["path"] for f in plan["files"]} == {"b.txt", "scripts/run.sh"}
    assert plan["files"][0]["path"] == "b.txt"
    assert plan["risks"] == [{"path": "scripts/run.sh", "reason": "リスクの高いパス (scripts/**)"}]
    assert plan["targetWorktree"] == str(repo)
    other = tmp_path / "copy"
    shutil.copytree(repo, other)
    _git(other, "merge", "--squash", "feature/x")
    _git(other, "commit", "-q", "-m", MSG)
    assert plan["resultTree"] == _git(other, "rev-parse", "HEAD^{tree}").strip()


def test_from_linked_worktree(repo: Path, tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), "feature/x")
    plan = _plan(wt)
    assert plan["ok"] is True, plan
    assert plan["targetWorktree"] == str(repo)


def test_target_not_checked_out(repo: Path) -> None:
    _git(repo, "checkout", "-q", "main")
    plan = _plan(repo)
    assert plan["ok"] is True and plan["targetWorktree"] is None


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"source": "develop"}, "bad_source"),
        ({"source": "main"}, "bad_source"),
        ({"source": "feature/../x"}, "bad_source"),
        ({"source": "feature/x y"}, "bad_source"),
        ({"target": "feature/x", "source": "feature/y"}, "bad_target"),
        ({"target": "topic"}, "bad_target"),
        ({"target": "release/*"}, "bad_target"),
        ({"source": "feature/none"}, "missing_ref"),
        ({"target": "main"}, "ok"),
        ({"message": ""}, "bad_message"),
        ({"message": "  \n"}, "bad_message"),
        ({"message": "a" * 1201}, "bad_message"),
        ({"message": "a\0b"}, "bad_message"),
    ],
)
def test_refusals_simple(repo: Path, kw: dict, code: str) -> None:
    r = _plan(repo, **kw)
    if code == "ok":
        assert r["ok"] is True
    else:
        assert r["ok"] is False and r["code"] == code, r
        assert all(ord(c) >= 32 for c in r["reason"])


def test_symbolic_ref(repo: Path) -> None:
    _git(repo, "symbolic-ref", "refs/heads/feature/sym", "refs/heads/feature/x")
    assert _plan(repo, source="feature/sym")["code"] == "bad_source"


def test_already_merged(repo: Path) -> None:
    _git(repo, "merge", "-q", "--no-ff", "-m", "m", "feature/x")
    assert _plan(repo)["code"] == "already_merged"


def test_no_change(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/same", "develop~1")
    _commit(repo, "c.txt", "dev\n", "other message")
    _git(repo, "checkout", "-q", "develop")
    r = _plan(repo, source="feature/same")
    assert r["code"] == "no_change", r


def test_conflict(repo: Path) -> None:
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, "a.txt", "1\nX\n3\n")
    _git(repo, "checkout", "-q", "develop")
    _commit(repo, "a.txt", "1\nY\n3\n")
    r = _plan(repo)
    assert r["code"] == "conflict" and r["files"] == ["a.txt"], r


def test_dirty_worktree(repo: Path) -> None:
    _write(repo, "untracked.txt", "u\n")
    assert _plan(repo)["code"] == "dirty_target_worktree"
    (repo / "untracked.txt").unlink()
    _write(repo, "a.txt", "changed\n")
    assert _plan(repo)["code"] == "dirty_target_worktree"
    _git(repo, "add", "a.txt")
    assert _plan(repo)["code"] == "dirty_target_worktree"


def test_operation_in_progress(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD").strip()
    (repo / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")
    assert _plan(repo)["code"] == "operation_in_progress"
    assert _plan(repo, checkTargetWorktree=True)["code"] == "operation_in_progress"


def test_skip_target_worktree_check(repo: Path) -> None:
    """checkTargetWorktree=false (要求側) は、統合先の worktree の状態を調べない。see docs/change/0055"""
    _write(repo, "untracked.txt", "u\n")
    _write(repo, "a.txt", "changed\n")
    assert _plan(repo)["code"] == "dirty_target_worktree"
    assert _plan(repo, checkTargetWorktree=False)["ok"] is True
    head = _git(repo, "rev-parse", "HEAD").strip()
    (repo / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")
    assert _plan(repo)["code"] == "operation_in_progress"
    assert _plan(repo, checkTargetWorktree=False)["ok"] is True
    # ほかの検査は残る
    assert _plan(repo, checkTargetWorktree=False, source="feature/nope")["ok"] is False


@pytest.mark.skipif(sys.platform == "win32", reason="改行入りのファイル名")
def test_unsafe_path(repo: Path) -> None:
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, "bad\nname.txt", "x\n")
    _git(repo, "checkout", "-q", "develop")
    assert _plan(repo)["code"] == "unsafe_path"


def test_symlink_is_risk(repo: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("symlink")
    _git(repo, "checkout", "-q", "feature/x")
    (repo / "lnk").symlink_to("a.txt")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "l")
    _git(repo, "checkout", "-q", "develop")
    r = _plan(repo)
    assert {"path": "lnk", "reason": "シンボリックリンクの変更"} in r["risks"]


@pytest.mark.skipif(sys.platform == "win32", reason="sh")
def test_external_merge_driver_not_run(repo: Path, tmp_path: Path) -> None:
    mark = tmp_path / "MARK"
    _git(repo, "config", "merge.evil.driver", f"sh -c 'touch {mark} %O'")
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, ".gitattributes", "* merge=evil\n")
    _commit(repo, "a.txt", "1\nX\n3\n")
    _git(repo, "checkout", "-q", "develop")
    _commit(repo, "a.txt", "1\nY\n3\n")
    r = _plan(repo)
    assert r["code"] == "external_driver", r
    assert not mark.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="sh")
@pytest.mark.parametrize("kind", ["clean", "smudge", "process"])
@pytest.mark.parametrize("renormalize", [False, True])
def test_external_filter_not_run(repo: Path, tmp_path: Path, kind: str, renormalize: bool) -> None:
    mark = tmp_path / "MARK"
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, ".gitattributes", "* filter=probe\n")
    _commit(repo, "a.txt", "1\n2\n3x\n")
    _git(repo, "checkout", "-q", "develop")
    _commit(repo, "a.txt", "1x\n2\n3\n")
    _git(repo, "config", f"filter.probe.{kind}", f"sh -c 'echo ran >> {mark}; cat'")
    if renormalize:
        _git(repo, "config", "merge.renormalize", "true")
    mark.unlink(missing_ok=True)
    r = _plan(repo)
    assert r["ok"] is False and r["code"] == "external_filter", r
    assert not mark.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="sh")
def test_hooks_and_textconv_not_run(repo: Path, tmp_path: Path) -> None:
    mark = tmp_path / "MARK"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("reference-transaction", "post-merge", "pre-commit"):
        h = hooks / name
        h.write_text(f"#!/bin/sh\ntouch {mark}\n", encoding="utf-8")
        h.chmod(h.stat().st_mode | stat.S_IXUSR)
    _git(repo, "config", "core.hooksPath", str(hooks))
    _git(repo, "config", "diff.evil.textconv", f"sh -c 'touch {mark}; cat' --")
    _git(repo, "checkout", "-q", "feature/x")
    _commit(repo, ".gitattributes", "*.txt diff=evil\n")
    _git(repo, "checkout", "-q", "develop")
    mark.unlink(missing_ok=True)
    r = _plan(repo)
    assert r["ok"] is True, r
    assert not mark.exists()
