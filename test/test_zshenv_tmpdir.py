"""`home/dot_zshenv` の、リポジトリ内で TMPDIR を `<repo>/.tmp` へ向ける関数の試験 (CHG-0042)。

pi のセッションの置き場 (`<repo>/.tmp/s/<ID>`) を TMPDIR にして起動された子の zsh が、
その値を `<repo>/.tmp` に戻してしまわないことを固定する。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZSHENV = ROOT / "home" / "dot_zshenv"

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh が無い")


def _function_source() -> str:
    text = ZSHENV.read_text(encoding="utf-8")
    start = text.index("function _tmpdir_repo_local_update()")
    end = text.index("\n_tmpdir_repo_local_update\n", start)
    return text[start:end]


def _run(cwd: Path, tmpdir: str, orig: str = "/orig-tmp") -> str:
    script = (
        f"{_function_source()}\n"
        f"export TMPDIR={tmpdir!r}\n"
        f"export _TMPDIR_REPO_LOCAL_ORIG={orig!r}\n"
        "_tmpdir_repo_local_update\nprint -r -- $TMPDIR"
    )
    proc = subprocess.run(
        ["zsh", "-f", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".git").mkdir(parents=True)
    (r / ".tmp").mkdir()
    return r.resolve()


def test_inside_a_repo_tmpdir_points_to_the_repo_tmp(repo: Path) -> None:
    assert _run(repo, "/tmp") == str(repo / ".tmp")


def test_a_pi_session_directory_is_kept(repo: Path) -> None:
    session = repo / ".tmp" / "s" / "deadbeef"
    session.mkdir(parents=True)
    assert _run(repo, str(session)) == str(session)
    # サブディレクトリで起動された子でも、同じリポジトリなら維持する
    sub = repo / "src"
    sub.mkdir()
    assert _run(sub, str(session)) == str(session)


def test_another_repos_session_directory_is_not_kept(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other" / ".tmp" / "s" / "deadbeef"
    other.mkdir(parents=True)
    assert _run(repo, str(other)) == str(repo / ".tmp")


def test_other_paths_under_the_repo_tmp_are_still_redirected(repo: Path) -> None:
    (repo / ".tmp" / "stuff").mkdir()
    assert _run(repo, str(repo / ".tmp" / "stuff")) == str(repo / ".tmp")


def test_outside_a_repo_the_original_value_returns() -> None:
    # 作業ツリーの外 (/tmp)。tmp_path はこのリポジトリの .tmp の中なので、上に .git があり、使えない
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        assert _run(Path(d), "/somewhere") == "/orig-tmp"
