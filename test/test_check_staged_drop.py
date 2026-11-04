"""scripts/check_staged_drop.py: ステージ済みの既存ファイルが空になっていないかの検査。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_staged_drop.py"
BODY = "".join(f"行{i}\n" for i in range(30))


def _env(tmp: Path) -> dict[str, str]:
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CEILING_DIRECTORIES": str(tmp),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }


class Repo:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.path = tmp / "repo"
        self.path.mkdir()
        self.git("init", "-q", "-b", "develop")

    def git(self, *args: str) -> str:
        r = subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_env(self.tmp),
            check=False,
        )
        assert r.returncode == 0, (args, r.stderr)
        return r.stdout

    def write(self, name: str, content: str | bytes) -> None:
        p = self.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")

    def commit(self) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")

    def stage(self) -> None:
        self.git("add", "-A")

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_env(self.tmp),
            check=False,
        )


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    r = Repo(tmp_path)
    r.write("big.txt", BODY)
    r.write("small.txt", "a\n" * 19)
    r.write("other.txt", BODY)
    r.write("bin.dat", b"\0" + b"x\n" * 30)
    r.commit()
    return r


def test_emptied_big_file_fails(repo: Repo) -> None:
    repo.write("big.txt", "")
    repo.stage()
    r = repo.check()
    assert r.returncode == 1
    assert "big.txt" in r.stdout
    assert "30 行" in r.stdout


def test_whitespace_only_fails(repo: Repo) -> None:
    repo.write("big.txt", "  \n\n\t\n")
    repo.stage()
    r = repo.check()
    assert r.returncode == 1
    assert "big.txt" in r.stdout


def test_small_file_emptied_passes(repo: Repo) -> None:
    repo.write("small.txt", "")
    repo.stage()
    assert repo.check().returncode == 0


def test_deleted_passes(repo: Repo) -> None:
    (repo.path / "big.txt").unlink()
    repo.stage()
    assert repo.check().returncode == 0


def test_rewritten_passes(repo: Repo) -> None:
    repo.write("big.txt", BODY + "追記\n")
    repo.stage()
    r = repo.check()
    assert r.returncode == 0
    assert r.stdout == ""


def test_new_empty_file_passes(repo: Repo) -> None:
    repo.write("new.txt", "")
    repo.stage()
    assert repo.check().returncode == 0


def test_binary_emptied_passes(repo: Repo) -> None:
    repo.write("bin.dat", b"")
    repo.stage()
    assert repo.check().returncode == 0


def test_rename_passes(repo: Repo) -> None:
    repo.git("mv", "big.txt", "moved.txt")
    repo.stage()
    assert repo.check().returncode == 0


def test_rename_then_empty_passes(repo: Repo) -> None:
    # リネームは対象外（--no-renames で D + A になるため M ではない）
    repo.git("mv", "big.txt", "moved.txt")
    repo.write("moved.txt", "")
    repo.stage()
    assert repo.check().returncode == 0


def test_no_head_passes(tmp_path: Path) -> None:
    r = Repo(tmp_path)
    r.write("a.txt", "")
    r.stage()
    assert r.check().returncode == 0


def test_large_shrink_warns_only(repo: Repo) -> None:
    repo.write("big.txt", "残り\n")
    repo.stage()
    r = repo.check()
    assert r.returncode == 0
    assert "大きく減りました" in r.stdout
    assert "big.txt 30 → 1 行" in r.stdout


def test_only_emptied_listed(repo: Repo) -> None:
    repo.write("big.txt", "")
    repo.write("other.txt", BODY + "x\n")
    repo.write("small.txt", "")
    repo.stage()
    r = repo.check()
    assert r.returncode == 1
    assert "big.txt" in r.stdout
    assert "other.txt" not in r.stdout
    assert "small.txt" not in r.stdout


def test_unicode_and_space_path(repo: Repo) -> None:
    repo.write("docs/日本語 の ファイル.md", BODY)
    repo.commit()
    repo.write("docs/日本語 の ファイル.md", "")
    repo.stage()
    r = repo.check()
    assert r.returncode == 1
    assert "docs/日本語 の ファイル.md" in r.stdout
