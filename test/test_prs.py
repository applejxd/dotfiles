"""scripts/prs.py: develop へのマージ待ちの一覧（枝名・先行コミット数・件名だけ）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prs.py"
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


def _commit(repo: Path, name: str, msg: str, when: int) -> None:
    (repo / name).write_text(msg, encoding="utf-8")
    _git(repo, "add", "-A")
    env_date = f"@{when + 1_700_000_000} +0000"
    subprocess.run(
        ["git", "commit", "-q", "-m", msg],
        cwd=repo,
        check=True,
        env={**os.environ, **ENV, "GIT_AUTHOR_DATE": env_date, "GIT_COMMITTER_DATE": env_date},
    )


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV, "GIT_CEILING_DIRECTORIES": str(repo.parent)},
        check=False,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "develop")
    _commit(r, "base.txt", "base", 1_000)
    return r


def test_empty_when_nothing_waits(repo: Path) -> None:
    p = _run(repo)
    assert p.returncode == 0 and p.stdout.strip() == "マージ待ちはありません"


def test_lists_ahead_branches_newest_first_with_count_and_subject(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/a", "develop")
    _commit(repo, "a.txt", "a の件名", 2_000)
    _git(repo, "checkout", "-q", "develop")
    _git(repo, "checkout", "-q", "-b", "bugfix/b", "develop")
    _commit(repo, "b1.txt", "b1", 3_000)
    _commit(repo, "b2.txt", "b の件名", 4_000)
    _git(repo, "checkout", "-q", "develop")
    lines = _run(repo).stdout.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("bugfix/b") and "2 コミット" in lines[0] and "b の件名" in lines[0]
    assert lines[1].startswith("feature/a") and "1 コミット" in lines[1] and "a の件名" in lines[1]


def test_integrated_branches_are_not_listed(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/done", "develop")
    _commit(repo, "d.txt", "d", 2_000)
    _git(repo, "checkout", "-q", "develop")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "feature/done")
    assert _run(repo).stdout.strip() == "マージ待ちはありません"


def test_branch_contained_in_another_is_hidden_unless_all(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/a", "develop")
    _commit(repo, "a.txt", "a", 2_000)
    _git(repo, "checkout", "-q", "-b", "feature/bundle-1")
    _commit(repo, "c.txt", "c", 3_000)
    _git(repo, "checkout", "-q", "develop")
    out = _run(repo).stdout
    assert "feature/bundle-1" in out and "feature/a " not in out and "1 件を隠した" in out
    full = _run(repo, "--all").stdout
    assert "feature/bundle-1" in full and "feature/a " in full and "隠した" not in full


def test_branches_at_the_same_commit_are_both_listed(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "feature/a", "develop")
    _commit(repo, "a.txt", "a", 2_000)
    _git(repo, "branch", "feature/a2")
    _git(repo, "checkout", "-q", "develop")
    out = _run(repo).stdout
    assert "feature/a " in out and "feature/a2" in out


def test_non_repo_fails_with_exit_2(tmp_path: Path) -> None:
    p = _run(tmp_path)
    assert p.returncode == 2 and "prs.py:" in p.stderr
