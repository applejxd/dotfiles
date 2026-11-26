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
    dest = repo / "home" / "dot_agents" / "skills" / "demo"
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


def _add_readme_skill(src, frontmatter):
    skill = src / "skills" / "readme-writer"
    skill.mkdir()
    (skill / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    _git(src, "add", "--", "skills/readme-writer")
    _git(src, "commit", "-qm", "readme")
    return skill


FRONT = '---\nname: readme-writer\ndescription: "説明: README"\nlicense: MIT\n'


@pytest.mark.parametrize("setting", ["", "disable-model-invocation: false\n", "disable-model-invocation: true\n"])
def test_only_distribution_uses_manual_invocation(labs, setting):
    src, repo, _, _ = labs
    upstream = FRONT + setting + "---\n\n# 本文\n"
    skill = _add_readme_skill(src, upstream)
    dest = repo / "home/dot_agents/skills/readme-writer"
    assert mod.sync("readme-writer", src, repo, check=True) == 1
    assert not dest.exists()
    assert mod.sync("readme-writer", src, repo) == 0
    expected = FRONT + "disable-model-invocation: true\n---\n\n# 本文\n"
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == expected
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == upstream
    assert mod.sync("readme-writer", src, repo, check=True) == 0


@pytest.mark.parametrize(
    "frontmatter",
    [
        "name: readme-writer\n",
        FRONT + "description: duplicate\n---\n",
        FRONT + "disable-model-invocation: yes\n---\n",
        FRONT + "disable-model-invocation: true\ndisable-model-invocation: false\n---\n",
        FRONT.replace('"説明: README"', '"閉じていない') + "---\n",
        FRONT.replace('"説明: README"', "null") + "---\n",
        FRONT.replace('"説明: README"', '" "') + "---\n",
        FRONT.replace('"説明: README"', '"' + "説" * 1025 + '"') + "---\n",
    ],
)
def test_invalid_frontmatter_does_not_replace_destination(labs, frontmatter):
    src, repo, _, _ = labs
    _add_readme_skill(src, frontmatter)
    dest = repo / "home/dot_agents/skills/readme-writer"
    dest.mkdir()
    marker = dest / "SKILL.md"
    marker.write_text("old\n", encoding="utf-8")
    for check in (True, False):
        with pytest.raises(mod.SyncError, match="frontmatter が不正"):
            mod.sync("readme-writer", src, repo, check=check)
        assert marker.read_text(encoding="utf-8") == "old\n"


def test_pinned_commit_keeps_reviewed_version_if_head_advances(labs):
    src, repo, dest, doc = labs
    origin = subprocess.check_output(
        ["git", "-C", str(src), "rev-parse", "HEAD"], encoding="utf-8"
    ).strip()
    assert mod.sync("demo", src, repo, check=True, commit=origin) == 1
    (src / "skills/demo/SKILL.md").write_text("変更後\n", encoding="utf-8")
    _git(src, "add", "--", "skills/demo/SKILL.md")
    _git(src, "commit", "-qm", "next")
    assert mod.sync("demo", src, repo, commit=origin) == 0
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "v1\n"
    assert origin[:7] in doc.read_text(encoding="utf-8")
    assert mod.sync("demo", src, repo, check=True, commit=origin) == 0
    assert mod.sync("demo", src, repo, check=True) == 1


@pytest.mark.parametrize("ref", ["HEAD", "HEAD~1", "abc1234"])
def test_only_complete_commit_ids_can_be_pinned(labs, ref):
    src, repo, dest, _ = labs
    with pytest.raises(mod.SyncError, match="完全なハッシュ"):
        mod.sync("demo", src, repo, commit=ref)
    assert (dest / "OLD.md").is_file()
