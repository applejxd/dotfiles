"""統合の実行器 (harness/integrate-exec.ts) の試験。使い捨ての実 git リポジトリで確かめる。

品質ゲート (hook・署名) を迂回しないこと、失敗時に元へ戻すこと、precheck が何も変えないことを見る。
see docs/change/0055
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import subprocess
import sys
import time
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


def _bg_hook(repo: Path, tmp_path: Path) -> Path:
    """背景の子孫を起動し、0.2 秒ごとにマーカーへ書く hook。マーカーのパスを返す"""
    marker = tmp_path / "marker.txt"
    pidf = tmp_path / "bg.pid"
    _hook(
        repo,
        tmp_path,
        f"(while true; do echo x >> '{marker}'; sleep 0.2; done) &\necho $! > '{pidf}'\nwait",
    )
    return marker


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _lines(p: Path) -> int:
    return len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0


@pytest.mark.parametrize("how", ["abort", "timeout"])
def test_stop_kills_hook_descendants(repo: Path, tmp_path: Path, how: str) -> None:
    plan = _plan(repo)
    marker = _bg_hook(repo, tmp_path)
    before = _snapshot(repo)
    kw = {"abortAfterMs": 1500} if how == "abort" else {"commitTimeoutMs": 1500}
    res = _exec(plan, repo, **kw)
    n = _lines(marker)
    assert n > 0, "hook の子孫が動いていない"
    time.sleep(1.0)
    assert _lines(marker) == n, "結果の確定後も子孫が書き続けている"
    pid = int((tmp_path / "bg.pid").read_text(encoding="utf-8").strip())
    assert not _alive(pid)
    if how == "abort":
        _unchanged(repo, before, res)
    else:
        _unchanged(repo, before, res, "failed_confirmed")


def test_unconfirmed_stop_does_not_roll_back(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "sleep 30")
    head = _git(repo, "rev-parse", "HEAD")
    res = _exec(plan, repo, abortAfterMs=1500, stopUnconfirmed=True)
    assert res["outcome"] == "unknown", res
    assert any("停止を確認できない" in e for e in res["evidence"]), res
    # rollback されない: HEAD は元のまま、index・作業ツリーは squash の変更が残る
    assert _git(repo, "rev-parse", "HEAD") == head
    assert (repo / "b.txt").exists()
    assert "b.txt" in _git(repo, "status", "--porcelain")


def test_confirmed_abort_rolls_back(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "sleep 30")
    before = _snapshot(repo)
    res = _exec(plan, repo, abortAfterMs=1500)
    _unchanged(repo, before, res)
    assert not (repo / "b.txt").exists()
    assert _git(repo, "status", "--porcelain") == ""


def _bg_exit0_hook(repo: Path, tmp_path: Path) -> Path:
    """背景の子孫を出力を切り離して起動し、exit 0 で終わる hook。マーカーのパスを返す"""
    marker = tmp_path / "marker.txt"
    _hook(
        repo,
        tmp_path,
        f"(while true; do echo x >> '{marker}'; sleep 0.2; done) >/dev/null 2>&1 &\n"
        f"echo $! > '{tmp_path / 'bg.pid'}'\nexit 0",
    )
    return marker


def test_normal_exit_with_background_descendant_is_stopped(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    marker = _bg_exit0_hook(repo, tmp_path)
    res = _exec(plan, repo)
    assert res["outcome"] == "success", res
    n = _lines(marker)
    assert n > 0, "hook の子孫が動いていない"
    time.sleep(1.0)
    assert _lines(marker) == n, "戻った後も子孫が書き続けている"
    assert not _alive(int((tmp_path / "bg.pid").read_text(encoding="utf-8").strip()))


def test_unconfirmed_stop_after_successful_commit_is_unknown(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "exit 0")
    res = _exec(plan, repo, "branch", unconfirmedFrom=2)
    assert res["outcome"] == "unknown" and res["phase"] == "commit", res
    assert any("停止を確認できない" in e for e in res["evidence"]), res
    assert _git(repo, "branch", "--list", "feature/x").strip() != "", "cleanup に進んだ"


def test_unconfirmed_stop_in_merge_is_unknown(repo: Path) -> None:
    plan = _plan(repo)
    head = _git(repo, "rev-parse", "HEAD")
    res = _exec(plan, repo, unconfirmedFrom=1)
    assert res["outcome"] == "unknown" and res["phase"] == "merge", res
    assert _git(repo, "rev-parse", "HEAD") == head
    assert (repo / "b.txt").exists(), "rollback された"


def _kill_group_of(pidfile: Path) -> None:
    if not pidfile.exists():
        return
    pid = int(pidfile.read_text(encoding="utf-8").strip())
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(pid), 9)


def test_returns_unknown_in_bounded_time_when_signals_do_nothing(
    repo: Path, tmp_path: Path
) -> None:
    plan = _plan(repo)
    pidf = tmp_path / "hook.pid"
    _hook(repo, tmp_path, f"echo $$ > '{pidf}'\nsleep 30")
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            [_node() or "node", str(EXEC_DRIVER)],
            input=json.dumps(
                {
                    "plan": plan,
                    "cleanup": "none",
                    "approverCwd": str(repo),
                    "abortAfterMs": 1500,
                    "noSignal": True,
                    "graceMs": 300,
                    "killMs": 300,
                }
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        res = json.loads(r.stdout)
    finally:
        _kill_group_of(pidf)
    assert time.monotonic() - t0 < 15
    assert res["outcome"] == "unknown", res
    assert any("停止を確認できない" in e for e in res["evidence"]), res


def test_sigterm_ignoring_hook_is_killed(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    pidf = tmp_path / "hook.pid"
    _hook(repo, tmp_path, f"trap '' TERM\necho $$ > '{pidf}'\nwhile true; do sleep 1; done")
    before = _snapshot(repo)
    try:
        res = _exec(plan, repo, abortAfterMs=1500, graceMs=500)
        _unchanged(repo, before, res)
        assert not _alive(int(pidf.read_text(encoding="utf-8").strip()))
    finally:
        _kill_group_of(pidf)


def _ref_hook(repo: Path, tmp_path: Path) -> Path:
    """feature/x の ref 更新のときだけ、背景の書き込みを起動して待つ reference-transaction hook"""
    d = tmp_path / "hooks"
    d.mkdir(exist_ok=True)
    marker = tmp_path / "ref-marker.txt"
    h = d / "reference-transaction"
    h.write_text(
        "#!/bin/sh\n"
        "if cat | grep -q 'refs/heads/feature/x'; then\n"
        f"  (while true; do echo x >> '{marker}'; sleep 0.2; done) >/dev/null 2>&1 &\n"
        f"  echo $! > '{tmp_path / 'ref.pid'}'\n"
        "  sleep 30\nfi\n",
        encoding="utf-8",
    )
    h.chmod(h.stat().st_mode | stat.S_IEXEC)
    _git(repo, "config", "core.hooksPath", str(d))
    return marker


def test_cleanup_ref_hook_descendants_are_stopped(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    marker = _ref_hook(repo, tmp_path)
    try:
        res = _exec(plan, repo, "branch", abortAfterMs=4000)
        n = _lines(marker)
        assert n > 0, "cleanup の hook が動いていない"
        time.sleep(1.0)
        assert _lines(marker) == n, "戻った後も子孫が書き続けている"
        assert not _alive(int((tmp_path / "ref.pid").read_text(encoding="utf-8").strip()))
        assert _git(repo, "branch", "--list", "feature/x").strip() != "", res
    finally:
        _kill_group_of(tmp_path / "ref.pid")


def test_cleanup_unconfirmed_stop_is_unknown(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _ref_hook(repo, tmp_path)
    try:
        res = _exec(plan, repo, "branch", abortAfterMs=4000, unconfirmedFrom=3)
        assert res["outcome"] == "unknown" and res["phase"] == "cleanup", res
        assert any("停止を確認できない" in e for e in res["evidence"]), res
    finally:
        _kill_group_of(tmp_path / "ref.pid")


# --- termination (停止の観測から直接決まる) と facts (承認の結果に載せる事実) ---

COMMON_FACTS = ("source_ref", "source_oid", "target_ref", "target_oid_before")


def _outcome(plan: dict, approver: Path, cleanup: str = "none", **kw) -> dict:
    res = _exec(plan, approver, cleanup, outcome=True, **kw)
    assert res["valid"] is True, res  # validateResultBody を通る
    return res


def _check_common_facts(plan: dict, body: dict) -> dict:
    f = body["facts"]
    assert f["source_ref"] == plan["source"]["ref"] and f["source_oid"] == plan["source"]["oid"]
    assert f["target_ref"] == plan["target"]["ref"]
    assert f["target_oid_before"] == plan["target"]["oid"]
    assert len(f["source_oid"]) in (40, 64) and len(f["target_oid_before"]) in (40, 64)
    return f


def test_termination_stopped_on_success_and_facts(repo: Path) -> None:
    plan = _plan(repo)
    res = _outcome(plan, repo)
    assert res["body"]["outcome"] == "success" and res["termination"] == "stopped", res
    f = _check_common_facts(plan, res["body"])
    assert f["result_commit"] == _git(repo, "rev-parse", "HEAD").strip()
    assert f["result_tree"] == _git(repo, "rev-parse", "HEAD^{tree}").strip()


def test_legacy_api_returns_plain_body(repo: Path) -> None:
    res = _exec(_plan(repo), repo)
    assert res["outcome"] == "success" and "termination" not in res and "body" not in res, res


def test_termination_stopped_on_hook_failure_no_result_commit(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "exit 1")
    res = _outcome(plan, repo)
    assert res["body"]["outcome"] == "failed_confirmed" and res["termination"] == "stopped", res
    f = _check_common_facts(plan, res["body"])
    assert "result_commit" not in f and "result_tree" not in f


def test_termination_stopped_on_refusal_and_facts(repo: Path) -> None:
    plan = _plan(repo)
    (repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    res = _outcome(plan, repo)
    assert res["body"]["outcome"] == "not_executed" and res["termination"] == "stopped", res
    f = _check_common_facts(plan, res["body"])
    assert "result_commit" not in f


def test_termination_stopped_on_confirmed_abort_rolls_back(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "sleep 30")
    before = _snapshot(repo)
    res = _outcome(plan, repo, abortAfterMs=1500)
    assert res["termination"] == "stopped", res
    _unchanged(repo, before, res["body"])
    assert "result_commit" not in res["body"]["facts"]


def test_termination_unconfirmed_in_merge(repo: Path) -> None:
    plan = _plan(repo)
    head = _git(repo, "rev-parse", "HEAD")
    res = _outcome(plan, repo, unconfirmedFrom=1)
    assert res["body"]["outcome"] == "unknown" and res["termination"] == "unconfirmed", res
    assert _git(repo, "rev-parse", "HEAD") == head and (repo / "b.txt").exists(), "rollback された"
    _check_common_facts(plan, res["body"])


def test_termination_unconfirmed_in_commit(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "sleep 30")
    head = _git(repo, "rev-parse", "HEAD")
    res = _outcome(plan, repo, abortAfterMs=1500, unconfirmedFrom=2)
    assert res["body"]["outcome"] == "unknown" and res["termination"] == "unconfirmed", res
    assert _git(repo, "rev-parse", "HEAD") == head and (repo / "b.txt").exists(), "rollback された"
    assert "result_commit" not in res["body"]["facts"]


def test_termination_unconfirmed_in_rollback(repo: Path, tmp_path: Path) -> None:
    plan = _plan(repo)
    _hook(repo, tmp_path, "exit 1")
    res = _outcome(
        plan, repo, unconfirmedFrom=3
    )  # merge・commit は確認でき、rollback の reset だけ確認できない
    assert res["body"]["outcome"] == "unknown" and res["termination"] == "unconfirmed", res
    assert any("停止を確認できない" in e for e in res["body"]["evidence"]), res


def test_termination_unconfirmed_in_cleanup_keeps_result_facts(repo: Path) -> None:
    plan = _plan(repo)
    res = _outcome(
        plan, repo, "branch", unconfirmedFrom=3
    )  # 統合は成立し、update-ref の停止だけ確認できない
    assert res["body"]["outcome"] == "unknown" and res["termination"] == "unconfirmed", res
    f = _check_common_facts(plan, res["body"])
    assert f["result_commit"] == _git(repo, "rev-parse", "HEAD").strip()
    assert f["result_tree"] == _git(repo, "rev-parse", "HEAD^{tree}").strip()


def test_termination_is_unconfirmed_on_an_unexpected_exception(repo: Path) -> None:
    """想定外の例外では、git・hook の停止を保証できない (fail-closed。承認側は running とロックを残す)"""
    plan = _plan(repo)
    broken = {**plan, "message": 5}  # 文字列でない → commit の準備で例外になる
    res = _outcome(broken, repo)
    assert res["body"]["outcome"] == "unknown", res
    assert any("例外" in e for e in res["body"]["evidence"]), res
    assert res["termination"] == "unconfirmed", res


# --- 実行途中の差し替え・外部 filter への備え ---


def test_cleanup_does_not_delete_symref_target(repo: Path, tmp_path: Path) -> None:
    """実行中に source ref が別ブランチへの symbolic ref に差し替わっても、参照先を削除しない"""
    plan = _plan(repo)
    oid = _git(repo, "rev-parse", "feature/x").strip()
    _git(repo, "branch", "other", oid)
    _hook(repo, tmp_path, "git symbolic-ref refs/heads/feature/x refs/heads/other")
    res = _exec(plan, repo, "branch")
    assert _git(repo, "rev-parse", "refs/heads/other").strip() == oid, res


def test_detached_head_during_commit_is_not_success(repo: Path, tmp_path: Path) -> None:
    """統合先 ref が結果コミットを指さないなら success にせず、source も消さない"""
    plan = _plan(repo)
    develop = _git(repo, "rev-parse", "develop").strip()
    _hook(repo, tmp_path, 'git update-ref --no-deref HEAD "$(git rev-parse HEAD)"')
    res = _exec(plan, repo, "branch")
    assert res["outcome"] == "unknown" and res["phase"] == "verify", res
    assert any("統合先 ref" in e for e in res["evidence"]), res
    assert any("手動で確認" in r for r in res["remainingCleanup"]), res
    assert _git(repo, "rev-parse", "develop").strip() == develop
    assert _git(repo, "branch", "--list", "feature/x").strip() != ""


def test_a_missing_target_ref_after_commit_is_not_success(repo: Path, tmp_path: Path) -> None:
    """HEAD が detach され、統合先 ref も読めない (消えた) ときも success にせず、source も消さない (読み取り失敗を見逃さない)"""
    plan = _plan(repo)
    _hook(
        repo,
        tmp_path,
        'git update-ref --no-deref HEAD "$(git rev-parse HEAD)" && git update-ref -d refs/heads/develop',
    )
    res = _exec(plan, repo, "branch")
    assert res["outcome"] == "unknown" and res["phase"] == "verify", res
    assert any("統合先を読めなかった" in e for e in res["evidence"]), res
    assert _git(repo, "branch", "--list", "feature/x").strip() != ""


def test_precheck_external_filter(repo: Path, tmp_path: Path) -> None:
    _commit(repo, ".gitattributes", "* filter=probe\n")
    plan = _plan(repo)
    marker = tmp_path / "filter-ran"
    _git(repo, "config", "filter.probe.clean", f"sh -c 'touch {marker}; cat'")
    head = _git(repo, "rev-parse", "HEAD")  # status は filter を起動するので使わない
    res = _exec(plan, repo)
    assert res["outcome"] == "not_executed" and res["phase"] == "precheck", res
    assert not marker.exists(), "外部 filter が実行された"
    assert _git(repo, "rev-parse", "HEAD") == head
