"""scripts/wt_clean.py: 統合済みの worktree の掃除（ビューアの cleanup と同じ規則）。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wt_clean.py"
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
        [sys.executable, str(SCRIPT), *args, "--repo", str(repo)],
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


class World:
    def __init__(self, tmp: Path) -> None:
        self.repo = tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "develop")
        (self.repo / ".gitignore").write_text("__pycache__/\n*.ign\n.tmp/\n")
        (self.repo / "a.txt").write_text("a\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.wts = self.repo / ".tmp" / "worktrees"

    def feature(self, name: str, merged: bool = True) -> Path:
        wt = self.wts / name
        _git(self.repo, "worktree", "add", "-q", "-b", f"feature/{name}", str(wt))
        (wt / f"{name}.txt").write_text("x\n")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-q", "-m", name)
        if merged:
            _git(self.repo, "merge", "-q", "--no-ff", "-m", "m", f"feature/{name}")
        return wt

    def branches(self) -> list[str]:
        return _git(
            self.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/feature/"
        ).split()

    def backups(self) -> list[Path]:
        return sorted((self.repo / ".git" / "pi-cleanup-backups").glob("*.tgz"))


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def test_merged_with_ignored_files_is_removed_with_backup(w):
    wt = w.feature("a")
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "x.pyc").write_text("pyc\n")
    (wt / "local.ign").write_text("ign\n")
    r = _run(w.repo, "a")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "削除した" in r.stdout
    assert not wt.exists() and w.branches() == []
    assert len(w.backups()) == 1 and w.backups()[0].name.startswith("a-")


def test_unmerged_changes_nothing(w):
    wt = w.feature("a", merged=False)
    (wt / "local.ign").write_text("ign\n")
    r = _run(w.repo, "a")
    assert r.returncode == 3 and "未統合" in r.stdout
    assert wt.exists() and w.branches() == ["feature/a"] and (wt / "local.ign").exists()


def test_tracked_change_is_kept(w):
    wt = w.feature("a")
    (wt / "a.txt").write_text("変更\n")
    r = _run(w.repo, "a")
    assert r.returncode == 3 and "拒否" in r.stdout
    assert wt.exists() and (wt / "a.txt").read_text() == "変更\n"


def test_untracked_file_is_kept(w):
    wt = w.feature("a")
    (wt / "new.txt").write_text("未追跡\n")
    r = _run(w.repo, "a")
    assert r.returncode == 3 and wt.exists() and (wt / "new.txt").exists()
    assert w.branches() == ["feature/a"]


def test_alive_owner_lock_is_kept(w):
    wt = w.feature("a")
    reason = f"owner=worker id=w1 pid={os.getpid()} started={int(time.time())}"
    _git(w.repo, "worktree", "lock", "--reason", reason, str(wt))
    r = _run(w.repo, "a")
    assert r.returncode == 3 and "有効な owner" in r.stdout
    assert wt.exists() and w.branches() == ["feature/a"]


def test_stale_owner_lock_is_not_released_and_worktree_is_kept(w):
    # 意図して変更: 旧い挙動（残骸を自動で unlock して掃除する）を、「解除せず残して reap を案内する」へ
    wt = w.feature("a")
    reason = f"owner=worker id=w1 pid={_dead_pid()} started={int(time.time())}"
    _git(w.repo, "worktree", "lock", "--reason", reason, str(wt))
    (wt / "local.ign").write_text("ign\n")
    r = _run(w.repo, "a")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "残骸の lock" in r.stdout and "wt_owner.py reap" in r.stdout
    assert wt.exists() and (wt / "local.ign").exists() and w.branches() == ["feature/a"]
    assert _git(w.repo, "worktree", "list", "--porcelain").count("locked") == 1


def test_stale_owner_lock_can_be_cleaned_after_reap(w):
    wt = w.feature("a")
    reason = f"owner=worker id=w1 pid={_dead_pid()} started={int(time.time())}"
    _git(w.repo, "worktree", "lock", "--reason", reason, str(wt))
    assert _run(w.repo, "a").returncode == 3
    reap = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "wt_owner.py"), "reap"],
        cwd=w.repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    assert reap.returncode == 0, reap.stdout + reap.stderr
    r = _run(w.repo, "a")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not wt.exists() and w.branches() == []


def test_human_lock_is_kept(w):
    wt = w.feature("a")
    _git(w.repo, "worktree", "lock", "--reason", "手で保護", str(wt))
    r = _run(w.repo, "a")
    assert r.returncode == 3 and "人が付けた lock" in r.stdout
    assert wt.exists() and w.branches() == ["feature/a"]


def test_backup_over_limit_keeps_worktree(w, monkeypatch):
    wt = w.feature("a")
    (wt / "big.ign").write_text("x" * 100)
    sys.path.insert(0, str(ROOT / "home/dot_claude/skills/feature-orchestration/scripts"))
    try:
        import wt_clean
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(wt_clean, "BACKUP_LIMIT", 10)
    res = wt_clean.clean_one(w.repo, "a", "develop", False)
    assert res.kind == "残した" and "上限" in res.detail
    assert wt.exists() and (wt / "big.ign").exists() and w.branches() == ["feature/a"]
    assert w.backups() == []


def test_dry_run_changes_nothing(w):
    wt = w.feature("a")
    (wt / "local.ign").write_text("ign\n")
    r = _run(w.repo, "a", "--dry-run")
    assert r.returncode == 0 and "dry-run" in r.stdout
    assert wt.exists() and (wt / "local.ign").exists() and w.branches() == ["feature/a"]
    assert w.backups() == []


def test_old_backups_are_pruned_to_five(w):
    dest = w.repo / ".git" / "pi-cleanup-backups"
    dest.mkdir()
    for i in range(7):
        p = dest / f"old{i}-20200101-00000{i}.tgz"
        p.write_bytes(b"")
        os.utime(p, (1000 + i, 1000 + i))
    wt = w.feature("a")
    (wt / "local.ign").write_text("ign\n")
    assert _run(w.repo, "a").returncode == 0
    assert len(w.backups()) == 5


def test_usage_error_exit_code(w, tmp_path):
    assert _run(w.repo).returncode == 2
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "a", "--repo", str(tmp_path / "nowhere")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert r.returncode == 2
