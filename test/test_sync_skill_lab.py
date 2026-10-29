"""scripts/sync_skill_lab.py の試験 (一時の git リポジトリだけを使う)。"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_skill_lab.py"
spec = importlib.util.spec_from_file_location("sync_skill_lab", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )


@pytest.fixture
def labs(tmp_path):
    src = tmp_path / "lab"
    (src / "skills" / "demo" / "scripts").mkdir(parents=True)
    (src / "skills" / "demo" / "SKILL.md").write_text("v1\n", encoding="utf-8")
    (src / "skills" / "demo" / "scripts" / "run.sh").write_text("echo 1\n", encoding="utf-8")
    (src / "skills" / "demo" / "scripts" / "run.sh").chmod(0o755)
    _git(src, "init", "-q", "-b", "main")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "init")
    repo = tmp_path / "repo"
    dest = repo / "home" / "dot_claude" / "skills" / "demo"
    dest.mkdir(parents=True)
    (dest / "OLD.md").write_text("stale\n", encoding="utf-8")
    (dest / ".venv").mkdir()
    (dest / ".venv" / "keep").write_text("x", encoding="utf-8")
    doc = repo / "docs" / "spec" / "demo.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "- 版: skill-lab のコミット `0000000`（2020-01-01）の追跡ファイル（9 件。`git archive` で）。\n",
        encoding="utf-8",
    )
    return src, repo, dest, doc


def test_check_reports_the_difference_without_touching(labs, capsys):
    src, repo, dest, _doc = labs
    assert mod.sync("demo", src, repo, check=True) == 1
    out = capsys.readouterr().out
    assert "+ SKILL.md" in out and "- OLD.md" in out
    assert (dest / "OLD.md").exists()


def test_sync_replaces_the_copy_keeps_runtime_dirs_and_updates_the_doc(labs):
    src, repo, dest, doc = labs
    assert mod.sync("demo", src, repo) == 0
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "v1\n"
    assert not (dest / "OLD.md").exists()
    assert (dest / ".venv" / "keep").exists()
    assert (dest / "scripts" / "run.sh").stat().st_mode & 0o111
    text = doc.read_text(encoding="utf-8")
    assert "`0000000`" not in text and "（2 件。`git archive`" in text
    assert mod.sync("demo", src, repo, check=True) == 0


def test_uncommitted_changes_in_skill_lab_are_refused(labs):
    src, repo, dest, _doc = labs
    (src / "skills" / "demo" / "SKILL.md").write_text("wip\n", encoding="utf-8")
    with pytest.raises(mod.SyncError, match="未コミット"):
        mod.sync("demo", src, repo)
    assert (dest / "OLD.md").exists()


@pytest.mark.parametrize("name", ["../x", "A", "a/b", ""])
def test_a_bad_name_is_refused(labs, name):
    src, repo, _dest, _doc = labs
    with pytest.raises(mod.SyncError):
        mod.sync(name, src, repo)


def test_a_missing_skill_is_refused(labs):
    src, repo, _dest, _doc = labs
    with pytest.raises(mod.SyncError, match="無い"):
        mod.sync("nope", src, repo)
