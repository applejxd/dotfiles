"""scripts/bundle.py: 統合用の枝 (bundle) の試験。使い捨ての git リポジトリで動かす。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bundle.py"
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


def _bundle(cwd: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV, **env},
        check=False,
    )


def _commit_file(repo: Path, branch: str, path: str, text: str) -> None:
    _git(repo, "checkout", "-q", branch)
    (repo / path).write_text(text, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", f"{branch}: {path}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    (r / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(r, "add", "shared.txt")
    _git(r, "commit", "-q", "-m", "init")
    for name in ("a", "b", "c"):
        _git(r, "branch", f"feature/{name}", "develop")
    _commit_file(r, "feature/a", "a.txt", "a\n")
    _commit_file(r, "feature/b", "b.txt", "b\n")
    _commit_file(r, "feature/c", "c.txt", "c\n")
    _git(r, "checkout", "-q", "develop")
    return r


def _conflicting(repo: Path) -> None:
    _commit_file(repo, "feature/a", "shared.txt", "from a\n")
    _commit_file(repo, "feature/b", "shared.txt", "from b\n")
    _git(repo, "checkout", "-q", "develop")


def test_start_merges_all_without_conflict(repo: Path) -> None:
    r = _bundle(repo, "start", "a", "feature/b", "c")
    assert r.returncode == 0, r.stderr
    wt = repo / ".tmp" / "worktrees" / "bundle-1"
    for f in ("a.txt", "b.txt", "c.txt"):
        assert (wt / f).is_file()
    assert _git(wt, "branch", "--show-current").strip() == "feature/bundle-1"
    st = _bundle(wt, "status")
    assert st.stdout.count("取り込み済み") == 3
    sm = _bundle(wt, "summary")
    assert "feature/a: 1 コミット" in sm.stdout
    assert "変更ファイル数: 3" in sm.stdout


def test_conflict_stops_with_exit_3_then_continue(repo: Path) -> None:
    _conflicting(repo)
    r = _bundle(repo, "start", "a", "b", "c")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "shared.txt" in r.stdout
    wt = repo / ".tmp" / "worktrees" / "bundle-1"
    assert not (wt / "c.txt").exists()
    assert "衝突中" in _bundle(wt, "status").stdout
    # 解消前は continue を拒否 (マーカーあり・未解決)
    assert _bundle(wt, "continue").returncode == 2
    # 解消するが add していない
    (wt / "shared.txt").write_text("resolved\n", encoding="utf-8")
    r2 = _bundle(wt, "continue")
    assert r2.returncode == 2
    _git(wt, "add", "-A")
    r3 = _bundle(wt, "continue")
    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert (wt / "c.txt").is_file()
    assert (wt / "shared.txt").read_text(encoding="utf-8") == "resolved\n"


def test_continue_rejects_leftover_markers(repo: Path) -> None:
    _conflicting(repo)
    assert _bundle(repo, "start", "a", "b").returncode == 3
    wt = repo / ".tmp" / "worktrees" / "bundle-1"
    _git(wt, "add", "-A")  # マーカーのまま add
    r = _bundle(wt, "continue")
    assert r.returncode == 2
    assert "マーカー" in r.stderr


def test_rejects_already_integrated_branch(repo: Path) -> None:
    _git(repo, "merge", "-q", "--no-edit", "feature/a")
    r = _bundle(repo, "start", "a", "b")
    assert r.returncode == 2
    assert "統合済み" in r.stderr
    assert not (repo / ".tmp" / "worktrees" / "bundle-1").exists()


def test_rejects_missing_branch(repo: Path) -> None:
    r = _bundle(repo, "start", "a", "nope")
    assert r.returncode == 2
    assert "存在しません" in r.stderr


def test_picks_free_number(repo: Path) -> None:
    _git(repo, "branch", "feature/bundle-1", "develop")
    r = _bundle(repo, "start", "a")
    assert r.returncode == 0, r.stderr
    assert (repo / ".tmp" / "worktrees" / "bundle-2").is_dir()


def test_old_train_branch_is_not_mistaken_for_bundle(repo: Path) -> None:
    # 旧称の枝 feature/train-N は bundle の枝として扱わない (番号も取らない)
    _git(repo, "branch", "feature/train-1", "develop")
    r = _bundle(repo, "start", "a")
    assert r.returncode == 0, r.stderr
    assert (repo / ".tmp" / "worktrees" / "bundle-1").is_dir()
    wt = repo / ".tmp" / "worktrees" / "bundle-1"
    assert _git(wt, "branch", "--show-current").strip() == "feature/bundle-1"


def test_verify_summary_parse(repo: Path) -> None:
    assert _bundle(repo, "start", "a").returncode == 0
    fake = f"{sys.executable} -c \"print('3 passed, 1 failed in 0.1s'); raise SystemExit(1)\""
    r = _bundle(repo, "verify", "--name", "bundle-1", BUNDLE_VERIFY_CMD=fake)
    assert r.returncode == 1
    assert "passed 3" in r.stdout and "failed 1" in r.stdout
    ok = f"{sys.executable} -c \"print('7 passed')\""
    r = _bundle(repo, "verify", "--name", "bundle-1", BUNDLE_VERIFY_CMD=ok)
    assert r.returncode == 0
    assert "passed 7" in r.stdout


def test_live_lock_of_other_owner_stops(repo: Path) -> None:
    wt = repo / ".tmp" / "worktrees" / "a"
    _git(repo, "worktree", "add", str(wt), "feature/a")
    _git(
        repo, "worktree", "lock", "--reason", f"owner=pi id=x pid={os.getpid()} started=1", str(wt)
    )
    r = _bundle(repo, "start", "a")
    assert r.returncode == 2
    assert "使用中" in r.stderr
    # 死んだ pid の lock は無視する
    _git(repo, "worktree", "unlock", str(wt))
    _git(repo, "worktree", "lock", "--reason", "owner=pi id=x pid=999999999 started=1", str(wt))
    assert _bundle(repo, "start", "a").returncode == 0
