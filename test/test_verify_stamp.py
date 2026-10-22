"""scripts/verify_stamp.py (コミット前の検証の印) の試験。使い捨ての git リポジトリで確かめる。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_stamp.py"

_spec = importlib.util.spec_from_file_location("verify_stamp", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
stamp = importlib.util.module_from_spec(_spec)
sys.modules["verify_stamp"] = stamp
_spec.loader.exec_module(stamp)


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.com",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.com",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_git_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return proc.stdout


@pytest.fixture(autouse=True)
def _no_git_env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("ignored.log\n")
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "b.txt").write_text("one\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def always_full(_paths) -> bool:
    return True


def run_check(repo: Path, capsys, needs_full=always_full) -> tuple[int, str]:
    capsys.readouterr()
    code = stamp.check(repo, needs_full)
    return code, capsys.readouterr().err


def test_matching_stamp_is_silent(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    stamp.write_stamp(repo)
    git(repo, "add", "a.txt")
    code, err = run_check(repo, capsys)
    assert code == 0
    assert err == ""


def test_edit_after_stamp_warns_but_returns_zero(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    stamp.write_stamp(repo)
    (repo / "a.txt").write_text("three\n")
    git(repo, "add", "a.txt")
    code, err = run_check(repo, capsys)
    assert code == 0
    assert "警告" in err
    assert "a.txt" in err


def test_no_stamp_warns(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    code, err = run_check(repo, capsys)
    assert code == 0
    assert "印がありません" in err


def test_nothing_staged_is_silent(repo, capsys):
    code, err = run_check(repo, capsys)
    assert code == 0
    assert err == ""


def test_partial_commit_matches_on_staged_paths_only(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    (repo / "b.txt").write_text("two\n")
    stamp.write_stamp(repo)
    git(repo, "add", "a.txt")
    code, err = run_check(repo, capsys)
    assert code == 0
    assert err == ""


def test_staged_deletion_is_ignored(repo, capsys):
    git(repo, "rm", "-q", "b.txt")
    assert stamp.staged(repo) == {}
    code, err = run_check(repo, capsys)
    assert code == 0
    assert err == ""


def test_mode_change_mismatches(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    stamp.write_stamp(repo)
    (repo / "a.txt").chmod(0o755)
    git(repo, "add", "a.txt")
    assert stamp.staged(repo)["a.txt"][0] == "100755"
    code, err = run_check(repo, capsys)
    assert code == 0
    assert "a.txt" in err


def test_snapshot_includes_untracked_and_skips_ignored(repo):
    (repo / "new.txt").write_text("new\n")
    (repo / "ignored.log").write_text("x\n")
    entries = stamp.snapshot(repo)
    assert "new.txt" in entries
    assert "ignored.log" not in entries
    assert entries["a.txt"][0] == "100644"


def test_snapshot_before_first_commit(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("x\n")
    assert "f.txt" in stamp.snapshot(tmp_path)
    assert stamp.write_stamp(tmp_path).is_file()
    data = json.loads(stamp.write_stamp(tmp_path).read_text())
    assert data["head"] is None
    assert data["version"] == 1


def test_write_stamp_leaves_index_and_refs_alone(repo):
    (repo / "a.txt").write_text("two\n")
    (repo / "new.txt").write_text("new\n")
    (repo / "b.txt").write_text("staged\n")
    git(repo, "add", "b.txt")

    def state() -> tuple[str, str]:
        return git(repo, "status", "--porcelain"), git(repo, "for-each-ref")

    before = state()
    dest = stamp.write_stamp(repo)
    assert state() == before
    assert not (repo / ".git" / "verify-stamp.index").exists()
    assert dest == repo / ".git" / "verify-stamp.json"
    assert dest.stat().st_mode & 0o777 == 0o600
    data = json.loads(dest.read_text())
    assert data["head"] == git(repo, "rev-parse", "HEAD").strip()
    assert data["entries"]["new.txt"][0] == "100644"


def test_warning_appends_one_log_line(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    run_check(repo, capsys)
    log = (repo / ".git" / "verify-stamp.log").read_text().splitlines()
    assert len(log) == 1
    rec = json.loads(log[0])
    assert rec["result"] == "no-stamp"
    assert rec["count"] == 1
    run_check(repo, capsys)
    assert len((repo / ".git" / "verify-stamp.log").read_text().splitlines()) == 2


def test_many_paths_are_abbreviated(repo, capsys):
    stamp.write_stamp(repo)
    for i in range(7):
        (repo / f"f{i}.txt").write_text("x\n")
    git(repo, "add", "-A")
    code, err = run_check(repo, capsys)
    assert code == 0
    assert "ほか 2 件" in err
    assert err.count("\n") == 1


def test_broken_stamp_still_returns_zero(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    (repo / ".git" / "verify-stamp.json").write_text("{not json")
    code, err = run_check(repo, capsys)
    assert code == 0
    assert "印がありません" in err


def test_selective_change_does_not_warn_via_plan(repo, capsys):
    (repo / "docs" / "spec").mkdir(parents=True)
    (repo / "docs" / "spec" / "x.md").write_text("doc\n")
    git(repo, "add", "docs")
    capsys.readouterr()
    code = stamp.check(repo)
    assert code == 0
    assert capsys.readouterr().err == ""


def test_unknown_path_warns_via_plan(repo, capsys):
    (repo / "a.txt").write_text("two\n")
    git(repo, "add", "a.txt")
    capsys.readouterr()
    code = stamp.check(repo)
    assert code == 0
    assert "警告" in capsys.readouterr().err
