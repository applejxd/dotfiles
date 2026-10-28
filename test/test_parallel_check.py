"""scripts/parallel_check.py: 並列実装の混線の検査 (本体の変更・宣言した範囲の外・複数 worktree の重複)。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "parallel_check.py"
ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(cwd: Path, *args: str) -> str:
    import os

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


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "develop")
    (root / ".gitignore").write_text(".tmp/\n", encoding="utf-8")
    (root / "base.txt").write_text("b\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _feature(root: Path, name: str) -> Path:
    wt = root / ".tmp" / "worktrees" / name
    _git(root, "worktree", "add", "-q", "-b", f"feature/{name}", str(wt), "develop")
    return wt


def _run(root: Path, *args: str):
    import os

    r = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    return r.returncode, json.loads(r.stdout)


def test_clean_state_is_ok(repo):
    a = _feature(repo, "a")
    (a / "a.txt").write_text("a\n", encoding="utf-8")
    code, out = _run(repo, "--owned", "a=a.txt")
    assert code == 0 and out["ok"], out
    assert out["worktrees"]["a"] == ["a.txt"]


def test_a_change_in_the_main_tree_is_reported(repo):
    _feature(repo, "a")
    (repo / "base.txt").write_text("changed\n", encoding="utf-8")
    code, out = _run(repo)
    assert code == 1 and any("本体の作業ツリー" in p for p in out["problems"]), out


def test_ignored_files_in_the_main_tree_are_not_changes(repo):
    _feature(repo, "a")
    (repo / ".tmp" / "scratch.txt").write_text("s\n", encoding="utf-8")
    code, out = _run(repo)
    assert code == 0, out


def test_a_change_outside_the_declared_paths_is_reported(repo):
    a = _feature(repo, "a")
    (a / "docs").mkdir()
    (a / "docs" / "x.md").write_text("x\n", encoding="utf-8")
    (a / "other.txt").write_text("o\n", encoding="utf-8")
    code, out = _run(repo, "--owned", "a=docs/**")
    assert code == 1, out
    assert any("other.txt" in p and "範囲の外" in p for p in out["problems"]), out
    assert not any("docs/x.md" in p for p in out["problems"]), out


def test_committed_changes_count_too(repo):
    a = _feature(repo, "a")
    (a / "c.txt").write_text("c\n", encoding="utf-8")
    _git(a, "add", "-A")
    _git(a, "commit", "-q", "-m", "wip")
    code, out = _run(repo, "--owned", "a=docs/**")
    assert code == 1 and "c.txt" in out["worktrees"]["a"], out


def test_two_worktrees_changing_the_same_file_are_reported(repo):
    a, b = _feature(repo, "a"), _feature(repo, "b")
    (a / "base.txt").write_text("from a\n", encoding="utf-8")
    (b / "base.txt").write_text("from b\n", encoding="utf-8")
    code, out = _run(repo)
    assert code == 1 and any("base.txt" in p and "複数" in p for p in out["problems"]), out


def test_an_undeclared_worktree_is_only_listed(repo):
    a = _feature(repo, "a")
    (a / "anything.txt").write_text("x\n", encoding="utf-8")
    code, out = _run(repo)
    assert code == 0 and out["worktrees"]["a"] == ["anything.txt"], out


def test_an_owned_name_without_a_worktree_is_reported(repo):
    code, out = _run(repo, "--owned", "ghost=a.txt")
    assert code == 1 and any("ghost" in p for p in out["problems"]), out


def test_owned_needs_a_name_and_a_glob(repo):
    import os

    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--owned", "oops"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    assert r.returncode != 0


def test_a_committed_rename_out_of_the_declared_paths_is_reported(repo):
    """範囲外のファイルを範囲内へ移したとき、旧パスの削除も範囲外の変更として数える。"""
    a = _feature(repo, "a")
    (a / "docs").mkdir()
    _git(a, "mv", "base.txt", "docs/base.txt")
    _git(a, "commit", "-q", "-m", "move")
    code, out = _run(repo, "--owned", "a=docs/**")
    assert code == 1, out
    assert "base.txt" in out["worktrees"]["a"] and "docs/base.txt" in out["worktrees"]["a"], out
    assert any("base.txt" in p and "範囲の外" in p for p in out["problems"]), out


def test_an_uncommitted_rename_counts_both_paths(repo):
    a = _feature(repo, "a")
    (a / "docs").mkdir()
    _git(a, "mv", "base.txt", "docs/base.txt")
    code, out = _run(repo, "--owned", "a=docs/**")
    assert code == 1 and "base.txt" in out["worktrees"]["a"], out


@pytest.mark.parametrize("bad", ["docs/**/x.md", "**/x.md", "/abs/path", "../up/x", "a=b/**c"])
def test_unsupported_globs_are_rejected(repo, bad):
    import os

    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--owned", f"a={bad}"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    assert r.returncode != 0, (bad, r.stdout)


def test_the_check_does_not_change_the_index_or_the_worktrees(repo):
    a = _feature(repo, "a")
    (a / "n.txt").write_text("n\n", encoding="utf-8")
    before = (_git(a, "status", "--porcelain"), _git(repo, "status", "--porcelain"))
    _run(repo, "--owned", "a=n.txt")
    assert (_git(a, "status", "--porcelain"), _git(repo, "status", "--porcelain")) == before
