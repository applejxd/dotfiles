"""盤面の収集部品 (``home/dot_config/pi/harness/board-collect.ts``) の試験。使い捨ての実 git リポジトリで確かめる。

``test/agents/pi/board_collect_driver.mjs`` が ``collectBoardInput`` を動かして JSON を出す (型除去に対応した node が要る)。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "board_collect_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(cwd, *args, stdin=None):
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=ENV,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


def commit(cwd, name, msg):
    Path(cwd, name).write_text(msg + "\n", encoding="utf-8")
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)


def drive(**arg):
    proc = subprocess.run(
        [_node(), str(RUNNER), json.dumps(arg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def collect(cwd, **kw):
    return drive(op="collect", cwd=str(cwd), now=int(time.time() * 1000), **kw)


@pytest.fixture
def repo(tmp_path):
    """develop + feature/a (2 commit 先行) + feature/b (未コミットの変更あり)。そのあと develop が 1 進む (a も b も behind 1)"""
    main = tmp_path / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "develop")
    commit(main, "base.txt", "base")
    wa, wb = tmp_path / "wt-a", tmp_path / "wt-b"
    git(main, "worktree", "add", "-q", "-b", "feature/a", str(wa))
    git(main, "worktree", "add", "-q", "-b", "feature/b", str(wb))
    commit(wa, "a1.txt", "a1")
    commit(wa, "a2.txt", "a2")
    commit(main, "dev1.txt", "dev1")
    Path(wb, "base.txt").write_text("changed\n", encoding="utf-8")
    return main


def state_of(res, branch):
    for w in res["input"]["worktrees"]:
        if w.get("branch") == branch:
            return res["input"]["worktreeStates"].get(w["path"])
    raise AssertionError(f"{branch} の worktree が無い")


def save_pending(main, source="feature/a"):
    rec = {
        "action": "git_integrate",
        "params": {"source": source},
        "premise": {},
        "reason": "request",
        "request": {"id": "r", "sessionId": "s", "cwd": str(main)},
        "createdAt": "2026-01-01T00:00:00.000Z",
    }
    r = drive(op="save", cwd=str(main), input=rec)
    assert r["ok"] is True, r
    return r["id"]


def test_ahead_behind_and_dirty_match_the_real_repo(repo):
    res = collect(repo)
    assert res["threw"] is False
    a, b = state_of(res, "feature/a"), state_of(res, "feature/b")
    assert (a["ahead"], a["behind"], a["dirty"]) == (2, 1, False)
    assert (b["ahead"], b["behind"], b["dirty"]) == (0, 1, True)
    assert 0 <= a["lastCommitAgeMs"] < 120_000
    text = "\n".join(res["lines"])
    assert "feature a ↑2 ↓1" in text and "feature b ↑0 ↓1 dirty" in text
    assert max(len(ln) for ln in res["lines"]) <= 44
    # 主の worktree は飾るだけ (状態を調べない)
    assert res["input"]["worktrees"][0]["branch"] == "develop"
    assert res["input"]["worktrees"][0]["path"] not in res["input"]["worktreeStates"]


def test_pending_op_is_listed_and_marks_the_feature(repo):
    save_pending(repo, "feature/a")
    res = collect(repo)
    ops = res["input"]["pending"]["ops"]
    assert len(ops) == 1 and ops[0]["state"] == "pending" and ops[0]["action"] == "git_integrate"
    assert ops[0]["source"] == "feature/a" and ops[0]["ageMs"] >= 0
    assert state_of(res, "feature/a")["hasPending"] is True
    assert "hasPending" not in state_of(res, "feature/b")
    text = "\n".join(res["lines"])
    assert "承認待ち" in text and "git_integrate feature/a" in text and "保留あり" in text
    assert res["input"]["pending"]["legacyCount"] == 0 and res["input"]["pending"]["broken"] == 0


def test_max_features_limits_the_inspected_worktrees(repo):
    res = collect(repo, maxFeatures=1)
    assert len(res["input"]["worktreeStates"]) == 1
    assert len(res["input"]["worktrees"]) == 3  # 一覧は全部、状態だけ絞る


def test_missing_target_drops_only_ahead_behind(repo):
    res = collect(repo, target="no-such-branch")
    assert res["threw"] is False
    b = state_of(res, "feature/b")
    assert "ahead" not in b and "behind" not in b
    assert b["dirty"] is True and "lastCommitAgeMs" in b  # 行は落とさず、取れた項目は残す
    assert any("feature b" in ln for ln in res["lines"])


def test_not_a_repo_does_not_throw(tmp_path):
    res = collect(tmp_path / "nowhere-nonexistent")
    assert res["threw"] is False and res["input"]["worktrees"] == []
    plain = tmp_path / "plain"
    plain.mkdir()
    res = collect(plain)
    assert res["threw"] is False and res["input"]["pending"]["ops"] == []


def test_broken_pending_ref_does_not_throw(repo):
    oid = git(repo, "hash-object", "-w", "--stdin", stdin="x").strip()
    git(repo, "update-ref", "refs/pi/pending/100000000000001", oid)
    res = collect(repo)
    assert res["threw"] is False
    p = res["input"]["pending"]
    assert p["ops"] == [] and p["legacyCount"] + p["broken"] >= 1  # 数えるだけで、行には出さない


def snapshot(main):
    out = [git(main, "for-each-ref")]
    for ln in git(main, "worktree", "list", "--porcelain").splitlines():
        if ln.startswith("worktree "):
            path = ln.split(" ", 1)[1]
            out.append(ln + "\n" + git(path, "status", "--porcelain"))
    return out


def test_collect_is_read_only(repo):
    save_pending(repo, "feature/a")
    before = snapshot(repo)
    collect(repo)
    collect(repo, target="no-such-branch")
    assert snapshot(repo) == before


def test_collect_does_not_run_hooks(repo, tmp_path):
    marker = tmp_path / "hook-ran"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in (
        "pre-commit",
        "post-checkout",
        "post-index-change",
        "reference-transaction",
        "post-commit",
        "pre-push",
    ):
        h = hooks / name
        h.write_text(f"#!/bin/sh\necho {name} >> '{marker}'\n", encoding="utf-8")
        h.chmod(0o755)
    fsm = tmp_path / "fsmonitor.sh"
    fsm.write_text(f"#!/bin/sh\necho fsmonitor >> '{marker}'\n", encoding="utf-8")
    fsm.chmod(0o755)
    git(repo, "config", "core.hooksPath", str(hooks))
    git(repo, "config", "core.fsmonitor", str(fsm))
    save_pending(repo, "feature/a")
    marker.unlink(missing_ok=True)  # 保存の側で動いたものは数えない。数えるのは収集だけ
    res = collect(repo)
    assert res["threw"] is False and state_of(res, "feature/b")["dirty"] is True
    assert not marker.exists(), marker.read_text(encoding="utf-8")


def test_external_filter_config_does_not_run_the_filter(repo):
    """外部 filter (clean) の設定があるとき、status を実行しない (filter が利用者の権限で起動しないこと)。ほかの項目は出す"""
    marker = repo.parent / "filter-ran"
    git(repo, "config", "filter.x.clean", f"touch {marker} && cat")
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.txt filter=x\n", encoding="utf-8")
    # 内容は同じで mtime だけ変える。git は内容を比べるために clean filter を起動する (設定が無ければ marker が出来る)
    wa = next(
        Path(w["path"])
        for w in collect(repo)["input"]["worktrees"]
        if w.get("branch") == "feature/a"
    )
    marker.unlink(missing_ok=True)
    os.utime(wa / "a1.txt", (1_000_000_000, 1_000_000_000))
    res = collect(repo)
    assert not marker.exists(), "外部 filter が起動した"
    st = state_of(res, "feature/a")
    assert "dirty" not in st, st  # 調べていない (false と言い切らない)
    assert st["ahead"] == 2 and st["behind"] == 1, st  # status 以外の項目は出す
