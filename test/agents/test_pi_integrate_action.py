"""git_integrate のアダプタ (harness/integrate-action.ts) の試験。使い捨ての実 git リポジトリで確かめる。

要求側 (capture)・承認側 (plan / recheck / execute)・二重承認・linked worktree で要求して本体で承認する流れを見る。
see docs/change/0055
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_integrate_exec import _hook
from test_pi_integrate_plan import PROTECTED, RISK, _commit, _git
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "integrate_action_driver.mjs"
CFG = {"target": "develop", "protectedRefs": PROTECTED, "riskPaths": RISK}
MSG = "feat: x\n\nbody line"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="hook をシェルスクリプトで作る")


def _run(payload: dict, timeout: int = 120) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps({"cfg": CFG, **payload}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=timeout,
    )
    return json.loads(out.stdout)


def _values(**kw: str) -> dict:
    return {"source": "feature/x", "message": MSG, **kw}


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
    _commit(r, "scripts/run.sh", "echo\n")
    _git(r, "checkout", "-q", "develop")
    _commit(r, "c.txt", "dev\n")
    return r


@pytest.fixture
def feat(repo: Path, tmp_path: Path) -> Path:
    p = tmp_path / "feat"
    _git(repo, "worktree", "add", "-q", str(p), "feature/x")
    return p


def _rev(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref).strip()


def test_spec_and_capture_premise(repo: Path) -> None:
    res = _run({"op": "capture", "cwd": str(repo), "values": _values(cleanup="branch")})
    spec = res["spec"]
    assert spec["id"] == "git_integrate" and spec["argv"] == []
    assert (
        spec["fields"]["cleanup"]["optional"] is True and "optional" not in spec["fields"]["source"]
    )
    cap = res["capture"]
    assert cap["ok"] is True, cap
    p = cap["premise"]
    assert p["kind"] == "git_integrate" and p["cleanup"] == "branch"
    assert p["source"] == "refs/heads/feature/x" and p["target"] == "refs/heads/develop"
    assert p["sourceOid"] == _rev(repo, "feature/x") and p["targetOid"] == _rev(repo, "develop")
    assert p["mergeBase"] == _git(repo, "merge-base", "develop", "feature/x").strip()
    assert len(p["resultTree"]) >= 40 and len(p["messageDigest"]) == 64
    assert cap["worktree"] == str(repo)


def test_capture_refusals(repo: Path) -> None:
    def cap(cwd: Path = repo, **kw: str) -> dict:
        return _run({"op": "capture", "cwd": str(cwd), "values": _values(**kw)})["capture"]

    bad = cap(cleanup="rm_rf")
    assert bad["ok"] is False and "cleanup" in bad["reason"]
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")
    dirty = cap()
    assert dirty["ok"] is False and "dirty_target_worktree" in dirty["reason"]
    _git(repo, "checkout", "--", "a.txt")
    _git(repo, "checkout", "-q", "-b", "feature/y", "develop")
    assert "already_merged" in cap(source="feature/y")["reason"]
    _git(repo, "checkout", "-q", "develop")
    _git(repo, "checkout", "-q", "-b", "feature/c1", "develop~1")
    _commit(repo, "c.txt", "conflict\n")
    _git(repo, "checkout", "-q", "develop")
    c = cap(source="feature/c1")
    assert c["ok"] is False and "conflict" in c["reason"] and "c.txt" in c["reason"]


def test_plan_summary_and_changes(repo: Path) -> None:
    res = _run(
        {"op": "flow", "requestCwd": str(repo), "approverCwd": str(repo), "values": _values()}
    )
    assert res["capture"]["ok"] is True
    lines = res["plan"]["summary"].split("\n")
    assert all(sum(2 if ord(ch) > 0x2E80 else 1 for ch in ln) <= 46 for ln in lines), lines
    text = res["plan"]["summary"]
    assert "feature/x → develop (squash)" in text and "衝突: なし" in text
    assert "scripts/run.sh" in text and "要求時から変わった点" not in text
    assert (
        "feat: x" in res["plan"]["view"]
        and "body line" in res["plan"]["view"]
        and "b.txt" in res["plan"]["view"]
    )
    assert res["recheck"] == {"ok": True}


def test_target_advanced_after_request(repo: Path) -> None:
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "beforePlan": [["commit", "-q", "--allow-empty", "-m", "advance1"]],
            "beforeRecheck": [["commit", "-q", "--allow-empty", "-m", "advance2"]],
        }
    )
    summary = res["plan"]["summary"]
    assert "要求時から変わった点" in summary and "統合先が進んだ" in summary
    assert res["recheck"]["ok"] is False and "統合先が進んだ" in res["recheck"]["reason"]


def test_execute_integrates(repo: Path) -> None:
    old = _rev(repo, "develop")
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "execute": True,
        }
    )
    assert res["exec"]["outcome"] == "success", res["exec"]
    assert _rev(repo, "develop~1") == old
    assert _git(repo, "log", "-1", "--format=%B").strip() == MSG
    assert _git(repo, "status", "--porcelain") == ""


def test_hook_changes_commit(repo: Path, tmp_path: Path) -> None:
    _hook(repo, tmp_path, "echo x > extra.txt\ngit add extra.txt")
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(repo),
            "approverCwd": str(repo),
            "values": _values(),
            "execute": True,
        }
    )
    assert res["exec"]["outcome"] == "success", res["exec"]
    assert any("hook が内容を変えた" in e for e in res["exec"]["evidence"]), res["exec"]


def test_double_approval_runs_once(repo: Path) -> None:
    before = _rev(repo, "develop")
    res = _run({"op": "double", "cwd": str(repo), "values": _values(), "before": before})
    assert res["commits"] == 1, res
    assert len(res["sent"]) == 1 and res["sent"][0]["outcome"] == "success", res
    assert sorted(r["level"] for r in res["replies"]) == ["info", "warning"], res
    assert _git(repo, "status", "--porcelain") == ""


def test_request_in_linked_worktree_approve_in_main(repo: Path, feat: Path) -> None:
    res = _run(
        {
            "op": "flow",
            "requestCwd": str(feat),
            "approverCwd": str(repo),
            "values": _values(cleanup="branch_and_worktree"),
            "execute": True,
        }
    )
    assert res["capture"]["ok"] is True and res["capture"]["worktree"] == str(repo), res["capture"]
    assert res["exec"]["outcome"] == "success", res["exec"]
    assert not feat.exists()
    assert _git(repo, "branch", "--list", "feature/x").strip() == ""
    assert (repo / "b.txt").exists()
