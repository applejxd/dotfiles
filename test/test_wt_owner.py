"""scripts/wt_owner.py: worktree の所有を git worktree lock の理由欄で表明する。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wt_owner.py"
ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _reason(repo: Path, wt: Path) -> str | None:
    """worktree の lock の理由（lock なしは None）。"""
    cur = None
    for line in _git(repo, "worktree", "list", "--porcelain", "-z").split("\0"):
        if line.startswith("worktree "):
            cur = Path(line[9:]).resolve()
        elif cur == wt.resolve() and (line == "locked" or line.startswith("locked ")):
            return line[6:].strip()
    return None


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    (r / "a.txt").write_text("a\n", encoding="utf-8")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-q", "-m", "init")
    _git(r, "worktree", "add", "-q", "-b", "feature/x", str(r / ".tmp" / "worktrees" / "x"))
    _git(r, "worktree", "add", "-q", "-b", "feature/y", str(r / ".tmp" / "worktrees" / "y"))
    return r


def _wt(repo: Path, name: str = "x") -> Path:
    return repo / ".tmp" / "worktrees" / name


def test_claim_writes_one_line_reason_and_release_removes_it(repo):
    wt = _wt(repo)
    r = _run(repo, "claim", "x", "--kind", "worker", "--id", "w1", "--pid", str(os.getpid()))
    assert r.returncode == 0, r.stderr
    reason = _reason(repo, wt)
    assert reason is not None
    assert reason.startswith(f"owner=worker id=w1 pid={os.getpid()} started=")
    assert "\n" not in reason
    assert _run(repo, "release", "x", "--id", "w1").returncode == 0
    assert _reason(repo, wt) is None


def test_claim_by_absolute_path_and_idempotent_for_same_id(repo):
    wt = _wt(repo)
    args = ["claim", str(wt), "--kind", "worker", "--id", "w1", "--pid", str(os.getpid())]
    assert _run(repo, *args).returncode == 0
    first = _reason(repo, wt)
    time.sleep(1.1)
    assert _run(repo, *args).returncode == 0
    assert _reason(repo, wt) == first  # 付け直さない


def test_claim_is_refused_while_another_live_owner_holds_it(repo):
    wt = _wt(repo)
    pid = str(os.getpid())
    assert _run(repo, "claim", "x", "--kind", "job", "--id", "j1", "--pid", pid).returncode == 0
    r = _run(repo, "claim", "x", "--kind", "worker", "--id", "w1", "--pid", pid)
    assert r.returncode == 3
    assert "id=j1" in r.stderr  # 所有者を表示する
    assert "id=j1" in (_reason(repo, wt) or "")


def test_claim_takes_over_a_stale_lock_of_a_dead_pid(repo):
    wt = _wt(repo)
    dead = str(_dead_pid())
    assert _run(repo, "claim", "x", "--kind", "job", "--id", "j1", "--pid", dead).returncode == 0
    r = _run(repo, "claim", "x", "--kind", "worker", "--id", "w1", "--pid", str(os.getpid()))
    assert r.returncode == 0, r.stderr
    assert "id=w1" in (_reason(repo, wt) or "")


def test_human_lock_is_never_overwritten_or_released(repo):
    wt = _wt(repo)
    _git(repo, "worktree", "lock", "--reason", "手で守っています", str(wt))
    assert _run(repo, "claim", "x", "--kind", "worker", "--id", "w1").returncode == 3
    assert _run(repo, "release", "x").returncode == 3
    assert _run(repo, "release", "x", "--id", "w1").returncode == 3
    assert _run(repo, "reap").returncode == 0
    assert _reason(repo, wt) == "手で守っています"
    assert "不明" in _run(repo, "status", "x").stdout


def test_lock_without_reason_is_unknown_not_stale(repo):
    wt = _wt(repo)
    _git(repo, "worktree", "lock", str(wt))
    assert _run(repo, "claim", "x", "--kind", "worker", "--id", "w1").returncode == 3
    assert _run(repo, "reap").returncode == 0
    assert _reason(repo, wt) == ""


def test_release_with_different_id_is_refused(repo):
    wt = _wt(repo)
    assert (
        _run(
            repo, "claim", "x", "--kind", "worker", "--id", "w1", "--pid", str(os.getpid())
        ).returncode
        == 0
    )
    r = _run(repo, "release", "x", "--id", "other")
    assert r.returncode == 3
    assert "id=w1" in (_reason(repo, wt) or "")
    assert _run(repo, "release", "x").returncode == 0  # id を指定しなければ解除できる


def test_status_shows_kind_id_pid_alive_and_age(repo):
    pid = str(os.getpid())
    _run(repo, "claim", "x", "--kind", "job", "--id", "j1", "--pid", pid)
    _run(repo, "claim", "y", "--kind", "worker", "--id", "w2", "--pid", str(_dead_pid()))
    out = _run(repo, "status").stdout
    assert "kind=job id=j1" in out and f"pid={pid} 生存" in out and "経過=" in out
    assert "kind=worker id=w2" in out and "残骸" in out
    assert (
        "lock なし" in _run(repo, "status", "x").stdout
        or "kind=job" in _run(repo, "status", "x").stdout
    )


def test_reap_removes_only_stale_locks(repo):
    _run(repo, "claim", "x", "--kind", "job", "--id", "j1", "--pid", str(os.getpid()))
    _run(repo, "claim", "y", "--kind", "worker", "--id", "w2", "--pid", str(_dead_pid()))
    r = _run(repo, "reap")
    assert r.returncode == 0
    assert _reason(repo, _wt(repo, "y")) is None
    assert "id=j1" in (_reason(repo, _wt(repo, "x")) or "")


def test_bad_inputs_are_exit_2(repo):
    assert _run(repo, "claim", "nosuch", "--kind", "worker", "--id", "w").returncode == 2
    assert _run(repo, "claim", "x", "--kind", "worker", "--id", "a b").returncode == 2
    assert _run(repo, "claim", "x", "--kind", "bogus", "--id", "w").returncode == 2


def test_claim_without_pid_uses_a_non_shell_ancestor_not_the_short_lived_shell(repo):
    r = _run(repo, "claim", "x", "--kind", "worker", "--id", "w1")
    assert r.returncode == 0, r.stderr
    # 呼び出した python（このプロセス）か、その祖先。claim 直後の解析プロセスは終わっていても生きている主体が選ばれる
    reason = _reason(repo, _wt(repo)) or ""
    pid = int(reason.split("pid=")[1].split()[0])
    assert (
        pid in {os.getpid(), os.getppid()}
        or Path(f"/proc/{pid}").exists()
        or sys.platform == "win32"
    )
